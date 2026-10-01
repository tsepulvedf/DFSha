"""Identidad, permisos y custodia local. Tokens almacenados como hashes."""
import base64
import hashlib
import hmac
import os
import re
import threading
from contextlib import contextmanager
from pathlib import Path
from argon2 import PasswordHasher, Type
from argon2.exceptions import VerificationError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from dfsha.common.domain import Fault, need, now, uid
from dfsha.control.metadata import SQLiteMetadataStore

PASSWORDS = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1, type=Type.ID)
AUTH_SLOTS = threading.BoundedSemaphore(2)


@contextmanager
def auth_slot():
    need(AUTH_SLOTS.acquire(timeout=.1), 'LIMIT_EXCEEDED')
    try:
        yield
    finally:
        AUTH_SLOTS.release()


def password_hash(password):
    need(12 <= len(password.encode()) <= 1024)
    with auth_slot():
        return PASSWORDS.hash(password)


def matches(encoded, password):
    if len(password.encode()) > 1024:
        return False
    try:
        with auth_slot():
            return PASSWORDS.verify(encoded, password)
    except VerificationError:
        return False


def protect(path):
    path = Path(path)
    path.chmod(0o600 if path.is_file() else 0o700)
    if os.name == 'nt':
        import csv
        import subprocess
        raw = subprocess.check_output(['whoami', '/user', '/fo', 'csv', '/nh'], text=True,
                                      creationflags=subprocess.CREATE_NO_WINDOW)
        sid = next(csv.reader(raw.strip().splitlines()))[1]
        rights = '(OI)(CI)F' if path.is_dir() else 'F'
        args = ['icacls', str(path), '/inheritance:r', '/grant:r', f'*{sid}:{rights}',
                f'*S-1-5-18:{rights}', f'*S-1-5-32-544:{rights}']
        subprocess.run(args, check=True, stdout=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)


def new_node(name, parent, owner, directory=True, mode=0o700):
    return dict(id=uid(), name=name, parent=parent, owner=owner, group=owner,
                mode=mode, acl=[], alive=True, kind='directory' if directory else 'file',
                revision=1, snapshot=None)


def initialize(cfg, username, password):
    need(re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', username) is not None)
    dbpath, keypath = Path(cfg['sqlite_path']), Path(cfg['key_path'])
    if cfg.get('metadata_key_path') and dbpath.is_file() and keypath.is_file():
        from dfsha.common.protected import MetadataCipher
        store = SQLiteMetadataStore(dbpath, MetadataCipher.configured(cfg))
        with store.transaction() as tx:
            system = tx.get('settings', 'system')
            need(system and not system.get('authority_migrated'), 'ALREADY_EXISTS')
            need(hashlib.sha256(keypath.read_bytes()).hexdigest() == system['key_sha256'], 'DATA_LOSS')
            user = next((u for u in tx.all('user') if u['username'] == username), None)
            need(user and user['admin'] and not user['disabled'] and matches(user['password'], password),
                 'ALREADY_EXISTS')
        return  # Explicit idempotent bootstrap; no reset, account recreation or grants.
    need(not dbpath.exists() and not keypath.exists(), 'ALREADY_EXISTS')
    root = Path(cfg['block_path'])
    need(not root.exists() or not any(root.iterdir()), 'ALREADY_EXISTS')
    encoded = password_hash(password)
    keypath.parent.mkdir(parents=True, exist_ok=True)
    protect(keypath.parent)
    with keypath.open('xb') as out:
        out.write(os.urandom(32))
        out.flush()
        os.fsync(out.fileno())
    protect(keypath)
    from dfsha.common.protected import MetadataCipher
    store = SQLiteMetadataStore(dbpath, MetadataCipher.configured(cfg))
    store.initialize()
    identity = uid()
    rootnode = new_node('', None, identity, mode=0o755)
    with store.transaction(True) as tx:
        tx.put('settings', dict(id='system', epoch=uid(), root=rootnode['id'], node=uid(),
                               key_sha256=hashlib.sha256(keypath.read_bytes()).hexdigest(),
                               strict_content_permissions=bool(cfg.get('metadata_key_path'))))
        tx.put('user', dict(id=identity, username=username, password=encoded, disabled=False, admin=True, revision=1))
        tx.put('group', dict(id=identity, name=username, members=[identity], revision=1))
        tx.put('node', rootnode)
        home = new_node('home', rootnode['id'], identity, mode=0o755)
        tx.put('node', home)
        tx.put('node', new_node(username, home['id'], identity))
    protect(dbpath.parent)
    root.mkdir(parents=True, exist_ok=True)
    protect(root)


class Authorizer:
    def __init__(self, key, system):
        self.key, self.system = key, system

    def authenticate(self, tx, token):
        session = tx.get('session', hashlib.sha256(token).hexdigest())
        need(session and not session['revoked'] and session['expires'] > now(), 'UNAUTHENTICATED')
        if hasattr(tx, 'session_live'):
            need(tx.session_live(session), 'UNAUTHENTICATED')
        user = tx.get('user', session['user'])
        need(user and not user['disabled'], 'UNAUTHENTICATED')
        return user, session

    def require(self, tx, user, node, bits):
        if user['admin'] and (not self.system.get('strict_content_permissions') or
                              node['kind'] == 'directory' and bits == 1):
            return
        groups = {g['id'] for g in tx.all('group') if user['id'] in g['members']}
        shift = 6 if node['owner'] == user['id'] else 3 if node['group'] in groups else 0
        allowed = (node['mode'] >> shift) & 7
        for entry in node['acl']:
            if entry['principal_id'] == user['id'] and not entry.get('is_group', False) or \
                    entry.get('is_group', False) and entry['principal_id'] in groups:
                allowed |= entry.get('permissions', 0)
        need(allowed & bits == bits, 'PERMISSION_DENIED')

    def capability(self, user_id, binding, block_id, action):
        return hmac.digest(self.key, '\0'.join((self.system['epoch'], user_id, binding, block_id, action)).encode(), 'sha256')

    def encrypt(self, data):
        nonce = os.urandom(12)
        return base64.b64encode(nonce + AESGCM(self.key).encrypt(nonce, data, b'dfsha-ledger-v1')).decode()

    def decrypt(self, text):
        data = base64.b64decode(text)
        return AESGCM(self.key).decrypt(data[:12], data[12:], b'dfsha-ledger-v1')
