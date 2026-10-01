from datetime import datetime, timedelta, timezone
import json
import os
import time
import psutil
from .db import connect, digest, dumps, enqueue, finish_run, now, start_run, uid
from .collection import ApiClient, fetch_oa


def store_extraction(settings, paper_id, source, result):
    text = source["text_content"]
    if digest(text) != source["text_hash"]:
        raise ValueError("Source text integrity failure")
    for item in result["mentions"] + result["assertions"]:
        value = item.get("text", item.get("quote"))
        if not 0 <= item["start"] < item["end"] <= len(text) or text[item["start"] : item["end"]] != value:
            raise ValueError("Candidate offsets do not match source")
    with connect(settings) as con:
        current = con.execute(
            "SELECT current_source_id,retracted FROM papers WHERE paper_id=?", (paper_id,)
        ).fetchone()
        if current[0] != source["source_id"]:
            raise ValueError("Source changed during extraction")
        existing = con.execute(
            "SELECT extraction_id,result_json FROM extractions WHERE paper_id=? AND source_hash=? "
            "AND engine_version=? AND dictionary_version=? AND active=1",
            (paper_id, source["text_hash"], result["engine_version"], result["dictionary_version"]),
        ).fetchone()
        if existing and json.loads(existing["result_json"]).get("rules_version") == result.get(
            "rules_version"
        ):
            return existing[0]
        prior = {
            r["fingerprint"]: r["status"]
            for r in con.execute(
                "SELECT a.fingerprint,a.status FROM assertions a JOIN extractions e USING(extraction_id) WHERE a.paper_id=? AND e.active=1",
                (paper_id,),
            )
        }
        con.execute("UPDATE extractions SET active=0 WHERE paper_id=?", (paper_id,))
        con.execute(
            "UPDATE assertions SET status='needs_review' WHERE paper_id=? AND status IN ('approved','corrected')",
            (paper_id,),
        )
        extraction_id = uid()
        con.execute(
            "INSERT INTO extractions VALUES(?,?,?,?,?,?,?,?,?)",
            (
                extraction_id,
                paper_id,
                source["source_id"],
                source["text_hash"],
                result["engine_version"],
                result["dictionary_version"],
                dumps(result),
                now(),
                1,
            ),
        )
        for mention in result["mentions"]:
            con.execute(
                "INSERT INTO mentions VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    uid(),
                    extraction_id,
                    paper_id,
                    mention["kind"],
                    mention["text"],
                    mention.get("normalized_id"),
                    mention["start"],
                    mention["end"],
                    mention["status"],
                    dumps(mention.get("payload", {})),
                ),
            )
        for assertion in result["assertions"]:
            fingerprint = digest(
                dumps(
                    [
                        source["text_hash"],
                        result["engine_version"],
                        result.get("rules_version"),
                        result["dictionary_version"],
                        assertion["subject"],
                        assertion["predicate"],
                        assertion["object"],
                        assertion["quote"],
                        assertion["start"],
                        assertion["end"],
                    ]
                )
            )
            status = "retracted" if current[1] else prior.get(fingerprint, "candidate")
            con.execute(
                "INSERT OR IGNORE INTO assertions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    uid(),
                    extraction_id,
                    paper_id,
                    fingerprint,
                    assertion["subject"],
                    assertion["predicate"],
                    assertion["object"],
                    assertion["quote"],
                    assertion["start"],
                    assertion["end"],
                    assertion["rule_id"],
                    status,
                    dumps(assertion.get("payload", {})),
                ),
            )
        organism = result.get("context", {}).get("organism", "unknown")
        if not isinstance(organism, str):
            organism = dumps(organism)
        con.execute("UPDATE papers SET organism=? WHERE paper_id=?", (organism, paper_id))
        con.execute(
            "INSERT INTO audit VALUES(?,?,?,?,?)",
            (uid(), "extracted", paper_id, dumps({"extraction_id": extraction_id}), now()),
        )
        return extraction_id


def process(settings, stage=None, limit=100, client=None):
    from .dictionaries import load_dictionaries
    from .extraction import extract

    client = client or ApiClient(settings)
    dictionaries = None if stage == "oa" else load_dictionaries(settings)
    run_id = start_run(settings, "process_" + (stage or "all"))
    counts = {"processed": 0, "failed": 0, "stages": {}}
    try:
        for _ in range(limit):
            if (
                psutil.virtual_memory().available < 2 * 1024**3
                or psutil.Process().memory_info().rss > 8 * 1024**3
            ):
                counts["throttled"] = True
                break
            with connect(settings) as con:
                con.execute("BEGIN IMMEDIATE")
                stale = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
                con.execute("UPDATE queue SET status='pending' WHERE status='running' AND due_at<?", (stale,))
                params = [now()]
                condition = "status='pending' AND due_at<=?"
                if stage:
                    condition += " AND stage=?"
                    params.append(stage)
                queue = con.execute(
                    "SELECT * FROM queue WHERE "
                    + condition
                    + " ORDER BY CASE stage WHEN 'extract' THEN 0 ELSE 1 END,queue_id LIMIT 1",
                    params,
                ).fetchone()
                if not queue:
                    break
                queue = dict(queue)
                con.execute(
                    "UPDATE queue SET status='running',due_at=?,attempts=attempts+1 WHERE queue_id=?",
                    (now(), queue["queue_id"]),
                )
                paper = dict(
                    con.execute("SELECT * FROM papers WHERE paper_id=?", (queue["paper_id"],)).fetchone()
                )
                source = con.execute(
                    "SELECT * FROM sources WHERE source_id=?", (paper["current_source_id"],)
                ).fetchone()
            try:
                if queue["stage"] == "oa":
                    status = fetch_oa(settings, paper, client)
                    with connect(settings) as con:
                        con.execute(
                            "UPDATE papers SET oa_status=? WHERE paper_id=?", (status, paper["paper_id"])
                        )
                else:
                    if source is None:
                        raise ValueError("No source available")
                    metadata = {
                        **paper,
                        "publication_types": json.loads(paper["publication_types"]),
                        "mesh": json.loads(paper["mesh"]),
                    }
                    result = extract(
                        source["text_content"], json.loads(source["sections"]), metadata, dictionaries
                    )
                    store_extraction(settings, paper["paper_id"], dict(source), result)
                with connect(settings) as con:
                    con.execute(
                        "UPDATE queue SET status='completed',error=NULL WHERE queue_id=?",
                        (queue["queue_id"],),
                    )
                counts["processed"] += 1
                counts["stages"][queue["stage"]] = counts["stages"].get(queue["stage"], 0) + 1
            except Exception as error:
                counts["failed"] += 1
                attempts = queue["attempts"] + 1
                due = (datetime.now(timezone.utc) + timedelta(minutes=min(1440, 5 * 2**attempts))).isoformat()
                with connect(settings) as con:
                    con.execute(
                        "UPDATE queue SET status=?,due_at=?,error=? WHERE queue_id=?",
                        ("failed" if attempts >= 5 else "pending", due, str(error), queue["queue_id"]),
                    )
                    if queue["stage"] == "oa":
                        con.execute(
                            "UPDATE papers SET oa_status='transient_failure' WHERE paper_id=?",
                            (paper["paper_id"],),
                        )
        finish_run(settings, run_id, "partial" if counts["failed"] else "completed", counts)
    except BaseException as error:
        finish_run(settings, run_id, "failed", counts, str(error))
        raise
    return {"run_id": run_id, **counts}


def requeue_oa(settings):
    with connect(settings) as con:
        rows = con.execute("SELECT paper_id FROM papers WHERE retracted=0").fetchall()
        for row in rows:
            enqueue(con, row[0], "oa")
    return {"queued": len(rows)}


def reprocess(settings):
    with connect(settings) as con:
        rows = con.execute("SELECT paper_id FROM papers").fetchall()
        for row in rows:
            enqueue(con, row[0], "extract")
    return {"queued": len(rows)}


def worker(settings, stage):
    from .extraction import RULES_VERSION

    with connect(settings) as con:
        # CLI holds this stage's exclusive lock, so previous owners have terminated.
        con.execute(
            "UPDATE queue SET status='pending',due_at=?,error='recovered after exclusive worker restart' "
            "WHERE stage=? AND status='running'",
            (now(), stage),
        )
        con.execute(
            "UPDATE runs SET status='interrupted',finished_at=?,error='worker restarted' WHERE kind=? AND status='running'",
            (now(), "process_" + stage),
        )
        if stage == "extract":
            for row in con.execute("SELECT paper_id,result_json FROM extractions WHERE active=1").fetchall():
                if json.loads(row["result_json"]).get("rules_version") != RULES_VERSION:
                    enqueue(con, row["paper_id"], "extract")
    if hasattr(os, "nice"):
        os.nice(10)
    while True:
        result = process(settings, stage, 100)
        if result["processed"] or result["failed"]:
            print(dumps(result), flush=True)
        time.sleep(15 if result["processed"] else 60)
