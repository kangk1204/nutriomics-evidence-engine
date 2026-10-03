"""Create a new sealed experiment without touching the existing literature service."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from nutriomics_evidence.neural_data import prepare_chemprot, prepare_bioredirect, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--exposure-root',type=Path,action='append',default=[])
    parser.add_argument('--drugprot-abstracts',type=Path,action='append',default=[])
    parser.add_argument('--bioredirect',action='store_true')
    parser.add_argument('--literature-source',type=Path)
    parser.add_argument('--exposure-json',type=Path,action='append',default=[])
    args = parser.parse_args()
    ids, hashes, files = set(),set(),[]
    for path in args.exposure_json:
        raw=path.read_bytes();value=json.loads(raw)
        ids.update(map(str,value['pmids']));hashes.update(value.get('text_hashes',[]))
        files.append({'path':str(path),'sha256':hashlib.sha256(raw).hexdigest()})
    for root in args.exposure_root:
        for path in root.glob('*/*/inputs.json'):
            raw = path.read_bytes()
            value = json.loads(raw)
            for d in value.get('documents',[]):
                ids.add(str(d['pmid']))
                hashes.add(hashlib.sha256(d['text'].encode()).hexdigest())
            files.append({'path':str(path),'sha256':hashlib.sha256(raw).hexdigest()})
    for path in args.drugprot_abstracts:
        raw = path.read_bytes()
        for line in raw.decode().splitlines():
            pmid,title,abstract = line.split('\t')
            ids.add(pmid)
            hashes.add(hashlib.sha256((title+' '+abstract).encode()).hexdigest())
        files.append({'path':str(path),'sha256':hashlib.sha256(raw).hexdigest()})
    if args.bioredirect:
        sys.path.insert(0,str(args.literature_source))
        from nutri_literature.public_corpora import parse_pubtator
        protocol = prepare_bioredirect(args.archive,args.output,parse_pubtator,ids,hashes)
    else:
        protocol = prepare_chemprot(args.archive,args.output,ids,hashes)
    write_json(args.output/'exposure_receipt.json',{'files':files,'unique_pmids':len(ids),'unique_texts':len(hashes)})
    print(json.dumps({k:{'retained_documents':v['retained_documents'],'pairs':v['candidate_pairs'],
                         'excluded':len(v['excluded_previously_exposed_pmids'])} for k,v in protocol['splits'].items()}))


if __name__=='__main__':
    main()
