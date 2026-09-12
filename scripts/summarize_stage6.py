"""Produce tablas legibles exclusivamente desde una medición E6 ejecutada."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=Path('docs/evidencias/etapa6/measurement-final.json'))
    parser.add_argument('--output', type=Path, default=Path('docs/evidencias/etapa6/medicion.md'))
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding='utf-8'))
    assert data['status'] == 'EJECUTADO'
    lines = ['# Medición E6: datos observados', '', f"Fuente: [{args.input.name}]({args.input.name}), {data['timestamp']}.", '',
        f"{data['bytes']} bytes, bloques de {data['block_size']} bytes, fragmentos de {data['chunk_bytes']}; R=3/W=2.",
        'Un host Windows; fallos de procesos. Una sesión SDK para esta medición; concurrencia en pruebas separadas.', '',
        f"SHA-256 original/descarga: `{data['original_sha256']}`.",
        f"SHA-256 esperado tras parche/descarga reparada: `{data['patched_expected_sha256']}`.", '',
        '## Tráfico inicial: put, tercera copia y get', '',
        'C→DN y DN→C son bytes útiles. S/S son bytes de objetos cifrados, con formato y tags, sin overhead TLS/TCP.',
        'No sumar envío y recepción S/S como si fueran copias diferentes. Se excluyen aquí parche y reparación posterior.', '',
        '| node_id / dominio administrativo | C→DN | DN→C | S/S enviado | S/S recibido |',
        '| --- | ---: | ---: | ---: | ---: |']
    domains = {c['node']['node_id']: c['node']['failure_domain'] for phase in ('before_failure', 'after_repair')
        for b in data[phase] for c in b['copies']}
    for node, row in data['transfer_traffic'].items():
        lines.append(f"| {node} / {domains[node]} | {row.get('client_write_bytes', 0)} | {row.get('client_read_bytes', 0)} | {row.get('replica_read_bytes', 0)} | {row.get('replica_write_bytes', 0)} |")
    lines += ['', f"Contenido de archivo por control: **{data['control_content_bytes']} bytes**. El control sí intercambia metadatos.", '',
        '## Parche de 4096 bytes', '',
        '| node_id | C→DN | DN→C | S/S enviado | S/S recibido | base procesada | resultado procesado | nuevo objeto cifrado local |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for node, row in data['patch_traffic'].items():
        fields = ('client_write_bytes', 'client_read_bytes', 'replica_read_bytes', 'replica_write_bytes',
            'patch_base_plaintext_processed_bytes', 'patch_result_processed_bytes', 'patch_ciphertext_stored_bytes')
        lines.append('| '+node+' | '+' | '.join(str(row.get(k, 0)) for k in fields)+' |')
    lines += ['', 'El coste interno incluye pasadas de autenticación/COW; no equivale a bytes enviados por el cliente.',
        'La lectura de validación se ejecuta después de cerrar esta ventana de contadores.', '',
        '## Copias por bloque y fase', '',
        'Antes corresponde al archivo original; degradado/reparado al archivo después del parche (cambia solo la versión del primer bloque).',
        'C es historial de confirmaciones; E son copias actualmente elegibles. Una copia no elegible se marca con ×.',
        'Las identidades abreviadas se resuelven en la tabla anterior o en el JSON; cada dominio es process-node_id.', '',
        '| Fase | Índice | block_version_id | R | C | E | Nodos (elegibilidad) | tareas pendientes |',
        '| --- | ---: | --- | ---: | ---: | ---: | --- | ---: |']
    for phase, label in (('before_failure', 'antes'), ('degraded', 'caído'), ('after_repair', 'reparado')):
        for b in data[phase]:
            nodes = ', '.join(x['node']['node_id'][:8]+('' if x.get('eligible') else ' ×') for x in b['copies'])
            lines.append(f"| {label} | {b['block'].get('block_index', 0)} | {b['block']['block_version_id']} | {b['target']} | {b.get('confirmed', 0)} | {b.get('eligible', 0)} | {nodes} | {b.get('pending_tasks', 0)} |")
    lines += ['', '## Tiempos y memoria', '', '| Medición | Segundos |', '| --- | ---: |']
    for key in ('upload_seconds', 'download_seconds', 'patch_commit_seconds', 'detect_seconds_from_stop',
                'alternate_seconds_from_open', 'repair_seconds_from_fourth_start'):
        lines.append(f'| {key} | {data[key]:.3f} |')
    lines += ['', data['memory_method'], 'El nodo detenido se mide antes de su salida; los demás al finalizar. No son máximos de todos los perfiles.', '',
        '| Proceso / node_id | PID real | Máximo residente MiB |', '| --- | ---: | ---: |']
    for label, row in [('cliente', data['memory']['client']), ('control', data['memory']['control'])] + [(x['node_id'], x) for x in data['memory']['datanodes']]:
        lines.append(f"| {label} | {row['pid']} | {row['peak_resident_bytes']/1048576:.2f} |")
    args.output.write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print(args.output)


if __name__ == '__main__':
    main()
