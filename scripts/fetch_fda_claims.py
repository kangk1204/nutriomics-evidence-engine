"""Freeze four source-checked FDA labeling annotations and their original files.

No graph writes, outcome prediction, therapeutic advice, or binding labels.
The full original sources govern use; concise conditions are not exhaustive.
"""
import argparse
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime,timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


DEFAULT_CONFIG = Path(__file__).resolve().parents[1]/"config"/"fda_claims.json"


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self,text):
        self.parts.append(text)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save(path,payload):
    Path(path).write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")


def validate_source(content,source):
    if source["kind"]=="pdf":
        if not content.startswith(b"%PDF-"):
            raise ValueError("Official source endpoint did not return a PDF")
        return {"format":"pdf","pdf_magic_verified":True,"semantic_pdf_parsing":False}
    if source["kind"]=="xml":
        root = ET.fromstring(content)
        if root.tag!="DIV8" or root.attrib.get("N")!="101.74":
            raise ValueError("Official eCFR XML is not the requested section")
        text = " ".join(" ".join(root.itertext()).split())
        if any(term.casefold() not in text.casefold() for term in source.get("required_text",[])):
            raise ValueError("eCFR XML is missing the required original claim conditions")
        return {"format":"xml","required_text_verified":True,"ecfr_snapshot_date":source["snapshot_date"],
                "section_verified":"101.74"}
    if source["kind"]!="html":
        raise ValueError("Unsupported configured regulatory source format")
    decoded = content.decode("utf-8",errors="replace")
    if not re.search(r"<(?:html|!doctype html)\b",decoded,re.I):
        raise ValueError("Official source endpoint did not return HTML")
    parser = TextParser()
    parser.feed(decoded)
    text = " ".join(" ".join(parser.parts).split())
    if any(term.casefold() not in text.casefold() for term in source.get("required_text",[])):
        raise ValueError("Official HTML source is missing its expected claim/qualifying text")
    asof = re.search(r"up to date as of\s+(\d{1,2}/\d{1,2}/\d{4})",text,re.I)
    return {"format":"html","required_text_verified":True,"observed_ecfr_as_of":asof.group(1) if asof else None}


def fetch(out,config_path=DEFAULT_CONFIG):
    out = Path(out)
    out.mkdir(parents=True,exist_ok=True)
    config_path = Path(config_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    annotations = config.get("annotations",[])
    if len(annotations)!=4 or len({row["id"] for row in annotations})!=4:
        raise ValueError("Expected four distinct approved regulatory annotations")
    client = requests.Session()
    client.headers["User-Agent"] = "NutriOmics-research/2026 source-provenance-fetch"
    client.mount("https://",HTTPAdapter(max_retries=Retry(total=4,backoff_factor=1,status_forcelist=[429,500,502,503,504])))
    records,failures = [],[]
    for annotation in annotations:
        sources = []
        for position,source in enumerate(annotation["sources"]):
            attempts = []
            for alternative,candidate in enumerate([source]+source.get("fallback_sources",[])):
                url = candidate["url"]
                if urlparse(url).hostname not in {"www.fda.gov","www.ecfr.gov"}:
                    raise ValueError("Regulatory source must use an approved official host")
                name = re.sub(r"[^A-Za-z0-9_.-]","_",annotation["id"])+f"_{position}_{alternative}."+candidate["kind"]
                path = out/name
                response = None
                try:
                    response = client.get(url,timeout=(20,120))
                    response.raise_for_status()
                    checked = validate_source(response.content,candidate)
                    path.write_bytes(response.content)
                    sources.append({"url":url,"requested_primary_url":source["url"],"final_url":response.url,"file":name,"bytes":len(response.content),
                                    "sha256":digest(response.content),"http_content_type":response.headers.get("Content-Type"),
                                    "http_last_modified":response.headers.get("Last-Modified"),"official_fallback_used":alternative>0,
                                    "failed_primary_attempts":attempts,**checked})
                    break
                except (requests.RequestException,ValueError,ET.ParseError) as error:
                    failed = {"annotation_id":annotation["id"],"source_url":url,"error":str(error)}
                    if response is not None:
                        rejected = path.with_name(path.name+".rejected")
                        rejected.write_bytes(response.content)
                        failed.update({"rejected_response_file":rejected.name,"rejected_response_sha256":digest(response.content),"http_status":response.status_code})
                    attempts.append(failed)
                    failures.append(failed)
        row = {**annotation,"frozen_sources":sources,"all_configured_sources_verified":len(sources)==len(annotation["sources"]),
               "tier":"regulatory_annotation","binding_affinity":None,"observed_individual_health_effect":None,
               "human_reviewed":False,"source_checked":len(sources)==len(annotation["sources"]),
               "review_basis":"Official source text checked by research agent; no independent expert sign-off"}
        records.append(row)
    save(out/"regulatory_annotations.json",{"schema_version":"1.0","annotations":records,"scope":config["scope"]})
    manifest = {"retrieved_utc":datetime.now(timezone.utc).isoformat(),"config_sha256":digest(config_path.read_bytes()),
                "configured_annotations":4,"complete_annotations":sum(row["source_checked"] for row in records),
                "downloaded_source_files":sum(len(row["frozen_sources"]) for row in records),"failures":failures,
                "annotations_sha256":digest((out/"regulatory_annotations.json").read_bytes()),
                "rights":"Official regulatory source; retain attribution and any embedded third-party terms",
                "conditions_policy":"Full original source controls; summarized use conditions are not exhaustive",
                "qualified_claim_policy":"Enforcement discretion is not FDA approval of a qualified claim and is not a measured health effect"}
    save(out/"source_manifest.json",manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--config",type=Path,default=DEFAULT_CONFIG)
    args = parser.parse_args()
    print(json.dumps(fetch(args.out,args.config),indent=2,ensure_ascii=False))


if __name__=="__main__":
    main()
