"""Stop only the designated inference PID at a complete flushed batch checkpoint."""
import argparse
import json
import os
from pathlib import Path
import signal
import time
from run_qwen_continuation import read_responses
from nutriomics_evidence.extraction import load_drugprot

p=argparse.ArgumentParser();p.add_argument('--pid',type=int,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--abstracts',type=Path,required=True);p.add_argument('--entities',type=Path,required=True)
a=p.parse_args();cohort=[d['pmid'] for d in load_drugprot(a.abstracts,a.entities)]
cmd=(Path('/proc')/str(a.pid)/'cmdline').read_bytes().replace(b'\0',b' ').decode()
if 'scripts/run_qwen.py infer' not in cmd or str(a.out) not in cmd:
    raise ValueError('PID is not the explicitly designated original inference')
for _ in range(200):
    os.kill(a.pid,signal.SIGSTOP)
    try:
        rows=read_responses(a.out/'responses.jsonl',set(cohort))
        complete=bool(rows) and len(rows)%4==0 and set(rows)==set(cohort[:len(rows)])
    except (ValueError,json.JSONDecodeError):
        complete=False
    if complete:
        # SIGTERM remains pending while stopped; SIGCONT delivers it before the
        # Python program continues, preserving the checked original checkpoint.
        os.kill(a.pid,signal.SIGTERM);os.kill(a.pid,signal.SIGCONT)
        print(json.dumps({'stopped_pid':a.pid,'flushed_batch4_documents':len(rows),'checkpoint_mutated':False}))
        break
    os.kill(a.pid,signal.SIGCONT);time.sleep(.05)
else:
    raise RuntimeError('Could not obtain a complete checkpoint; original process left running')
