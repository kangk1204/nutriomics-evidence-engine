"""Explicit migration of staged FDC composition; no production DB writes.

The pre-correction Parquet is retained with its SHA. Rejections remain queryable
and are excluded from serving composition. Four native single-analyte nutrients
are exported for independent chemical verification by the DTI pipeline.
"""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil
import sqlite3
import duckdb
try:
    from nutriomics_evidence.public_expansion import digest,sql_literal,mass_exceeds_basis_sql
except ModuleNotFoundError:
    from public_expansion import digest,sql_literal,mass_exceeds_basis_sql

def correct(root:Path):
    derived=root/'derived';summary_path=derived/'summary.json'
    summary=json.loads(summary_path.read_text())
    target=derived/'food_composition.parquet';before=derived/'food_composition_before_mass_qc.parquet'
    if not before.exists():shutil.copy2(target,before)
    con=duckdb.connect(str(derived/'expansion.duckdb'));con.execute('SET threads=2');con.execute('SET enable_progress_bar=false')
    con.execute(f'CREATE OR REPLACE TEMP VIEW composition_before AS SELECT * FROM read_parquet({sql_literal(before)})')
    predicate=mass_exceeds_basis_sql()
    rejected=derived/'food_composition_rejections.parquet'
    replacement=derived/'food_composition_corrected.parquet'
    con.execute(f"COPY (SELECT *, 'mass_exceeds100g_basis' rejection_reason FROM composition_before WHERE {predicate}) TO {sql_literal(rejected)} (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.execute(f'COPY (SELECT * FROM composition_before WHERE NOT {predicate}) TO {sql_literal(replacement)} (FORMAT PARQUET, COMPRESSION ZSTD)')
    replacement.replace(target)
    con.execute(f'CREATE OR REPLACE VIEW food_composition AS SELECT * FROM read_parquet({sql_literal(target)})')
    con.execute(f'CREATE OR REPLACE VIEW food_composition_rejections AS SELECT * FROM read_parquet({sql_literal(rejected)})')
    rejected_n=con.execute('SELECT count(*) FROM food_composition_rejections').fetchone()[0]
    source=json.loads((root/'receipts/usda_fdc_202604.json').read_text())
    provenance={'source_id':source['source_id'],'source_zip_sha256':source['sha256'],'source_url':source['url'],'native_basis':'source100g','mass_bound_applied':True,'structure_assigned_from_nutrient_name':False,'labels_and_analytical_measurements_kept_separate':True}
    export=derived/'fdc_single_analyte_positive.csv'
    con.execute(f"""COPY (SELECT c.nutrient_id analyte_nutrient_id,c.nutrient_name,c.unit,c.amount,c.basis,
      f.source_food_id fdc_id,f.food_id,f.description food_name,f.data_type,f.publication_date,
      c.source_row_id,c.source_id,c.derivation_id,c.data_points,
      CASE WHEN f.data_type='branded_food' THEN 'manufacturer_label' ELSE 'source_food_composition' END food_evidence_kind,
      {sql_literal(source['sha256'])} source_file_sha256,{sql_literal(json.dumps(provenance,sort_keys=True))} provenance_json
      FROM food_composition c JOIN food f USING(food_id) WHERE c.nutrient_id IN ('1057','1058','1111','1112') AND c.amount>0
      ORDER BY c.nutrient_id,try_cast(f.source_food_id AS BIGINT),c.source_row_id)
      TO {sql_literal(export)} (FORMAT CSV, HEADER true)""")
    counts=con.execute("SELECT nutrient_id,nutrient_name,unit,count(*),count(DISTINCT food_id),max(amount) FROM food_composition WHERE nutrient_id IN ('1057','1058','1111','1112') AND amount>0 GROUP BY ALL ORDER BY nutrient_id").fetchall()
    by_unit=con.execute('SELECT unit,count(*) FROM food_composition_rejections GROUP BY unit').fetchall()
    summary['food']['composition_records']=con.execute('SELECT count(*) FROM food_composition').fetchone()[0]
    summary['food']['composition_rejected_mass_records']=rejected_n
    summary['food']['checks']['physically_impossible_mass_rows_rejected']=rejected_n
    summary['food']['mass_policy']=provenance['native_basis']+': mass <=100g,100000mg,100000000ug; no mass inference for IU/activity units; overlapping nutrients never summed'
    receipt={'schema_version':1,'corrected_utc':datetime.now(timezone.utc).isoformat(),'pre_qc_rows':con.execute('SELECT count(*) FROM composition_before').fetchone()[0],
      'eligible_rows':summary['food']['composition_records'],'rejected_rows':rejected_n,'rejected_by_unit':dict(by_unit),'rejection_reason':'mass_exceeds100g_basis',
      'pre_qc_artifact':{'path':str(before),'sha256':digest(before)},'corrected_artifact':{'path':str(target),'sha256':digest(target)},
      'rejection_artifact':{'path':str(rejected),'sha256':digest(rejected)},'single_analyte_export':{'path':str(export),'sha256':digest(export),'rows':sum(row[3] for row in counts),'native_analyte_counts':counts},
      'provenance':provenance,'combined_D2_D3_nutrients_exported':False,'chemical_structure_identity_claimed':False}
    (derived/'food_mass_correction.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    summary['food']['mass_correction_receipt']={'path':str(derived/'food_mass_correction.json'),'sha256':digest(derived/'food_mass_correction.json')}
    db=sqlite3.connect(derived/'expansion_lookup.sqlite')
    db.execute("INSERT OR REPLACE INTO metadata VALUES('summary',?)",(json.dumps(summary),));db.commit();db.close()
    summary_path.write_text(json.dumps(summary,indent=2),encoding='utf-8')
    con.execute('CHECKPOINT');con.close();print(json.dumps(receipt),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);a=p.parse_args();correct(a.root)
