"""Consultas sobre la fuente autoritativa; sin crear pins ni cambiar revisiones."""
import base64
import json
import unicodedata
from dfsha.common.domain import need, Fault, asdict, proto, now, canonical
from dfsha.v1 import common_pb2 as c, namespace_pb2 as ns, control_pb2 as ctl


class Queries:
    def __init__(self, app):
        self.app = app

    def walk(self, tx, user, path):
        need(path.startswith('/') and len(path.encode()) <= 4096 and '\\' not in path and '\0' not in path)
        pieces = [unicodedata.normalize('NFC', p) for p in path.split('/') if p]
        need(len(pieces) <= 32 and all(len(p.encode()) <= 255 for p in pieces), 'LIMIT_EXCEEDED')
        node = tx.get('node', self.app.system['root'])
        for piece in pieces:
            need(node['kind'] == 'directory', 'NOT_DIRECTORY')
            self.app.auth.require(tx, user, node, 1)
            if piece == '.':
                continue
            if piece == '..':
                node = tx.get('node', node['parent']) if node['parent'] else node
            else:
                children = tx.children(node['id'])
                node = next((n for n in children if n['name'] == piece), None)
                need(node, 'NOT_FOUND')
        return node

    def path(self, tx, user, ref):
        need(ref.path and len(ref.path.encode()) <= 4096)
        if ref.path.startswith('/'):
            return ref.path
        need(ref.cwd_path.startswith('/') and ref.cwd_id)
        try:
            cwd = self.walk(tx, user, ref.cwd_path)
        except Fault as exc:
            if exc.reason in ('NOT_FOUND', 'NOT_DIRECTORY'):
                raise Fault('CWD_GONE') from None
            raise
        need(cwd['id'] == ref.cwd_id and cwd['kind'] == 'directory', 'CWD_GONE')
        return ref.cwd_path.rstrip('/') + '/' + ref.path

    def resolve(self, tx, user, ref):
        return self.walk(tx, user, self.path(tx, user, ref))

    def parent(self, tx, user, ref):
        path = self.path(tx, user, ref).rstrip('/')
        need(path and path != '/', 'ROOT_PROTECTED')
        parent_path, _, name = path.rpartition('/')
        name = unicodedata.normalize('NFC', name)
        need(name not in ('', '.', '..') and len(name.encode()) <= 255 and '\\' not in name and '\0' not in name)
        parent = self.walk(tx, user, parent_path or '/')
        need(parent['kind'] == 'directory', 'NOT_DIRECTORY')
        self.app.auth.require(tx, user, parent, 3)
        # Check full path depth too, even though the new child does not exist yet.
        need(len([p for p in (parent_path + '/' + name).split('/') if p]) <= 32, 'LIMIT_EXCEEDED')
        return parent, name

    def entry(self, tx, node):
        value = ns.Entry(object_id=node['id'], name=node['name'],
                         kind=c.DIRECTORY if node['kind'] == 'directory' else c.FILE, revision=node['revision'])
        if node['snapshot']:
            snap = tx.get('snapshot', node['snapshot'])
            value.snapshot.CopyFrom(proto(c.SnapshotRef, snap['ref']))
            value.size_bytes = value.snapshot.size_bytes
        return value

    def Stat(self, tx, user, session, req):
        node = self.resolve(tx, user, req.path)
        self.app.auth.require(tx, user, node, 1 if node['kind'] == 'directory' else 4)
        return self.entry(tx, node)

    def List(self, tx, user, session, req):
        node = self.resolve(tx, user, req.path)
        need(node['kind'] == 'directory', 'NOT_DIRECTORY')
        self.app.auth.require(tx, user, node, 5)
        need(1 <= req.page.limit <= 100)
        need(len(req.page.cursor) <= 512, 'LIMIT_EXCEEDED')
        last = ''
        if req.page.cursor:
            try:
                cursor = json.loads(base64.urlsafe_b64decode(req.page.cursor))
                need(cursor['id'] == node['id'] and cursor['revision'] == node['revision'] and
                     cursor['user'] == user['id'], 'LIST_CHANGED')
                previous = next((n for n in tx.children(node['id']) if n['id'] == cursor['last']), None)
                need(previous, 'INVALID_ARGUMENT')
                last = previous['name']
            except (ValueError, KeyError, TypeError):
                raise Fault('INVALID_ARGUMENT') from None
        children = [n for n in tx.children(node['id']) if n['name'] > last]
        selected = children[:req.page.limit]
        cursor = '' if len(children) <= req.page.limit else base64.urlsafe_b64encode(canonical(
            dict(id=node['id'], revision=node['revision'], user=user['id'], last=selected[-1]['id']))).decode()
        return ns.ListResponse(entries=[self.entry(tx, n) for n in selected], next_cursor=cursor,
                               directory_revision=node['revision'])

    def GetAcl(self, tx, user, session, req):
        node = self.resolve(tx, user, req.path)
        self.app.auth.require(tx, user, node, 4)
        return c.Acl(owner_id=node['owner'], group_id=node['group'], owner_permissions=node['mode'] >> 6,
                     group_permissions=(node['mode'] >> 3) & 7, other_permissions=node['mode'] & 7,
                     entries=[proto(c.AclEntry, a) for a in node['acl']], authz_revision=node['revision'])

    def GetOperation(self, tx, user, session, req):
        op = tx.get('upload', req.operation_id) if req.operation_id else next((o for o in tx.all('upload')
            if o['user'] == user['id'] and o['request_id'] == req.original_request_id), None)
        need(op and op['user'] == user['id'], 'NOT_FOUND')
        result = ctl.OperationStatus(operation=proto(c.OperationRef, op['operation']), state=op['state'],
                                     expires_at_unix_ms=op['expires'])
        if op.get('result'):
            result.result.CopyFrom(proto(c.CommitResult, op['result']))
        if op.get('begin'):
            result.write_intent.CopyFrom(proto(ctl.BeginWriteRequest, op['begin']))
        return result

    def handle(self, tx, user, session, identity):
        handle = tx.get('handle', identity)
        need(handle and handle['user'] == user['id'] and handle['session'] == session['id'] and
             not handle['closed'] and handle['expires'] > now(), 'STALE_HANDLE')
        node = tx.get('node', handle['file'])
        self.app.auth.require(tx, user, node, 4)
        for ancestor in handle['ancestors']:
            self.app.auth.require(tx, user, tx.get('node', ancestor), 1)
        return handle, tx.get('snapshot', handle['snapshot'])

    def ResolveBlocks(self, tx, user, session, req):
        handle, snap = self.handle(tx, user, session, req.handle_id)
        need(asdict(req.snapshot) == snap['ref'], 'VERSION_CONFLICT')
        need(1 <= req.page.limit <= 64)
        offset = req.offset if req.HasField('offset') else 0
        length = req.length if req.HasField('length') else int(snap['ref'].get('size_bytes', 0)) - offset
        total = int(snap['ref'].get('size_bytes', 0))
        need(offset <= total and offset + length <= total)
        try:
            index = int(req.page.cursor or '0')
        except ValueError:
            raise Fault('INVALID_ARGUMENT') from None
        size = int(snap['ref']['block_size_bytes'])
        blocks = [proto(c.BlockRef, b) for b in snap['blocks'] if
                  int(b.get('block_index', 0)) * size < offset + length and
                  int(b.get('block_index', 0)) * size + int(b['size_bytes']) > offset]
        need(0 <= index <= len(blocks))
        selected = blocks[index:index + req.page.limit]
        return ctl.BlockPlan(blocks=[self.app.plan(b, user, handle, read=True, tx=tx) for b in selected],
            next_cursor=str(index + len(selected)) if index + len(selected) < len(blocks) else '',
            snapshot=req.snapshot)
