"""Correct a citation URL only; preserve raw hash, rows and prior full-integrity audit."""
import argparse
import hashlib
import json
from pathlib import Path
from nutriomics_evidence.graph import canonical, connect, structure_coverage
from nutriomics_evidence.sources import now

p=argparse.ArgumentParser();p.add_argument('--database',type=Path,required=True);p.add_argument('--bridge',type=Path,required=True);p.add_argument('--snapshot',type=Path,required=True)
a=p.parse_args()
manifest=json.loads((a.bridge/'bridge_source_manifest.json').read_text())
snapshot=json.loads(a.snapshot.read_text())
if snapshot['integrity']!='ok' or snapshot['errors']:raise ValueError('Prior full graph integrity did not pass')
url=manifest['sources'][0]['url']
db=connect(a.database)
with db:
    row=db.execute("SELECT id,metadata_json FROM source WHERE id LIKE 'USDA-Flavonoids-R03-3:%'").fetchone()
    if row is None:raise ValueError('Frozen source is missing')
    record=json.loads(row['metadata_json']);before=record['source_url']
    record['source_url']=url;record['upstream_provenance']=manifest['sources']
    db.execute('UPDATE source SET metadata_json=? WHERE id=?',(canonical(record),row['id']))
    snapshot['structure_coverage']=structure_coverage(db)
    snapshot['unresolved_structure_nodes_definition']='Legacy count lacking an exact_structure mapping; use structure_coverage for own molecular structure availability'
    snapshot['food_panel']['source_specific_food_ids']=db.execute("SELECT count(*) FROM node WHERE kind='food' AND id LIKE 'USDA-Flav-R03-3:%'").fetchone()[0]
    snapshot['metadata_url_correction']={'source_id':row['id'],'old_url':before,'correct_url':url,'utc':now(),'raw_sha256_unchanged':record['sha256'],'audit_scope':'Metadata only; prior full integrity_check passed, no structural/measurement changes'}
    tables={t:db.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in snapshot['tables']}
    if tables!=snapshot['tables']:raise ValueError('Frozen table counts changed')
db.close()
a.snapshot.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(snapshot,ensure_ascii=False,indent=2))
