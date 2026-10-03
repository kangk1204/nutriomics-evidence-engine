"""Register actual measured/reference modalities without cross-cohort fusion."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import duckdb
try:
    from nutriomics_evidence.public_expansion import digest,sql_literal
except ModuleNotFoundError:
    from public_expansion import digest,sql_literal

def methylation(prepared:Path,derived:Path):
    source=prepared/'matrices.npz';source_sha=digest(source);rows=0;finite_count=0;invalid_count=0;samples=[];writer=None
    with np.load(source,allow_pickle=False) as archive:
        probe_ids=archive['probe_ids'];common=archive['common_probes']
        for dataset,key,samplekey,probes in [('GSE193795','primary','primary_samples',probe_ids),('GSE42774','external','external_samples',common)]:
            matrix=archive[key];ids=archive[samplekey]
            if matrix.shape!=(len(ids),len(probes)) or len(set(ids))!=len(ids) or len(set(probes))!=len(probes):raise ValueError('invalid methylation matrix identities')
            metadata=pd.read_csv(prepared/('primary_metadata.tsv' if key=='primary' else 'external_metadata.tsv'),sep='\t').set_index('sample_id')
            if not set(ids).issubset(set(metadata.index)):raise ValueError('methylation sample absent source metadata')
            for index,sample in enumerate(ids):
                values=matrix[index];finite=np.isfinite(values);valid=finite&(values>=0)&(values<=1)
                statuses=np.where(~finite,'missing',np.where(valid,'observed_source_processed','invalid_beta_range'))
                table=pa.table({'study_id':[dataset]*len(probes),'sample_id':[str(sample)]*len(probes),'probe_id':probes,'beta_value':values,'unit':['beta_fraction']*len(probes),'value_status':statuses,'source_sha256':[source_sha]*len(probes),'raw_idat_reprocessed':[False]*len(probes)})
                if writer is None:writer=pq.ParquetWriter(derived/'methylation_abundance.parquet',table.schema,compression='zstd')
                writer.write_table(table);rows+=len(probes);finite_count+=int(finite.sum());invalid_count+=int((finite&~valid).sum())
                m=metadata.loc[sample]
                samples.append({'study_id':dataset,'sample_id':str(sample),'phenotype':m.get('phenotype'),'tissue':m.get('characteristic_tissue',m.get('source_name_ch1')),'platform_id':m.get('platform_id'),'same_person_ffq_or_metabolomics':False})
    if writer:writer.close()
    pd.DataFrame(samples).to_parquet(derived/'methylation_sample.parquet',index=False)
    return {'type':'epigenomics','source_path':str(source),'source_sha256':source_sha,'sample_counts':{study:int(n) for study,n in pd.DataFrame(samples).groupby('study_id').size().items()},'measurement_rows':rows,'finite_values':finite_count,'invalid_beta_range':invalid_count,'raw_idat_reprocessed':False,'cohort_linkage_to_other_modalities':False}

def metabolomics(source:Path,atlas_src:Path,derived:Path):
    sys.path.insert(0,str(atlas_src))
    from nutriomics_atlas.metabolomics import audit_matrix
    values,samples,audit=audit_matrix(source)
    samples['study_id']='ST001257';samples.to_parquet(derived/'metabolomic_sample.parquet',index=False)
    with pq.ParquetWriter(derived/'metabolomic_abundance.parquet',pa.schema([('study_id',pa.string()),('sample_id',pa.string()),('feature_id',pa.string()),('abundance',pa.float64()),('unit',pa.string()),('identified_structure',pa.bool_())]),compression='zstd') as writer:
        for sample,row in values.iterrows():
            n=len(row);writer.write_table(pa.table({'study_id':['ST001257']*n,'sample_id':[sample]*n,'feature_id':['AN002086:'+str(feature) for feature in row.index],'abundance':row.to_numpy(dtype=float),'unit':['depositor_log2_abundance']*n,'identified_structure':[False]*n}))
    return {'type':'metabolomics','source_inputs':audit['inputs'],'people':audit['independent_people'],'human_measurements':audit['urine_samples'],'food_preparations':audit['food_preparations'],'analytical_features':audit['analytical_features'],'finite_values':audit['finite_values'],'missing_values':audit['missing_values'],'measurement_rows':values.size,'identified_compounds':0,'cohort_linkage_to_other_modalities':False,'period_or_sequence_available':False}

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--methyl-prepared',type=Path,required=True);p.add_argument('--metabolomics-source',type=Path,required=True);p.add_argument('--atlas-src',type=Path,required=True);a=p.parse_args()
    derived=a.root/'derived'
    methyl=methylation(a.methyl_prepared,derived);metabo=metabolomics(a.metabolomics_source,a.atlas_src,derived)
    registry={'schema_version':1,'registered_utc':datetime.now(timezone.utc).isoformat(),'patient_multiomics_fusion_performed':False,'individual_modality_sources_are_different_people':True,'modalities':{'epigenomics':methyl,'metabolomics':metabo,'genomics':json.loads((a.root/'genotype_reference_receipt.json').read_text()),'ffq':json.loads((derived/'summary.json').read_text())['ffq']}}
    con=duckdb.connect(str(derived/'expansion.duckdb'));con.execute('SET threads=2');con.execute('SET enable_progress_bar=false')
    for name in ['methylation_abundance','methylation_sample','metabolomic_abundance','metabolomic_sample']:
        path=derived/f'{name}.parquet';con.execute(f'CREATE OR REPLACE VIEW {name} AS SELECT * FROM read_parquet({sql_literal(path)})')
    registry['query_row_counts']={name:con.execute(f'SELECT count(*) FROM {name}').fetchone()[0] for name in ['methylation_abundance','methylation_sample','metabolomic_abundance','metabolomic_sample','genotype_reference_call','genotype_reference_sample','ffq_frequency','ffq_participant']}
    con.execute('CHECKPOINT');con.close()
    (derived/'modality_registry.json').write_text(json.dumps(registry,indent=2),encoding='utf-8')
    summary=json.loads((derived/'summary.json').read_text());summary['modality_registry']={'path':str(derived/'modality_registry.json'),'sha256':digest(derived/'modality_registry.json'),'types_available':['genomics_reference','epigenomics_measured','ffq_frequency','metabolomics_processed_anonymous_features'],'same_person_fusion':False}
    summary['outputs']=[{'path':str(path),'sha256':digest(path),'bytes':path.stat().st_size} for path in sorted(derived.glob('*')) if path.suffix in {'.parquet','.duckdb','.sqlite'}]
    (derived/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(json.dumps({'status':'complete','modality_query_counts':registry['query_row_counts']}),flush=True)

if __name__=='__main__':main()
