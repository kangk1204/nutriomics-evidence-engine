"""Execute the selected model's source-offset adapter on the approved host."""
from pathlib import Path
from transfer_owned import remote,HOSTS

root=HOSTS['gpu'][1]
code=f"""import pathlib,sys,json,hashlib,torch
root=pathlib.Path({root!r});repo=root/'final_2026/repos/nutriomics-evidence-engine';sys.path.insert(0,str(repo/'src'))
from nutriomics_evidence.neural_ner import NeuralGeneMentionProvider
torch.set_num_threads(2);out=root/'final_2026/expansion_20261003/nlp/ner_v1'
if not (out/'result.json').exists():raise RuntimeError('Wait for the immutable selected model and final evaluation')
provider=NeuralGeneMentionProvider(out/'selected_model',device='cpu')
short='α: This source mentions ACE and AGT, together with tumor necrosis factor.'
long=('A neutral source sentence is included for coverage. '*80)+short
rows=[]
for name,text in [('unicode_short',short),('long_source',long)]:
    mentions=provider.extract(text)
    if not all(text[m['start']:m['end']]==m['text'] for m in mentions):raise ValueError('Source-offset integrity failed')
    rows.append({{'input':name,'source_text':text,'source_sha256':hashlib.sha256(text.encode()).hexdigest(),'characters':len(text),'mentions':mentions,'offsets_match_source':True}})
result={{'device':'cpu','CPU_threads':2,'model_sha256':json.loads((out/'result.json').read_text())['model_sha256'],'adapter_sha256':hashlib.sha256((repo/'src/nutriomics_evidence/neural_ner.py').read_bytes()).hexdigest(),'software_offset_smoke_only_not_accuracy_validation':True,'cases':rows}}
(out/'inference_smoke.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({{'offset_checks_passed':True,'mentions':[len(r['mentions']) for r in rows]}}))
"""
print(remote('gpu',code,interpreter=root+'/nlp/.venv/bin/python').decode())
