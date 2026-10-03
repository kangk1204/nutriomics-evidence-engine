"""Indexed IGSR/1000 Genomes reference genotypes; no diet-person linkage.

Downloads the small official index and panel, then only indexed chromosome11
blocks overlapping the prespecified FADS region. Full chromosome download is
never a fallback.
"""
import argparse
from datetime import datetime,timezone
import gzip
import hashlib
import json
from pathlib import Path
import requests
import pysam
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

BASE="https://ftp.1000genomes.ebi.ac.uk/vol1/ftp/release/20130502/"
VCF="ALL.chr11.phase3_shapeit2_mvncall_integrated_v5b.20130502.genotypes.vcf.gz"
PANEL="integrated_call_samples_v3.20130502.ALL.panel"

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',required=True,type=Path);a=p.parse_args()
    raw=a.root/'raw';derived=a.root/'derived';raw.mkdir(parents=True,exist_ok=True);derived.mkdir(parents=True,exist_ok=True)
    receipt={'schema_version':1,'started_utc':datetime.now(timezone.utc).isoformat(),'population':'public IGSR/1000 Genomes phase3 reference; not dietary intervention participants','build':'GRCh37','region':'11:61560000-61750000','same_person_omics_linkage':False,'full_chromosome_download':False,'sources':[]}
    try:
        for name in [VCF+'.tbi',PANEL]:
            path=raw/name
            if not path.exists():
                r=requests.get(BASE+name,timeout=90);r.raise_for_status();path.write_bytes(r.content)
            receipt['sources'].append({'url':BASE+name,'path':str(path),'sha256':sha(path),'bytes':path.stat().st_size})
        with requests.head(BASE+VCF,timeout=60) as r:
            r.raise_for_status();receipt['vcf_remote_metadata']={'url':BASE+VCF,**{k:r.headers.get(k) for k in ['Content-Length','ETag','Last-Modified']}}
        output=raw/'IGSR_phase3_GRCh37_FADS_region.vcf.gz'
        index=raw/(VCF+'.tbi')
        with pysam.TabixFile(BASE+VCF,index=str(index)) as tb,gzip.open(output,'wt') as stream:
            for header in tb.header:stream.write(header+'\n')
            for line in tb.fetch('11',61559999,61750000):stream.write(line+'\n')
        panel=pd.read_csv(raw/PANEL,sep='\t').dropna(axis=1,how='all')
        panel['study_id']='IGSR_phase3_reference';panel['same_person_diet_or_omics']=False
        panel.to_parquet(derived/'genotype_reference_sample.parquet',index=False)
        records=[];writer=None;variants=0;all_samples=[];nrows=0
        try:
            with gzip.open(output,'rt') as f:
                for line in f:
                    if line.startswith('#CHROM'):
                        all_samples=line.rstrip().split('\t')[9:]
                        if not set(all_samples).issubset(set(panel['sample'])):raise ValueError('VCF sample absent panel')
                    elif not line.startswith('#'):
                        parts=line.rstrip().split('\t');variants+=1
                        keys=parts[8].split(':');gtindex=keys.index('GT')
                        for sample,value in zip(all_samples,parts[9:],strict=True):
                            gt=value.split(':')[gtindex]
                            records.append({'study_id':'IGSR_phase3_reference','sample_id':sample,'build':'GRCh37','chromosome':parts[0],'position':int(parts[1]),'variant_id':parts[2],'ref':parts[3],'alt':parts[4],'GT':gt,'phased':'|' in gt,'source_id':'IGSR_phase3_20130502_v5b','reference_context_only':True})
                        if len(records)>=100000:
                            table=pa.Table.from_pylist(records)
                            if writer is None:writer=pq.ParquetWriter(derived/'genotype_reference_call.parquet',table.schema,compression='zstd')
                            writer.write_table(table);nrows+=len(records);records=[]
                if records:
                    table=pa.Table.from_pylist(records)
                    if writer is None:writer=pq.ParquetWriter(derived/'genotype_reference_call.parquet',table.schema,compression='zstd')
                    writer.write_table(table);nrows+=len(records)
        finally:
            if writer:writer.close()
        receipt.update(status='complete',variants=variants,vcf_samples=len(all_samples),panel_samples=len(panel),genotype_calls=nrows,subset_sha256=sha(output),outputs=[{'path':str(path),'sha256':sha(path),'bytes':path.stat().st_size} for path in derived.glob('genotype_reference*.parquet')])
    except Exception as exc:receipt.update(status='failed',error=f'{type(exc).__name__}: {exc}')
    receipt['finished_utc']=datetime.now(timezone.utc).isoformat()
    (a.root/'genotype_reference_receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8');print(json.dumps(receipt),flush=True)
    return int(receipt['status']!='complete')

if __name__=='__main__':raise SystemExit(main())
