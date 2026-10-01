"""Loopback API. Automatic candidates and reviewed evidence remain distinct."""

from contextlib import asynccontextmanager
import json
from pathlib import Path
import re
from typing import Literal
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from . import auth
from .db import connect, digest, dumps, initialize, now, uid
from .settings import Settings


def _json(value, default=None):
    try:
        return json.loads(value) if value else default
    except (TypeError, ValueError):
        return default


def _links(row):
    result = {"pubmed": f"https://pubmed.ncbi.nlm.nih.gov/{quote(str(row['pmid']), safe='')}/"}
    if row.get("doi"):
        result["doi"] = "https://doi.org/" + quote(row["doi"], safe="/")
    if row.get("pmcid"):
        result["europe_pmc"] = "https://europepmc.org/articles/" + quote(row["pmcid"], safe="")
    return result


def _paper(row):
    result = dict(row)
    for field in ("publication_types", "mesh", "authors"):
        if field in result:
            result[field] = _json(result[field], [])
    result["retracted"] = bool(result["retracted"])
    result["official_links"] = _links(result)
    return result


def _source(row, with_text=False):
    result = dict(row)
    result.pop("raw_path", None)
    result["raw_hash"] = result.pop("sha256")
    result["sections"] = _json(result["sections"], [])
    if not with_text:
        result.pop("text_content", None)
    return result


def _extraction(row):
    result = dict(row)
    result.update(_extraction_validity(row))
    for field in ("current_source_id", "text_hash", "text_content"):
        result.pop(field, None)
    result["result"] = _json(result.pop("result_json"), {})
    result["active"] = bool(result["active"])
    return result


def _assertion(row):
    result = dict(row)
    if "payload" in result:
        result["payload"] = _json(result["payload"], {})
    return result


def _corrected(con, assertion):
    """Use reviewed labels without ever changing the saved original quotation."""
    latest = con.execute(
        "SELECT * FROM reviews WHERE assertion_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1",
        (assertion["assertion_id"],),
    ).fetchone()
    if latest:
        assertion["review"] = dict(latest)
        assertion["review"]["corrected_payload"] = _json(latest["corrected_payload"])
        if latest["decision"] == "corrected" and assertion["status"] == "approved":
            correction = _json(latest["corrected_payload"], {})
            assertion["original_relation"] = {
                field: assertion[field] for field in ("subject", "predicate", "object")
            }
            for field in ("subject", "predicate", "object"):
                assertion[field] = correction[field]
    return assertion


def _extraction_validity(row):
    from .extraction import RULES_VERSION

    reasons = []
    text = row["text_content"]
    if _json(row["result_json"], {}).get("rules_version") != RULES_VERSION:
        reasons.append("rules_changed")
    if not row["active"]:
        reasons.append("inactive")
    if row["current_source_id"] != row["source_id"]:
        reasons.append("source_changed")
    if row["source_hash"] != row["text_hash"] or row["text_hash"] != digest(text):
        reasons.append("text_integrity")
    return {"current_valid": not reasons, "stale_reasons": reasons}


def _evidence_valid(row):
    text = row["text_content"]
    return (
        _extraction_validity(row)["current_valid"]
        and not row["retracted"]
        and 0 <= row["start"] < row["end"] <= len(text)
        and text[row["start"] : row["end"]] == row["quote"]
    )


_EXTRACTION_QUERY = """SELECT e.*,p.current_source_id,s.text_hash,s.text_content
 FROM extractions e JOIN papers p ON p.paper_id=e.paper_id
 JOIN sources s ON s.source_id=e.source_id"""


_ASSERTION_QUERY = """SELECT a.*,e.active,e.source_id,e.source_hash,e.engine_version,e.dictionary_version,e.result_json,
 s.text_hash,s.sha256 AS raw_hash,s.text_content,s.url AS source_url,s.kind AS source_kind,
 p.current_source_id,p.retracted,p.pmid,p.doi,p.pmcid,p.title
 FROM assertions a JOIN extractions e ON e.extraction_id=a.extraction_id
 JOIN sources s ON s.source_id=e.source_id JOIN papers p ON p.paper_id=a.paper_id"""


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assertion_id: str = Field(min_length=1, max_length=128)
    decision: Literal["approved", "rejected", "corrected"]
    comment: str = Field(default="", max_length=10000)
    corrected_payload: dict | None = None


def create_app(settings=None):
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(_app):
        initialize(settings)
        yield

    service = FastAPI(title="Nutriomics Literature", version="0.1.0", lifespan=lifespan)
    service.state.settings = settings
    bearer = HTTPBearer(auto_error=False)

    def reviewer(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        username = auth.verify_token(settings, credentials.credentials) if credentials else None
        if username is None:
            raise HTTPException(401, "검수자 로그인이 필요합니다.", headers={"WWW-Authenticate": "Bearer"})
        return username

    @service.get("/healthz")
    def healthz():
        with connect(settings) as con:
            con.execute("SELECT 1").fetchone()
        return {"status": "ok", "engine": "heuristic-v1"}

    @service.get("/api/v1/soak-status")
    def soak_status():
        from .monitor import status

        return status(settings)

    @service.get("/api/v1/topics")
    def topics():
        with connect(settings) as con:
            rows = con.execute(
                "SELECT t.*,ts.watermark,ts.updated_at AS last_success_at "
                "FROM topics t LEFT JOIN topic_state ts ON ts.topic_id=t.topic_id "
                "AND ts.query_version=t.query_version ORDER BY t.rowid"
            ).fetchall()
        return {"items": [dict(row) for row in rows]}

    @service.get("/api/v1/papers")
    def papers(
        q: str = Query(default="", max_length=512),
        topic: str | None = None,
        limit: int = Query(default=25, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ):
        conditions, args = [], []
        tokens = re.findall(r"\w+", q, flags=re.UNICODE)
        if q.strip() and not tokens:
            return {"items": [], "total": 0, "limit": limit, "offset": offset}
        if tokens:
            conditions.append("p.paper_id IN (SELECT rowid FROM papers_fts WHERE papers_fts MATCH ?)")
            args.append(" AND ".join('"' + token + '"' for token in tokens))
        if topic:
            conditions.append(
                "EXISTS(SELECT 1 FROM paper_topics pt JOIN topics t ON t.topic_id=pt.topic_id "
                "AND t.query_version=pt.query_version WHERE pt.paper_id=p.paper_id "
                "AND pt.topic_id=? AND t.enabled=1)"
            )
            args.append(topic)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        with connect(settings) as con:
            total = con.execute("SELECT COUNT(*) FROM papers p" + where, args).fetchone()[0]
            rows = con.execute(
                "SELECT p.* FROM papers p"
                + where
                + " ORDER BY p.pub_date DESC,p.paper_id DESC LIMIT ? OFFSET ?",
                [*args, limit, offset],
            ).fetchall()
            items = []
            for row in rows:
                item = _paper(row)
                results = con.execute(
                    _EXTRACTION_QUERY + " WHERE e.paper_id=? ORDER BY e.active DESC,e.created_at DESC",
                    (row["paper_id"],),
                ).fetchall()
                result = next((r for r in results if _extraction_validity(r)["current_valid"]), None)
                item["summary_current"] = bool(result)
                item["summary_status"] = "current" if result else ("stale" if results else "pending")
                item["summary"] = _json(result["result_json"], {}) if result else None
                item["topics"] = [
                    r[0]
                    for r in con.execute(
                        "SELECT DISTINCT pt.topic_id FROM paper_topics pt JOIN topics t "
                        "ON t.topic_id=pt.topic_id AND t.query_version=pt.query_version "
                        "WHERE pt.paper_id=? AND t.enabled=1",
                        (row["paper_id"],),
                    )
                ]
                items.append(item)
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    @service.get("/api/v1/papers/{paper_id}")
    def paper(paper_id: int):
        with connect(settings) as con:
            row = con.execute("SELECT * FROM papers WHERE paper_id=?", (paper_id,)).fetchone()
            if row is None:
                raise HTTPException(404, "문헌을 찾을 수 없습니다.")
            result = _paper(row)
            result["sources"] = [
                _source(s, with_text=True)
                for s in con.execute(
                    "SELECT * FROM sources WHERE paper_id=? ORDER BY retrieved_at DESC", (paper_id,)
                )
            ]
            result["extractions"] = [
                _extraction(e)
                for e in con.execute(
                    _EXTRACTION_QUERY + " WHERE e.paper_id=? ORDER BY e.created_at DESC", (paper_id,)
                )
            ]
            current_ids = [e["extraction_id"] for e in result["extractions"] if e["current_valid"]]
            result["summary_current"] = bool(current_ids)
            result["summary_status"] = (
                "current" if current_ids else ("stale" if result["extractions"] else "pending")
            )
            result["mentions"] = [
                _assertion(m)
                for m in con.execute(
                    "SELECT m.* FROM mentions m JOIN extractions e ON e.extraction_id=m.extraction_id "
                    "WHERE m.paper_id=? AND e.active=1 ORDER BY m.start",
                    (paper_id,),
                )
                if m["extraction_id"] in current_ids
            ]
            result["assertions"] = []
            for assertion in con.execute(
                _ASSERTION_QUERY + " WHERE a.paper_id=? ORDER BY a.start", (paper_id,)
            ):
                item = _corrected(con, _assertion(assertion))
                item["current_valid"] = _evidence_valid(assertion)
                reviewed = item.get("review", {})
                review_valid = (
                    reviewed.get("decision") in ("approved", "corrected")
                    and reviewed.get("fingerprint") == item["fingerprint"]
                    and item["payload"].get("explicit_relation")
                )
                item["display_status"] = (
                    item["status"]
                    if item["current_valid"] and (item["status"] != "approved" or review_valid)
                    else "needs_review"
                )
                item.pop("text_content", None)
                item.pop("result_json", None)
                result["assertions"].append(item)
            result["topics"] = [
                r[0]
                for r in con.execute(
                    "SELECT DISTINCT pt.topic_id FROM paper_topics pt JOIN topics t ON t.topic_id=pt.topic_id "
                    "AND t.query_version=pt.query_version WHERE pt.paper_id=? AND t.enabled=1",
                    (paper_id,),
                )
            ]
        return result

    @service.get("/api/v1/evidence-map")
    def evidence_map(
        topic: str | None = None,
        gene: str | None = Query(default=None, max_length=128),
        status: Literal["all", "candidate", "approved", "needs_review", "rejected"] = "all",
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ):
        conditions = [
            "e.active=1",
            "p.retracted=0",
            "p.current_source_id=e.source_id",
            "e.source_hash=s.text_hash",
            "EXISTS(SELECT 1 FROM paper_topics current_pt JOIN topics current_t "
            "ON current_t.topic_id=current_pt.topic_id AND current_t.query_version=current_pt.query_version "
            "WHERE current_pt.paper_id=a.paper_id AND current_t.enabled=1)",
        ]
        args = []
        if topic:
            conditions.append(
                "EXISTS(SELECT 1 FROM paper_topics pt JOIN topics t ON t.topic_id=pt.topic_id "
                "AND t.query_version=pt.query_version WHERE pt.paper_id=a.paper_id "
                "AND pt.topic_id=? AND t.enabled=1)"
            )
            args.append(topic)
        if status != "all":
            conditions.append("a.status=?")
            args.append(status)
        if gene:
            conditions.append(
                "(a.subject=? COLLATE NOCASE OR a.object=? COLLATE NOCASE OR "
                "EXISTS(SELECT 1 FROM mentions m WHERE m.extraction_id=e.extraction_id "
                "AND m.kind='gene' AND (m.text=? COLLATE NOCASE OR m.normalized_id=? COLLATE NOCASE) "
                "AND m.start>=a.start AND m.end<=a.end))"
            )
            args.extend([gene, gene, gene, gene])
        with connect(settings) as con:
            rows = con.execute(
                _ASSERTION_QUERY
                + " WHERE "
                + " AND ".join(conditions)
                + " ORDER BY a.paper_id DESC,a.start,a.assertion_id",
                args,
            ).fetchall()
            valid = []
            for row in rows:
                if not _evidence_valid(row):
                    continue
                if row["status"] == "approved":
                    latest = con.execute(
                        "SELECT decision,fingerprint FROM reviews WHERE assertion_id=? "
                        "ORDER BY created_at DESC,rowid DESC LIMIT 1",
                        (row["assertion_id"],),
                    ).fetchone()
                    if (
                        not latest
                        or latest["decision"] not in ("approved", "corrected")
                        or latest["fingerprint"] != row["fingerprint"]
                        or not _json(row["payload"], {}).get("explicit_relation")
                    ):
                        continue
                valid.append(row)
            selected = valid[offset : offset + limit]
            edges = []
            nodes = {}
            for row in selected:
                edge = _corrected(con, _assertion(row))
                edge.pop("text_content")
                edge.pop("result_json", None)
                edge["official_links"] = _links(edge)
                edge["id"] = edge["assertion_id"]
                edge["is_reviewed"] = edge["status"] == "approved"
                edge["relation_is_causal"] = False  # no graph-path causal inference
                for name in (edge["subject"], edge["object"]):
                    label, kind = name, "entity"
                    for endpoint in ("subject_mention", "object_mention"):
                        mention = edge["payload"].get(endpoint, {})
                        if name in (mention.get("normalized_id"), mention.get("text")):
                            label = mention.get("payload", {}).get("symbol") or mention.get("text") or name
                            kind = mention.get("kind", "entity")
                    nodes[name] = {"id": name, "label": label, "kind": kind}
                edges.append(edge)
        return {
            "nodes": list(nodes.values()),
            "edges": edges,
            "total": len(valid),
            "limit": limit,
            "offset": offset,
            "notice": "자동 후보와 검수 근거를 구분합니다. 연결 경로는 인과 효과를 뜻하지 않습니다.",
        }

    @service.post("/api/v1/auth/login")
    def login(body: Login):
        if not auth.authenticate(settings, body.username, body.password):
            raise HTTPException(401, "계정 또는 비밀번호가 올바르지 않습니다.")
        return auth.create_session(settings, body.username)

    @service.post("/api/v1/auth/logout")
    def logout(_username=Depends(reviewer), credentials=Depends(bearer)):
        auth.revoke_token(settings, credentials.credentials)
        return {"status": "logged_out"}

    @service.post("/api/v1/reviews")
    def review(body: Review, username=Depends(reviewer)):
        correction = None
        if body.decision == "corrected":
            supplied = body.corrected_payload or {}
            if set(supplied) != {"subject", "predicate", "object"} or not body.comment.strip():
                raise HTTPException(
                    422, "수정은 subject, predicate, object와 수정 사유를 모두 입력해야 합니다."
                )
            if any(
                not isinstance(supplied[f], str) or not supplied[f].strip() or len(supplied[f]) > 512
                for f in ("subject", "predicate", "object")
            ):
                raise HTTPException(422, "수정 관계의 각 항목은 1~512자 문자열이어야 합니다.")
            correction = {f: supplied[f].strip() for f in ("subject", "predicate", "object")}
        elif body.corrected_payload is not None:
            raise HTTPException(422, "수정 내용은 corrected 결정에서만 사용하세요.")
        with connect(settings, durable=True) as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute(_ASSERTION_QUERY + " WHERE a.assertion_id=?", (body.assertion_id,)).fetchone()
            if row is None:
                raise HTTPException(404, "근거 후보를 찾을 수 없습니다.")
            if not _evidence_valid(row):
                raise HTTPException(
                    409, "원문·추출 버전이 변경되었거나 철회된 문헌입니다. 최신 후보를 확인하세요."
                )
            payload = _json(row["payload"], {})
            if body.decision != "rejected" and not payload.get("explicit_relation"):
                raise HTTPException(409, "명시적 관계 규칙을 통과한 원문 근거만 승인할 수 있습니다.")
            if correction:
                anchors = {row["subject"], row["object"]}
                for mention in con.execute(
                    "SELECT * FROM mentions WHERE extraction_id=? AND start>=? AND end<=?",
                    (row["extraction_id"], row["start"], row["end"]),
                ):
                    if row["text_content"][mention["start"] : mention["end"]] != mention["text"]:
                        continue
                    anchors.add(mention["text"])
                    if mention["normalized_id"]:
                        anchors.add(mention["normalized_id"])
                    symbol = _json(mention["payload"], {}).get("symbol")
                    if symbol:
                        anchors.add(symbol)
                if (
                    correction["subject"] not in anchors
                    or correction["object"] not in anchors
                    or correction["subject"] == correction["object"]
                ):
                    raise HTTPException(422, "수정 주어·목적어는 해당 원문에 연결된 탐지 항목이어야 합니다.")
                if correction["predicate"] not in {"increases", "decreases", "affects", "associated_with"}:
                    raise HTTPException(
                        422, "관계는 increases, decreases, affects, associated_with 중 선택하세요."
                    )
            review_id = uid()
            con.execute(
                "INSERT INTO reviews VALUES(?,?,?,?,?,?,?,?)",
                (
                    review_id,
                    body.assertion_id,
                    username,
                    body.decision,
                    body.comment,
                    dumps(correction) if correction else None,
                    row["fingerprint"],
                    now(),
                ),
            )
            status = "rejected" if body.decision == "rejected" else "approved"
            con.execute("UPDATE assertions SET status=? WHERE assertion_id=?", (status, body.assertion_id))
            con.execute(
                "INSERT INTO audit VALUES(?,?,?,?,?)",
                (
                    uid(),
                    "review",
                    row["paper_id"],
                    dumps(
                        {
                            "review_id": review_id,
                            "reviewer": username,
                            "decision": body.decision,
                            "source_hash": row["source_hash"],
                            "fingerprint": row["fingerprint"],
                        }
                    ),
                    now(),
                ),
            )
        return {
            "review_id": review_id,
            "assertion_id": body.assertion_id,
            "status": status,
            "reviewer": username,
        }

    @service.get("/api/v1/runs")
    def runs(limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0)):
        with connect(settings) as con:
            total = con.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
            items = [
                dict(r)
                for r in con.execute(
                    "SELECT * FROM runs ORDER BY started_at DESC LIMIT ? OFFSET ?", (limit, offset)
                )
            ]
            for item in items:
                item["detail"] = _json(item["detail"], {})
            jobs = [dict(r) for r in con.execute("SELECT * FROM jobs ORDER BY due_at DESC LIMIT 100")]
            queue = [
                dict(r)
                for r in con.execute("SELECT stage,status,COUNT(*) AS tasks FROM queue GROUP BY stage,status")
            ]
            counts = {
                "papers": con.execute("SELECT COUNT(*) FROM papers").fetchone()[0],
                "summarized_papers": len(
                    {
                        r["paper_id"]
                        for r in con.execute(_EXTRACTION_QUERY + " WHERE e.active=1")
                        if _extraction_validity(r)["current_valid"]
                    }
                ),
                "oa_papers": con.execute(
                    "SELECT COUNT(DISTINCT paper_id) FROM sources WHERE kind='fulltext'"
                ).fetchone()[0],
                "retracted_papers": con.execute("SELECT COUNT(*) FROM papers WHERE retracted=1").fetchone()[
                    0
                ],
            }
        return {
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
            "jobs": jobs,
            "queue": queue,
            "counts": counts,
        }

    @service.get("/api/v1/reports")
    def reports(limit: int = Query(default=25, ge=1, le=100), offset: int = Query(default=0, ge=0)):
        with connect(settings) as con:
            total = con.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
            items = []
            for row in con.execute(
                "SELECT * FROM reports ORDER BY generated_at DESC LIMIT ? OFFSET ?", (limit, offset)
            ):
                item = dict(row)
                item["snapshot"] = _json(item.pop("snapshot_json"), {})
                item["downloads"] = {
                    format_name: f"/api/v1/reports/{quote(item['report_id'], safe='')}/download/{format_name}"
                    for format_name in _json(item.pop("paths"), {})
                    if format_name in ("html", "markdown", "csv")
                }
                items.append(item)
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    @service.get("/api/v1/reports/{report_id}/download/{format_name}")
    def download(report_id: str, format_name: Literal["html", "markdown", "csv"]):
        with connect(settings) as con:
            row = con.execute("SELECT paths FROM reports WHERE report_id=?", (report_id,)).fetchone()
        path = _json(row["paths"], {}).get(format_name) if row else None
        if not isinstance(path, str):
            raise HTTPException(404, "리포트 파일이 없습니다.")
        report_root = settings.reports.resolve()
        resolved = Path(path).resolve() if Path(path).is_absolute() else (report_root / path).resolve()
        if not resolved.is_relative_to(report_root) or not resolved.is_file():
            raise HTTPException(404, "리포트 파일이 없습니다.")
        suffixes = {"html": ".html", "markdown": ".md", "csv": ".csv"}
        if resolved.suffix.lower() != suffixes[format_name]:
            raise HTTPException(404, "리포트 형식이 일치하지 않습니다.")
        types = {"html": "text/html", "markdown": "text/markdown", "csv": "text/csv"}
        return FileResponse(
            resolved,
            media_type=types[format_name],
            filename=resolved.name,
            headers={
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
            },
        )

    return service


app = create_app()
