"""Official BC2GM sentence split, text-duplicate audit and dev-only neural selection.

PMIDs are absent in this authorized IOB distribution: document independence and
pretraining overlap cannot be asserted. Report sentence/span results accordingly.
"""
import argparse,hashlib,json,random,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from nutriomics_evidence.neural_data import sha,write_json
from nutriomics_evidence.token_evaluation import span_metrics,encode_word_chunks,reconstruct_word_predictions

MODEL='microsoft/BiomedNLP-BiomedBERT-base-uncased-abstract-fulltext'
REVISION='e1354b7a3a09615f6aba48dfad4b7a613eef7062'
LABELS=['O','B-GENE','I-GENE']


def read_iob(path,include_labels=True):
    rows=[];words=[];labels=[]
    for line in path.read_text(encoding='utf-8').splitlines()+['']:
        if not line.strip():
            if words:rows.append({'words':words,'labels':labels,'sentence_sha256':hashlib.sha256(' '.join(words).lower().encode()).hexdigest()})
            words=[];labels=[];continue
        word,label=line.rsplit('\t',1)
        if include_labels and label not in LABELS:raise ValueError('Unknown native BC2GM tag')
        words.append(word);labels.append(label if include_labels else 'O')
    return rows


def main():
    p=argparse.ArgumentParser();p.add_argument('--raw',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--epochs',type=int,default=5);a=p.parse_args()
    if a.epochs!=5:raise ValueError('The frozen protocol requires five epochs')
    if a.out.exists():raise FileExistsError('Use a new immutable run directory')
    a.out.mkdir(parents=True)
    data={k:read_iob(a.raw/f'bc2gm_{native}.tsv',include_labels=k!='test') for k,native in [('train','train'),('dev','devel'),('test','test')]}
    # Ignore final native annotation fields during text-only duplicate auditing.
    # Gold annotations are interpreted only after selected predictions are fixed.
    hashes={k:{r['sentence_sha256'] for r in rows} for k,rows in data.items()}
    duplicate_audit={'original_sentences':{k:len(v) for k,v in data.items()},
      'unique_lowercase_sentence_texts':{k:len(v) for k,v in hashes.items()},
      'within_split_duplicate_sentences':{k:len(data[k])-len(hashes[k]) for k in data},
      'original_cross_split_intersections':{f'{x}_{y}':len(hashes[x]&hashes[y]) for x,y in [('train','dev'),('train','test'),('dev','test')]},
      'normalization':'lowercase space-joined native tokens; does not detect paraphrases or article/pretraining overlap'}
    rejected={k:0 for k in data}
    for k,exclude in [('train',hashes['dev']|hashes['test']),('dev',hashes['test'])]:
        kept=[r for r in data[k] if r['sentence_sha256'] not in exclude];rejected[k]=len(data[k])-len(kept);data[k]=kept
    duplicate_audit['excluded_sentences']=rejected
    duplicate_audit['retained_sentences']={k:len(v) for k,v in data.items()}
    duplicate_audit['within_test_duplicates_retained_not_independent_documents']=True
    write_json(a.out/'duplicate_audit.json',duplicate_audit)
    import numpy as np,torch
    from torch.utils.data import DataLoader
    from transformers import AutoTokenizer,AutoModelForTokenClassification,DataCollatorForTokenClassification
    random.seed(20261003);np.random.seed(20261003);torch.manual_seed(20261003);torch.set_num_threads(2)
    if not torch.cuda.is_available():raise RuntimeError('This protocol requires the approved GPU')
    torch.cuda.set_per_process_memory_fraction(.36);device='cuda'
    tok=AutoTokenizer.from_pretrained(MODEL,revision=REVISION)
    model=AutoModelForTokenClassification.from_pretrained(MODEL,revision=REVISION,num_labels=3,id2label=dict(enumerate(LABELS)),label2id={x:i for i,x in enumerate(LABELS)}).to(device)
    # Preserve whole sentences; no silent truncation. Split long inputs at native
    # word boundaries with explicit word indices, then reconstruct exact spans.
    def encoded(rows,use_gold):return encode_word_chunks(tok,rows,LABELS,use_gold,max_tokens=254)
    train=encoded(data['train'],True);dev=encoded(data['dev'],False)
    collator=DataCollatorForTokenClassification(tok)
    def predict(pieces,rows):
        model.eval();predicted_chunks=[]
        with torch.inference_mode():
            for start in range(0,len(pieces),8):
                group=pieces[start:start+8];batch=collator([r['features'] for r in group]);batch.pop('labels')
                with torch.autocast('cuda',dtype=torch.bfloat16):logits=model(**{k:v.to(device) for k,v in batch.items()}).logits
                predicted_chunks.extend(logits.argmax(-1).cpu().tolist())
        return reconstruct_word_predictions(rows,pieces,predicted_chunks,LABELS)
    protocol={'protocol_id':'bc2gm-biomedbert-20261003-v1','model':MODEL,'revision':REVISION,'seed':20261003,'epochs':a.epochs,
      'learning_rate':2e-5,'batch':4,'gradient_accumulation':4,'max_wordpieces':254,
      'source_sha256':{k:sha(a.raw/f'bc2gm_{native}.tsv') for k,native in [('train','train'),('dev','devel'),('test','test')]},
      'sentences':{k:len(r) for k,r in data.items()},'duplicate_sentences_excluded':rejected,
      'original_pmids_available':False,'document_overlap_verifiable':False,'pretraining_overlap_known':False,
      'selection':'maximum development exact-span F1','evaluation_unit':'official-split sentence and exact gene span',
      'torch':torch.__version__,'gpu':torch.cuda.get_device_name(0),'code_sha256':sha(Path(__file__)),
      'evaluation_code_sha256':sha(Path(__file__).resolve().parents[1]/'src/nutriomics_evidence/token_evaluation.py'),
      'chunking':'complete words, no overlap; checked coverage; reconstructed first-wordpiece labels across whole native sentences',
      'training_chunks':len(train),'development_chunks':len(dev),'training_words':sum(len(r['words']) for r in data['train']),
      'runtime':{'numpy':np.__version__,'transformers':__import__('transformers').__version__,'python':sys.version},
      'precision':'CUDA bfloat16 autocast; FP32 optimizer parameters','VRAM_fraction_cap':.36,'CPU_threads':2}
    write_json(a.out/'protocol.json',protocol)
    loader=DataLoader([x['features'] for x in train],batch_size=4,shuffle=True,collate_fn=collator,generator=torch.Generator().manual_seed(20261003))
    opt=torch.optim.AdamW(model.parameters(),lr=2e-5,weight_decay=.01);best=-1.;history=[];began=time.time()
    for epoch in range(a.epochs):
        model.train();opt.zero_grad();losses=[]
        for step,batch in enumerate(loader):
            accumulation=min(4,len(loader)-(step//4)*4)
            with torch.autocast('cuda',dtype=torch.bfloat16):raw_loss=model(**{k:v.to(device) for k,v in batch.items()}).loss;loss=raw_loss/accumulation
            loss.backward();losses.append(float(raw_loss.detach()))
            if (step+1)%4==0 or step+1==len(loader):torch.nn.utils.clip_grad_norm_(model.parameters(),1.);opt.step();opt.zero_grad()
        devpred=predict(dev,data['dev']);metrics=span_metrics([r['labels'] for r in data['dev']],devpred)
        row={'epoch':epoch+1,'loss':float(np.mean(losses)),'dev':metrics,'elapsed_seconds':time.time()-began};history.append(row);write_json(a.out/'history.json',history);print(json.dumps(row),flush=True)
        if metrics['f1']>best:best=metrics['f1'];model.save_pretrained(a.out/'selected_model');tok.save_pretrained(a.out/'selected_model')
    model=AutoModelForTokenClassification.from_pretrained(a.out/'selected_model').to(device)
    model_hash=sha(a.out/'selected_model/model.safetensors')
    write_json(a.out/'test_unlock.json',{'model_sha256':model_hash,'selection_final':True,'test_used_for_selection':False})
    testpred=predict(encoded(data['test'],False),data['test'])
    with (a.out/'test_predictions.jsonl').open('w',encoding='utf-8') as out:
        for row,pred in zip(data['test'],testpred):out.write(json.dumps({'sentence_sha256':row['sentence_sha256'],'words':row['words'],'predicted_labels':pred})+'\n')
    if sha(a.raw/'bc2gm_test.tsv')!=protocol['source_sha256']['test']:raise ValueError('Native final gold changed')
    final_gold=read_iob(a.raw/'bc2gm_test.tsv')
    if [r['sentence_sha256'] for r in final_gold]!=[r['sentence_sha256'] for r in data['test']]:raise ValueError('Final source alignment changed')
    result=span_metrics([r['labels'] for r in final_gold],testpred)
    result.update(protocol_id=protocol['protocol_id'],model_sha256=model_hash,predictions_sha256=sha(a.out/'test_predictions.jsonl'),sentences=len(data['test']),document_independence_unverified=True,test_used_for_selection=False)
    write_json(a.out/'test_evaluation_receipt.json',{'native_gold_interpreted_after_predictions_closed':True,
      'native_test_sha256':sha(a.raw/'bc2gm_test.tsv'),'predictions_sha256':sha(a.out/'test_predictions.jsonl'),
      'selected_model_sha256':model_hash,'selected_epoch':max(history,key=lambda r:r['dev']['f1'])['epoch'],
      'test_prediction_passes':1,'test_used_for_selection':False,'official_PMID_mapping_available':False})
    write_json(a.out/'result.json',result);print(json.dumps(result),flush=True)


if __name__=='__main__':main()
