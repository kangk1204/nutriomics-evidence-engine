"""Compact query-backed integration receipt with explicit metric units."""
import argparse
from datetime import datetime,timezone
import importlib.metadata
import json
from pathlib import Path
import duckdb
try:
    from nutriomics_evidence.public_expansion import digest
except ModuleNotFoundError:
    from public_expansion import digest

QUERIES={
 'standardized_records':('SELECT count(*) FROM food_composition','eligible FDC nutrient records; one source-row ID; not sum of heterogeneous modalities'),
 'canonical_food':('SELECT count(*) FROM food','GTIN/market product or native nonbranded food identity'),
 'native_food':('SELECT count(*) FROM food_records','native FDC versioned food IDs including laboratory records'),
 'natural_structures':('SELECT count(*) FROM natural_products','verified source InChI full-key distinct, single-component natural structures'),
 'measured_interaction_assertions':('SELECT count(*) FROM bindingdb_measurement','deduplicated measured Ki/Kd/IC50/EC50 assertions with source/assay/conditions/construct; censoring retained'),
 'exact_measured_interaction_assertions':('SELECT count(*) FROM bindingdb_measurement WHERE exact_positive','same measured assertions with exact positive numeric label only'),
 'binding_affinity_assertions':("SELECT count(*) FROM bindingdb_measurement WHERE endpoint IN ('Kd','Ki')",'measured Kd/Ki source assertions; separate from IC50/EC50'),
 'unique_compound_target_pairs':('SELECT count(DISTINCT full_inchikey||\':\'||target_id) FROM bindingdb_measurement','distinct exact full-key and native construct/species/all-chain target identity'),
 'ctd_response_records':('SELECT count(*) FROM chemical_gene_interaction','native curated chemical/gene response records; not binding measurements'),
 'ffq_frequency':('SELECT count(*) FROM ffq_frequency','cycle/SEQN/native variable/food daily-frequency records; portions absent'),
 'ffq_people':('SELECT count(*) FROM ffq_participant WHERE has_ffq_frequency','actual respondents with at least one FFQ frequency; not all DEMO participants'),
 'ffq_demographic_people':('SELECT count(*) FROM ffq_participant','DEMO participants with cycle+SEQN linkage; has_ffq_frequency differentiates respondents'),
 'genotype_calls':('SELECT count(*) FROM genotype_reference_call','reference-only GT records, sample/GRCh37 locus/alleles; no diet-cohort linkage'),
 'genotype_people':('SELECT count(*) FROM genotype_reference_sample','IGSR reference individuals'),
 'methylation_cells':('SELECT count(*) FROM methylation_abundance','CpG/sample beta cells including explicit missing values'),
 'methylation_observed':("SELECT count(*) FROM methylation_abundance WHERE value_status='observed_source_processed'",'finite processed beta in [0,1]'),
 'methylation_samples':('SELECT count(*) FROM methylation_sample','132 primary and 16 exploratory external samples'),
 'metabolomic_cells':('SELECT count(*) FROM metabolomic_abundance','anonymous analytical-feature/sample log2 abundance cells; missing cells retained'),
 'metabolomic_finite':('SELECT count(*) FROM metabolomic_abundance WHERE isfinite(abundance)','finite depositor log2 abundances; no second log transform'),
 'metabolomic_samples':('SELECT count(*) FROM metabolomic_sample','76 human urine and 14 food-preparation samples; 19 humans'),
 'food_mass_rejections':('SELECT count(*) FROM food_composition_rejections','physically impossible source100g mass records; preserved but excluded from serving'),
 'bindingdb_label_rejections':('SELECT count(*) FROM bindingdb_label_rejections','nonpositive/nonfinite/malformed endpoint labels; excluded from measured registry')}

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',required=True,type=Path);a=p.parse_args();root=a.root;d=root/'derived'
    summary=json.loads((d/'summary.json').read_text());audit=json.loads((d/'allrow_audit.json').read_text())
    con=duckdb.connect(str(d/'expansion.duckdb'),read_only=True);con.execute('SET threads=2');con.execute('SET enable_progress_bar=false')
    metrics={name:{'value':con.execute(query).fetchone()[0],'unit':unit,'sql':query} for name,(query,unit) in QUERIES.items()};con.close()
    metrics['added_food']={'value':summary['food']['delta']['exact_added_canonical_food'],'unit':'new canonical FDC native food IDs relative to exact frozen food-ID snapshot; baseline other namespaces retained separately','sql':'SELECT count(*) FROM food f ANTI JOIN read_parquet(baseline_food_ids.parquet) b ON f.food_id=b.id'}
    metrics['verified_food_single_compounds']=summary['verified_food_single_compounds']|{'unit':'new full-structure compound identities with confirmed edible-food occurrence; source-membership flag not accepted'}
    receipt={'schema_version':1,'generated_utc':datetime.now(timezone.utc).isoformat(),'root':str(root),'serving_database':{'path':str(d/'expansion.duckdb'),'sha256':digest(d/'expansion.duckdb'),'readonly':True},
      'summary':{'path':str(d/'summary.json'),'sha256':digest(d/'summary.json')},'allrow_audit':{'path':str(d/'allrow_audit.json'),'sha256':digest(d/'allrow_audit.json'),'passed':audit['all_structural_checks_zero']},
      'baseline':json.loads((root/'baseline_food_receipt.json').read_text()),'metrics':metrics,
      'native_vs_dedup':{'food':summary['food'],'natural_products':summary['natural_products'],'bindingdb':summary['bindingdb_measured_endpoints']},
      'modalities':json.loads((d/'modality_registry.json').read_text()),'same_person_multiomics_claim':False,'production_modified':False,
      'raw_access_failures':{'foodb':'official bulk403, no bypass or invented occurrence proof','bindingdb_202609':'official historical archive404; no original historical SHA/independence proof'},
      'environment':{'python':__import__('sys').version,'packages':{name:importlib.metadata.version(name) for name in ['duckdb','pyarrow','pandas','numpy','rdkit','requests']}},
      'milestone_judgments':{'standardized_1m':metrics['standardized_records']['value']>=1000000,'added_food_90k':metrics['added_food']['value']>=90000,'natural_structures_400k':metrics['natural_structures']['value']>=400000,'measured_assertions_1_68m':metrics['measured_interaction_assertions']['value']>=1680000,'verified_food_single_compounds_2000':metrics['verified_food_single_compounds']['count']>=2000,'same_person_multiomics':False}}
    path=d/'integration_receipt.json';path.write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(json.dumps({'integration_receipt_path':str(path),'sha256':digest(path),'summary_sha256':receipt['summary']['sha256'],'database_sha256':receipt['serving_database']['sha256'],'metrics':{k:v.get('value',v.get('count')) for k,v in metrics.items()},'milestone_judgments':receipt['milestone_judgments']}),flush=True)

if __name__=='__main__':main()
