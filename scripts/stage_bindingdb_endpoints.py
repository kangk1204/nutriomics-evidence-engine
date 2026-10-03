"""One broad native BindingDB pass, distinct from the strict Kd training task.

Preserves Ki/Kd/IC50/EC50 and censoring; never supplies negative untested pairs.
Source native InChI->fullInChIKey verification is not a complete SMILES audit.
Protein complexes/constructs remain annotated and are not silently pooled with
wildtype monomers. This is a measured-assertion registry, not a DTI benchmark.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime,timezone
from functools import lru_cache
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re
import zipfile
import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from rdkit.Chem import inchi
from rdkit import RDLogger
try:
    from nutriomics_evidence.public_expansion import digest,sql_literal,verified_source
except ModuleNotFoundError:
    from public_expansion import digest,sql_literal,verified_source

ENDPOINTS=('Ki','IC50','Kd','EC50')
AFFINITY=re.compile(r'^\s*(<=|>=|<|>|=|≤|≥|~)?\s*([+]?\d*\.?\d+(?:[eE][+-]?\d+)?)\s*$')
FULLKEY=re.compile(r'^[A-Z]{14}-[A-Z]{10}-[A-Z]$')
AA=set('ACDEFGHIKLMNPQRSTVWYXBZUOJ')
CONSTRUCT=re.compile(r'\b[A-Z]\d{2,}[A-Z]\b|\bmut(?:ant|ation)\b|truncat|fusion|\[\d+\s*[-:]\s*\d+\]',re.I)
STRING_FIELDS=['source_record_id','reactant_set_id','monomer_id','full_inchikey','computed_inchikey','smiles','source_inchi','target_id','target_name','species','protein_chain_sequences_json','uniprot_ids_json','endpoint','relation','unit','value_raw','doi','pmid','patent','pubchem_aid','curation_source','ph','temperature_c','publication_date','curation_date','source_id']
SCHEMA=pa.schema([(key,pa.string()) for key in STRING_FIELDS]+[('value_nm',pa.float64()),('exact_positive',pa.bool_()),('inchi_hash_verified',pa.bool_()),('protein_sequences_valid',pa.bool_()),('explicit_construct',pa.bool_()),('multichain_target',pa.bool_()),('raw_ordinal',pa.int64()),('declared_chains',pa.int32()),('observed_chains',pa.int32())])

def parse_affinity(raw:str):
    match=AFFINITY.fullmatch(raw)
    if not match:raise ValueError('malformed_numeric_or_relation')
    relation={'≤':'<=','≥':'>='}.get(match[1],match[1] or '=')
    value=float(match[2])
    if not math.isfinite(value) or value<=0:raise ValueError('nonpositive_or_nonfinite')
    return relation,value

@lru_cache(maxsize=500000)
def verify_inchi(source_inchi:str,fullkey:str):
    if not FULLKEY.fullmatch(fullkey) or not source_inchi.startswith('InChI='):return '',False
    calculated=inchi.InchiToInchiKey(source_inchi) or ''
    return calculated,calculated==fullkey

def native_rows(path:Path):
    csv.field_size_limit(64*1024*1024)
    with zipfile.ZipFile(path) as archive:
        members=[name for name in archive.namelist() if name.endswith(('.tsv','.txt'))]
        if len(members)!=1:raise ValueError('expected exactly one TSV member')
        with archive.open(members[0]) as binary,io.TextIOWrapper(binary,encoding='utf-8',errors='strict',newline='') as stream:
            yield from csv.reader(stream,delimiter='\t',quoting=csv.QUOTE_NONE)

def write_batch(writer,records,schema=SCHEMA):
    if records:writer.write_table(pa.Table.from_pylist(records,schema=schema))

def stream_endpoints(raw:Path,destination:Path,rejections:Path):
    RDLogger.DisableLog('rdApp.warning');RDLogger.DisableLog('rdApp.error')
    counts=Counter();endpoint_counts=Counter();iterator=native_rows(raw);header=next(iterator);header[0]=header[0].lstrip('\ufeff')
    indexes={name:i for i,name in enumerate(header)}
    for column in ['BindingDB Reactant_set_id','Ligand InChI','Ligand InChI Key']+[f'{ep} (nM)' for ep in ENDPOINTS]:
        if column not in indexes:raise ValueError('missing native column: '+column)
    sequence_columns=[(name,i) for name,i in indexes.items() if name.startswith('BindingDB Target Chain Sequence')]
    uniprot_columns=[(name,i) for name,i in indexes.items() if re.fullmatch(r'UniProt \((SwissProt|TrEMBL)\) Primary ID of Target Chain(?: \d+)?',name)]
    rejected_schema=pa.schema([('source_record_id',pa.string()),('reactant_set_id',pa.string()),('endpoint',pa.string()),('value_raw',pa.string()),('rejection_reason',pa.string()),('raw_ordinal',pa.int64())])
    records=[];reject=[]
    with pq.ParquetWriter(destination,SCHEMA,compression='zstd') as output,pq.ParquetWriter(rejections,rejected_schema,compression='zstd') as rejected_output:
        for ordinal,row in enumerate(iterator,1):
            counts['raw_rows']+=1
            def get(name):
                i=indexes.get(name);return row[i].strip() if i is not None and i<len(row) else ''
            rsid=get('BindingDB Reactant_set_id');chains=[row[i].strip().upper() for _,i in sequence_columns if i<len(row) and row[i].strip()]
            # Multiset identity retains repeated chains; target name/species preserve native constructs.
            chains.sort();species=get('Target Source Organism According to Curator or DataSource');target_name=get('Target Name')
            valid_seq=bool(chains) and all(len(seq)>=20 and set(seq)<=AA for seq in chains)
            uniprot=sorted(set(row[i].strip() for _,i in uniprot_columns if i<len(row) and row[i].strip()))
            chains_json=json.dumps(chains,separators=(',',':'))
            target_id=hashlib.sha256(json.dumps([chains,species,target_name],separators=(',',':')).encode()).hexdigest()
            declared=get('Number of Protein Chains in Target (>1 implies a multichain complex)')
            declared_n=int(declared) if declared.isdigit() else None
            computed,verified=verify_inchi(get('Ligand InChI'),get('Ligand InChI Key'))
            base={'reactant_set_id':rsid,'monomer_id':get('BindingDB MonomerID'),'full_inchikey':get('Ligand InChI Key'),'computed_inchikey':computed,
                'smiles':get('Ligand SMILES'),'source_inchi':get('Ligand InChI'),'target_id':target_id,'target_name':target_name,'species':species,
                'protein_chain_sequences_json':chains_json,'uniprot_ids_json':json.dumps(uniprot,separators=(',',':')),'unit':'nM',
                'doi':get('Article DOI').lower().removeprefix('https://doi.org/'),'pmid':get('PMID'),'patent':get('Patent Number'),'pubchem_aid':get('PubChem AID'),
                'curation_source':get('Curation/DataSource'),'ph':get('pH'),'temperature_c':get('Temp (C)'),
                'publication_date':get('Date of publication'),'curation_date':get('Date in BindingDB'),'source_id':'bindingdb_202610',
                'inchi_hash_verified':verified,'protein_sequences_valid':valid_seq,'explicit_construct':bool(CONSTRUCT.search(target_name)),
                'multichain_target':len(chains)>1 or (declared_n is not None and declared_n>1),'raw_ordinal':ordinal,'declared_chains':declared_n,'observed_chains':len(chains)}
            any_endpoint=False
            for endpoint in ENDPOINTS:
                raw_value=get(endpoint+' (nM)')
                if not raw_value:continue
                any_endpoint=True;counts['nonempty_endpoint_values']+=1;source_record_id=f'{ordinal}:{endpoint}'
                try:relation,value=parse_affinity(raw_value)
                except ValueError as exc:
                    counts['rejected_'+str(exc)]+=1
                    reject.append({'source_record_id':source_record_id,'reactant_set_id':rsid,'endpoint':endpoint,'value_raw':raw_value,'rejection_reason':str(exc),'raw_ordinal':ordinal});continue
                records.append(base|{'source_record_id':source_record_id,'endpoint':endpoint,'relation':relation,'value_nm':value,'value_raw':raw_value,'exact_positive':relation=='='})
                endpoint_counts[(endpoint,relation)]+=1
            if not any_endpoint:counts['no_affinity_endpoint']=counts.get('no_affinity_endpoint',0)+1
            if len(records)>=25000:write_batch(output,records);records.clear()
            if len(reject)>=25000:write_batch(rejected_output,reject,rejected_schema);reject.clear()
            if ordinal%500000==0:print(json.dumps({'stage':'native_measured_endpoints','raw_rows':ordinal,'valid_labels':sum(endpoint_counts.values())}),flush=True)
        write_batch(output,records);write_batch(rejected_output,reject,rejected_schema)
    return {'raw_counts':dict(counts),'typed_endpoint_relation_counts':[{'endpoint':ep,'relation':relation,'rows':n} for (ep,relation),n in sorted(endpoint_counts.items())]}

def extract_map(root:Path,sid:str):
    receipt=verified_source(root,sid);destination=root/'extracted'/sid;destination.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(receipt['actual_path']) as archive:
        member=archive.infolist()[0];path=destination/Path(member.filename).name
        if not path.exists() or path.stat().st_size!=member.file_size:
            with archive.open(member) as source,path.open('wb') as target:
                import shutil;shutil.copyfileobj(source,target,8*1024*1024)
    return path

def stage(root:Path):
    derived=root/'derived';receipt=verified_source(root,'bindingdb_202610')
    source_rows=derived/'bindingdb_measured_source_records.parquet';rejections=derived/'bindingdb_label_rejections.parquet'
    parse=stream_endpoints(Path(receipt['actual_path']),source_rows,rejections)
    con=duckdb.connect(str(derived/'expansion.duckdb'));con.execute('SET threads=2');con.execute("SET memory_limit='12GB'");con.execute('SET enable_progress_bar=false')
    for name,path in [('bindingdb_measured_source_records',source_rows),('bindingdb_label_rejections',rejections)]:
        con.execute(f'CREATE OR REPLACE VIEW {name} AS SELECT * FROM read_parquet({sql_literal(path)})')
    map_path=extract_map(root,'bindingdb_rsid_202610');assay_path=extract_map(root,'bindingdb_assays_202610')
    tab=lambda path:f"read_csv({sql_literal(path)},header=true,delim='\\t',quote='',all_varchar=true,strict_mode=true,max_line_size=16777216)"
    # Assay mapping can be many-to-many. Aggregate native aliases; do not multiply measurements.
    con.execute(f"CREATE OR REPLACE TEMP TABLE rsid_assays AS SELECT REACTANT_SET_ID reactant_set_id,string_agg(DISTINCT ENTRYID_ASSAYID,';' ORDER BY ENTRYID_ASSAYID) assay_ids FROM {tab(map_path)} GROUP BY REACTANT_SET_ID")
    assay_out=derived/'bindingdb_assay_description.parquet'
    con.execute(f"COPY (SELECT DISTINCT ENTRYID||'_'||ASSAYID assay_id,ASSAY_NAME assay_name,DESCRIPTION assay_description FROM {tab(assay_path)}) TO {sql_literal(assay_out)} (FORMAT PARQUET,COMPRESSION ZSTD)")
    con.execute(f'CREATE OR REPLACE VIEW bindingdb_assay_description AS SELECT * FROM read_parquet({sql_literal(assay_out)})')
    con.execute("""CREATE OR REPLACE TEMP TABLE native_source_aliases AS SELECT DISTINCT doi,pmid,patent,pubchem_aid FROM bindingdb_measured_source_records""")
    # Resolve DOI/PMID/patent aliases conservatively; assay IDs remain separate native observations.
    parent={}
    def find(value):
        parent.setdefault(value,value)
        while parent[value]!=value:parent[value]=parent[parent[value]];value=parent[value]
        return value
    aliases=con.execute('SELECT * FROM native_source_aliases').fetchall()
    for doi,pmid,patent,aid in aliases:
        identifiers=[prefix+value for prefix,value in [('doi:',doi),('pmid:',pmid),('patent:',patent)] if value]
        for value in identifiers:find(value)
        if identifiers:
            best=min(find(value) for value in identifiers)
            for value in identifiers:parent[find(value)]=best
    import pandas as pd
    alias_rows=[]
    for doi,pmid,patent,aid in aliases:
        identifiers=[prefix+value for prefix,value in [('doi:',doi),('pmid:',pmid),('patent:',patent)] if value]
        group=min(find(value) for value in identifiers) if identifiers else ('pubchem_aid:'+aid if aid else '')
        alias_rows.append({'doi':doi,'pmid':pmid,'patent':patent,'pubchem_aid':aid,'source_group':group})
    con.register('alias_frame',pd.DataFrame(alias_rows))
    con.execute("""CREATE OR REPLACE TEMP VIEW typed_measurement AS SELECT r.*,coalesce(a.assay_ids,'') assay_ids,g.source_group,
      CASE WHEN NOT r.inchi_hash_verified THEN 'unverified_full_structure'
           WHEN NOT r.protein_sequences_valid THEN 'unresolved_protein_sequence'
           WHEN g.source_group='' AND coalesce(a.assay_ids,'')='' THEN 'missing_source_or_assay'
           ELSE 'eligible_measured_assertion' END eligibility
      FROM bindingdb_measured_source_records r LEFT JOIN rsid_assays a USING(reactant_set_id)
      JOIN alias_frame g USING(doi,pmid,patent,pubchem_aid)""")
    # Source group, native assay, conditions, construct-preserved target and endpoint remain in identity.
    measurekey="sha256(to_json([full_inchikey,target_id,source_group,assay_ids,endpoint,relation,cast(value_nm AS VARCHAR),unit,ph,temperature_c]))"
    candidates=derived/'bindingdb_measurement_candidates.parquet'
    con.execute(f'COPY (SELECT {measurekey} measurement_id,* FROM typed_measurement) TO {sql_literal(candidates)} (FORMAT PARQUET,COMPRESSION ZSTD)')
    con.execute(f'CREATE OR REPLACE VIEW bindingdb_measurement_candidates AS SELECT * FROM read_parquet({sql_literal(candidates)})')
    measurements=derived/'bindingdb_measurement.parquet'
    con.execute(f"COPY (SELECT * EXCLUDE(rn) FROM (SELECT *,row_number() OVER(PARTITION BY measurement_id ORDER BY raw_ordinal,source_record_id) rn FROM bindingdb_measurement_candidates WHERE eligibility='eligible_measured_assertion') WHERE rn=1) TO {sql_literal(measurements)} (FORMAT PARQUET,COMPRESSION ZSTD)")
    con.execute(f'CREATE OR REPLACE VIEW bindingdb_measurement AS SELECT * FROM read_parquet({sql_literal(measurements)})')
    ledger=derived/'bindingdb_source_ledger.parquet'
    con.execute(f"COPY (SELECT DISTINCT reactant_set_id,doi,pmid,patent,pubchem_aid,assay_ids,source_group,curation_source,publication_date,curation_date FROM bindingdb_measurement_candidates) TO {sql_literal(ledger)} (FORMAT PARQUET,COMPRESSION ZSTD)")
    con.execute(f'CREATE OR REPLACE VIEW bindingdb_source_ledger AS SELECT * FROM read_parquet({sql_literal(ledger)})')
    checks={
      'duplicate_measurement_id':con.execute('SELECT count(*)-count(DISTINCT measurement_id) FROM bindingdb_measurement').fetchone()[0],
      'nonpositive_or_nonfinite':con.execute('SELECT count(*) FROM bindingdb_measurement WHERE value_nm<=0 OR NOT isfinite(value_nm)').fetchone()[0],
      'unverified_structure_or_sequence':con.execute('SELECT count(*) FROM bindingdb_measurement WHERE NOT inchi_hash_verified OR NOT protein_sequences_valid').fetchone()[0],
      'invalid_endpoint_or_unit':con.execute("SELECT count(*) FROM bindingdb_measurement WHERE endpoint NOT IN ('Kd','Ki','IC50','EC50') OR unit!='nM'").fetchone()[0],
      'bad_exact_label':con.execute("SELECT count(*) FROM bindingdb_measurement WHERE exact_positive!=(relation='=')").fetchone()[0]}
    counts=con.execute('SELECT endpoint,relation,count(*) FROM bindingdb_measurement GROUP BY ALL ORDER BY endpoint,relation').fetchall()
    audit={'schema_version':1,'generated_utc':datetime.now(timezone.utc).isoformat(),'source_sha256':receipt['sha256'],'parser':parse,
      'typed_native_measurement_rows':con.execute('SELECT count(*) FROM bindingdb_measured_source_records').fetchone()[0],
      'measured_dedup_assertions':con.execute('SELECT count(*) FROM bindingdb_measurement').fetchone()[0],
      'exact_positive_dedup_assertions':con.execute('SELECT count(*) FROM bindingdb_measurement WHERE exact_positive').fetchone()[0],
      'unique_construct_preserved_compound_target_pairs':con.execute('SELECT count(DISTINCT full_inchikey||\':\'||target_id) FROM bindingdb_measurement').fetchone()[0],
      'source_ledger_rows':con.execute('SELECT count(*) FROM bindingdb_source_ledger').fetchone()[0],
      'eligibility_source_row_counts':dict(con.execute('SELECT eligibility,count(*) FROM bindingdb_measurement_candidates GROUP BY eligibility').fetchall()),
      'endpoint_relation_counts':[{'endpoint':ep,'relation':relation,'rows':n} for ep,relation,n in counts],
      'distinct_full_inchikey':con.execute('SELECT count(DISTINCT full_inchikey) FROM bindingdb_measurement').fetchone()[0],
      'distinct_construct_preserved_targets':con.execute('SELECT count(DISTINCT target_id) FROM bindingdb_measurement').fetchone()[0],
      'checks':checks,'deduplication':'exact fullInChIKey; sorted complete chain sequences + species + native target construct name; DOI/PMID/patent alias closure; native assay IDs; endpoint/relation/nM/pH/temperature preserved',
      'source_registry_not_a_training_benchmark':True,'strict_Kd_model_rows_not_inherited':True,'censored_labels_used_as_exact':False,'untested_pairs_used_as_negative':False,
      'all_smiles_independently_validated':False,'unknown_cross_source_replicates_may_remain':True,'all_assays_binding_not_assumed':True,
      'independent_sources_proven_for_food_model':False}
    con.execute('CHECKPOINT');con.close()
    audit['outputs']=[{'path':str(path),'sha256':digest(path),'bytes':path.stat().st_size} for path in sorted(derived.glob('bindingdb_*.parquet'))]
    audit_path=derived/'bindingdb_endpoint_audit.json';audit_path.write_text(json.dumps(audit,indent=2),encoding='utf-8')
    summary_path=derived/'summary.json';summary=json.loads(summary_path.read_text());summary['bindingdb_measured_endpoints']=audit|{'audit_path':str(audit_path),'audit_sha256':digest(audit_path)};summary_path.write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps({key:value for key,value in audit.items() if key!='outputs'}),flush=True)
    if not all(value==0 for value in checks.values()):raise ValueError('BindingDB staged structural check failed')
    return audit

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);a=p.parse_args();stage(a.root)
