"""Acquire pinned official public releases into an isolated staging directory.

Complete archives are checked before atomic promotion. Never writes production DBs.
"""
from __future__ import annotations
import argparse
import concurrent.futures
import gzip
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone
import time
import zipfile
import requests

SOURCES = [
    ("bindingdb_202610", "https://www.bindingdb.org/rwd/bind/downloads/BindingDB_All_202610_tsv.zip", "BindingDB_All_202610_tsv.zip", "2026-10", "BindingDB academic use; preserve attribution and source terms"),
    ("bindingdb_assays_202610", "https://www.bindingdb.org/rwd/bind/downloads/BindingDB_Assays_202610_tsv.zip", "BindingDB_Assays_202610_tsv.zip", "2026-10", "BindingDB academic use; preserve attribution and source terms"),
    ("bindingdb_rsid_202610", "https://www.bindingdb.org/rwd/bind/downloads/BindingDB_rsid_eaids_202610_tsv.zip", "BindingDB_rsid_eaids_202610_tsv.zip", "2026-10", "BindingDB academic use; preserve attribution and source terms"),
    ("usda_fdc_202604", "https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_csv_2026-04-30.zip", "FoodData_Central_csv_2026-04-30.zip", "2026-04-30", "US federal public-domain data"),
    ("coconut_202610", "https://coconut.s3.uni-jena.de/prod/downloads/2026-10/coconut_csv-10-2026.zip", "coconut_csv-10-2026.zip", "2026-10", "CC0"),
    ("lotus_202301", "https://zenodo.org/api/records/7534071/files/230106_frozen.csv.gz/content", "230106_frozen.csv.gz", "2023-01-06 frozen", "CC0 (Wikidata/Zenodo); references retain source rights"),
    ("lotus_metadata_202301", "https://zenodo.org/api/records/7534071/files/230106_frozen_metadata.csv.gz/content", "230106_frozen_metadata.csv.gz", "2023-01-06 frozen", "CC0 (Wikidata/Zenodo); references retain source rights"),
]
for year, cycle, suffix in [(2003, "2003-2004", "C"), (2005, "2005-2006", "D")]:
    for table in ("FFQDC", "FFQRAW", "FOODLK", "VARLK", "DEMO", "BPX", "BPQ"):
        name = f"{table}_{suffix}"
        SOURCES.append((f"nhanes_{name}", f"https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/{year}/DataFiles/{name}.XPT", f"{name}.XPT", cycle, "US federal public data; NHANES analytic guidelines"))
        SOURCES.append((f"nhanes_{name}_documentation", f"https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/{year}/DataFiles/{name}.htm", f"{name}.htm", cycle, "US federal public documentation"))

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8*1024*1024), b""):
            h.update(block)
    return h.hexdigest()

def verify_archive(path: Path) -> dict:
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            bad = archive.testzip()
            if bad:
                raise ValueError(f"CRC error: {bad}")
            return {"validation": "full_zip_crc", "members": [{"name": i.filename, "bytes": i.file_size, "crc32": i.CRC} for i in archive.infolist()]}
    if path.suffix.lower() == ".gz":
        size = 0
        with gzip.open(path, "rb") as stream:
            for block in iter(lambda: stream.read(8*1024*1024), b""):
                size += len(block)
        return {"validation": "full_gzip_crc_to_eof", "uncompressed_bytes": size}
    if path.suffix.lower() == ".xpt":
        with path.open("rb") as stream:
            header = stream.read(80)
        if not header.startswith(b"HEADER RECORD*******LIBRARY HEADER RECORD!!!!!!!"):
            raise ValueError("not a SAS transport file (possibly HTML error response)")
        return {"validation": "sas_transport_header; full parser validation in ETL"}
    return {"validation": "source_document_snapshot"}

def download(source: tuple, root: Path) -> dict:
    sid, url, name, version, license_note = source
    path = root / "raw" / name
    receipt = root / "receipts" / f"{sid}.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    now = lambda: datetime.now(timezone.utc).isoformat()
    result = dict(source_id=sid, url=url, version=version, license=license_note, started_at=now(), path=str(path), redistribution_review="source_terms_recorded; raw data never committed")
    try:
        if not path.exists():
            partial = path.with_name(path.name + ".part")
            for attempt in range(3):
                try:
                    with requests.get(url, stream=True, timeout=(30,120), headers={"User-Agent": "NutriOmicsResearch/1.0 public dataset acquisition"}) as response:
                        response.raise_for_status()
                        result["response"] = {k: response.headers.get(k) for k in ("Content-Type", "Content-Length", "ETag", "Last-Modified")}
                        result["resolved_url"] = response.url
                        with partial.open("wb") as output:
                            for chunk in response.iter_content(1024*1024):
                                if chunk:
                                    output.write(chunk)
                    # Use the intended suffix for validation without renaming an unchecked file.
                    if path.suffix.lower() == ".zip":
                        with zipfile.ZipFile(partial) as archive:
                            bad = archive.testzip()
                            if bad: raise ValueError(f"CRC error: {bad}")
                    elif path.suffix.lower() == ".gz":
                        with gzip.open(partial, "rb") as stream:
                            while stream.read(8*1024*1024): pass
                    elif path.suffix.lower() == ".xpt":
                        with partial.open("rb") as transport:
                            valid_header = transport.read(80).startswith(b"HEADER RECORD*******LIBRARY HEADER RECORD!!!!!!!")
                        if not valid_header:
                            raise ValueError("not a SAS transport file")
                    partial.replace(path)
                    break
                except Exception:
                    if attempt == 2: raise
                    time.sleep(2*(attempt+1))
        result.update(status="complete", sha256=sha256(path), bytes=path.stat().st_size, **verify_archive(path))
    except Exception as exc:
        result.update(status="failed", error=f"{type(exc).__name__}: {exc}")
    result["finished_at"] = now()
    receipt.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"source_id": sid, "status": result["status"], "bytes": result.get("bytes"), "error": result.get("error")}), flush=True)
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=3, choices=range(1,5))
    parser.add_argument("--only", nargs="*")
    args = parser.parse_args()
    sources = [s for s in SOURCES if not args.only or s[0] in args.only]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda s: download(s, args.root), sources))
    manifest = {"schema_version": 1, "acquisition_only": True, "production_db_modified": False, "sources": results}
    args.root.mkdir(parents=True, exist_ok=True)
    (args.root / "acquisition_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return int(any(r["status"] != "complete" for r in results))

if __name__ == "__main__":
    raise SystemExit(main())
