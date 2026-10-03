import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import zipfile
import duckdb
import pytest

spec=importlib.util.spec_from_file_location('endpoint_staging',Path(__file__).parents[1]/'scripts/stage_bindingdb_endpoints.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

def test_native_endpoint_parser_retains_censoring_and_rejects_bad_labels():
    assert module.parse_affinity(' >= 2.5e3 ')==('>=',2500.)
    assert module.parse_affinity('≤10')==('<=',10.)
    assert module.parse_affinity('20')==('=',20.)
    for value in ['NaN','Inf','0','-20','1-4','10uM']:
        with pytest.raises(ValueError):module.parse_affinity(value)

def archive(root,sid,rows):
    target=root/'raw'/f'{sid}.zip'
    buffer=io.StringIO();csv.writer(buffer,delimiter='\t',quoting=csv.QUOTE_NONE,escapechar='\\').writerows(rows)
    with zipfile.ZipFile(target,'w') as z:z.writestr(sid+'.tsv',buffer.getvalue())
    (root/'receipts'/f'{sid}.json').write_text(json.dumps({'source_id':sid,'status':'complete','path':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}))

def test_endpoint_registry_dedups_same_assay_preserves_endpoint_and_invalid_structure(tmp_path):
    for name in ['raw','receipts','derived']:(tmp_path/name).mkdir()
    (tmp_path/'derived/summary.json').write_text('{}')
    header=['BindingDB Reactant_set_id','Ligand SMILES','Ligand InChI','Ligand InChI Key','BindingDB MonomerID','Target Name','Target Source Organism According to Curator or DataSource','Ki (nM)','IC50 (nM)','Kd (nM)','EC50 (nM)','Article DOI','PMID','Number of Protein Chains in Target (>1 implies a multichain complex)','BindingDB Target Chain Sequence 1']
    base=['1','CCO','InChI=1S/C2H6O/c1-2-3/h3H,2H2,1H3','LFQSCWFLJHTTHZ-UHFFFAOYSA-N','7','Target','Homo sapiens','10','','>20','','10.1000/test','123','1','ACDEFGHIKLMNPQRSTVWYACD']
    rows=[base]
    second=base.copy();second[0]='2';rows.append(second)
    third=base.copy();third[0]='3';third[7]='';third[8]='=40';third[9]='';third[11]='';rows.append(third)
    invalid=base.copy();invalid[0]='4';invalid[7]='NaN';invalid[9]='';invalid[10]='0';rows.append(invalid)
    unknown=base.copy();unknown[0]='5';unknown[3]='';unknown[7]='';unknown[9]='50';rows.append(unknown)
    archive(tmp_path,'bindingdb_202610',[header]+rows)
    archive(tmp_path,'bindingdb_rsid_202610',[['REACTANT_SET_ID','ENTRYID_ASSAYID']]+[[str(i),'285_1'] for i in range(1,6)])
    archive(tmp_path,'bindingdb_assays_202610',[['ENTRYID','ASSAYID','ASSAY_NAME','DESCRIPTION'],['285','1','Binding assay','Assay source']])
    audit=module.stage(tmp_path)
    assert audit['parser']['raw_counts']['raw_rows']==5
    assert audit['typed_native_measurement_rows']==6
    assert audit['measured_dedup_assertions']==3
    assert audit['exact_positive_dedup_assertions']==2
    assert audit['eligibility_source_row_counts']['unverified_full_structure']==1
    assert all(value==0 for value in audit['checks'].values())
    con=duckdb.connect(str(tmp_path/'derived/expansion.duckdb'),read_only=True)
    assert con.execute('SELECT endpoint,relation,value_nm FROM bindingdb_measurement ORDER BY endpoint').fetchall()==[('IC50','=',40.),('Kd','>',20.),('Ki','=',10.)]
    assert con.execute('SELECT count(*) FROM bindingdb_label_rejections').fetchone()[0]==2
    assert con.execute("SELECT source_group FROM bindingdb_measurement WHERE endpoint='IC50'").fetchone()[0]=='doi:10.1000/test'
    con.close()
