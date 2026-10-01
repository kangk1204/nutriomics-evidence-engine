"""Freeze the existing literature-service prototype into a separate evidence view."""
import argparse
import json
from pathlib import Path
from nutriomics_evidence.literature_bridge import import_snapshot

if __name__ == '__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--report',type=Path,required=True)
    p.add_argument('--expected-sha256',required=True)
    p.add_argument('--database',type=Path,required=True)
    p.add_argument('--previous-manifest',type=Path)
    p.add_argument('--deployment',type=Path)
    p.add_argument('--receipt',type=Path,required=True)
    a=p.parse_args()
    result=import_snapshot(a.report,a.database,expected_sha256=a.expected_sha256,
        previous_manifest=a.previous_manifest,deployment=a.deployment)
    a.receipt.parent.mkdir(parents=True,exist_ok=True)
    a.receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('papers','imported_current_assertions','approved_assertions','overlap')}))
