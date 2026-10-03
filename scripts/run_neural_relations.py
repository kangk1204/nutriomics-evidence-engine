"""Fine-tune raw-pretrained BiomedBERT; unlock native gold once after dev selection."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import random
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from nutriomics_evidence.neural_data import sha,write_json,CPR_LABELS

MODEL = 'microsoft/BiomedNLP-BiomedBERT-base-uncased-abstract-fulltext'
REVISION = 'e1354b7a3a09615f6aba48dfad4b7a613eef7062'


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def metrics(y, score, threshold):
    import numpy as np
    from sklearn.metrics import roc_auc_score,average_precision_score,brier_score_loss,precision_recall_fscore_support
    p,r,f,_ = precision_recall_fscore_support(y,score>=threshold,average='binary',zero_division=0)
    return {'auroc':float(roc_auc_score(y,score)), 'average_precision':float(average_precision_score(y,score)),
            'brier':float(brier_score_loss(y,score)), 'precision':float(p),'recall':float(r),'f1':float(f),
            'threshold':float(threshold),'pairs':len(y),'positive_pairs':int(np.sum(y))}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--epochs',type=int,default=8)
    parser.add_argument('--batch',type=int,default=2)
    parser.add_argument('--accumulation',type=int,default=8)
    parser.add_argument('--max-length',type=int,default=384)
    parser.add_argument('--literature-source',type=Path)
    args=parser.parse_args()
    if args.out.exists():raise FileExistsError('Immutable training output already exists')
    args.out.mkdir(parents=True)
    import numpy as np
    import torch
    from torch.utils.data import DataLoader
    from transformers import AutoTokenizer,AutoModelForSequenceClassification,get_linear_schedule_with_warmup
    from sklearn.metrics import roc_auc_score
    seed=20261003
    random.seed(seed);np.random.seed(seed);torch.manual_seed(seed);torch.cuda.manual_seed_all(seed)
    torch.set_num_threads(2)
    if not torch.cuda.is_available():raise RuntimeError('GPU training required for this sealed neural protocol')
    torch.cuda.set_per_process_memory_fraction(.36)
    device=torch.device('cuda')
    protocol=json.loads((args.data/'protocol.json').read_text())
    for split in ['train','dev','test']:
        if sha(args.data/f'{split}.jsonl')!=protocol['splits'][split]['inputs_sha256']:
            raise ValueError('Sealed input changed')
    train,dev=rows(args.data/'train.jsonl'),rows(args.data/'dev.jsonl')
    if not train or not dev:raise ValueError('No training/development rows survived source audit')
    labels=protocol['labels']
    tokenizer=AutoTokenizer.from_pretrained(MODEL,revision=REVISION)
    tokenizer.add_special_tokens({'additional_special_tokens':['[CHEM]','[/CHEM]','[GENE]','[/GENE]']})
    model=AutoModelForSequenceClassification.from_pretrained(MODEL,revision=REVISION,num_labels=len(labels),
             problem_type='multi_label_classification',id2label=dict(enumerate(labels)),label2id={l:i for i,l in enumerate(labels)})
    model.resize_token_embeddings(len(tokenizer));model.gradient_checkpointing_enable();model.to(device)
    def collate(items):
        encoded=tokenizer([r['text'] for r in items],padding=True,truncation=True,max_length=args.max_length,return_tensors='pt')
        if 'labels' in items[0]:encoded['labels']=torch.tensor([r['labels'] for r in items],dtype=torch.float32)
        return encoded
    def probabilities(items):
        model.eval();parts=[]
        with torch.no_grad():
            for batch in DataLoader(items,batch_size=args.batch*2,collate_fn=collate):
                batch.pop('labels',None)
                with torch.autocast('cuda',dtype=torch.bfloat16):
                    output=model(**{k:v.to(device) for k,v in batch.items()})
                parts.append(torch.sigmoid(output.logits.float()).cpu().numpy())
        return np.concatenate(parts)
    train_labels=np.array([r['labels'] for r in train])
    pos=train_labels.sum(0)
    weight=torch.tensor(np.minimum((len(train)-pos)/np.maximum(pos,1),10),dtype=torch.float32,device=device)
    criterion=torch.nn.BCEWithLogitsLoss(pos_weight=weight)
    loader=DataLoader(train,batch_size=args.batch,shuffle=True,collate_fn=collate,generator=torch.Generator().manual_seed(seed))
    optimizer=torch.optim.AdamW(model.parameters(),lr=2e-5,weight_decay=.01)
    total_steps=((len(loader)+args.accumulation-1)//args.accumulation)*args.epochs
    scheduler=get_linear_schedule_with_warmup(optimizer,int(total_steps*.1),total_steps)
    run_protocol={**protocol,'model':MODEL,'model_revision':REVISION,'epochs':args.epochs,'learning_rate':2e-5,
                  'batch':args.batch,'gradient_accumulation':args.accumulation,'max_length':args.max_length,
                  'selection':'maximum development binary AUROC; development-only F1 threshold',
                  'torch':torch.__version__,'cuda':torch.version.cuda,'gpu':torch.cuda.get_device_name(0),
                  'seed':seed,'code_sha256':sha(Path(__file__)),'test_opened':False}
    write_json(args.out/'training_protocol.json',run_protocol)
    best=-1;history=[];started=time.time()
    ydev=np.array([any(r['labels']) for r in dev],dtype=int)
    for epoch in range(args.epochs):
        model.train();loss_sum=0.;optimizer.zero_grad(set_to_none=True)
        for step,batch in enumerate(loader):
            target=batch.pop('labels').to(device)
            with torch.autocast('cuda',dtype=torch.bfloat16):
                logits=model(**{k:v.to(device) for k,v in batch.items()}).logits
                loss=criterion(logits.float(),target)/args.accumulation
            loss.backward();loss_sum+=float(loss.item())*args.accumulation
            if (step+1)%args.accumulation==0 or step+1==len(loader):
                torch.nn.utils.clip_grad_norm_(model.parameters(),1.)
                optimizer.step();scheduler.step();optimizer.zero_grad(set_to_none=True)
        prob=probabilities(dev);score=1-np.prod(1-prob,axis=1)
        auc=float(roc_auc_score(ydev,score));record={'epoch':epoch+1,'loss':loss_sum/len(loader),'dev_auroc':auc,'elapsed_seconds':time.time()-started}
        history.append(record);print(json.dumps(record),flush=True);write_json(args.out/'history.json',history)
        if auc>best:
            best=auc;model.save_pretrained(args.out/'selected_model');tokenizer.save_pretrained(args.out/'selected_model')
            np.save(args.out/'selected_dev_probabilities.npy',prob)
    model=AutoModelForSequenceClassification.from_pretrained(args.out/'selected_model').to(device)
    dev_prob=np.load(args.out/'selected_dev_probabilities.npy');dev_score=1-np.prod(1-dev_prob,axis=1)
    trials=[metrics(ydev,dev_score,t) for t in np.linspace(.05,.95,19)]
    selected=max(trials,key=lambda m:(m['f1'],m['precision']))
    selected_model_hash=sha(args.out/'selected_model/model.safetensors')
    lock={'model_sha256':selected_model_hash,'threshold':selected['threshold'],'selected_dev':selected,
          'opened_at_unix':time.time(),'gold_sha256':protocol['splits']['test']['gold_sha256'],
          'test_was_used_for_model_selection':False}
    write_json(args.out/'test_unlock.json',lock)
    # Predict before reading gold. All pair probabilities, including negatives, are retained.
    test=rows(args.data/'test.jsonl');test_prob=probabilities(test);test_score=1-np.prod(1-test_prob,axis=1)
    np.save(args.out/'test_label_probabilities.npy',test_prob)
    with (args.out/'test_predictions.jsonl').open('w',encoding='utf-8') as f:
        for row,prob,score in zip(test,test_prob,test_score):
            f.write(json.dumps({k:v for k,v in row.items() if k!='text'}|{'score':float(score),'label_probabilities':list(map(float,prob))})+'\n')
    if sha(args.out/'selected_model/model.safetensors')!=selected_model_hash:raise ValueError('Selected model changed after unlock')
    if protocol['protocol_id'].startswith('biored'):
        sys.path.insert(0,str(args.literature_source))
        from nutri_literature.public_corpora import parse_pubtator
        gold_docs=parse_pubtator((args.data/'test_native.pubtator').read_text())
        expected={(d['pmid'],frozenset((r['entity1'],r['entity2']))) for d in gold_docs for r in d['relations']}
        y=np.array([(r['pmid'],frozenset((r['chemical_id'],r['gene_id']))) in expected for r in test],dtype=int)
    else:
        from nutriomics_evidence.neural_data import read_cpr_gold
        gold=read_cpr_gold(args.data/'test_gold_standard.tsv')
        y=np.array([(r['pmid'],r['chemical_id'],r['gene_id']) in gold for r in test],dtype=int)
    result=metrics(y,test_score,selected['threshold'])
    result.update(protocol_id=protocol['protocol_id'],gold_mentions_used=True,clinical_efficacy_evaluated=False,
                  documents=protocol['splits']['test']['retained_documents'],model_sha256=selected_model_hash,
                  predictions_sha256=sha(args.out/'test_predictions.jsonl'),evaluation_type='sealed_public_native_gold',
                  selected_development=selected,elapsed_seconds=time.time()-started)
    # Paper bootstrap respects correlated pairs, and retains undefined one-class resamples as exclusions.
    pmids=np.array([r['pmid'] for r in test]);unique=np.unique(pmids);rng=np.random.default_rng(seed);values=[]
    indices={p:np.flatnonzero(pmids==p) for p in unique}
    for _ in range(2000):
        index=np.concatenate([indices[p] for p in rng.choice(unique,len(unique),replace=True)])
        if len(np.unique(y[index]))==2:values.append(float(roc_auc_score(y[index],test_score[index])))
    result['paper_bootstrap_auroc_ci95']=list(map(float,np.quantile(values,[.025,.975])))
    result['bootstrap_valid']=len(values)
    write_json(args.out/'result.json',result);print(json.dumps(result),flush=True)
    # Training-only lexical comparator uses the identical native task and sealed split.
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    vectorizer=TfidfVectorizer(ngram_range=(1,2),min_df=2,max_features=100000,sublinear_tf=True)
    x=vectorizer.fit_transform([r['text'] for r in train])
    lexical=LogisticRegression(C=1,max_iter=1000,class_weight='balanced',random_state=seed)
    lexical.fit(x,np.array([any(r['labels']) for r in train],dtype=int))
    lexical_dev=lexical.predict_proba(vectorizer.transform([r['text'] for r in dev]))[:,1]
    lexical_selected=max([metrics(ydev,lexical_dev,t) for t in np.linspace(.05,.95,19)],key=lambda m:(m['f1'],m['precision']))
    lexical_score=lexical.predict_proba(vectorizer.transform([r['text'] for r in test]))[:,1]
    write_json(args.out/'lexical_comparator.json',metrics(y,lexical_score,lexical_selected['threshold'])|
               {'fit_scope':'official train only','threshold_scope':'development only','same_test_gold':True})


if __name__=='__main__':main()
