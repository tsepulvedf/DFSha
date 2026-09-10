"""Inicialización explícita; nunca reemplaza claves o bases existentes."""
import argparse
import getpass
from pathlib import Path
import sys
from dfsha.common.config import read_config
from dfsha.control.auth import initialize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['init'])
    parser.add_argument('--config', type=Path, default=Path('deploy/monolith.example.toml'))
    parser.add_argument('--username', default='admin')
    parser.add_argument('--password-stdin', action='store_true')
    args = parser.parse_args()
    cfg = read_config(args.config)
    password = sys.stdin.readline().rstrip('\r\n') if args.password_stdin else getpass.getpass('Contraseña inicial: ')
    initialize({**cfg['server'], **cfg.get('distributed', cfg.get('monolith', {}))}, args.username, password)
    print('EJECUTADO: almacenamiento inicializado; conserve la clave y los metadatos juntos en backups seguros.')


if __name__ == '__main__':
    main()
