"""Recalculate final metrics from fixed predictions; never rerun/retune a model."""
import csv
import hashlib
import importlib.util
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
BASE=HERE.parents[3]
SOURCE=BASE/'expansion_20261003/nlp/raw/bc2gm_test.tsv'
RECEIPTS=HERE/'receipts/ner_v1'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    protocol=json.loads((RECEIPTS/'protocol.json').read_text())
    result=json.loads((RECEIPTS/'result.json').read_text())
    history=json.loads((RECEIPTS/'history.json').read_text())
    evaluation=json.loads((RECEIPTS/'test_evaluation_receipt.json').read_text())
    assert sha(HERE/'executed_run_biomed_ner.py')==protocol['code_sha256']
    assert sha(HERE/'executed_token_evaluation.py')==protocol['evaluation_code_sha256']
    assert sha(SOURCE)==protocol['source_sha256']['test']
    assert sha(RECEIPTS/'test_predictions.jsonl')==result['predictions_sha256']
    assert len(history)==5 and evaluation['selected_epoch']==max(history,key=lambda r:r['dev']['f1'])['epoch']
    assert evaluation['test_prediction_passes']==1 and evaluation['test_used_for_selection'] is False
    spec=importlib.util.spec_from_file_location('executed_token_metrics',HERE/'executed_token_evaluation.py')
    metric_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(metric_module)
    gold=[];words=[];labels=[]
    for line in SOURCE.read_text(encoding='utf-8').splitlines()+['']:
        if not line.strip():
            if words:gold.append({'words':words,'labels':labels})
            words=[];labels=[]
        else:
            word,label=line.rsplit('\t',1);words.append(word);labels.append(label)
    predictions=[json.loads(line) for line in (RECEIPTS/'test_predictions.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len(gold)==len(predictions)==5038
    assert all(g['words']==p['words'] and 'gold_labels' not in p for g,p in zip(gold,predictions))
    recalculated=metric_module.span_metrics([g['labels'] for g in gold],[p['predicted_labels'] for p in predictions])
    assert all(abs(recalculated[key]-result[key])<1e-14 for key in recalculated)
    report={'checks_passed':True,'native_test_sentences':len(gold),'selected_epoch':evaluation['selected_epoch'],
            'fixed_predictions_recalculated':recalculated,'model_sha256':result['model_sha256'],
            'prediction_sha256':result['predictions_sha256'],'source_sha256':sha(SOURCE),
            'no_new_model_prediction_or_tuning':True,'article_independence_or_pretraining_overlap_established':False}
    (HERE/'verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    columns=['split','epoch','selection','precision','recall','f1','true_positive_spans','false_positive_spans','false_negative_spans']
    with (HERE/'model_comparison.tsv').open('w',newline='',encoding='utf-8') as fh:
        writer=csv.DictWriter(fh,fieldnames=columns,delimiter='\t');writer.writeheader()
        for row in history:writer.writerow({'split':'development','epoch':row['epoch'],'selection':'selected' if row['epoch']==evaluation['selected_epoch'] else 'not selected',**row['dev']})
        writer.writerow({'split':'final native test','epoch':evaluation['selected_epoch'],'selection':'development only',**recalculated})
    print(json.dumps(report))


if __name__=='__main__':main()
