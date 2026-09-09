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


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument('--config', type=Path, default=Path('deploy/monolith.example.toml'))
    root.add_argument('--session-file', type=Path, default=Path('.runtime/client/session.json'))
    sub = root.add_subparsers(dest='command', required=True)
    for name in ('login', 'useradd'):
        cmd = sub.add_parser(name)
        cmd.add_argument('username')
        cmd.add_argument('--password-stdin', action='store_true')
    for name in ('pwd', 'logout', 'shell'):
        sub.add_parser(name)
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
    return root


def execute(client, args):
    command = args.command
    if command in ('login', 'useradd'):
        password = sys.stdin.readline().rstrip('\r\n') if args.password_stdin else getpass.getpass('Contraseña: ')
        result = client.login(args.username, password) if command == 'login' else client.create_user(args.username, password)
        return {'user_id': result.user_id}  # Never display tokens or password material.
    if command in ('send', 'put', 'receive', 'get'):
        return getattr(client, command)(args.source, args.destination, args.overwrite)
    if command == 'chmod':
        return client.chmod(args.path, args.mode)
    if command == 'ls':
        return [asdict(e) for e in client.ls(args.path)]
    return getattr(client, command)(*([args.path] if hasattr(args, 'path') else []))


def main():
    root = parser()
    args = root.parse_args()
    cfg = read_config(args.config)
    state = json.loads(args.session_file.read_text(encoding='utf-8')) if args.session_file.exists() else {}
    client = Client(cfg['client']['public_target'], cfg['server']['certificate_dir'],
                    proto(Session, state['session']) if state.get('session') else None)
    client.cwd, client.cwd_id = state.get('cwd', '/'), state.get('cwd_id', '')

    def save():
        if client.session:
            args.session_file.parent.mkdir(parents=True, exist_ok=True)
            protect(args.session_file.parent)
            args.session_file.write_text(json.dumps(dict(session=asdict(client.session), cwd=client.cwd,
                                                        cwd_id=client.cwd_id)), encoding='utf-8')
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
