"""Official openFDA UNII snapshot and conservative targeted identity adapter.

Names yield candidate mappings. An explicit UNII input yields regulatory identity.
Neither creates a verified structure, approval, safety, efficacy or binding label.
Graph access is read-only; the engine owner performs any authorized ingestion.
"""
import argparse
import hashlib
import json
import re
import sqlite3
import unicodedata
import zipfile
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

INDEX = "https://api.fda.gov/download.json"
UNII_RE = re.compile(r"^[A-Z0-9]{10}$")
DEFAULT_TERMS = ["caffeine","quercetin","resveratrol","epigallocatechin gallate","ascorbic acid","folic acid","potassium","magnesium","sodium chloride"]


def sha(path):
    hasher = hashlib.sha256()
    with open(path,"rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):
            hasher.update(block)
    return hasher.hexdigest()


def save(path,payload):
    path = Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding="utf-8")


def normalized_name(text):
    # Do not delete salt/stereochemical qualifiers, punctuation or chemical-form words.
    return " ".join(unicodedata.normalize("NFKC",text).casefold().split())


def strings(value,field):
    if isinstance(value,str):
        value = [value]
    if not isinstance(value,list) or not value or any(not isinstance(item,str) or not item.strip() for item in value):
        raise ValueError(f"Invalid nonempty source field: {field}")
    return [item.strip() for item in value]


def normalize_records(raw):
    if not isinstance(raw,list) or not raw:
        raise ValueError("openFDA results must be a nonempty list")
    grouped = {}
    variants = Counter()
    for index,record in enumerate(raw):
        if not isinstance(record,dict) or "unii" not in record:
            raise ValueError(f"Missing UNII field in row {index}")
        codes = strings(record["unii"],"unii")
        if any(not UNII_RE.fullmatch(code) for code in codes):
            raise ValueError(f"Invalid UNII in row {index}")
        name_key = next((key for key in ("substance_name","subtstance_name","substance_names") if key in record),None)
        if name_key is None:
            raise ValueError(f"No known source substance-name field in row {index}: {list(record)}")
        names = strings(record[name_key],name_key)
        variants[name_key] += 1
        for code in codes:
            item = grouped.setdefault(code,{"id":"FDA-UNII:"+code,"unii":code,"names":set(),"source_record_indices":[],
                                             "multi_unii_source_record":False,"structure_verified":False,"regulatory_approval":None,
                                             "safety_or_efficacy":None,"binding_affinity":None,"human_reviewed":False})
            item["names"].update(names)
            item["source_record_indices"].append(index)
            item["multi_unii_source_record"] |= len(codes)>1
    for item in grouped.values():
        item["names"] = sorted(item["names"])
        item["schema_checked"] = True
        item["relation"] = "regulatory_identity"
        item["basis"] = "Official openFDA structured UNII/name record; molecular form and cross-database structure equality not established"
    return grouped,dict(variants)


def load_subjects(subjects_json=None,database=None):
    subjects = []
    if subjects_json:
        payload = json.loads(Path(subjects_json).read_text(encoding="utf-8"))
        subjects = payload["subjects"] if isinstance(payload,dict) else payload
        if not isinstance(subjects,list):
            raise ValueError("Subjects input must be a list or {'subjects':list}")
        for row in subjects:
            if not isinstance(row,dict) or not isinstance(row.get("subject"),str) or not row["subject"].strip() or not isinstance(row.get("name"),str) or not row["name"].strip():
                raise ValueError("Each subject requires a source node ID and name")
    if database:
        connection = sqlite3.connect(Path(database).resolve().as_uri()+"?mode=ro",uri=True)
        try:
            known = dict(connection.execute("SELECT id,name FROM node WHERE kind='chemical'"))
        finally:
            connection.close()
        if subjects:
            if any(row["subject"] not in known for row in subjects):
                raise ValueError("Subjects input includes a node absent from the existing graph")
        else:
            subjects = [{"subject":identifier,"name":name} for identifier,name in sorted(known.items())]
    if len({row["subject"] for row in subjects})!=len(subjects):
        raise ValueError("Duplicate subject ID")
    return subjects


def targeted_mappings(grouped,subjects,terms):
    by_name = {}
    for code,item in grouped.items():
        for name in item["names"]:
            by_name.setdefault(normalized_name(name),set()).add(code)
    mappings,unmatched = [],[]
    for subject in subjects:
        if subject.get("unii"):
            code = subject["unii"]
            if not isinstance(code,str) or not UNII_RE.fullmatch(code) or code not in grouped:
                raise ValueError("Explicit source UNII input not present in checked snapshot")
            candidates,relation = {code},"regulatory_identity"
            basis = "Explicit input UNII verified against original openFDA structured record; not an exact-structure match"
        else:
            candidates = by_name.get(normalized_name(subject["name"]),set())
            relation = "candidate_name"
            basis = "Exact NFKC/casefold/whitespace-normalized source-name match only; chemical-form/structure equality requires review"
        if not candidates:
            unmatched.append(subject)
        for code in sorted(candidates):
            mappings.append({"subject":subject["subject"],"namespace":"FDA-UNII","identifier":code,"relation":relation,
                             "basis":basis,"reviewed":False,"structure_verified":False,"match_name":subject["name"],
                             "source_names":grouped[code]["names"],"multiple_candidate_uniis":len(candidates)>1,
                             "multi_unii_source_record":grouped[code]["multi_unii_source_record"],"source_record_indices":grouped[code]["source_record_indices"],
                             "regulatory_approval":None,"binding_affinity":None})
    selected = []
    for term in terms:
        codes = sorted(by_name.get(normalized_name(term),set()))
        selected.append({"term":term,"matching_uniis":codes,"match_basis":"name candidate only","records":[grouped[code] for code in codes]})
    return mappings,unmatched,selected


def fetch(args):
    out = Path(args.out)
    out.mkdir(parents=True,exist_ok=True)
    client = requests.Session()
    client.headers["User-Agent"] = "NutriOmics-research/2026 FDA-identity-source-adapter"
    client.mount("https://",HTTPAdapter(max_retries=Retry(total=4,backoff_factor=1,status_forcelist=[429,500,502,503,504])))
    response = client.get(INDEX,timeout=(20,90))
    response.raise_for_status()
    index = response.json()
    entry = index["results"]["other"]["unii"]
    if entry["export_date"]!=args.expected_version or entry["total_records"]!=args.expected_records:
        raise ValueError("FDA source manifest changed; explicitly choose a new expected version/count and output directory")
    save(out/"download_index.json",index)
    if len(entry["partitions"])!=1 or entry["partitions"][0]["records"]!=args.expected_records:
        raise ValueError("Unexpected UNII partition layout")
    url = entry["partitions"][0]["file"]
    if not url.startswith("https://download.open.fda.gov/other/unii/") or not url.endswith(".json.zip"):
        raise ValueError("UNII archive is not on the official expected endpoint")
    archive_path = out/Path(url).name
    if not archive_path.exists():
        temporary = archive_path.with_suffix(".partial")
        with client.get(url,stream=True,timeout=(30,180)) as response:
            response.raise_for_status()
            with open(temporary,"wb") as stream:
                for chunk in response.iter_content(1024*1024):
                    stream.write(chunk)
        temporary.replace(archive_path)
    with zipfile.ZipFile(archive_path) as archive:
        if archive.testzip():
            raise ValueError("Official UNII archive failed CRC")
        names = [name for name in archive.namelist() if name.endswith(".json")]
        if len(names)!=1:
            raise ValueError("Expected one official UNII JSON member")
        raw_json = archive.read(names[0])
        payload = json.loads(raw_json)
        member = names[0]
    if not isinstance(payload,dict) or not isinstance(payload.get("results"),list):
        raise ValueError("Invalid openFDA export JSON structure")
    if payload.get("meta",{}).get("last_updated")!=args.expected_version:
        raise ValueError("Archive payload date differs from the explicitly pinned FDA export version")
    raw = payload["results"]
    if len(raw)!=args.expected_records:
        raise ValueError(f"Snapshot records mismatch: {len(raw)} != {args.expected_records}")
    grouped,variants = normalize_records(raw)
    with open(out/"unii_records.jsonl","w",encoding="utf-8") as stream:
        for code in sorted(grouped):
            stream.write(json.dumps(grouped[code],ensure_ascii=False)+"\n")
    subjects = load_subjects(args.subjects_json,args.database)
    mappings,unmatched,selected = targeted_mappings(grouped,subjects,args.terms)
    mapping_payload = {"source_url":url,"version":args.expected_version,"mappings":mappings,
                       "scope":"FDA identity/name candidates; no exact structure, binding, approval or health-effect claim"}
    # Check against the existing engine contract without modifying graph modules.
    from nutriomics_evidence.identity import validate_mapping
    for row in mappings:
        validate_mapping(row)
    save(out/"identity_mappings.json",mapping_payload)
    save(out/"targeted_terms.json",selected)
    save(out/"unmatched_subjects.json",unmatched)
    result = {"retrieved_utc":datetime.now(timezone.utc).isoformat(),"provider":"FDA/openFDA","index_url":INDEX,
              "index_sha256":sha(out/"download_index.json"),"export_date":entry["export_date"],
              "payload_source_last_updated":payload.get("meta",{}).get("last_updated"),"source_url":url,
              "archive_sha256":sha(archive_path),"archive_bytes":archive_path.stat().st_size,"json_member":member,
              "json_member_sha256":hashlib.sha256(raw_json).hexdigest(),"zip_crc_verified":True,"raw_records":len(raw),
              "unique_uniis":len(grouped),"source_name_field_variants":variants,"target_subjects":len(subjects),
              "mapping_rows":len(mappings),"unmatched_subjects":len(unmatched),"selected_terms":len(selected),
              "candidate_name_mappings":sum(row["relation"]=="candidate_name" for row in mappings),
              "regulatory_identity_mappings":sum(row["relation"]=="regulatory_identity" for row in mappings),
              "exact_structure_mappings":0,"new_binding_labels":0,"regulatory_approval_or_efficacy_claims":0,
              "mapping_sha256":sha(out/"identity_mappings.json"),"normalized_records_sha256":sha(out/"unii_records.jsonl"),
              "license":payload.get("meta",{}).get("license","https://open.fda.gov/license/"),
              "terms":payload.get("meta",{}).get("terms","https://open.fda.gov/terms/"),
              "rights":"Preserve original third-party conditions; public regulatory identity does not establish structure equality or blanket commercial/redistribution permission"}
    save(out/"source_manifest.json",result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--expected-version",default="2026-09-30")
    parser.add_argument("--expected-records",type=int,default=176555)
    parser.add_argument("--subjects-json",type=Path,help="Optional source node IDs/names and explicit UNII codes")
    parser.add_argument("--database",type=Path,help="Read-only chemical-node names from the existing evidence graph")
    parser.add_argument("--terms",nargs="+",default=DEFAULT_TERMS)
    args = parser.parse_args()
    print(json.dumps(fetch(args),indent=2,ensure_ascii=False))


if __name__=="__main__":
    main()
