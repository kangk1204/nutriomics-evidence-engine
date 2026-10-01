"""Official DrugProt development corpus and six source-recorded PubMed searches.

The raw corpus/abstracts stay outside Git. Downloaded public text is not assigned
a blanket redistribution license. No gold relation is used for prompt creation.
"""
import argparse
import hashlib
import json
import time
import zipfile
from collections import Counter
from datetime import datetime,timezone,date
from pathlib import Path
import xml.etree.ElementTree as ET
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DRUGPROT_RECORD = "5119892"
DRUGPROT_FILE = "drugprot-training-development-test-background.zip"
DRUGPROT_MD5 = "c706ebf04580c3126154d96a43e64f2e"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
DEFAULT_QUERIES = Path(__file__).resolve().parents[1]/"config"/"literature_topics.json"
APPROVED_TOPIC_IDS = {"HTN","DASH","omega3","vitD","caffeine","cocoa_flavanol"}


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(path,algorithm="sha256"):
    hasher = hashlib.new(algorithm)
    with open(path,"rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):
            hasher.update(block)
    return hasher.hexdigest()


def save_json(path,payload):
    path = Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")


def session():
    client = requests.Session()
    client.headers["User-Agent"] = "NutriOmics-research/2026 source-provenance-fetch"
    client.mount("https://",HTTPAdapter(max_retries=Retry(total=4,backoff_factor=1,status_forcelist=[429,500,502,503,504])))
    return client


def fetch_drugprot(out):
    out = Path(out)
    out.mkdir(parents=True,exist_ok=True)
    client = session()
    metadata_url = f"https://zenodo.org/api/records/{DRUGPROT_RECORD}"
    metadata,metadata_error = None,None
    try:
        response = client.get(metadata_url,timeout=(20,90))
        response.raise_for_status()
        metadata = response.json()
        save_json(out/"zenodo_record.json",metadata)
    except (requests.RequestException,ValueError) as error:
        metadata_error = str(error)
    url = f"https://zenodo.org/records/{DRUGPROT_RECORD}/files/{DRUGPROT_FILE}?download=1"
    archive_path = out/DRUGPROT_FILE
    if not archive_path.exists():
        temporary = archive_path.with_suffix(".partial")
        with client.get(url,stream=True,timeout=(30,180)) as response:
            response.raise_for_status()
            with open(temporary,"wb") as stream:
                for chunk in response.iter_content(1024*1024):
                    stream.write(chunk)
        temporary.replace(archive_path)
    actual_md5 = digest(archive_path,"md5")
    if actual_md5!=DRUGPROT_MD5:
        raise ValueError("Official pinned DrugProt archive MD5 mismatch")
    files = {}
    wanted = {f"drugprot_development_{kind}.tsv" for kind in ("abstracts","entities","relations")}
    native_aliases = {"drugprot_development_abstracs.tsv":"drugprot_development_abstracts.tsv"}
    with zipfile.ZipFile(archive_path) as archive:
        if archive.testzip():
            raise ValueError("DrugProt ZIP CRC failure")
        for member in archive.infolist():
            raw_basename = Path(member.filename).name
            basename = native_aliases.get(raw_basename,raw_basename)
            if basename in wanted:
                if basename in files:
                    raise ValueError("Ambiguous duplicated development archive member")
                destination = out/"development"/basename
                destination.parent.mkdir(parents=True,exist_ok=True)
                destination.write_bytes(archive.read(member))
                files[basename] = {"sha256":digest(destination),"bytes":destination.stat().st_size,"archive_member":member.filename,
                                   "native_filename":raw_basename,"canonical_filename":basename,"provider_filename_typo_normalized":raw_basename!=basename}
    if set(files)!=wanted:
        raise ValueError(f"Missing official development files: {wanted-set(files)}")
    from nutriomics_evidence.extraction import load_drugprot
    documents = load_drugprot(out/"development"/"drugprot_development_abstracts.tsv",out/"development"/"drugprot_development_entities.tsv")
    if len(documents)!=750:
        raise ValueError(f"Expected official 750-document development cohort, found {len(documents)}")
    result = {"retrieved_utc":now(),"record_id":DRUGPROT_RECORD,"version":"1.2","doi":"10.5281/zenodo.5119892",
              "url":url,"archive_md5":actual_md5,"archive_sha256":digest(archive_path),"archive_bytes":archive_path.stat().st_size,
              "zip_crc_verified":True,"files":files,"documents":len(documents),"metadata_error":metadata_error,
              "license_metadata":metadata.get("metadata",{}).get("license") if metadata else None,
              "license_note":"Retain original corpus/PubMed text rights; do not infer a license from the overview paper",
              "gold_mentions_used":True,"benchmark_scope":"Development 750 relation extraction; no NER or pretraining-contamination independence claim",
              "paper":"https://pmc.ncbi.nlm.nih.gov/articles/PMC10683943/"}
    save_json(out/"source_manifest.json",result)
    return result


def element_text(element):
    return "".join(element.itertext()) if element is not None else ""


def parse_pubmed(xml):
    records = []
    root = ET.fromstring(xml)
    if root.tag!="PubmedArticleSet":
        raise ValueError("Expected official PubmedArticleSet XML")
    for article in root:
        if article.tag=="DeleteCitation":
            continue  # Requested but withdrawn IDs stay in the fetch completeness ledger.
        if article.tag=="PubmedArticle":
            citation = article.find("MedlineCitation")
            data = citation.find("Article") if citation is not None else None
            id_paths = ["PubmedData/ArticleIdList/ArticleId"]
            title_path,publication_path = "ArticleTitle","Journal/JournalIssue/PubDate"
        elif article.tag=="PubmedBookArticle":
            citation = data = article.find("BookDocument")
            id_paths = ["BookDocument/ArticleIdList/ArticleId","PubmedBookData/ArticleIdList/ArticleId"]
            title_path,publication_path = "ArticleTitle","Book/PubDate"
        else:
            raise ValueError(f"Unsupported PubMed source record element: {article.tag}")
        if citation is None or data is None:
            raise ValueError("PubMed source citation/body is missing")
        pmid = citation.findtext("PMID")
        if not pmid or not pmid.isdecimal():
            raise ValueError("PubMed source PMID is missing or invalid")
        ids = {element.attrib.get("IdType"):element_text(element) for path in id_paths for element in article.findall(path)}
        title = element_text(data.find(title_path))
        if article.tag=="PubmedBookArticle" and not title:
            title = element_text(data.find("Book/BookTitle"))
        records.append({"pmid":pmid,"doi":ids.get("doi"),"pmcid":ids.get("pmc"),
                        "title":title,"record_type":article.tag,"book_accession":ids.get("bookaccession"),
                        "abstract":"\n".join((element.attrib.get("Label","")+": " if element.attrib.get("Label") else "")+element_text(element) for element in data.findall("Abstract/AbstractText")),
                        "journal":data.findtext("Journal/Title"),"book_title":data.findtext("Book/BookTitle"),"publication_date":element_text(data.find(publication_path)),
                        "publication_types":[element_text(element) for path in ("PublicationTypeList/PublicationType","PublicationType") for element in data.findall(path)],
                        "mesh":[element_text(element) for element in citation.findall("MeshHeadingList/MeshHeading/DescriptorName")],
                        "source_url":f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/","evidence_status":"retrieved literature; relations not extracted or validated"})
    if len({record["pmid"] for record in records})!=len(records):
        raise ValueError("Duplicate PMID in official PubMed XML response")
    return records


def completeness_ledger(requested,records):
    if len(set(requested))!=len(requested) or any(not isinstance(pmid,str) or not pmid.isdecimal() for pmid in requested):
        raise ValueError("Invalid/duplicate requested PubMed PMIDs")
    observed = {record["pmid"] for record in records}
    unexpected = sorted(observed-set(requested))
    if unexpected:
        raise ValueError(f"Unrequested PMID in official PubMed response: {unexpected}")
    missing = sorted(set(requested)-observed)
    return {"requested_records":len(requested),"returned_records":len(records),"missing_pmids":missing,
            "complete":not missing,"missing_policy":"No invented abstract/record; missing requested IDs remain auditable and excluded from retrieval"}


def fetch_pubmed(out,retmax=100,max_date=None,query_file=None,email=None):
    out = Path(out)
    out.mkdir(parents=True,exist_ok=True)
    if not 1<=retmax<=200:
        raise ValueError("retmax must be between 1 and the approved 200 records per topic")
    topics = json.loads(Path(query_file or DEFAULT_QUERIES).read_text(encoding="utf-8"))
    if not isinstance(topics,dict) or set(topics)!=APPROVED_TOPIC_IDS or any(not isinstance(q,str) or not q.strip() for q in topics.values()):
        raise ValueError("Expected the approved six nonempty PubMed topic queries")
    client = session()
    max_date = max_date or date.today().isoformat()
    date.fromisoformat(max_date)
    searches = {}
    all_records = {}
    common = {"db":"pubmed","tool":"nutriomics_evidence_research"}
    if email:
        common["email"] = email
    for topic,query in topics.items():
        query = f"({query}) AND (\"1900/01/01\"[Date - Publication] : \"{max_date.replace('-','/')}\"[Date - Publication])"
        params = {**common,"term":query,"retmode":"json","retmax":retmax,"sort":"relevance"}
        response = client.get(EUTILS+"esearch.fcgi",params=params,timeout=(20,90))
        response.raise_for_status()
        search = response.json()
        if "esearchresult" not in search:
            raise ValueError(f"Invalid PubMed search response: {topic}")
        save_json(out/f"{topic}_esearch.json",search)
        pmids = search["esearchresult"]["idlist"]
        time.sleep(0.4)
        xml_file = out/f"{topic}_efetch.xml"
        records = []
        if pmids:
            response = client.post(EUTILS+"efetch.fcgi",data={**common,"id":",".join(pmids),"retmode":"xml"},timeout=(20,120))
            response.raise_for_status()
            xml_file.write_bytes(response.content)
            records = parse_pubmed(response.content)
            for record in records:
                if record["pmid"] not in all_records:
                    record["topics"] = []
                    all_records[record["pmid"]] = record
                all_records[record["pmid"]]["topics"].append(topic)
        ledger = completeness_ledger(pmids,records)
        save_json(out/f"{topic}_completeness.json",ledger)
        searches[topic] = {"query":query,"matched_count":int(search["esearchresult"]["count"]),"selected_pmids":pmids,
                           "record_types":dict(Counter(record["record_type"] for record in records)),
                           "completeness":ledger,"esearch_sha256":digest(out/f"{topic}_esearch.json"),"efetch_sha256":digest(xml_file) if xml_file.exists() and pmids else None}
        time.sleep(0.4)
        print(f"{topic}: matched {searches[topic]['matched_count']}, requested {len(pmids)}, retrieved {len(records)}, missing {len(ledger['missing_pmids'])}",flush=True)
    with open(out/"articles.jsonl","w",encoding="utf-8") as stream:
        for pmid in sorted(all_records):
            stream.write(json.dumps(all_records[pmid],ensure_ascii=False)+"\n")
    manifest = {"retrieved_utc":now(),"provider":"NCBI PubMed E-utilities","max_publication_date":max_date,"retmax_per_topic":retmax,
                "selection":"PubMed relevance ordering; frozen PMID list; not a systematic-review exhaustive census",
                "unique_documents":len(all_records),"searches":searches,"articles_sha256":digest(out/"articles.jsonl"),
                "missing_pmids":sorted({pmid for item in searches.values() for pmid in item["completeness"]["missing_pmids"]}),
                "query_config_sha256":digest(Path(query_file or DEFAULT_QUERIES)),
                "license_note":"Preserve publisher/original abstract rights; public retrieval does not establish blanket CC0 redistribution",
                "gold_or_verified_relations":False}
    save_json(out/"source_manifest.json",manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode",required=True)
    drugprot = sub.add_parser("drugprot")
    drugprot.add_argument("--out",type=Path,required=True)
    pubmed = sub.add_parser("pubmed")
    pubmed.add_argument("--out",type=Path,required=True)
    pubmed.add_argument("--retmax",type=int,default=100)
    pubmed.add_argument("--max-date",default="2026-10-01")
    pubmed.add_argument("--queries",type=Path)
    pubmed.add_argument("--email")
    args = parser.parse_args()
    result = fetch_drugprot(args.out) if args.mode=="drugprot" else fetch_pubmed(args.out,args.retmax,args.max_date,args.queries,args.email)
    print(json.dumps(result,indent=2,ensure_ascii=False))


if __name__=="__main__":
    main()
