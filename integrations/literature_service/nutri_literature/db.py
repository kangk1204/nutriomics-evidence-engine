"""Local SQLite, short transactions, immutable source/extraction history."""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import sqlite3
import uuid
from .settings import Settings


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return uuid.uuid4().hex


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def digest(value):
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


SCHEMA = """
CREATE TABLE IF NOT EXISTS topics(topic_id TEXT PRIMARY KEY, name TEXT NOT NULL, query TEXT NOT NULL,
 query_version TEXT NOT NULL, start_date TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS topic_state(topic_id TEXT, query_version TEXT, watermark TEXT,
 updated_at TEXT, PRIMARY KEY(topic_id,query_version));
CREATE TABLE IF NOT EXISTS papers(paper_id INTEGER PRIMARY KEY, pmid TEXT UNIQUE NOT NULL, doi TEXT,
 pmcid TEXT, title TEXT NOT NULL, pub_date TEXT, abstract TEXT NOT NULL DEFAULT '',
 publication_types TEXT NOT NULL DEFAULT '[]', mesh TEXT NOT NULL DEFAULT '[]',
 authors TEXT NOT NULL DEFAULT '[]', organism TEXT NOT NULL DEFAULT 'unknown',
 oa_status TEXT NOT NULL DEFAULT 'pending', license TEXT, retracted INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, current_source_id TEXT);
CREATE INDEX IF NOT EXISTS papers_doi ON papers(doi);
CREATE INDEX IF NOT EXISTS papers_pmcid ON papers(pmcid);
CREATE TABLE IF NOT EXISTS paper_topics(paper_id INTEGER REFERENCES papers(paper_id),
 topic_id TEXT REFERENCES topics(topic_id), query_version TEXT NOT NULL,
 PRIMARY KEY(paper_id,topic_id,query_version));
CREATE TABLE IF NOT EXISTS sources(source_id TEXT PRIMARY KEY, paper_id INTEGER REFERENCES papers(paper_id),
 kind TEXT NOT NULL, sha256 TEXT NOT NULL, text_hash TEXT NOT NULL, raw_path TEXT NOT NULL,
 text_content TEXT NOT NULL, sections TEXT NOT NULL DEFAULT '[]', url TEXT NOT NULL, license TEXT,
 retrieved_at TEXT NOT NULL, UNIQUE(paper_id,kind,sha256));
CREATE TABLE IF NOT EXISTS extractions(extraction_id TEXT PRIMARY KEY, paper_id INTEGER REFERENCES papers(paper_id),
 source_id TEXT REFERENCES sources(source_id), source_hash TEXT NOT NULL,
 engine_version TEXT NOT NULL, dictionary_version TEXT NOT NULL,
 result_json TEXT NOT NULL, created_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS mentions(mention_id TEXT PRIMARY KEY, extraction_id TEXT REFERENCES extractions(extraction_id),
 paper_id INTEGER REFERENCES papers(paper_id), kind TEXT NOT NULL, text TEXT NOT NULL, normalized_id TEXT,
 start INTEGER NOT NULL, end INTEGER NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS assertions(assertion_id TEXT PRIMARY KEY, extraction_id TEXT REFERENCES extractions(extraction_id),
 paper_id INTEGER REFERENCES papers(paper_id), fingerprint TEXT NOT NULL, subject TEXT NOT NULL,
 predicate TEXT NOT NULL, object TEXT NOT NULL, quote TEXT NOT NULL, start INTEGER NOT NULL, end INTEGER NOT NULL,
 rule_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'candidate', payload TEXT NOT NULL,
 UNIQUE(extraction_id,fingerprint));
CREATE TABLE IF NOT EXISTS accounts(username TEXT PRIMARY KEY, password_hash TEXT NOT NULL, enabled INTEGER DEFAULT 1,
 created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, username TEXT REFERENCES accounts(username),
 expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reviews(review_id TEXT PRIMARY KEY, assertion_id TEXT REFERENCES assertions(assertion_id),
 reviewer TEXT REFERENCES accounts(username), decision TEXT NOT NULL, comment TEXT NOT NULL DEFAULT '',
 corrected_payload TEXT, fingerprint TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs(run_id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL,
 started_at TEXT NOT NULL, finished_at TEXT, detail TEXT NOT NULL DEFAULT '{}', error TEXT);
CREATE TABLE IF NOT EXISTS queue(queue_id INTEGER PRIMARY KEY, paper_id INTEGER REFERENCES papers(paper_id),
 stage TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER DEFAULT 0,
 due_at TEXT NOT NULL, error TEXT, UNIQUE(paper_id,stage));
CREATE TABLE IF NOT EXISTS jobs(job_key TEXT PRIMARY KEY, kind TEXT NOT NULL, due_at TEXT NOT NULL,
 status TEXT NOT NULL, started_at TEXT, finished_at TEXT, attempts INTEGER NOT NULL DEFAULT 0, error TEXT);
CREATE TABLE IF NOT EXISTS reports(report_id TEXT PRIMARY KEY, generated_at TEXT NOT NULL,
 period_start TEXT NOT NULL, period_end TEXT NOT NULL, snapshot_hash TEXT NOT NULL,
 snapshot_json TEXT NOT NULL, paths TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit(event_id TEXT PRIMARY KEY, kind TEXT NOT NULL, paper_id INTEGER,
 detail TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS health_checks(observed_at TEXT PRIMARY KEY, api_up INTEGER NOT NULL,
 ui_up INTEGER NOT NULL, detail TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS extractions_paper_active ON extractions(paper_id,active,created_at);
CREATE INDEX IF NOT EXISTS mentions_extraction_kind ON mentions(extraction_id,kind,start);
CREATE INDEX IF NOT EXISTS assertions_extraction ON assertions(extraction_id);
CREATE INDEX IF NOT EXISTS reviews_assertion ON reviews(assertion_id,created_at);
CREATE INDEX IF NOT EXISTS runs_started ON runs(started_at);
CREATE INDEX IF NOT EXISTS queue_pending ON queue(status,stage,due_at);
CREATE INDEX IF NOT EXISTS sources_paper_kind ON sources(paper_id,kind,retrieved_at);
CREATE INDEX IF NOT EXISTS audit_kind ON audit(kind);
CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts USING fts5(title,abstract,content='papers',content_rowid='paper_id');
CREATE TRIGGER IF NOT EXISTS papers_ai AFTER INSERT ON papers BEGIN
 INSERT INTO papers_fts(rowid,title,abstract) VALUES(new.paper_id,new.title,new.abstract); END;
CREATE TRIGGER IF NOT EXISTS papers_au AFTER UPDATE ON papers BEGIN
 INSERT INTO papers_fts(papers_fts,rowid,title,abstract) VALUES('delete',old.paper_id,old.title,old.abstract);
 INSERT INTO papers_fts(rowid,title,abstract) VALUES(new.paper_id,new.title,new.abstract); END;
"""


@contextmanager
def connect(settings: Settings, durable=False):
    settings.ensure()
    con = sqlite3.connect(settings.database, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=30000")
    con.execute("PRAGMA synchronous=" + ("FULL" if durable else "NORMAL"))
    try:
        yield con
        con.commit()
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()


def initialize(settings):
    with connect(settings) as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript(SCHEMA)
    sync_topics(settings)


def sync_topics(settings):
    config = json.loads(settings.config.read_text(encoding="utf-8"))
    with connect(settings) as con:
        con.execute("UPDATE topics SET enabled=0")
        for topic in config["topics"]:
            version = digest(dumps({k: topic[k] for k in ["query", "start_date"]}))
            con.execute(
                "INSERT INTO topics VALUES(?,?,?,?,?,?) ON CONFLICT(topic_id) DO UPDATE SET "
                "name=excluded.name,query=excluded.query,query_version=excluded.query_version,"
                "start_date=excluded.start_date,enabled=excluded.enabled",
                (
                    topic["id"],
                    topic["name"],
                    topic["query"],
                    version,
                    topic["start_date"],
                    int(topic.get("enabled", True)),
                ),
            )


def start_run(settings, kind):
    run_id = uid()
    with connect(settings) as con:
        con.execute(
            "INSERT INTO runs(run_id,kind,status,started_at) VALUES(?,?,?,?)",
            (run_id, kind, "running", now()),
        )
    return run_id


def finish_run(settings, run_id, status, detail=None, error=None):
    with connect(settings) as con:
        con.execute(
            "UPDATE runs SET status=?,finished_at=?,detail=?,error=? WHERE run_id=?",
            (status, now(), dumps(detail or {}), error, run_id),
        )


def enqueue(con, paper_id, stage):
    con.execute(
        "INSERT INTO queue(paper_id,stage,status,due_at) VALUES(?,?,'pending',?) "
        "ON CONFLICT(paper_id,stage) DO UPDATE SET status='pending',attempts=0,due_at=excluded.due_at,error=NULL",
        (paper_id, stage, now()),
    )


def save_source(con, paper_id, kind, raw_path, raw_bytes, text, sections, url, license=None):
    sha = digest(raw_bytes)
    found = con.execute(
        "SELECT source_id FROM sources WHERE paper_id=? AND kind=? AND sha256=?", (paper_id, kind, sha)
    ).fetchone()
    if found:
        return found["source_id"]
    source_id = uid()
    con.execute(
        "INSERT INTO sources VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            source_id,
            paper_id,
            kind,
            sha,
            digest(text),
            str(raw_path),
            text,
            dumps(sections),
            url,
            license,
            now(),
        ),
    )
    return source_id
