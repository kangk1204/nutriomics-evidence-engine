"""Read an in-flight response snapshot without inspecting relation scores."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('--original',type=Path,required=True);p.add_argument('--continuation',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
a=p.parse_args();lock=json.loads((a.continuation/'continuation_lock.json').read_text())
expected=set(lock['original_pmids'])|set(lock['continuation_pmids_in_source_order']);assert len(expected)==750
rows=[];snapshots=[]
for path in (a.original/'responses.jsonl',a.continuation/'residual_responses.jsonl'):
    data=path.read_bytes() if path.exists() else b''
    lines=data.split(b'\n');complete=data.endswith(b'\n') or not data
    records=[json.loads(line) for line in lines[:-1] if line]
    rows.extend(records);snapshots.append({'file':str(path),'sha256_at_read':hashlib.sha256(data).hexdigest(),'complete_last_LF':complete,'records':len(records)})
pmids=[r['pmid'] for r in rows];assert len(pmids)==len(set(pmids)) and set(pmids)<=expected
status={'asof_utc':datetime.now(timezone.utc).isoformat(),'status':'running_unscored_snapshot','documents':len(rows),'target_documents':750,
        'source_documents':snapshots,'score_artifacts_read':False,'relation_performance':None,'execution_batches':[4,8]}
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(status,indent=2));print(json.dumps(status))
