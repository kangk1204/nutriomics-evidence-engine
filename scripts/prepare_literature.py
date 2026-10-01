"""Freeze scoped CTD dictionary candidates over the approved PubMed corpus."""
import argparse
import json
from pathlib import Path
from nutriomics_evidence.literature import prepare

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--articles", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--ctd-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--expected-documents", type=int, default=1198)
    args = parser.parse_args()
    print(json.dumps(prepare(args.articles, args.source_manifest, args.ctd_dir, args.out, args.expected_documents), indent=2))
