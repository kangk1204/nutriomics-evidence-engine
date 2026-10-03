"""Launch only authorized fresh NER or resumed endocrine jobs on known hosts."""
import argparse
import json
from pathlib import Path
from transfer_owned import remote,HOSTS


def main():
    p=argparse.ArgumentParser();p.add_argument('job',choices=['ner','endocrine']);a=p.parse_args()
    if a.job=='ner':
        root=HOSTS['gpu'][1]
        code=f"""import pathlib,subprocess,os,json
root=pathlib.Path({root!r}); out=root/'final_2026/expansion_20261003/nlp/ner_v1'
if out.exists():raise RuntimeError('Existing immutable NER directory; inspect existing PID, never duplicate restart')
doc=root/'final_2026/repos/nutriomics-evidence-engine/docs/biomed_ner_20261003_v1';doc.mkdir(parents=True,exist_ok=True)
env=dict(os.environ,OMP_NUM_THREADS='2',MKL_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2',TOKENIZERS_PARALLELISM='false')
cmd=[str(root/'nlp/.venv/bin/python'),str(root/'final_2026/repos/nutriomics-evidence-engine/scripts/run_biomed_ner.py'),'--raw',str(root/'final_2026/expansion_20261003/nlp/raw'),'--out',str(out),'--epochs','5']
log=doc/'run.log'; process=subprocess.Popen(cmd,cwd=root,env=env,stdout=log.open('ab'),stderr=subprocess.STDOUT,start_new_session=True)
receipt={{'job':'bc2gm_five_epoch_ner','pid':process.pid,'log':str(log),'output':str(out),'gpu_token_released_by':'dti_extension','max_VRAM_fraction':.36,'CPU_threads':2,'command':cmd}}
(doc/'job_receipt.json').write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt))
"""
        result=remote('gpu',code)
    else:
        root=HOSTS['cpu'][1]
        code=f"""import pathlib,subprocess,os,json,shlex,datetime
root=pathlib.Path({root!r}); out=root/'artifacts/endocrine_extension_20261003_v1'
if out.exists():raise RuntimeError('Existing immutable endocrine result directory; inspect existing PID')
raw=root/'data/endocrine_ranges_20261003_v2';log=root/'data/endocrine_ranges_20261003_v2.log'
for proc in pathlib.Path('/proc').iterdir():
 if not proc.name.isdigit() or int(proc.name)==os.getpid():continue
 try:tokens=(proc/'cmdline').read_bytes().decode(errors='replace').split(chr(0))
 except OSError:continue
 if any(pathlib.PurePosixPath(token).name in ('download_endocrine_ranges.py','run_endocrine_extension.py') for token in tokens):
  raise RuntimeError('Owned acquisition or analysis already live: PID '+proc.name)
stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
previous_status=json.loads((raw/'range_acquisition_status.json').read_text()) if (raw/'range_acquisition_status.json').exists() else None
old_receipt=root/'data/endocrine_ranges_20261003_v2_job.json'
if old_receipt.exists():(root/('data/endocrine_ranges_20261003_v2_job_previous_'+stamp+'.json')).write_bytes(old_receipt.read_bytes())
if previous_status:(raw/('range_acquisition_status_previous_'+stamp+'.json')).write_text(json.dumps(previous_status,indent=2))
python=root.parent/'.venv/bin/python';env=dict(os.environ,OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
download=[str(python),str(root/'scripts/download_endocrine_ranges.py'),'--output',str(raw),'--threads','2','--chunk-mib','8']
analyse=[str(python),str(root/'scripts/run_endocrine_extension.py'),'--raw',str(raw/'BetaValue_Raw.txt'),'--metadata',str(root/'data/extensions_20261003_v1/sample_characteristics.xlsx'),'--output',str(out)]
command=shlex.join(download)+' && '+shlex.join(analyse)
process=subprocess.Popen(command,shell=True,executable='/bin/bash',cwd=root,env=env,stdout=log.open('ab'),stderr=subprocess.STDOUT,start_new_session=True)
receipt={{'job':'endocrine_ranges_then_center_nested','supervisor_pid':process.pid,'started_utc':stamp,'prior_gpu_download_pid':2186079,'prior_gpu_pid_dead_verified':True,'prior_partial_bytes':109051904,'resumed_previous_status':previous_status,'active_owned_process_guard_passed':True,'log':str(log),'raw_directory':str(raw),'output':str(out),'download_threads':2,'analysis_threads':1,'command':command}}
(root/'data/endocrine_ranges_20261003_v2_job.json').write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt))
"""
        result=remote('cpu',code)
    text=result.decode();print(text)
    target=Path(__file__).resolve().parent/(a.job+'_job_receipt.json');target.write_text(text,encoding='utf-8')


if __name__=='__main__':main()
