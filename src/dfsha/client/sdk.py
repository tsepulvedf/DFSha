"""SDK C/S: compone RF1/RF2, sin acceso a SQLite ni al volumen del servidor."""
from contextlib import contextmanager
import base64
import hashlib
import os
from pathlib import Path
import posixpath
import threading
import time
import uuid
import unicodedata

import grpc
from dfsha.common.domain import CHUNK, DEADLINES, intent, manifest_hash, need, Fault
from dfsha.common.rpc import channel
from dfsha.v1 import (common_pb2 as c, identity_pb2 as ident, identity_pb2_grpc as ig,
                     namespace_pb2 as ns, namespace_pb2_grpc as ng,
                     control_pb2 as ctl, control_pb2_grpc as cg, data_pb2 as data, data_pb2_grpc as dg)
from dfsha.v1 import diagnostic_pb2 as diagnostic, diagnostic_pb2_grpc as diagnostic_rpc
from dfsha.v1 import nodes_pb2 as nodes, nodes_pb2_grpc as nodes_rpc
from dfsha.client.access import AccessClient


class Client(AccessClient):
    def __init__(self, target, cert_dir, session=None):
        self.target, self.cert_dir = target, Path(cert_dir)
        self.control_timeout = 15 if isinstance(target, (tuple, list)) else 5
        if isinstance(target, (tuple, list)):
            from dfsha.common.failover import FailoverChannel
            self.channel = FailoverChannel([channel(x, self.cert_dir) for x in target])
        else:
            self.channel = channel(target, self.cert_dir)
        self.authentication = ig.AuthenticationServiceStub(self.channel)
        self.identity = ig.IdentityServiceStub(self.channel)
        self.namespace = ng.NamespaceServiceStub(self.channel)
        self.uploads = cg.UploadServiceStub(self.channel)
        self.files = cg.FileAccessServiceStub(self.channel)
        self.cluster = nodes_rpc.ClusterAdministrationServiceStub(self.channel)
        self.session = session
        self.cwd, self.cwd_id = '/', ''
        self.last_commit_request = None
        self.traffic = {}  # Useful bytes confirmed per dynamically resolved node, no tokens or paths.
        self._handle_guards, self._handle_guards_lock = {}, threading.Lock()

    def handle_guard(self, handle):
        with self._handle_guards_lock:
            return self._handle_guards.setdefault(handle.handle_id, threading.RLock())

    def record_traffic(self, node_id, field, amount):
        record = self.traffic.setdefault(node_id, dict(client_write_bytes=0, client_read_bytes=0))
        record[field] += amount

    def shutdown(self):
        self.channel.close()

    def nodes(self):
        return self.call(self.cluster.ListNodes, nodes.ClusterQuery())

    def protection(self, path=None, *, operation_id='', snapshot_id='', cursor=''):
        return self.call(self.cluster.GetProtection, nodes.ProtectionRequest(path=self.path(path) if path else None,
            operation_id=operation_id, snapshot_id=snapshot_id, page=c.PageRequest(limit=64, cursor=cursor)))

    def promote(self, path, revision):
        return self.call(self.cluster.PromoteProtection, nodes.PromoteProtectionRequest(path=self.path(path), expected_policy_revision=revision))

    def wait_durable(self, operation_id, seconds=240):
        deadline = time.monotonic()+seconds
        while True:
            cursor, ready = '', True
            while True:
                status = self.protection(operation_id=operation_id, cursor=cursor)
                need(status.operation_state in (c.PREPARING, c.COMMITTED), 'OPERATION_EXPIRED')
                ready = ready and status.durable_ready
                if not status.next_cursor:
                    break
                cursor = status.next_cursor
            if ready:
                return
            need(time.monotonic() < deadline, 'INSUFFICIENT_REPLICAS')
            time.sleep(.1)

    def copy_status(self, task_id):
        return self.call(self.cluster.CopyStatus, nodes.GetTaskRequest(task_id=task_id))

    def copy_block(self, remote, index, destination):
        handle = self.open_read(remote)
        try:
            plan = self.call(self.files.ResolveBlocks, ctl.ResolveBlocksRequest(handle_id=handle.handle_id,
                snapshot=handle.snapshot, offset=index * handle.snapshot.block_size_bytes,
                length=min(handle.snapshot.block_size_bytes, handle.snapshot.size_bytes - index * handle.snapshot.block_size_bytes),
                page=c.PageRequest(limit=1)))
            need(len(plan.blocks) == 1)
            block = plan.blocks[0]
            return self.call(self.cluster.CopyBlock, nodes.CopyBlockRequest(block=block.block,
                source_node_id=block.locations[0].node_id, destination_node_id=destination))
        finally:
            self.close(handle)

    @property
    def metadata(self):
        if not self.session:
            raise ValueError('Inicie sesión primero')
        return (('authorization', 'Bearer ' + base64.b64encode(self.session.token).decode()),)

    def prepare(self, request, request_id=None):
        request.context.CopyFrom(c.RequestContext(request_id=request_id or str(uuid.uuid4()),
            user_id=self.session.user_id, service_epoch=self.session.service_epoch))
        request.context.intent_sha256 = intent(request)
        return request

    def call(self, rpc, request, deadline=5, retries=2):
        if deadline == 5:
            deadline = self.control_timeout
        if not request.context.request_id:
            self.prepare(request)
        for attempt in range(retries + 1):
            try:
                return rpc(request, metadata=self.metadata, timeout=deadline, wait_for_ready=True)
            except grpc.RpcError as exc:
                recoverable = (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED) if isinstance(self.target, (list, tuple)) else (grpc.StatusCode.UNAVAILABLE,)
                if exc.code() not in recoverable or attempt == retries:
                    raise
                time.sleep(0.1 * (attempt + 1))

    def login(self, username, password):
        # Bound establishment separately: a cold TLS/DNS connection must not
        # consume the complete five-second authentication RPC budget.
        diagnostic_rpc.DiagnosticServiceStub(self.channel).Health(
            diagnostic.HealthRequest(request_id=str(uuid.uuid4())), timeout=10, wait_for_ready=True)
        self.session = self.authentication.Login(ident.LoginRequest(request_id=str(uuid.uuid4()),
            username=username, password=password), timeout=self.control_timeout)
        self.cwd, self.cwd_id = '/', self.stat('/').object_id
        return self.session

    def logout(self):
        result = self.call(self.authentication.Logout, ident.SessionRequest(session_id=self.session.session_id))
        self.session = None
        return result

    def path(self, value):
        return c.PathRef(path=str(value), cwd_path=self.cwd, cwd_id=self.cwd_id)

    def stat(self, path='.'):
        return self.call(self.namespace.Stat, ns.PathRequest(path=self.path(path)))

    def pwd(self):
        entry = self.stat('.')  # Validate directory identity, not just a cached string.
        need(entry.kind == c.DIRECTORY, 'CWD_GONE')
        return self.cwd

    def cd(self, path):
        entry = self.stat(path)
        need(entry.kind == c.DIRECTORY, 'NOT_DIRECTORY')
        # Stat on a directory checks x; cd does not require permission to list it.
        self.cwd = unicodedata.normalize('NFC', posixpath.normpath(path if path.startswith('/') else self.cwd.rstrip('/') + '/' + path))
        if self.cwd.startswith('//'):
            self.cwd = '/' + self.cwd.lstrip('/')
        self.cwd_id = entry.object_id
        return self.cwd

    def ls_page(self, path='.', limit=100, cursor=''):
        return self.call(self.namespace.List, ns.ListRequest(path=self.path(path), page=c.PageRequest(limit=limit, cursor=cursor)))

    def ls(self, path='.'):
        cursor = ''
        while True:
            page = self.ls_page(path, cursor=cursor)
            yield from page.entries
            cursor = page.next_cursor
            if not cursor:
                break

    def mkdir(self, path):
        return self.call(self.namespace.Mkdir, ns.PathRequest(path=self.path(path)))

    def rmdir(self, path):
        return self.call(self.namespace.Rmdir, ns.PathRequest(path=self.path(path)))

    def rm(self, path):
        return self.call(self.namespace.Remove, ns.PathRequest(path=self.path(path)))

    def create_user(self, username, password):
        return self.call(self.identity.CreateUser, ident.CreateUserRequest(username=username, password=password))

    def get_acl(self, path):
        return self.call(self.identity.GetAcl, ident.GetAclRequest(path=self.path(path)))

    def chmod(self, path, mode):
        need(0 <= mode <= 0o777)
        acl = self.get_acl(path)
        acl.owner_permissions, acl.group_permissions, acl.other_permissions = mode >> 6, (mode >> 3) & 7, mode & 7
        return self.call(self.identity.SetAcl, ident.SetAclRequest(path=self.path(path), acl=acl,
                                                                 expected_revision=acl.authz_revision))

    def open_read(self, path):
        return self.call(self.files.Open, ctl.OpenRequest(path=self.path(path), mode=ctl.R))

    def close(self, handle):
        with self.handle_guard(handle):
            return self.call(self.files.Close, ctl.HandleRequest(handle_id=handle.handle_id,
                                                                expected_handle_revision=handle.revision))

    @contextmanager
    def keepalive(self, value, upload=False):
        stop, failures = threading.Event(), []

        def renew():
            while not stop.wait(30):
                try:
                    if upload:
                        updated = self.call(self.uploads.RenewUpload, ctl.OperationRequest(operation=value.operation))
                    else:
                        updated = self.call(self.files.RenewHandle, ctl.HandleRequest(handle_id=value.handle_id,
                                                                  expected_handle_revision=value.revision))
                    value.CopyFrom(updated)
                except Exception as exc:
                    failures.append(exc)
                    return
        thread = threading.Thread(target=renew, daemon=True)
        thread.start()
        try:
            yield
            if failures:
                raise failures[0]
        finally:
            stop.set()
            thread.join(timeout=20)

    def send(self, local, remote, overwrite=False):
        local = Path(local)
        with local.open('rb') as source:
            stat = os.fstat(source.fileno())
            total = stat.st_size
            full_hash = hashlib.sha256()
            while chunk := source.read(CHUNK):
                full_hash.update(chunk)
            source.seek(0)
            expected = None
            if overwrite:
                try:
                    expected = self.stat(remote).snapshot
                except grpc.RpcError as exc:
                    if exc.code() != grpc.StatusCode.NOT_FOUND:
                        raise
            plan = self.call(self.uploads.BeginUpload, ctl.BeginUploadRequest(path=self.path(remote),
                overwrite=overwrite, total_bytes=total, file_sha256=full_hash.digest(), expected_snapshot=expected))
            blocks, page, page_index = [], [], 0
            try:
                with self.keepalive(plan, upload=True):
                    count = (total + plan.block_bytes - 1) // plan.block_bytes
                    for index in range(count):
                        start = index * plan.block_bytes
                        length = min(plan.block_bytes, total - start)
                        digest, left = hashlib.sha256(), length
                        while left:
                            chunk = source.read(min(CHUNK, left))
                            need(chunk, 'CHECKSUM_MISMATCH')
                            digest.update(chunk)
                            left -= len(chunk)
                        source.seek(start)
                        allocation = self.call(self.uploads.AllocateBlocks, ctl.AllocateBlocksRequest(
                            operation=plan.operation, fence=plan.fence, blocks=[c.BlockRef(file_id=plan.file_id,
                                block_index=index, size_bytes=length, plaintext_sha256=digest.digest())])).blocks[0]
                        header = self.prepare(data.PutBlockHeader(operation=plan.operation, block=allocation.block,
                            fence=plan.fence, capability=allocation.grants[0].capability))

                        def frames():
                            source.seek(start)
                            yield data.PutBlockFrame(header=header)
                            offset = 0
                            while offset < length:
                                chunk = source.read(min(CHUNK, length - offset))
                                need(chunk, 'CHECKSUM_MISMATCH')
                                yield data.PutBlockFrame(chunk=data.DataChunk(offset=offset, data=chunk))
                                offset += len(chunk)
                        # Endpoint comes from the authoritative plan, never a client placement table.
                        with channel(allocation.locations[0].client_endpoint, self.cert_dir) as connection:
                            rpc = dg.BlockServiceStub(connection).PutBlock
                            for attempt in range(3):
                                try:
                                    receipt = rpc(frames(), metadata=self.metadata, timeout=DEADLINES[plan.block_bytes])
                                    break
                                except grpc.RpcError as exc:
                                    if exc.code() != grpc.StatusCode.UNAVAILABLE or attempt == 2:
                                        raise
                                    time.sleep(.1)
                        need(receipt.block == allocation.block and receipt.operation_id == plan.operation.operation_id,
                             'CHECKSUM_MISMATCH')
                        self.record_traffic(receipt.node_id, 'client_write_bytes', length)
                        source.seek(start + length)
                        blocks.append(allocation.block)
                        page.append(allocation.block)
                        if len(page) == 64 or index == count - 1:
                            self.call(self.uploads.StageManifestPage, ctl.StageManifestPageRequest(operation=plan.operation,
                                fence=plan.fence, page_index=page_index, blocks=page, page_sha256=manifest_hash(page)))
                            page, page_index = [], page_index + 1
                    need(os.fstat(source.fileno()).st_size == total and os.fstat(source.fileno()).st_mtime_ns == stat.st_mtime_ns,
                         'CHECKSUM_MISMATCH')
                    seal = self.call(self.uploads.SealManifest, ctl.SealManifestRequest(operation=plan.operation,
                        fence=plan.fence, page_count=page_index, block_count=len(blocks), total_bytes=total,
                        manifest_sha256=manifest_hash(blocks)), deadline=300)
                    request = self.prepare(ctl.CommitUploadRequest(operation=plan.operation, seal=seal, fence=plan.fence))
                    if plan.minimum_durable > 1:
                        self.wait_durable(plan.operation.operation_id)
                    self.last_commit_request = request
                    try:
                        return self.call(self.uploads.CommitUpload, request)
                    except grpc.RpcError as exc:
                        if exc.code() not in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED):
                            raise
                        try:
                            status = self.operation(plan.operation.operation_id)
                        except grpc.RpcError:
                            raise Fault('OUTCOME_UNKNOWN') from exc
                        if status.state == c.COMMITTED:
                            return status.result
                        # A still-preparing result does not prove that an
                        # in-flight commit cannot finish after this observation.
                        raise Fault('OUTCOME_UNKNOWN') from exc
            except BaseException as failure:
                if isinstance(failure, Fault) and failure.reason == 'OUTCOME_UNKNOWN':
                    raise
                try:
                    self.call(self.uploads.AbortUpload, ctl.OperationRequest(operation=plan.operation), retries=0)
                except Exception:
                    pass
                raise

    put = send

    def download_block(self, handle, allocation, out, digest):
        """Retry the same immutable block via fresh locations; roll back only its local partial bytes."""
        block, failed = allocation.block, set()
        start = out.tell()
        baseline = digest.copy()
        for attempt in range(3):
            candidates = [(loc, grant) for loc, grant in zip(allocation.locations, allocation.grants)
                          if loc.node_id not in failed]
            if not candidates:
                need(False, 'DATA_UNAVAILABLE')
            location, grant = candidates[0]
            request = self.prepare(data.GetBlockRequest(handle_id=handle.handle_id, snapshot=handle.snapshot,
                block=block, offset=0, length=block.size_bytes, capability=grant.capability))
            try:
                with channel(location.client_endpoint, self.cert_dir) as connection:
                    frames = dg.BlockServiceStub(connection).GetBlock(request, metadata=self.metadata,
                        timeout=DEADLINES[handle.snapshot.block_size_bytes])
                    first = next(frames)
                    need(first.WhichOneof('frame') == 'header' and first.header.block == block and
                         first.header.range_sha256 == block.plaintext_sha256 and first.header.length == block.size_bytes,
                         'CHECKSUM_MISMATCH')
                    block_hash, offset, current = hashlib.sha256(), 0, baseline.copy()
                    for frame in frames:
                        need(frame.WhichOneof('frame') == 'chunk' and frame.chunk.offset == offset and
                             0 < len(frame.chunk.data) <= CHUNK and offset + len(frame.chunk.data) <= block.size_bytes,
                             'CHECKSUM_MISMATCH')
                        out.write(frame.chunk.data)
                        current.update(frame.chunk.data)
                        block_hash.update(frame.chunk.data)
                        offset += len(frame.chunk.data)
                    need(offset == block.size_bytes and block_hash.digest() == block.plaintext_sha256, 'CHECKSUM_MISMATCH')
                    self.record_traffic(location.node_id, 'client_read_bytes', offset)
                    return current, offset
            except grpc.RpcError as exc:
                if exc.code() not in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED, grpc.StatusCode.DATA_LOSS) or attempt == 2:
                    raise
                failed.add(location.node_id)
                out.seek(start)
                out.truncate()
                fresh = self.call(self.files.ResolveBlocks, ctl.ResolveBlocksRequest(handle_id=handle.handle_id,
                    snapshot=handle.snapshot, offset=block.block_index * handle.snapshot.block_size_bytes,
                    length=block.size_bytes, page=c.PageRequest(limit=1)))
                need(fresh.snapshot == handle.snapshot and len(fresh.blocks) == 1 and fresh.blocks[0].block == block,
                     'CHECKSUM_MISMATCH')
                allocation = fresh.blocks[0]
                if not any(loc.node_id not in failed for loc in allocation.locations):
                    raise exc

    def receive_handle(self, handle, local, overwrite=False):
        target = Path(local)
        need(not target.exists() or overwrite, 'ALREADY_EXISTS')
        temporary = target.parent / ('.dfsha-' + str(uuid.uuid4()) + '.part')
        digest, total, blocks, cursor = hashlib.sha256(), 0, [], ''
        try:
            with self.keepalive(handle), temporary.open('xb') as out:
                os.chmod(temporary, 0o600)
                while True:
                    plan = self.call(self.files.ResolveBlocks, ctl.ResolveBlocksRequest(handle_id=handle.handle_id,
                        snapshot=handle.snapshot, offset=0, length=handle.snapshot.size_bytes,
                        page=c.PageRequest(limit=64, cursor=cursor)))
                    need(plan.snapshot == handle.snapshot, 'CHECKSUM_MISMATCH')
                    for allocation in plan.blocks:
                        block = allocation.block
                        need(block.block_index == len(blocks), 'CHECKSUM_MISMATCH')
                        digest, received = self.download_block(handle, allocation, out, digest)
                        total += received
                        blocks.append(block)
                    cursor = plan.next_cursor
                    if not cursor:
                        break
                need(total == handle.snapshot.size_bytes and (not handle.snapshot.HasField('file_sha256') or digest.digest() == handle.snapshot.file_sha256) and
                     manifest_hash(blocks) == handle.snapshot.manifest_sha256, 'CHECKSUM_MISMATCH')
                out.flush()
                os.fsync(out.fileno())
            if overwrite:
                os.replace(temporary, target)
            else:
                os.link(temporary, target)  # Atomic no-clobber publication on NTFS/POSIX.
                temporary.unlink()
            return dict(bytes=total, sha256=digest.hexdigest())
        finally:
            temporary.unlink(missing_ok=True)

    def receive(self, remote, local, overwrite=False):
        handle = self.open_read(remote)
        try:
            return self.receive_handle(handle, local, overwrite)
        finally:
            self.close(handle)

    get = receive
