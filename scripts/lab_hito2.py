"""Preparar, arrancar y detener exclusivamente un laboratorio E4 identificado por su raíz."""
import argparse
import json
from pathlib import Path
from hito2_runtime import Cluster
from runtime import wait_until


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('init', 'start', 'add-fourth', 'status', 'stop'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--block-size', type=int, choices=(4194304, 67108864, 134217728), default=4194304)
    parser.add_argument('--rf3', action='store_true', help='Activar RF3 E5 en una raíz nueva; H2 histórico permanece reproducible')
    parser.add_argument('--replication', action='store_true', help='E6 R3/W2 con dominios simulados de proceso')
    args = parser.parse_args()
    if args.command == 'init':
        app = Cluster(args.root, block_size=args.block_size, rf3=args.rf3, replication=args.replication)
        print(json.dumps(dict(status='EJECUTADO', config=str(app.control.config), client_ca=str(app.certs),
            note='Usuario admin; contraseña development-password, exclusiva de este laboratorio local')))
        return
    app = Cluster.load(args.root)
    if args.command in ('start', 'add-fourth'):
        if args.command == 'start':
            app.start()
        else:
            app.nodes[3].start()
            client = app.client()
            try:
                identity = app.nodes[3].info['node_id']
                wait_until(lambda: any(x.node.node_id == identity and x.state == 'READY' and
                    x.node.boot_generation == app.nodes[3].info['generation'] for x in app.statuses(client).nodes), seconds=45)
            finally:
                client.shutdown()
        print(json.dumps(dict(status='EJECUTADO', target=app.target, root=str(app.directory))))
    elif args.command == 'stop':
        processes = app.nodes + [app.control]
        for process in processes:
            if process.ready.exists():
                process.stop_file.touch()
        wait_until(lambda: all(not p.ready.exists() for p in processes), seconds=30)
        print('EJECUTADO: procesos del laboratorio detenidos; datos conservados')
    else:
        client = app.client()
        try:
            from dfsha.common.domain import asdict
            print(json.dumps(asdict(app.statuses(client)), indent=2))
        finally:
            client.shutdown()


if __name__ == '__main__':
    main()
