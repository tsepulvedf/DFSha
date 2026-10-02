"""Install/refresh only the dedicated academy profile; prompt secrets without echo."""
import argparse
import configparser
import getpass
import io
import os
from pathlib import Path
import re
from dfsha.control.auth import protect


def save(home, region, access, secret, token, refresh=False):
    if not re.fullmatch(r'[a-z]{2}-[a-z]+-\d', region):
        raise ValueError('Region explicita requerida')
    if not all(v.strip() and '\n' not in v and '\r' not in v for v in (access,secret,token)):
        raise ValueError('Credenciales temporales completas requeridas; nunca omitir token')
    root=Path(home)/'.aws';root.mkdir(exist_ok=True);protect(root)
    updates=[]
    for name,section,values in (
        ('credentials','academy',dict(aws_access_key_id=access,aws_secret_access_key=secret,aws_session_token=token)),
        ('config','profile academy',dict(region=region,output='json'))):
        path=root/name
        if path.is_symlink():raise ValueError('No seguir enlaces de credenciales')
        parser=configparser.RawConfigParser();parser.read(path)
        if parser.has_section(section) and not refresh:raise ValueError('Perfil existente: revisar; --refresh solo tras identificar Academy')
        if parser.has_section(section):parser.remove_section(section)
        parser.add_section(section)
        for key,value in values.items():parser.set(section,key,value)
        text=io.StringIO();parser.write(text);updates.append((path,text.getvalue()))
    # Preserve all other profile values. ConfigParser normalizes comments/spacing.
    for path,text in updates:
        pending=path.with_name(path.name+'.dfsha-pending')
        with pending.open('x',encoding='utf-8') as stream:
            protect(pending);stream.write(text);stream.flush();os.fsync(stream.fileno())
        os.replace(pending,path);protect(path)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--region',required=True)
    p.add_argument('--refresh',action='store_true');a=p.parse_args()
    save(Path.home(),a.region,getpass.getpass('AWS access key (oculto): '),
         getpass.getpass('AWS secret key (oculto): '),getpass.getpass('AWS session token (oculto): '),a.refresh)
    print('Perfil academy escrito fuera de Git; acceso y cuenta aun requieren preflight.')
