"""Stream explicitly named staging files over verified Tailscale SSH.

Only the isolated public_expansion directory is writable on the destination.
"""
import argparse
import base64
import json
from pathlib import Path
import shlex
import subprocess
import tarfile

HOST = "keunsoo4070@keunsoo4070-z790-aorus-elite-ax"
DESTINATION = "/home/keunsoo4070/projects/nutriomics-phase1-20261003/public_expansion"

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--files", nargs="+", required=True)
    args=p.parse_args()
    paths=[args.root / name for name in args.files]
    for path in paths:
        if not path.is_file() or not path.resolve().is_relative_to(args.root.resolve()):
            raise ValueError(f"not a staging file: {path}")
    remote = f"""import sys,tarfile,pathlib,hashlib,json
root=pathlib.Path({DESTINATION!r});root.mkdir(parents=True,exist_ok=True)
names=[]
with tarfile.open(fileobj=sys.stdin.buffer,mode='r|') as archive:
 for item in archive:
  resolved=(root/item.name).resolve()
  if not resolved.is_relative_to(root.resolve()) or not item.isfile():raise ValueError('unsafe archive member')
  archive.extract(item,root,filter='data');names.append(item.name)
print(json.dumps(dict(destination=str(root),files=names)))
"""
    command="python3 -c "+shlex.quote("import base64;exec(base64.b64decode('"+base64.b64encode(remote.encode()).decode()+"'))")
    process=subprocess.Popen(["tailscale","ssh",HOST,command], stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        with tarfile.open(fileobj=process.stdin,mode="w|") as archive:
            for path in paths:
                archive.add(path,arcname=path.relative_to(args.root).as_posix(),recursive=False)
        process.stdin.close(); process.stdin=None
        stdout,stderr=process.communicate(timeout=1800)
    except Exception:
        if process.stdin:
            try:process.stdin.close()
            except OSError:pass
            process.stdin=None
        if process.poll() is None:process.kill()
        stdout,stderr=process.communicate(timeout=15)
        print(stdout.decode(errors="replace"));print(stderr.decode(errors="replace"))
        raise
    print(stdout.decode(errors="replace"));print(stderr.decode(errors="replace"))
    return process.returncode

if __name__=="__main__":raise SystemExit(main())
