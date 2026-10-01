import argparse
import json
from pathlib import Path
from nutriomics_evidence.graph_bridge import integrate

p = argparse.ArgumentParser()
p.add_argument('--database', type=Path, required=True)
p.add_argument('--bridge', type=Path, required=True)
p.add_argument('--regulatory', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
result = integrate(a.database, a.bridge, a.regulatory)
a.output.parent.mkdir(parents=True, exist_ok=True)
a.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False, indent=2))
