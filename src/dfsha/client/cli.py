"""CLI y shell RF1/RF2. Contraseñas por terminal/stdin, nunca como argumentos."""
import argparse
import getpass
import json
from pathlib import Path
import shlex
import sys
import grpc
from dfsha.client.sdk import Client
from dfsha.common.config import read_config
from dfsha.common.domain import asdict, proto, Fault
from dfsha.common.rpc import controlled_error
from dfsha.control.auth import protect
from dfsha.v1.identity_pb2 import Session
from dfsha.v1.control_pb2 import Handle
from dfsha.v1.common_pb2 import Fence


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument('--config', type=Path, default=Path('deploy/monolith.example.toml'))
    root.add_argument('--session-file', type=Path, default=Path('.runtime/client/session.json'))
    sub = root.add_subparsers(dest='command', required=True)
    for name in ('login', 'useradd'):
        cmd = sub.add_parser(name)
        cmd.add_argument('username')
        cmd.add_argument('--password-stdin', action='store_true')
    for name in ('pwd', 'logout', 'shell', 'nodes'):
        sub.add_parser(name)
    copy = sub.add_parser('copy-block')
    copy.add_argument('path')
    copy.add_argument('index', type=int)
    copy.add_argument('destination_node_id')
    status = sub.add_parser('copy-status')
    status.add_argument('task_id')
    status = sub.add_parser('protection')
    status.add_argument('path')
    status.add_argument('--cursor', default='')
    status = sub.add_parser('promote')
    status.add_argument('path')
    status.add_argument('revision', type=int)
    for name in ('ls', 'stat', 'cd', 'mkdir', 'rmdir', 'rm'):
        cmd = sub.add_parser(name)
        cmd.add_argument('path', nargs='?' if name in ('ls', 'stat') else None, default='.')
    cmd = sub.add_parser('chmod')
    cmd.add_argument('mode', type=lambda v: int(v, 8))
    cmd.add_argument('path')
    for name in ('send', 'put', 'receive', 'get'):
        cmd = sub.add_parser(name)
        cmd.add_argument('source')
        cmd.add_argument('destination')
        cmd.add_argument('--overwrite', action='store_true')
    cmd = sub.add_parser('open')
    cmd.add_argument('path')
    cmd.add_argument('mode', choices=('r', 'r+', 'w', 'w+', 'x', 'x+'))
    cmd.add_argument('alias', help='Nombre local del handle en el archivo de sesión')
    for name in ('close', 'renew-handle'):
        sub.add_parser(name).add_argument('alias')
    for name in ('read', 'write'):
        cmd = sub.add_parser(name)
        cmd.add_argument('alias')
        cmd.add_argument('offset', type=int)
        if name == 'read':
            cmd.add_argument('length', type=int)
            cmd.add_argument('destination', type=Path)
        else:
            cmd.add_argument('source', type=Path)
            cmd.add_argument('--request-id')
    cmd = sub.add_parser('lock')
    cmd.add_argument('alias')
    cmd.add_argument('lock_alias')
    cmd.add_argument('--whole-file', action='store_true')
    cmd.add_argument('--offset', type=int)
    cmd.add_argument('--length', type=int)
    cmd.add_argument('--wait-ms', type=int, default=0)
    for name in ('unlock', 'renew-lock'):
        sub.add_parser(name).add_argument('lock_alias')
    sub.add_parser('operation').add_argument('operation_id')
    return root


def execute(client, args):
    command = args.command
    if command == 'protection':
        return client.protection(args.path, cursor=args.cursor)
    if command == 'promote':
        return client.promote(args.path, args.revision)
    if command == 'open':
        if args.alias in client.handles:
            raise ValueError('El alias ya tiene un handle; ciérrelo primero')
        handle = client.open(args.path, args.mode)
        client.handles[args.alias] = handle
        return handle
    if command in ('close', 'renew-handle', 'read', 'write', 'lock'):
        if args.alias not in client.handles:
            raise ValueError('Alias de handle inexistente')
        handle = client.handles[args.alias]
        if command == 'close':
            result = client.close(handle)
            del client.handles[args.alias]
            return result
        if command == 'renew-handle':
            return client.renew_handle(handle)
        if command == 'lock':
            if args.lock_alias in client.fences:
                raise ValueError('Alias de lock existente')
            fence = client.lock(handle, args.offset, args.length, whole_file=args.whole_file, wait_ms=args.wait_ms)
            client.fences[args.lock_alias] = fence
            return {'lock_alias': args.lock_alias, 'generation': fence.generation}
        if command == 'write':
            from dfsha.control.leases import MAX_DELTA
            with args.source.open('rb') as stream:
                payload = stream.read(MAX_DELTA + 1)
            count = client.write(handle, args.offset, payload, request_id=args.request_id)
            return {'written': count, 'operation_id': client.last_operation.operation_id if hasattr(client, 'last_operation') else None}
        import os
        import tempfile
        descriptor, temporary = tempfile.mkstemp(prefix='.dfsha-read-', dir=args.destination.resolve().parent)
        try:
            count = 0
            with os.fdopen(descriptor, 'wb') as out:
                for chunk in client.iter_read(handle, args.offset, args.length):
                    out.write(chunk)
                    count += len(chunk)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temporary, args.destination)
            return {'read': count}
        finally:
            Path(temporary).unlink(missing_ok=True)
    if command in ('unlock', 'renew-lock'):
        if args.lock_alias not in client.fences:
            raise ValueError('Alias de lock inexistente')
        fence = client.fences[args.lock_alias]
        if command == 'renew-lock':
            client.renew_lock(fence)
            return {'generation': fence.generation}
        result = client.unlock(fence)
        del client.fences[args.lock_alias]
        return result
    if command == 'operation':
        return client.operation(args.operation_id)
    if command in ('login', 'useradd'):
        password = sys.stdin.readline().rstrip('\r\n') if args.password_stdin else getpass.getpass('Contraseña: ')
        result = client.login(args.username, password) if command == 'login' else client.create_user(args.username, password)
        return {'user_id': result.user_id}  # Never display tokens or password material.
    if command in ('send', 'put', 'receive', 'get'):
        return getattr(client, command)(args.source, args.destination, args.overwrite)
    if command == 'chmod':
        return client.chmod(args.path, args.mode)
    if command == 'copy-block':
        return client.copy_block(args.path, args.index, args.destination_node_id)
    if command == 'copy-status':
        return client.copy_status(args.task_id)
    if command == 'ls':
        return [asdict(e) for e in client.ls(args.path)]
    return getattr(client, command)(*([args.path] if hasattr(args, 'path') else []))


def main():
    root = parser()
    args = root.parse_args()
    cfg = read_config(args.config)
    state = json.loads(args.session_file.read_text(encoding='utf-8')) if args.session_file.exists() else {}
    client = Client(cfg['client']['public_target'], cfg['client'].get('certificate_dir') or cfg['server']['certificate_dir'],
                    proto(Session, state['session']) if state.get('session') else None)
    client.cwd, client.cwd_id = state.get('cwd', '/'), state.get('cwd_id', '')
    client.handles = {k: proto(Handle, v) for k, v in state.get('handles', {}).items()}
    client.fences = {k: proto(Fence, v) for k, v in state.get('locks', {}).items()}

    def save():
        if client.session:
            args.session_file.parent.mkdir(parents=True, exist_ok=True)
            protect(args.session_file.parent)
            args.session_file.write_text(json.dumps(dict(session=asdict(client.session), cwd=client.cwd,
                                                        cwd_id=client.cwd_id,
                                                        handles={k: asdict(v) for k, v in client.handles.items()},
                                                        locks={k: asdict(v) for k, v in client.fences.items()})), encoding='utf-8')
            protect(args.session_file)
        else:
            args.session_file.unlink(missing_ok=True)

    def run(command):
        result = execute(client, command)
        save()
        print(json.dumps(asdict(result) if hasattr(result, 'DESCRIPTOR') else result, ensure_ascii=False))
    try:
        if args.command == 'shell':
            while True:
                try:
                    line = input(f'dfsha:{client.cwd}> ').strip()
                    if line in ('exit', 'quit'):
                        break
                    if not line:
                        continue
                    command = root.parse_args(shlex.split(line))
                    if command.command == 'shell':
                        continue
                    run(command)
                except (EOFError, KeyboardInterrupt):
                    break
                except (grpc.RpcError, Fault, ValueError, OSError) as exc:
                    print(json.dumps(controlled_error(exc) if isinstance(exc, grpc.RpcError) else
                                     {'status': 'FALLIDO', 'reason': str(exc)}))
                except SystemExit:
                    continue
        else:
            run(args)
    except (grpc.RpcError, Fault, ValueError, OSError) as exc:
        print(json.dumps(controlled_error(exc) if isinstance(exc, grpc.RpcError) else
                         {'status': 'FALLIDO', 'reason': str(exc)}), file=sys.stderr)
        raise SystemExit(1)
    finally:
        client.shutdown()


if __name__ == '__main__':
    main()
