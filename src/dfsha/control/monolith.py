"""Composición H1 y transporte. SQLite/coord./bloques/autorización siguen separados."""
import base64
import hashlib
import hmac
import importlib
import json
import os
from pathlib import Path
import sqlite3
import threading

import grpc
from google.protobuf import message_factory
from dfsha.common.domain import (Fault, need, uid, uuid, now, asdict, proto, intent,
                                  manifest_hash, PROFILES, DEADLINES, CHUNK)
from dfsha.common.local import LocalCoordinator, LocalPlacement
from dfsha.common.rpc import abort
from dfsha.common.telemetry import event
from dfsha.control.auth import Authorizer, matches
from dfsha.control.metadata import SQLiteMetadataStore
from dfsha.control.queries import Queries
from dfsha.control.commands import Commands
from dfsha.datanode.blocks import EncryptedBlockStore
from dfsha.v1 import common_pb2 as c, control_pb2 as ctl, identity_pb2 as ident, data_pb2 as data


class Monolith:
    def __init__(self, cfg):
        self.cfg = cfg
        need(cfg['block_size_bytes'] in PROFILES)
        need(Path(cfg['sqlite_path']).is_file(), 'NOT_FOUND')
        key_path = Path(cfg['key_path'])
        if not key_path.is_file() or len(key_path.read_bytes()) != 32:
            raise RuntimeError('MASTER_KEY_MISSING_OR_INVALID: restaure la clave original; no se regenera')
        key = key_path.read_bytes()
        self.store = SQLiteMetadataStore(cfg['sqlite_path'])
        with self.store.transaction() as tx:
            self.system = tx.get('settings', 'system')
        if not self.system or hashlib.sha256(key).hexdigest() != self.system['key_sha256']:
            raise RuntimeError('MASTER_KEY_MISMATCH: no se puede abrir el almacenamiento existente')
        self.auth = Authorizer(key, self.system)
        self.blocks = self.make_blocks(cfg['block_path'], key)
        self.coordinator = LocalCoordinator()
        self.placement = LocalPlacement(self.system['node'])
        self.queries = Queries(self)
        self.commands = Commands(self)
        self.verified_seals = {}
        self.maintenance_lock = threading.RLock()
        self.owner_lock = Path(cfg['sqlite_path']).with_suffix('.owner').open('a+b')
        self.owner_lock.seek(0)
        if not self.owner_lock.read(1):
            self.owner_lock.write(b'1')
            self.owner_lock.flush()
        self.owner_lock.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.owner_lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.owner_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.owner_lock.close()
            raise RuntimeError('STORAGE_ALREADY_OPEN: un único monolito puede poseer esta raíz') from None
        self.collect(restart=True)

    def credentials(self, context):
        values = [v for k, v in context.invocation_metadata() if k == 'authorization']
        need(len(values) == 1 and values[0].startswith('Bearer '), 'UNAUTHENTICATED')
        try:
            return base64.b64decode(values[0][7:], validate=True)
        except ValueError:
            raise Fault('UNAUTHENTICATED') from None

    def authenticated(self, tx, token, request):
        user, session = self.auth.authenticate(tx, token)
        ctx = request.context
        uuid(ctx.request_id)
        need(ctx.user_id == user['id'] and ctx.service_epoch == self.system['epoch'], 'UNAUTHENTICATED')
        return user, session

    def ledger_id(self, user, request):
        return self.system['epoch'] + ':' + user['id'] + ':' + request.context.request_id

    def replay(self, tx, user, request, method, response_type):
        need(request.context.intent_sha256 == intent(request))
        previous = tx.get('ledger', self.ledger_id(user, request))
        if previous:
            need(previous['method'] == method and previous['digest'] == intent(request).hex(), 'IDEMPOTENCY_MISMATCH')
            if hasattr(request, 'password'):
                need(matches(previous['password_verifier'], request.password), 'IDEMPOTENCY_MISMATCH')
            return response_type.FromString(self.auth.decrypt(previous['response']))
        return None

    def remember(self, tx, user, request, method, response):
        record = dict(id=self.ledger_id(user, request), method=method, digest=intent(request).hex(),
                      response=self.auth.encrypt(response.SerializeToString()))
        if hasattr(request, 'password'):
            target = next(u for u in tx.all('user') if u['username'] == request.username)
            record['password_verifier'] = target['password']
        tx.put('ledger', record)

    def fault(self, name):
        directory = self.cfg.get('test_fault_dir')
        if not directory:
            return False
        marker = Path(directory) / name
        try:
            marker.rename(marker.with_suffix('.used'))
        except FileNotFoundError:
            return False
        if name in ('after_block_persist', 'before_publish'):
            os._exit(93)
        return True

    def Login(self, request, context):
        uuid(request.request_id)
        with self.store.transaction() as tx:
            user = next((u for u in tx.all('user') if u['username'] == request.username), None)
        # A fixed valid hash prevents the unknown-user path from skipping Argon2.
        dummy = '$argon2id$v=19$m=19456,t=2,p=1$ZGYtc2hhLWR1bW15LXNhbHQ$AoSIjKnHgcYoiDZOGtzyEMrePTYVKYnGNoh++8ucPeE'
        valid = matches(user['password'] if user else dummy, request.password)
        need(user and not user['disabled'] and valid, 'UNAUTHENTICATED')
        token = os.urandom(32)
        session = dict(id=hashlib.sha256(token).hexdigest(), session_id=uid(), user=user['id'],
                       expires=now() + 3600000, revoked=False)
        with self.store.transaction(True) as tx:
            current = tx.get('user', user['id'])
            need(not current['disabled'] and current['password'] == user['password'], 'UNAUTHENTICATED')
            tx.put('session', session)
        return ident.Session(session_id=session['session_id'], user_id=user['id'], token=token,
                             expires_at_unix_ms=session['expires'], service_epoch=self.system['epoch'])

    def unary(self, method, response_type, request, context):
        if method == 'Lock' and hasattr(self, 'leases'):
            import time
            need(request.wait_timeout_ms <= 5000)
            stop = time.monotonic() + request.wait_timeout_ms / 1000
            while True:
                try:
                    return self.unary_once(method, response_type, request, context)
                except Fault as exc:
                    if exc.reason != 'LOCK_CONFLICT' or time.monotonic() >= stop:
                        raise
                    need(context.is_active(), 'DEADLINE_EXCEEDED')
                    time.sleep(min(.025, max(0, stop - time.monotonic())))
        return self.unary_once(method, response_type, request, context)

    def unary_once(self, method, response_type, request, context):
        if method == 'Login':
            return self.Login(request, context)
        token = self.credentials(context)
        query = getattr(self.queries, method, None)
        if query:
            with self.store.transaction() as tx:
                user, session = self.authenticated(tx, token, request)
                return query(tx, user, session, request)
        with self.store.transaction() as tx:
            if method == 'Logout':
                old_session = tx.get('session', hashlib.sha256(token).hexdigest())
                if old_session and old_session['revoked']:
                    old_user = tx.get('user', old_session['user'])
                    need(request.context.user_id == old_user['id'] and
                         request.context.service_epoch == self.system['epoch'], 'UNAUTHENTICATED')
                    uuid(request.context.request_id)
                    previous = self.replay(tx, old_user, request, method, response_type)
                    need(previous is not None, 'UNAUTHENTICATED')
                    return previous
            user, session = self.authenticated(tx, token, request)
            previous = self.replay(tx, user, request, method, response_type)
            if previous is not None:
                return previous
        if method == 'SealManifest':
            with self.store.transaction() as tx:
                op = self.commands.operation(tx, user, session, request.operation, request.fence)
                blocks = self.manifest(op)
            self.verify_seal(op, blocks, context)
            self.verified_seals[op['id']] = manifest_hash(blocks)
        if method in ('CommitUpload', 'CommitWrite'):
            self.fault('before_publish')
        with self.store.transaction(True) as tx:
            user, session = self.authenticated(tx, token, request)
            previous = self.replay(tx, user, request, method, response_type)
            if previous is not None:
                return previous
            response = getattr(self.commands, method)(tx, user, session, request)
            self.remember(tx, user, request, method, response)
        if method in ('CommitUpload', 'CommitWrite') and self.fault('after_commit_drop_response'):
            raise Fault('SERVICE_UNAVAILABLE')
        return response

    def upload_plan(self, op):
        return ctl.UploadPlan(operation=proto(c.OperationRef, op['operation']), file_id=op['file'],
            content_epoch=op['epoch'], block_bytes=op['block_size'], expires_at_unix_ms=op['expires'],
            fence=c.Fence(lock_id=op['id'], service_epoch=self.system['epoch'], generation=op['epoch'],
                          lease_id=1, whole_file=True, includes_size=True, expires_at_unix_ms=op['expires']))

    def handle_message(self, tx, handle):
        expires = self.leases.expiry_hint(handle) if hasattr(self, 'leases') else handle['expires']
        return ctl.Handle(handle_id=handle['id'], snapshot=proto(c.SnapshotRef, tx.get('snapshot', handle['snapshot'])['ref']),
                          mode=handle.get('mode', ctl.R), expires_at_unix_ms=expires, revision=handle['revision'])

    def make_blocks(self, root, key):
        return EncryptedBlockStore(root, key)

    def reserve_upload(self, tx, total, block_size):
        import shutil
        reserved = total + ((total + block_size - 1) // block_size) * 4096 + ((total + CHUNK - 1) // CHUNK) * 20
        pending = sum(o['reserved'] for o in tx.all('upload') if o['state'] == c.PREPARING)
        used = sum(b['stored_size'] for b in tx.all('block'))
        need(reserved + pending + used <= self.cfg['capacity_bytes'] and
             reserved + pending + 1048576 <= shutil.disk_usage(self.blocks.root).free, 'NO_SPACE')
        return reserved

    def verify_seal(self, op, blocks, context):
        digest = hashlib.sha256()
        with self.coordinator.admit(op['block_size']):
            for block in blocks:
                with self.blocks.pin(block.block_version_id):
                    for chunk in self.blocks.read_verified(block):
                        need(context.is_active(), 'DEADLINE_EXCEEDED')
                        digest.update(chunk)
        need(digest.hexdigest() == op['sha'], 'CHECKSUM_MISMATCH')

    def retire_block(self, tx, block):
        tx.delete('block', block['id'])

    def plan(self, block, user, binding, read=False, tx=None):
        action = 'read' if read else 'write'
        return c.PlannedBlock(block=block, locations=[self.placement.location()], grants=[c.BlockGrant(
            capability=self.auth.capability(user['id'], binding['id'], block.block_version_id, action),
            action=c.READ_DATA if read else c.WRITE_DATA, block=block, node_id=self.system['node'],
            length=block.size_bytes, expires_at_unix_ms=binding['expires'])],
            reservation=None if read else c.StorageReservation(reservation_id=binding['id'], node_id=self.system['node'],
                operation_id=binding['id'], bytes=binding['reserved'], expires_at_unix_ms=binding['expires']))

    def manifest(self, op):
        count = (op['total'] + op['block_size'] - 1) // op['block_size']
        need(len(op['pages']) == (count + 63) // 64, 'CHECKSUM_MISMATCH')
        blocks = [proto(c.BlockRef, b) for i in range(len(op['pages'])) for b in op['pages'].get(str(i), [])]
        need(len(blocks) == count and sum(b.size_bytes for b in blocks) == op['total'] and
             all(b.block_index == i for i, b in enumerate(blocks)), 'CHECKSUM_MISMATCH')
        return blocks

    def PutBlock(self, requests, context):
        first = next(requests, None)
        need(first is not None and first.WhichOneof('frame') == 'header')
        header = first.header
        token = self.credentials(context)
        with self.store.transaction() as tx:
            user, session = self.authenticated(tx, token, header)
            previous = self.replay(tx, user, header, 'PutBlock', c.DurableReceipt)
            if previous is not None:
                return previous
            op = self.commands.operation(tx, user, session, header.operation, header.fence)
            block = header.block
            need(op['allocations'].get(str(block.block_index)) == asdict(block), 'VERSION_CONFLICT')
            expected = self.auth.capability(user['id'], op['id'], block.block_version_id, 'write')
            need(hmac.compare_digest(expected, header.capability), 'PERMISSION_DENIED')
            need(not tx.get('block', block.block_version_id), 'ALREADY_EXISTS')
        remaining = context.time_remaining()
        need(remaining is not None and remaining <= DEADLINES[op['block_size']] + 2)

        def chunks():
            total = 0
            for frame in requests:
                need(context.is_active(), 'DEADLINE_EXCEEDED')
                need(frame.WhichOneof('frame') == 'chunk' and frame.chunk.offset == total and
                     len(frame.chunk.data) == min(CHUNK, block.size_bytes - total) and len(frame.chunk.data) > 0)
                total += len(frame.chunk.data)
                yield frame.chunk.data
        with self.coordinator.admit(op['block_size']), self.blocks.pin(block.block_version_id, exclusive=True):
            stored, digest = self.blocks.put(block, chunks())
            self.fault('after_block_persist')
            receipt = c.DurableReceipt(receipt_id=uid(), operation_id=op['id'], block=block,
                node_id=self.system['node'], boot_generation=1, failure_domain='local-host',
                stored_size_bytes=stored, ciphertext_sha256=digest, durable_at_unix_ms=now())
            with self.store.transaction(True) as tx:
                user, session = self.authenticated(tx, token, header)
                op = self.commands.operation(tx, user, session, header.operation, header.fence)
                tx.put('block', dict(id=block.block_version_id, file=block.file_id, operation=op['id'],
                    ref=asdict(block), stored_size=stored, receipt=asdict(receipt)))
                op['reserved'] = max(0, op['reserved'] - stored)
                tx.put('upload', op)
                self.remember(tx, user, header, 'PutBlock', receipt)
            return receipt

    def GetBlock(self, request, context):
        token = self.credentials(context)
        with self.store.transaction() as tx:
            user, session = self.authenticated(tx, token, request)
            handle, snap = self.queries.handle(tx, user, session, request.handle_id)
            need(asdict(request.snapshot) == snap['ref'], 'VERSION_CONFLICT')
            block = request.block
            need(asdict(block) in snap['blocks'], 'PERMISSION_DENIED')
            expected = self.auth.capability(user['id'], handle['id'], block.block_version_id, 'read')
            need(hmac.compare_digest(expected, request.capability), 'PERMISSION_DENIED')
            need((not request.HasField('offset') or request.offset == 0) and
                 (not request.HasField('length') or request.length == block.size_bytes), 'UNSUPPORTED_MODE')
            size = int(snap['ref']['block_size_bytes'])
        remaining = context.time_remaining()
        need(remaining is not None and remaining <= DEADLINES[size] + 2)
        with self.coordinator.admit(size), self.blocks.pin(block.block_version_id):
            iterator = self.blocks.read_verified(block)
            first = next(iterator, None)  # Full verification before even the header.
            yield data.ReadBlockFrame(header=data.ReadBlockHeader(block=block, length=block.size_bytes,
                                                                  range_sha256=block.plaintext_sha256))
            offset = 0
            if first is not None:
                yield data.ReadBlockFrame(chunk=data.DataChunk(offset=offset, data=first))
                offset += len(first)
            for chunk in iterator:
                need(context.is_active(), 'DEADLINE_EXCEEDED')
                yield data.ReadBlockFrame(chunk=data.DataChunk(offset=offset, data=chunk))
                offset += len(chunk)

    def operation_live(self, tx, op):
        if not op or op['state'] != c.PREPARING:
            return False
        if hasattr(self, 'leases') and op.get('kind') == 'write':
            handle = tx.get('handle', op['handle'])
            locks = [tx.get('lock', identity) for identity in op['locks']]
            return bool(handle and not handle['closed'] and self.leases.live(handle) and
                        all(lock and self.leases.live(lock) for lock in locks))
        return op['expires'] > now()

    def collect(self, restart=False):
        with self.maintenance_lock:
            with self.store.transaction(True) as tx:
                if hasattr(self, 'leases'):
                    for op in tx.all('upload'):
                        if op.get('kind') == 'write' and op['state'] == c.PREPARING:
                            handle = tx.get('handle', op['handle'])
                            locks = [tx.get('lock', identity) for identity in op['locks']]
                            if not handle or not self.leases.live(handle) or any(not x or not self.leases.live(x) for x in locks):
                                op.update(state=c.EXPIRED, reserved=0)
                                tx.put('upload', op)
                        if op['state'] != c.PREPARING:
                            self.leases.release_operation(tx, op)
                    for handle in tx.all('handle'):
                        if not self.leases.live(handle):
                            handle['closed'] = True
                            tx.put('handle', handle)
                for op in tx.all('upload'):
                    if op['state'] == c.PREPARING and (restart or not self.operation_live(tx, op)):
                        op.update(state=c.ABORTED if restart else c.EXPIRED, reserved=0)
                        tx.put('upload', op)
                pins = {h['snapshot'] for h in tx.all('handle') if not h['closed'] and
                        (self.leases.live(h) if hasattr(self, 'leases') else h['expires'] > now())}
                pins.update(n['snapshot'] for n in tx.all('node') if n['alive'] and n['snapshot'])
                retained = set()
                # S/S tasks pin their source even if the logical name is removed meanwhile.
                retained.update(t['block']['block_version_id'] for t in tx.all('task') if
                    t['kind'] == 'copy' and t['expires'] > now() and t['status']['state'] in ('ACCEPTED', 'RUNNING'))
                for snap in tx.all('snapshot'):
                    if snap['id'] in pins:
                        retained.update(b['block_version_id'] for b in snap['blocks'])
                    else:
                        tx.delete('snapshot', snap['id'])
                for op in tx.all('upload'):
                    if op['state'] == c.PREPARING:
                        retained.update(b['block_version_id'] for b in op['allocations'].values())
                for block in tx.all('block'):
                    if block['id'] not in retained:
                        self.retire_block(tx, block)
            self.blocks.collect(retained)

    def register(self, server):
        """Register only implemented methods; remaining methods retain explicit UNIMPLEMENTED."""
        implemented = set()
        for module in ('identity', 'namespace', 'control', 'data', 'nodes'):
            descriptor = importlib.import_module(f'dfsha.v1.{module}_pb2').DESCRIPTOR
            for service in descriptor.services_by_name.values():
                methods = {}
                for method in service.methods:
                    if method.name in ('PutBlock', 'GetBlock') and not getattr(self, 'serves_content', True):
                        continue
                    if method.name not in ('Login', 'PutBlock', 'GetBlock') and not (
                        hasattr(self.queries, method.name) or hasattr(self.commands, method.name)):
                        continue
                    request_type = message_factory.GetMessageClass(method.input_type)
                    response_type = message_factory.GetMessageClass(method.output_type)
                    shape = ('stream' if method.client_streaming else 'unary') + '_' + ('stream' if method.server_streaming else 'unary')
                    name = method.name

                    def invoke(req, context, name=name, response_type=response_type):
                        try:
                            if name == 'PutBlock':
                                return self.PutBlock(req, context)
                            remaining = context.time_remaining()
                            # gRPC rounds timeout encoding upward (observed 300.999...s
                            # for a 300s caller deadline). Allow rounding plus clock
                            # conversion jitter, without accepting unbounded calls.
                            need(remaining is not None and remaining <= (302 if name == 'SealManifest' else 7))
                            return self.unary(name, response_type, req, context)
                        except Fault as exc:
                            import traceback
                            location = traceback.extract_tb(exc.__traceback__)[-2]
                            event('rpc_rejected', code=f'{name}:{exc.reason}:{Path(location.filename).name}:{location.lineno}')
                            abort(context, exc.code, c.ErrorReason.Value(exc.reason))
                        except sqlite3.Error:
                            abort(context, grpc.StatusCode.UNAVAILABLE, c.SERVICE_UNAVAILABLE)
                        except OSError:
                            abort(context, grpc.StatusCode.UNAVAILABLE, c.DATA_UNAVAILABLE)

                    def streaming(req, context):
                        try:
                            yield from self.GetBlock(req, context)
                        except Fault as exc:
                            abort(context, exc.code, c.ErrorReason.Value(exc.reason))
                    methods[name] = getattr(grpc, f'{shape}_rpc_method_handler')(
                        streaming if method.server_streaming else invoke,
                        request_deserializer=request_type.FromString,
                        response_serializer=lambda response: response.SerializeToString())
                    implemented.add((service.full_name, name))
                if methods:
                    server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler(service.full_name, methods),))
        return implemented
