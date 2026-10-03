"""Register the DTI team's frozen official-food standard-analyte panel.

The edible-food concept and normalized chemical concept are linked as reported;
aglycone-equivalent amounts are never native free-ligand exposure measurements.
"""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import duckdb
import pandas as pd
from rdkit import Chem
try:
    from nutriomics_evidence.public_expansion import digest,sql_literal
except ModuleNotFoundError:
    from public_expansion import digest,sql_literal

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);a=p.parse_args();root=a.root;d=root/'derived';raw=root/'raw/food_standard_panel'
    manifest=json.loads((raw/'input_manifest.json').read_text())
    for item in manifest['inputs']:
        if digest(raw/item['name'])!=item['sha256']:raise ValueError('food panel input hash mismatch:'+item['name'])
    panel=pd.read_csv(raw/'verified_food_compounds_v4.csv',dtype=str,keep_default_na=False)
    for row in panel.itertuples():
        cid=int(float(row.pubchem_cid));properties_path=raw/f'pubchem_cid_{cid}_properties.json'
        if digest(properties_path)!=row.properties_sha256:raise ValueError('PubChem property SHA mismatch')
        properties=json.loads(properties_path.read_text())['PropertyTable']['Properties'][0]
        if int(properties['CID'])!=cid or properties['InChIKey']!=row.compound_id:raise ValueError('PubChem CID/full-key mismatch')
    panel['recomputed_standard_full_inchikey']=[Chem.MolToInchiKey(Chem.MolFromSmiles(smiles)) for smiles in panel.smiles]
    if not panel.recomputed_standard_full_inchikey.eq(panel.compound_id).all():raise ValueError('standard structure key mismatch')
    if panel.compound_id.duplicated().any():raise ValueError('duplicate standard full structure')
    panel['food_evidence_kind']='official_food_standard_analyte_concept';panel['native_free_oral_ligand_exposure_verified']=False
    panel['registry_source_id']='food_standard_panel_v4_20261003';panel.to_parquet(d/'food_standard_analyte_panel.parquet',index=False)
    con=duckdb.connect(str(d/'expansion.duckdb'));con.execute('SET threads=2');con.execute('SET enable_progress_bar=false')
    con.execute(f'CREATE OR REPLACE VIEW food_standard_analyte_panel AS SELECT * FROM read_parquet({sql_literal(d/"food_standard_analyte_panel.parquet")})')
    foods=pd.read_csv(raw/'isoflavone_FOOD_DES.csv',dtype=str,keep_default_na=False)
    values=pd.read_csv(raw/'isoflavone_ISFL_DAT.csv',dtype=str,keep_default_na=False)
    definitions=pd.read_csv(raw/'isoflavone_NUTR_DEF.csv',dtype=str,keep_default_na=False)
    for name,frame in [('usda_isoflavone_food',foods),('usda_isoflavone_native_measurement',values),('usda_isoflavone_analyte_definition',definitions)]:
        frame.to_parquet(d/f'{name}.parquet',index=False);con.execute(f'CREATE OR REPLACE VIEW {name} AS SELECT * FROM read_parquet({sql_literal(d/(name+".parquet"))})')
    con.execute(f"""COPY (SELECT v.*,n.NutrDesc analyte_name,n.Unit unit,'mg_per100g_fresh_edible_aglycone_equivalent' basis,
      'usda_isoflavone_r2_1' source_id,'USDA-ISFL-R2-1:'||v.NDB_No food_id
      FROM usda_isoflavone_native_measurement v JOIN usda_isoflavone_analyte_definition n ON v.Nutr_No=n.Nutr_no
      WHERE try_cast(v.Isfl_Val AS DOUBLE)>=0 AND try_cast(v.Isfl_Val AS DOUBLE)<=100000 AND isfinite(try_cast(v.Isfl_Val AS DOUBLE)) AND v.Nutr_No!='713')
      TO {sql_literal(d/'usda_isoflavone_composition.parquet')} (FORMAT PARQUET,COMPRESSION ZSTD)""")
    con.execute(f'CREATE OR REPLACE VIEW usda_isoflavone_composition AS SELECT * FROM read_parquet({sql_literal(d/"usda_isoflavone_composition.parquet")})')
    receipt={'schema_version':1,'registered_utc':datetime.now(timezone.utc).isoformat(),'standard_full_structures':len(panel),
      'standard_food_chemical_concept_definition':'source official positive food analyte + independently normalized unique PubChem standard concept; aglycone/stereo/native ligand limitations retained',
      'native_free_exposure_count':0,'already_counted_in_existing_baseline_not_a_new33_claim':True,'verified_2000_milestone_met':False,
      'isoflavone_foods':len(foods),'isoflavone_native_measurements':len(values),'isoflavone_analyte_definitions':len(definitions),
      'isoflavone_single_analyte_measurements':con.execute('SELECT count(*) FROM usda_isoflavone_composition').fetchone()[0],
      'inputs':manifest['inputs'],'food_identity_merged_with_FDC_by_name':False,'source_foods_added_to_canonical_FDC_delta':False,
      'outputs':[{'path':str(path),'sha256':digest(path)} for path in sorted(d.glob('*isoflavone*.parquet'))]+[{'path':str(d/'food_standard_analyte_panel.parquet'),'sha256':digest(d/'food_standard_analyte_panel.parquet')}]}
    con.execute('CHECKPOINT');con.close();(d/'food_standard_panel_receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    summary_path=d/'summary.json';summary=json.loads(summary_path.read_text());summary['food_standard_analyte_panel']=receipt|{'receipt_sha256':digest(d/'food_standard_panel_receipt.json')};summary_path.write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps({key:value for key,value in receipt.items() if key not in ['outputs','inputs']}),flush=True)

if __name__=='__main__':main()
