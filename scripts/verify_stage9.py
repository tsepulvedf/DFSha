"""E9 recoverable local checks or scoped external functional check; never fabricates cloud acceptance."""
import argparse
from datetime import datetime, timezone
import getpass
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import tomllib
from uuid import uuid4

from runtime import ROOT
from verify_stage8 import atomic_json, sources


def external(args, report, checkpoint):
    from cloud_bundle import validate, attest
    from dfsha.client.sdk import Client
    from dfsha.common.domain import CHUNK
    from measure_stage6 import full
    inventory=validate(json.loads(args.inventory.read_text()))
    attest(inventory,json.loads(args.preflight.read_text()))
    cfg=tomllib.loads(args.config.read_text())['client']
    expected=[n['public_host']+':7443' for n in sorted(inventory['nodes'],key=lambda n:n['slot'])]
    if cfg.get('public_targets')!=expected:raise ValueError('Use entradas públicas del inventario verificado')
    if not args.username or not args.remote_dir or not args.client_origin:
        raise ValueError('Exigir usuario ordinario, directorio autorizado y descripción del cliente externo')
    client=Client(expected,cfg['certificate_dir'])
    password=getpass.getpass('Contraseña del usuario ordinario: ')
    client.login(args.username,password);del password
    directory=ROOT/'.runtime/verification-e9'/report['run_id'];directory.mkdir(parents=True,exist_ok=True)
    remote=args.remote_dir.rstrip('/')+'/e9-'+report['run_id']
    report['client_origin_declared']=args.client_origin
    report['external_scope']='RF1/RF2/RF3 and client bytes only; VM failure, host telemetry and backup are separate pending cases'
    report['resolved_endpoints']={h:socket.gethostbyname(h) for h in [n['public_host'] for n in inventory['nodes']]}
    try:
        client.mkdir(remote);client.cd(remote)
        source=directory/'source.bin';dest=directory/'download.bin'
        with source.open('wb') as out:
            pattern=bytes(range(256))*(CHUNK//256)
            for _ in range(536870912//CHUNK):out.write(pattern)
        def sha(path):
            with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
        original=sha(source);checkpoint('source_ready')
        start=time.monotonic();client.send(source,'large');report['upload_seconds']=time.monotonic()-start
        report['copies_before']=full(client,'large');checkpoint('R3')
        domains={n['node_id']:n['vm_id'] for n in inventory['nodes']}
        for block in report['copies_before']:
            observed={copy['node']['node_id']:copy['node']['failure_domain'] for copy in block['copies'] if copy.get('eligible')}
            if observed!=domains:raise ValueError('Copias no corresponden a los tres hosts inventariados')
        start=time.monotonic();client.receive('large',dest);report['download_seconds']=time.monotonic()-start
        if sha(dest)!=original:raise ValueError('DOWNLOAD_HASH_MISMATCH')
        report['sha256']=original;report['initial_client_traffic']=json.loads(json.dumps(client.traffic))
        if sum(v['client_write_bytes']>0 and v['client_read_bytes']>0 for v in client.traffic.values())<2:
            raise ValueError('No se demuestra tráfico útil en dos DN')
        reader=client.open('large','r');writer=client.open('large','r+')
        offset=writer.snapshot.block_size_bytes//2
        before=client.read(reader,offset,4096)
        lock=client.lock(writer,offset,4096)
        try:
            before_bytes=sum(v['client_write_bytes'] for v in client.traffic.values())
            start=time.monotonic();assert client.write(writer,offset,b'P'*4096,fences=(lock,))==4096
            report['patch_seconds']=time.monotonic()-start
            report['patch_client_bytes']=sum(v['client_write_bytes'] for v in client.traffic.values())-before_bytes
            assert report['patch_client_bytes']==4096
        finally:client.unlock(lock)
        assert client.read(reader,offset,4096)==before
        assert client.read(writer,offset,4096)==b'P'*4096
        client.close(reader);client.close(writer)
        with source.open('r+b') as out:out.seek(offset);out.write(b'P'*4096)
        client.receive('large',dest,overwrite=True)
        assert sha(dest)==sha(source)
        report['patched_sha256']=sha(dest);report['copies_after']=full(client,'large')
        report['client_traffic']=client.traffic
        report['server_to_server_bytes']=None;report['control_file_content_bytes_measured']=None
        report['status']='EXTERNAL_FUNCTIONAL_SCOPE_PASSED_E9_PENDING'
        report['pending']=['Provider VM stop/failover/rejoin','host/process metrics and S/S counters',
            'negative authorizations and group administration','cloud encrypted backup/restore','majority loss/recovery']
        checkpoint('functional_finished')
    finally:client.shutdown()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    mode=p.add_mutually_exclusive_group(required=True);mode.add_argument('--local',action='store_true');mode.add_argument('--external',action='store_true')
    for name in ('config','inventory','preflight'):p.add_argument('--'+name,type=Path)
    for name in ('username','remote-dir','client-origin'):p.add_argument('--'+name)
    args=p.parse_args()
    run=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+str(uuid4())[:8]
    directory=ROOT/'docs/evidencias/etapa9'/run;directory.mkdir(parents=True)
    private=ROOT/'.runtime/verification-e9'/run;private.mkdir(parents=True)
    report=dict(run_id=run,start=datetime.now(timezone.utc).isoformat(),end=None,status='EN_CURSO',
        argv=sys.argv,source_sha256=sources(),commands=[],cloud_resources_created=[],supervisor_exit_code=None)
    def checkpoint(phase):
        report['phase']=phase;atomic_json(directory/'result.json',report)
        print(json.dumps(dict(run_id=run,phase=phase)),flush=True)
    checkpoint('starting');code=1
    try:
        if args.local:
            commands=[[sys.executable,'-m','pip','check'],[sys.executable,'scripts/generate_proto.py','--check'],
                [sys.executable,'-m','pytest','-v','tests/test_stage9_deployment.py','tests/test_transport.py',
                 'tests/test_stage8_storage.py','tests/test_stage8_gate_recovery.py','-p','stage8_journal',
                 '--junitxml='+str(private/'pytest.xml')]]
            env=dict(os.environ,PYTHONUTF8='1',PYTHONUNBUFFERED='1',PYTHONPATH=str(ROOT/'scripts'),DFSHA_TEST_JOURNAL=str(directory/'cases.jsonl'))
            for i,command in enumerate(commands):
                row=dict(argv=command,exit_code=None);report['commands'].append(row);checkpoint('command_start')
                with (private/f'command-{i+1}.log').open('wb') as log:
                    process=subprocess.Popen(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
                    row['pid']=process.pid;checkpoint('command_running');row['exit_code']=process.wait()
                checkpoint('command_finished')
                if row['exit_code']:raise RuntimeError('LOCAL_CHECK_FAILED')
            report['status']='LOCAL_APROBADO_CLOUD_BLOQUEADO'
        else:external(args,report,checkpoint)
        code=0
    except (Exception,KeyboardInterrupt) as exc:
        report['status']='INTERRUMPIDO' if isinstance(exc,KeyboardInterrupt) else 'FALLIDO'
        report['error_type']=type(exc).__name__  # No tokens/passwords/full RPC exception payload.
    finally:
        report['end']=datetime.now(timezone.utc).isoformat();report['source_unchanged']=report['source_sha256']==sources()
        if not report['source_unchanged']:report['status']='CODE_CHANGED';code=1
        report['intended_exit_code']=code  # Wrapper records actual process exit separately.
        checkpoint('finished')
    return code


if __name__=='__main__':raise SystemExit(main())
