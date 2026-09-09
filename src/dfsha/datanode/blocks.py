"""Contenedor DFSHAB01: registros AES-GCM acotados; ninguna ruta de usuario."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import struct
import threading
import base64

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.keywrap import aes_key_wrap, aes_key_unwrap
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.keywrap import InvalidUnwrap
from dfsha.common.domain import CHUNK, Fault, canonical, need, uid, uuid

MAGIC = b'DFSHAB01'


class EncryptedBlockStore:
    def __init__(self, root, key):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.key = key
        self.key_id = hashlib.sha256(key).hexdigest()
        self.active = {}
        self.writers = set()
        self.guard = threading.RLock()

    def path(self, file_id, block_id):
        path = self.root / uuid(file_id) / (uuid(block_id) + '.blk')
        need(path.resolve().is_relative_to(self.root), 'PERMISSION_DENIED')
        need(not path.is_symlink() and not path.parent.is_symlink(), 'PERMISSION_DENIED')
        return path

    @contextmanager
    def pin(self, block_id, exclusive=False):
        with self.guard:
            need(block_id not in self.writers and (not exclusive or block_id not in self.active), 'LOCK_BUSY')
            self.active[block_id] = self.active.get(block_id, 0) + 1
            if exclusive:
                self.writers.add(block_id)
        try:
            yield
        finally:
            with self.guard:
                self.active[block_id] -= 1
                if self.active[block_id] == 0:
                    del self.active[block_id]
                self.writers.discard(block_id)

    def put(self, block, chunks):
        target = self.path(block.file_id, block.block_version_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.parent / (uid() + '.staging')
        dek, prefix = os.urandom(32), os.urandom(8)
        header = canonical(dict(version=1, file_id=block.file_id, block_id=block.block_version_id,
            size=block.size_bytes, sha256=block.plaintext_sha256.hex(), key_id=self.key_id,
            wrapped_dek=base64.b64encode(aes_key_wrap(self.key, dek)).decode(),
            nonce_prefix=base64.b64encode(prefix).decode()))
        digest, total = hashlib.sha256(), 0
        try:
            with temporary.open('xb') as out:
                out.write(MAGIC + struct.pack('>I', len(header)) + header)
                aes = AESGCM(dek)
                for index, chunk in enumerate(chunks):
                    need(0 < len(chunk) <= CHUNK and total + len(chunk) <= block.size_bytes)
                    nonce = prefix + struct.pack('>I', index)
                    encrypted = aes.encrypt(nonce, chunk, header + struct.pack('>II', index, len(chunk)))
                    out.write(struct.pack('>I', len(encrypted)))
                    out.write(encrypted)
                    total += len(chunk)
                    digest.update(chunk)
                need(total == block.size_bytes and digest.digest() == block.plaintext_sha256,
                     'CHECKSUM_MISMATCH')
                out.flush()
                os.fsync(out.fileno())
            need(not target.exists(), 'ALREADY_EXISTS')
            os.replace(temporary, target)
            # POSIX also persists the directory entry. Windows os.fsync flushes
            # file contents; power-loss guarantees depend on NTFS/storage stack.
            if os.name != 'nt':
                fd = os.open(target.parent, os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            cipher_hash = hashlib.sha256()
            with target.open('rb') as stream:
                while chunk := stream.read(CHUNK):
                    cipher_hash.update(chunk)
            return target.stat().st_size, cipher_hash.digest()
        except OSError as exc:
            raise Fault('NO_SPACE' if exc.errno in (28, 122) or getattr(exc, 'winerror', 0) == 112
                        else 'DATA_UNAVAILABLE') from exc
        finally:
            temporary.unlink(missing_ok=True)

    def read_verified(self, block):
        """Verify the ENTIRE object before releasing any plaintext; then verify each record again."""
        try:
            with self.path(block.file_id, block.block_version_id).open('rb') as stream:
                need(stream.read(8) == MAGIC, 'DATA_LOSS')
                size_raw = stream.read(4)
                need(len(size_raw) == 4, 'DATA_LOSS')
                length = struct.unpack('>I', size_raw)[0]
                need(0 < length <= 4096, 'DATA_LOSS')
                header = stream.read(length)
                obj = json.loads(header)
                need(obj['version'] == 1 and obj['file_id'] == block.file_id and
                     obj['block_id'] == block.block_version_id and obj['size'] == block.size_bytes and
                     obj['sha256'] == block.plaintext_sha256.hex() and obj['key_id'] == self.key_id, 'DATA_LOSS')
                dek = aes_key_unwrap(self.key, base64.b64decode(obj['wrapped_dek']))
                prefix = base64.b64decode(obj['nonce_prefix'])
                need(len(prefix) == 8, 'DATA_LOSS')
                start = stream.tell()

                def records():
                    index = 0
                    while raw := stream.read(4):
                        need(len(raw) == 4, 'DATA_LOSS')
                        length = struct.unpack('>I', raw)[0]
                        need(16 < length <= CHUNK + 16, 'DATA_LOSS')
                        data = stream.read(length)
                        need(len(data) == length, 'DATA_LOSS')
                        yield AESGCM(dek).decrypt(prefix + struct.pack('>I', index), data,
                                                  header + struct.pack('>II', index, length - 16))
                        index += 1
                digest, total = hashlib.sha256(), 0
                for data in records():
                    digest.update(data)
                    total += len(data)
                need(total == block.size_bytes and digest.digest() == block.plaintext_sha256, 'DATA_LOSS')
                stream.seek(start)
                yield from records()
        except Fault:
            raise
        except (OSError, ValueError, KeyError, struct.error, InvalidTag, InvalidUnwrap) as exc:
            raise Fault('DATA_LOSS') from exc

    def collect(self, retained):
        with self.guard:
            for folder in self.root.iterdir():
                if not folder.is_dir() or folder.is_symlink():
                    continue
                try:
                    uuid(folder.name)
                except Fault:
                    continue
                for path in folder.iterdir():
                    if path.suffix not in ('.blk', '.staging') or path.is_symlink():
                        continue
                    if path.suffix == '.staging' and self.active:
                        continue
                    if path.stem in retained or path.stem in self.active:
                        continue
                    try:
                        path.unlink()
                    except PermissionError:  # A retained/open Windows reader may still own a file descriptor.
                        pass
