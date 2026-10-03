"""Isolated FooDB historical source acquisition/audit, never mutates frozen DBs."""
import argparse
import bz2
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import requests

COMMIT='3d2bcf9523911fabc8a07c731226ac87a2af262e'
BASE=f'https://raw.githubusercontent.com/SWi1/FooDB_polyphenol_analysis/{COMMIT}/'
FILES={
 'Compound.csv.bz2':('FooDB/Compound.csv.bz2','727abb16c4598f9e1aeca3e9fc15819a598d1ad5',5177304),
 'Content.csv.bz2':('FooDB/Content.csv.bz2','1904c7d67f88452e4f3861c73ffd0595b0e74b6f',22720186),
 'Food.csv':('FooDB/Food.csv','2974ffffbfa8f315c16db11b65e7b0fa9bdc637f',885915),
 'source_dictionary.md':('FooDB/README.md','f744d9b179cbac9d0c07c9b641d59f8031b1b36c',6016),
 'source_README.md':('README.md','2f3863e874ee984fc8284d2823f363b9dc7119f6',7255),
 'edible_part_rules.Rmd':('Estimation/E3A_Polyphenol_Estimation_Duke_Filtering.Rmd','b8b7ba0f2d9ffaaf203c67fcdc47f14684d1ed1b',5185),
 'source_code_LICENSE':('LICENSE','fdfb1d093e9d4143bd42f71079b38a1ca91097c1',1078)}

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''):h.update(block)
    return h.hexdigest()

def acquire(root:Path):
    raw=root/'raw';raw.mkdir(parents=True,exist_ok=True);sources=[]
    for name,(relative,git_sha,size) in FILES.items():
        path=raw/name
        if not path.exists():
            temp=path.with_suffix(path.suffix+'.part')
            with requests.get(BASE+relative,stream=True,timeout=(30,120)) as response:
                response.raise_for_status()
                with temp.open('wb') as f:
                    for chunk in response.iter_content(1024*1024):
                        if chunk:f.write(chunk)
            temp.replace(path)
        blob=hashlib.sha1(f'blob {path.stat().st_size}\0'.encode())
        with path.open('rb') as f:
            for block in iter(lambda:f.read(8*1024*1024),b''):blob.update(block)
        if path.stat().st_size!=size or blob.hexdigest()!=git_sha:raise ValueError('pinned Git blob mismatch:'+name)
        decoded=None
        if name.endswith('.bz2'):
            decoded=0
            with bz2.open(path,'rb') as f:
                for block in iter(lambda:f.read(8*1024*1024),b''):decoded+=len(block)
        sources.append({'name':name,'source_url':BASE+relative,'source_commit':COMMIT,'git_blob_sha1':git_sha,'sha256':digest(path),'bytes':path.stat().st_size,'full_bzip2_eof_decoded_bytes':decoded,'status':'complete'})
        print(json.dumps({'source':name,'status':'complete','bytes':path.stat().st_size}),flush=True)
    manifest={'schema_version':1,'acquired_utc':datetime.now(timezone.utc).isoformat(),'source_version':'FooDB Sept2022 mirror documented by original study authors','redistributor':'Wilson et al. USDA ARS WHNRC/Texas A&M; DOI10.1016/j.tjnut.2024.08.010','upstream_origin':'https://foodb.ca/downloads','mirror_commit':COMMIT,
        'data_license':'CC-BY-NC-4.0','data_license_source':'https://foodb.ca/compliance','data_license_terms':'https://creativecommons.org/licenses/by-nc/4.0/',
        'author_repository_code_license':'MIT','author_repository':'https://github.com/SWi1/FooDB_polyphenol_analysis','source_paper_doi':'10.1016/j.tjnut.2024.08.010','source_paper_author_verification':'https://www.ars.usda.gov/research/publications/publication/?seqNo115=410641',
        'raw_redistribution_allowed':False,'raw_git_commit_allowed':False,'research_analysis_authorized':True,
        'license_note':'FooDB data and metadata carry CC-BY-NC-4.0; the author repository MIT license applies to code and does not relicense third-party data. Noncommercial research reuse with attribution is permitted by the upstream license. This project keeps raw/derived records private and out of Git; raw_redistribution_allowed=false is project policy, not a claim that the license forbids all noncommercial redistribution. Commercial use requires separate FooDB permission.',
        'sources':sources}
    (root/'acquisition.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    return manifest

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',required=True,type=Path);p.add_argument('--phase',choices=['acquire','inspect','stage','finalize','all'],default='all');a=p.parse_args()
    if a.phase in ['acquire','all']:acquire(a.root)
    if a.phase in ['inspect','stage','finalize','all']:
        try:from nutriomics_evidence.food_compound_extension import inspect,stage,finalize
        except ModuleNotFoundError:from food_compound_extension_module import inspect,stage,finalize
        if a.phase=='inspect':inspect(a.root)
        elif a.phase=='finalize':finalize(a.root)
        else:stage(a.root)

if __name__=='__main__':main()
