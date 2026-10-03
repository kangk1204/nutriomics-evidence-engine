import argparse
from pathlib import Path
from nutriomics_evidence.public_expansion import run
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--root",type=Path,required=True);p.add_argument("--threads",type=int,default=2);p.add_argument("--baseline",type=Path)
    a=p.parse_args();run(a.root,a.threads,a.baseline)
