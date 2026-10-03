"""Bounded direct-SSH transport for explicit owned files and small receipts."""
import argparse
import base64
import io
from pathlib import Path,PurePosixPath
import shlex
import subprocess
import tarfile

BASE=Path('C:/Projects/00_NutriGenomics_auto')
HOSTS={'gpu':('keunsoo4070@100.93.148.94','/home/keunsoo4070/projects/nutriomics-phase1-20261003'),
       'cpu':('keunsoo@100.82.52.41','/home/keunsoo/projects/nutriomics-2026-final/nutriomics-htn-methylation')}


def remote(host,code,data=None,interpreter='python3'):
    encoded=base64.b64encode(code.encode()).decode()
    command=shlex.quote(interpreter)+' -c '+shlex.quote("import base64;exec(base64.b64decode('"+encoded+"'))")
    result=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=8',HOSTS[host][0],command],input=data,capture_output=True,timeout=120)
    if result.returncode:
        error=result.stderr.decode(errors='replace')+result.stdout.decode(errors='replace')
        raise RuntimeError('\n'.join(line for line in error.splitlines() if 'base64.b64decode(' not in line))
    return result.stdout


def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['upload','collect']);p.add_argument('--host',choices=HOSTS,default='gpu')
    p.add_argument('--files',nargs='*',default=[]);p.add_argument('--base',type=Path,default=BASE);p.add_argument('--directory');p.add_argument('--destination',type=Path);a=p.parse_args()
    root=HOSTS[a.host][1]
    if a.mode=='upload':
        buffer=io.BytesIO()
        with tarfile.open(fileobj=buffer,mode='w:gz') as archive:
            for item in a.files:
                path=Path(item).resolve();archive.add(path,arcname=path.relative_to(a.base.resolve()).as_posix())
        code=f"import sys,tarfile,io; t=tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read())); t.extractall({root!r},filter='data'); print('uploaded',len(t.getmembers()))"
        print(remote(a.host,code,buffer.getvalue()).decode())
    else:
        directory=PurePosixPath(a.directory)
        if not directory.as_posix().startswith(root+'/') or '..' in directory.parts:raise ValueError('Unauthorized collection root')
        code=f"import sys,tarfile; t=tarfile.open(fileobj=sys.stdout.buffer,mode='w|gz'); t.add({str(directory)!r},arcname={directory.name!r},filter=lambda m:None if m.issym() or m.islnk() or '/selected_model' in m.name or m.name.endswith(('.pt','.bin','.safetensors')) else m); t.close()"
        data=remote(a.host,code);a.destination.mkdir(parents=True,exist_ok=True)
        tarfile.open(fileobj=io.BytesIO(data)).extractall(a.destination,filter='data');print('collected bytes',len(data))


if __name__=='__main__':main()
