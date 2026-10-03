"""Freeze SQL counts, provenance, and complete artifacts after isolated ETL."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import duckdb
import pandas as pd
try:
    from nutriomics_evidence.public_expansion import digest,sql_literal,mass_exceeds_basis_sql
except ModuleNotFoundError:
    from public_expansion import digest,sql_literal,mass_exceeds_basis_sql

QUERIES={
 'food_duplicate_id':'SELECT count(*)-count(DISTINCT food_id) FROM food',
 'food_duplicate_identity':'SELECT count(*)-count(DISTINCT identity_key) FROM food',
 'food_invalid_registry_type':"SELECT count(*) FROM food WHERE data_type NOT IN ('branded_food','sr_legacy_food','foundation_food','survey_fndds_food')",
 'composition_negative_or_nonfinite':"SELECT count(*) FROM food_composition WHERE amount<0 OR NOT isfinite(amount)",
 'composition_impossible_per100g_mass':"SELECT count(*) FROM food_composition WHERE "+mass_exceeds_basis_sql(),
 'composition_empty_unit_or_basis':"SELECT count(*) FROM food_composition WHERE unit IS NULL OR basis!='source100g'",
 'composition_duplicate_source_row':'SELECT count(*)-count(DISTINCT source_row_id) FROM food_composition',
 'composition_orphan_food':'SELECT count(*) FROM food_composition c ANTI JOIN food f USING(food_id)',
 'natural_product_duplicate_full_key':'SELECT count(*)-count(DISTINCT full_inchikey) FROM natural_products',
 'natural_product_unverified_or_mixture':'SELECT count(*) FROM natural_products WHERE NOT inchi_hash_verified OR NOT single_component',
 'ffq_duplicate_source_row':'SELECT count(*)-count(DISTINCT source_row_id) FROM ffq_frequency',
 'ffq_orphan_person':'SELECT count(*) FROM ffq_frequency f ANTI JOIN ffq_participant p USING(participant_id)',
 'ffq_negative_frequency':'SELECT count(*) FROM ffq_frequency WHERE FFQ_FREQ<0',
 'ffq_portion_or_absolute_intake_claim':'SELECT count(*) FROM ffq_frequency WHERE portion_size_available OR absolute_nutrient_intake_derived',
 'genotype_nonreference_claim':'SELECT count(*) FROM genotype_reference_call WHERE NOT reference_context_only',
 'genotype_orphan_reference_sample':'SELECT count(*) FROM genotype_reference_call g ANTI JOIN genotype_reference_sample p ON g.sample_id=p.sample',
 'genotype_wrong_build_or_coordinate':"SELECT count(*) FROM genotype_reference_call WHERE build!='GRCh37' OR chromosome!='11' OR position<61560000 OR position>61750000",
 'methylation_invalid_beta':'SELECT count(*) FROM methylation_abundance WHERE value_status=\'invalid_beta_range\'',
 'methylation_orphan_sample':'SELECT count(*) FROM methylation_abundance m ANTI JOIN methylation_sample s USING(study_id,sample_id)',
 'metabolomic_orphan_sample':'SELECT count(*) FROM metabolomic_abundance m ANTI JOIN metabolomic_sample s USING(study_id,sample_id)',
 'metabolomic_false_structure_identity':'SELECT count(*) FROM metabolomic_abundance WHERE identified_structure',
}

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);a=p.parse_args();root=a.root;derived=root/'derived'
    con=duckdb.connect(str(derived/'expansion.duckdb'));con.execute('SET threads=2');con.execute('SET enable_progress_bar=false')
    sources=[]
    for receipt_path in sorted((root/'receipts').glob('*.json')):
        r=json.loads(receipt_path.read_text())
        if r.get('status')=='complete':
            actual=root/'raw'/r['path'].replace('\\','/').rsplit('/',1)[-1]
            if digest(actual)!=r['sha256']:raise ValueError('source changed before freeze:'+r['source_id'])
            sources.append({'source_id':r['source_id'],'url':r['url'],'version':r['version'],'license':r['license'],'raw_path':str(actual),'sha256':r['sha256'],'validation':r['validation']})
    sources.append({'source_id':'ctd_20260929','url':'https://ctdbase.org/reports/CTD_chem_gene_ixns.csv.gz','version':'2026-09-29','license':'CTD terms; user-provided raw; no Git redistribution','raw_path':str(root/'raw/CTD_chem_gene_ixns.csv.gz'),'sha256':digest(root/'raw/CTD_chem_gene_ixns.csv.gz'),'validation':'prior full-gzip audit exact hash; complete strict CSV parse in current ETL'})
    genotype=json.loads((root/'genotype_reference_receipt.json').read_text())
    sources.append({'source_id':'IGSR_phase3_20130502_v5b','url':genotype['vcf_remote_metadata']['url'],'version':'GRCh37 phase3 20130502 v5b','license':'public IGSR reference; source attribution/reuse policy retained','raw_path':str(root/'raw/IGSR_phase3_GRCh37_FADS_region.vcf.gz'),'sha256':genotype['subset_sha256'],'validation':'indexed region only; original index SHA and remote metadata in genotype receipt; full source chromosome not hashed/downloaded'})
    modality=json.loads((derived/'modality_registry.json').read_text())
    methyl=modality['modalities']['epigenomics']
    if digest(Path(methyl['source_path']))!=methyl['source_sha256']:raise ValueError('prepared methylation source changed before freeze')
    for accession in ['GSE193795','GSE42774']:
        sources.append({'source_id':accession,'url':'https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc='+accession,'version':'frozen prepared matrix2026-10-01','license':'GEO public research data; cite dataset/authors; no raw Git redistribution','raw_path':methyl['source_path'],'sha256':methyl['source_sha256'],'validation':'existing source-processed beta matrix identities/range; no rawIDAT rerun'})
    for input_record in modality['modalities']['metabolomics']['source_inputs']:
        if digest(root/'raw/ST001257'/input_record['name'])!=input_record['sha256']:raise ValueError('ST001257 input changed before freeze: '+input_record['name'])
        if input_record['name']=='untargeted.tsv':
            sources.append({'source_id':'ST001257_AN002086','url':input_record['source_url'],'version':'existing frozen depositor processed source','license':'public MetabolomicsWorkbench; cite study/authors','raw_path':str(root/'raw/ST001257/untargeted.tsv'),'sha256':input_record['sha256'],'validation':'source manifest hash; sample/factor identities checked by existing atlas audit'})
    panel_receipt_path=derived/'food_standard_panel_receipt.json'
    if panel_receipt_path.exists():
        panel_receipt=json.loads(panel_receipt_path.read_text())
        for item in panel_receipt['inputs']:
            path=root/'raw/food_standard_panel'/item['name']
            if digest(path)!=item['sha256']:raise ValueError('food standard panel input changed')
            if item['name']=='Isoflav_R2-1.accdb':
                sources.append({'source_id':'usda_isoflavone_r2_1','url':'https://www.ars.usda.gov/ARSUserFiles/80400535/Data/isoflav/Isoflav_R2-1.accdb','version':'Release2.1','license':'US federal public-domain data','raw_path':str(path),'sha256':item['sha256'],'validation':'official ACCDB parsed by DTI pipeline; native tables preserved; totals excluded from single-analyte composition'})
            elif item['name'].startswith('pubchem_cid_'):
                sources.append({'source_id':item['name'].removesuffix('_properties.json'),'url':item['source_url'],'version':'frozen response2026-10-03','license':'PubChem attribution and individual provider terms retained','raw_path':str(path),'sha256':item['sha256'],'validation':'exact PubChem CID and fullInChIKey checked; source SMILES recomputed standard full key; food concept/aglycone limitations retained'})
    frame=pd.DataFrame(sources);frame.to_parquet(derived/'source_registry.parquet',index=False)
    con.execute(f'CREATE OR REPLACE VIEW source_registry AS SELECT * FROM read_parquet({sql_literal(derived/"source_registry.parquet")})')
    queries=dict(QUERIES)
    tables=['food','food_records','food_composition','food_composition_rejections','natural_products','natural_product_occurrence','chemical_gene_interaction','ffq_frequency','ffq_participant','genotype_reference_call','genotype_reference_sample','methylation_abundance','methylation_sample','metabolomic_abundance','metabolomic_sample','source_registry']
    if panel_receipt_path.exists():
        tables+=['food_standard_analyte_panel','usda_isoflavone_food','usda_isoflavone_native_measurement','usda_isoflavone_analyte_definition','usda_isoflavone_composition']
        queries.update({'food_standard_panel_bad_key':'SELECT count(*) FROM food_standard_analyte_panel WHERE compound_id!=recomputed_standard_full_inchikey',
            'food_standard_panel_unjustified_exposure_claim':'SELECT count(*) FROM food_standard_analyte_panel WHERE native_free_oral_ligand_exposure_verified',
            'isoflavone_composition_total_promoted_single_analyte':"SELECT count(*) FROM usda_isoflavone_composition WHERE Nutr_No='713'",
            'isoflavone_composition_orphan_food':'SELECT count(*) FROM usda_isoflavone_composition c ANTI JOIN usda_isoflavone_food f USING(NDB_No)'})
    if con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='bindingdb_measurement'").fetchone()[0]:
        tables+=['bindingdb_measured_source_records','bindingdb_measurement_candidates','bindingdb_measurement','bindingdb_source_ledger','bindingdb_assay_description','bindingdb_label_rejections']
        queries.update({
            'bindingdb_duplicate_measurement':'SELECT count(*)-count(DISTINCT measurement_id) FROM bindingdb_measurement',
            'bindingdb_nonpositive_or_nonfinite':'SELECT count(*) FROM bindingdb_measurement WHERE value_nm<=0 OR NOT isfinite(value_nm)',
            'bindingdb_unverified_structure_or_target':'SELECT count(*) FROM bindingdb_measurement WHERE NOT inchi_hash_verified OR NOT protein_sequences_valid',
            'bindingdb_censored_as_exact':"SELECT count(*) FROM bindingdb_measurement WHERE exact_positive!=(relation='=')",
            'bindingdb_wrong_endpoint_or_unit':"SELECT count(*) FROM bindingdb_measurement WHERE endpoint NOT IN ('Kd','Ki','IC50','EC50') OR unit!='nM'"})
    checks={name:con.execute(query).fetchone()[0] for name,query in queries.items()}
    row_counts={name:con.execute(f'SELECT count(*) FROM {name}').fetchone()[0] for name in tables}
    con.execute('CHECKPOINT');con.close()
    audit={'schema_version':1,'frozen_utc':datetime.now(timezone.utc).isoformat(),'complete_sql_checks':checks,'all_structural_checks_zero':all(value==0 for value in checks.values()),'queries':queries,'row_counts':row_counts,'production_db_modified':False,'same_person_multimodal_fusion':False,'known_limits':['Food baseline uses exact native source IDs; branded-product identities dedup GTIN/market within new FDC source','FDC supplier/source errors exceeding 100g mass per100g are retained only in rejection ledger','COCONUT source InChI hash verified, all source SMILES not independently recomputed','FooDB source membership and LOTUS organism occurrence not verified edible-food occurrence','Genotypes are reference participants; methylation, NHANES, ST001257 participants are different cohorts','ST001257 analytical features lack confirmed compound identities','FFQ daily frequency has no portion size; no absolute nutrient amounts derived','BindingDB source assertion registry preserves Ki/Kd/IC50/EC50/censoring separately; not all endpoints imply physical binding; strict Kd benchmark separate']}
    code_root=root/'code';audit['code_sha256']={path.name:digest(path) for path in sorted(code_root.glob('*.py'))}
    audit['outputs']=[{'path':str(path),'sha256':digest(path),'bytes':path.stat().st_size} for path in sorted(derived.glob('*')) if path.suffix in {'.parquet','.duckdb','.sqlite'}]
    (derived/'allrow_audit.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
    summary=json.loads((derived/'summary.json').read_text());summary['allrow_audit']={'path':str(derived/'allrow_audit.json'),'sha256':digest(derived/'allrow_audit.json'),'passed':audit['all_structural_checks_zero']};summary['outputs']=audit['outputs'];summary['frozen_utc']=audit['frozen_utc']
    (derived/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps({'checks':checks,'row_counts':row_counts,'summary_sha256':digest(derived/'summary.json')}),flush=True)
    return int(not audit['all_structural_checks_zero'])

if __name__=='__main__':raise SystemExit(main())
