"""Record counts from a completed run; never invent execution or model metrics."""
from __future__ import annotations
import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from nutriomics_evidence.graph import connect,validate
from nutriomics_evidence.sources import atomic_json,now,sha256


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--database',type=Path)
    parser.add_argument('--ctd-audit',type=Path)
    parser.add_argument('--junit',type=Path)
    parser.add_argument('--drugprot-evaluation',type=Path)
    parser.add_argument('--output',type=Path,default=Path('docs/validated_snapshot.json'))
    args=parser.parse_args()
    manifest=json.loads(args.manifest.read_text(encoding='utf-8'))
    result={'schema_version':1,'recorded_at':now(),'status':'actual_run_artifact_counts',
            'ctd':{name:{key:row[key] for key in ('sha256','bytes','rows','version','report_created','gzip_crc','parquet_sha256')}
                   for name,row in manifest['files'].items()},
            'clinical_validation_performed':False,'patient_multiomics_fusion_performed':False,
            'structure_name_matches_promoted_to_exact':0,'direct_binding_labels_from_CTD':0}
    if args.database:
        db=connect(args.database,readonly=True)
        try:
            result['graph']=validate(db)
            result['graph']['database_sha256']=sha256(args.database)
            result['graph']['node_kinds']={row[0]:row[1] for row in db.execute('SELECT kind,count(*) FROM node GROUP BY kind')}
            result['graph']['measurement_status']={row[0]:row[1] for row in db.execute('SELECT status,count(*) FROM measurement GROUP BY status')}
        finally:db.close()
    if args.ctd_audit:
        result['ctd_all_files_audit']=json.loads(args.ctd_audit.read_text(encoding='utf-8'))
        result['ctd_all_files_audit'].pop('source_dir',None)
    if args.junit:
        suites=list(ET.parse(args.junit).getroot().iter('testsuite'))
        if not suites:raise ValueError('JUnit has no test suites')
        result['tests']={key:sum(int(suite.attrib.get(key,0)) for suite in suites) for key in ('tests','failures','errors','skipped')}
        result['tests']['junit_sha256']=sha256(args.junit)
        result['tests']['passed']=result['tests']['tests']-result['tests']['failures']-result['tests']['errors']-result['tests']['skipped']
    if args.drugprot_evaluation:
        result['drugprot']=json.loads(args.drugprot_evaluation.read_text(encoding='utf-8'))
    else:result['drugprot']={'real_corpus_evaluation_recorded':False,'qwen_inference_recorded':False}
    atomic_json(args.output,result)
    print(json.dumps({'output':str(args.output),'ctd_files':len(result['ctd']),'tests':result.get('tests'),'graph':result.get('graph')},indent=2))


if __name__=='__main__':main()
