"""Freeze a source-linked report; back up SQLite through its online backup API."""

import csv
import html
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .db import connect, digest, dumps, now, uid
from .extraction import RULES_VERSION


def _period(value, default):
    moment = datetime.fromisoformat(value) if isinstance(value, str) else (value or default)
    if moment.tzinfo is None:
        raise ValueError("Report dates must include a timezone")
    return moment.astimezone(UTC).isoformat()


def _snapshot(settings, start, end):
    with connect(settings) as con:
        con.execute("BEGIN")
        papers = [
            dict(row)
            for row in con.execute(
                "SELECT * FROM papers WHERE updated_at>=? AND updated_at<? ORDER BY pmid", (start, end)
            )
        ]
        for paper in papers:
            pid = paper["paper_id"]
            paper["topics"] = [
                dict(row)
                for row in con.execute(
                    "SELECT DISTINCT t.topic_id,t.name,t.query_version FROM paper_topics p JOIN topics t USING(topic_id) "
                    "WHERE p.paper_id=? AND p.query_version=t.query_version AND t.enabled=1 ORDER BY t.topic_id",
                    (pid,),
                )
            ]
            extraction = con.execute(
                "SELECT e.*,s.kind AS source_kind,s.url AS source_url,s.license AS source_license,"
                "s.text_hash AS source_text_hash,s.text_content AS source_text "
                "FROM extractions e JOIN sources s USING(source_id) "
                "WHERE e.paper_id=? AND e.active=1 ORDER BY e.created_at DESC,e.extraction_id DESC LIMIT 1",
                (pid,),
            ).fetchone()
            paper["extraction"] = dict(extraction) if extraction else None
            if extraction:
                source_text = paper["extraction"].pop("source_text")
                paper["extraction"]["result"] = json.loads(paper["extraction"].pop("result_json"))
                paper["extraction_current"] = (
                    extraction["source_id"] == paper["current_source_id"]
                    and extraction["source_hash"] == extraction["source_text_hash"] == digest(source_text)
                    and paper["extraction"]["result"].get("rules_version") == RULES_VERSION
                )
                paper["assertions"] = [
                    dict(row)
                    for row in con.execute(
                        "SELECT * FROM assertions WHERE extraction_id=? ORDER BY start,assertion_id",
                        (extraction["extraction_id"],),
                    )
                ]
                for assertion in paper["assertions"]:
                    assertion["reviews"] = [
                        dict(row)
                        for row in con.execute(
                            "SELECT reviewer,decision,comment,corrected_payload,fingerprint,created_at FROM reviews "
                            "WHERE assertion_id=? ORDER BY created_at,rowid",
                            (assertion["assertion_id"],),
                        )
                    ]
                    latest_review = assertion["reviews"][-1] if assertion["reviews"] else {}
                    review_matches = latest_review.get("fingerprint") == assertion[
                        "fingerprint"
                    ] and latest_review.get("decision") in ("approved", "corrected")
                    correction = (
                        latest_review.get("corrected_payload")
                        if latest_review.get("decision") == "corrected" and assertion["status"] == "approved"
                        else None
                    )
                    assertion["effective"] = {
                        key: assertion[key] for key in ["subject", "predicate", "object"]
                    }
                    if correction:
                        assertion["effective"].update(
                            {
                                key: value
                                for key, value in json.loads(correction).items()
                                if key in assertion["effective"]
                            }
                        )
                    assertion["source_span_valid"] = (
                        0 <= assertion["start"] < assertion["end"] <= len(source_text)
                        and source_text[assertion["start"] : assertion["end"]] == assertion["quote"]
                    )
                    assertion["display_status"] = (
                        assertion["status"]
                        if paper["extraction_current"]
                        and assertion["source_span_valid"]
                        and not paper["retracted"]
                        and (assertion["status"] != "approved" or review_matches)
                        else "needs_review"
                    )
            else:
                paper["extraction_current"] = False
                paper["assertions"] = []
        counts = {
            "papers_total": con.execute("SELECT count(*) FROM papers").fetchone()[0],
            "new_papers": con.execute(
                "SELECT count(*) FROM papers WHERE created_at>=? AND created_at<?", (start, end)
            ).fetchone()[0],
            "changed_papers": sum(paper["created_at"] < start for paper in papers),
            "papers_in_report": len(papers),
            "abstract_only": sum(
                not p["extraction"] or p["extraction"]["source_kind"] == "pubmed" for p in papers
            ),
            "full_text": sum(
                bool(p["extraction"] and p["extraction"]["source_kind"] == "fulltext") for p in papers
            ),
            "retracted": sum(p["retracted"] for p in papers),
            "relation_candidates": sum(len(p["assertions"]) for p in papers),
            "approved_relations": sum(
                a["display_status"] == "approved" for p in papers for a in p["assertions"]
            ),
            "summarized_papers": sum(p["extraction_current"] for p in papers),
            "full_text_rate": (
                sum(bool(p["extraction"] and p["extraction"]["source_kind"] == "fulltext") for p in papers)
                / len(papers)
                if papers
                else None
            ),
            "review_decisions": sum(len(a["reviews"]) for p in papers for a in p["assertions"]),
        }
        runs = [
            dict(row)
            for row in con.execute(
                "SELECT * FROM runs WHERE started_at>=? AND started_at<? ORDER BY started_at", (start, end)
            )
        ]
        counts["failed_runs"] = sum(r["status"] in ("failed", "partial") for r in runs)
    return {
        "schema_version": "literature-report-v1",
        "generated_at": now(),
        "period_start": start,
        "period_end": end,
        "counts": counts,
        "papers": papers,
        "runs": runs,
        "quality": {
            "status": "not_evaluated",
            "precision": None,
            "recall": None,
            "f1": None,
            "note": "수동 검토한 정답셋의 평가 전에는 추출 정확도를 산출하지 않습니다.",
        },
        "interpretation": "자동 추출은 후보입니다. 원문 공기출현이나 규칙 점수는 인과관계 또는 정확도가 아닙니다.",
    }


def _text(value):
    if isinstance(value, dict):
        return value.get("text", dumps(value))
    return str(value) if value else "미확인"


def _render(snapshot):
    counts = snapshot["counts"]
    lines = [
        "# 영양유전체 문헌 정리",
        "",
        f"기간: {snapshot['period_start']} — {snapshot['period_end']}",
        "",
        f"신규 {counts['new_papers']}편 · 변경 {counts['changed_papers']}편 · 관계 후보 {counts['relation_candidates']}건",
        "",
        snapshot["interpretation"],
        "",
        snapshot["quality"]["note"],
        "",
    ]

    def esc(value):
        return html.escape(str(value), quote=True)

    overview = (
        f"누적 고유 문헌 {counts['papers_total']}편 · 기간 신규/변경 고유 문헌 {counts['papers_in_report']}편 · "
        f"기간 문헌의 현재 요약 {counts['summarized_papers']}편 · 본문 확보 {counts['full_text']}편 · "
        f"검수 승인 관계 {counts['approved_relations']}건 · 철회 {counts['retracted']}편 · 실패 실행 {counts['failed_runs']}건"
    )
    lines += [overview, ""]
    sections = [
        "<h1>영양유전체 문헌 정리</h1>",
        f"<p>기간: {esc(snapshot['period_start'])} — {esc(snapshot['period_end'])}</p>",
        f"<p>신규 {counts['new_papers']}편 · 변경 {counts['changed_papers']}편 · 관계 후보 {counts['relation_candidates']}건</p>",
        f"<p>{esc(snapshot['interpretation'])}</p><p>{esc(snapshot['quality']['note'])}</p>",
        f"<p>{esc(overview)}</p>",
    ]
    for paper in snapshot["papers"]:
        title, pmid = paper["title"], paper["pmid"]
        url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        lines += [
            f"## PMID {pmid}: {title}",
            "",
            f"원문: {url}",
            "주제: " + ", ".join(t["name"] for t in paper["topics"]),
            "",
        ]
        sections += [
            f"<article><h2>PMID {esc(pmid)}: {esc(title)}</h2>",
            f'<p><a href="{esc(url)}">PubMed 원문</a> · {esc(", ".join(t["name"] for t in paper["topics"]))}</p>',
        ]
        if paper["retracted"]:
            lines += ["**철회 표시: 해석에 사용하지 않음**", ""]
            sections += ["<p><strong>철회 표시: 해석에 사용하지 않음</strong></p>"]
        extraction = paper["extraction"]
        if not extraction:
            lines += ["요약: 추출 대기", ""]
            sections += ["<p>요약: 추출 대기</p></article>"]
            continue
        summary = extraction["result"].get("summary", {})
        for key, label in [("method", "연구설계"), ("results", "주요 결과"), ("limitations", "한계")]:
            values = summary.get(key, "미확인")
            values = values if isinstance(values, list) else [values]
            if not values:
                values = ["미확인"]
            for value in values:
                text = _text(value)
                locator = (
                    f" [문자 {value['start']}:{value['end']}]"
                    if isinstance(value, dict) and "start" in value and "end" in value
                    else ""
                )
                lines += [f"- {label}: {text}{locator}"]
                sections += [f"<p><b>{label}</b>: {esc(text)}{esc(locator)}</p>"]
        lines += [
            "",
            f"근거 SHA256: {extraction['source_hash']}",
            f"엔진: {extraction['engine_version']} · 사전: {extraction['dictionary_version']}",
            f"규칙: {extraction['result'].get('rules_version', '미확인')}",
            "",
        ]
        sections += [
            (
                f"<p class=provenance>근거 SHA256: {esc(extraction['source_hash'])}<br>"
                f"엔진: {esc(extraction['engine_version'])} · 사전: {esc(extraction['dictionary_version'])}<br>"
                f"규칙: {esc(extraction['result'].get('rules_version', '미확인'))}</p>"
            )
        ]
        for assertion in paper["assertions"]:
            effective = assertion["effective"]
            relation = f"{effective['subject']} → {effective['predicate']} → {effective['object']}"
            lines += [
                f"- 관계 후보 ({assertion['display_status']}): {relation}",
                f"  근거 [{assertion['start']}:{assertion['end']}]: {assertion['quote']}",
            ]
            sections += [
                (
                    f"<p><b>관계 후보 ({esc(assertion['display_status'])})</b>: {esc(relation)}</p>"
                    f"<blockquote>{esc(assertion['quote'])} [{assertion['start']}:{assertion['end']}]</blockquote>"
                )
            ]
        sections += ["</article>"]
        lines += [""]
    if not snapshot["papers"]:
        lines += ["해당 기간 신규·변경 문헌이 없습니다."]
        sections += ["<p>해당 기간 신규·변경 문헌이 없습니다.</p>"]
    style = "body{font:16px system-ui;max-width:1000px;margin:40px auto;padding:0 24px;line-height:1.6}article{border-top:1px solid #ccd;padding:20px 0}blockquote{border-left:3px solid #aac;padding-left:16px}.provenance{font-size:12px;overflow-wrap:anywhere}"
    return (
        "\n".join(lines) + "\n",
        f'<!doctype html><html lang="ko"><meta charset="utf-8"><title>영양유전체 문헌 정리</title><style>{style}</style><body>'
        + "\n".join(sections)
        + "</body></html>",
    )


def generate_report(settings, period_start=None, period_end=None):
    current = datetime.now(UTC)
    end = _period(period_end, current)
    start = _period(period_start, datetime.fromisoformat(end) - timedelta(days=7))
    if start >= end:
        raise ValueError("Report period must have start before end")
    snapshot = _snapshot(settings, start, end)
    report_id = uid()
    directory = settings.reports / report_id
    directory.mkdir(parents=True, exist_ok=False)
    markdown, document = _render(snapshot)
    paths = {
        kind: str(directory / filename)
        for kind, filename in [("html", "report.html"), ("markdown", "report.md"), ("csv", "evidence.csv")]
    }
    Path(paths["html"]).write_text(document, encoding="utf-8")
    Path(paths["markdown"]).write_text(markdown, encoding="utf-8")
    fields = [
        "record_type",
        "pmid",
        "title",
        "topics",
        "source_hash",
        "engine_version",
        "dictionary_version",
        "rules_version",
        "subject",
        "predicate",
        "object",
        "status",
        "quote",
        "start",
        "end",
        "pubmed_url",
    ]
    with Path(paths["csv"]).open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for paper in snapshot["papers"]:
            extraction = paper["extraction"] or {}
            base = {
                "pmid": paper["pmid"],
                "title": paper["title"],
                "topics": ";".join(t["topic_id"] for t in paper["topics"]),
                "pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{paper['pmid']}/",
                "rules_version": extraction.get("result", {}).get("rules_version", ""),
                **{
                    key: extraction.get(key, "")
                    for key in ["source_hash", "engine_version", "dictionary_version"]
                },
            }
            rows = [{"record_type": "paper", **base}]
            rows += [
                {
                    "record_type": "relation_candidate",
                    **base,
                    **{key: assertion[key] for key in ["quote", "start", "end"]},
                    **assertion["effective"],
                    "status": assertion["display_status"],
                }
                for assertion in paper["assertions"]
            ]
            for row in rows:
                writer.writerow(
                    {
                        key: "'" + value
                        if isinstance(value, str) and value.startswith(("=", "+", "-", "@"))
                        else value
                        for key, value in row.items()
                    }
                )
    serialized = dumps(snapshot)
    (directory / "snapshot.json").write_text(serialized, encoding="utf-8")
    snapshot_hash = digest(serialized)
    with connect(settings) as con:
        con.execute(
            "INSERT INTO reports VALUES(?,?,?,?,?,?,?)",
            (report_id, snapshot["generated_at"], start, end, snapshot_hash, serialized, dumps(paths)),
        )
    return {
        "report_id": report_id,
        "snapshot_hash": snapshot_hash,
        "counts": snapshot["counts"],
        "paths": paths,
    }


def backup(settings):
    settings.ensure()
    if not settings.database.is_file():
        raise FileNotFoundError("Literature database does not exist")
    current = datetime.now(UTC)
    path = settings.backups / ("literature-" + current.strftime("%Y%m%dT%H%M%SZ") + "-" + uid() + ".sqlite3")
    source = sqlite3.connect(settings.database.resolve().as_uri() + "?mode=ro", uri=True)
    destination = sqlite3.connect(path)
    try:
        source.backup(destination, pages=256, sleep=0.05)
        checks = [row[0] for row in destination.execute("PRAGMA integrity_check")]
        foreign_keys = destination.execute("PRAGMA foreign_key_check").fetchall()
        if checks != ["ok"] or foreign_keys:
            raise ValueError("Backup integrity check failed")
    finally:
        destination.close()
        source.close()
    receipt = {
        "path": str(path),
        "sha256": digest(path.read_bytes()),
        "created_at": current.isoformat(),
        "integrity": "ok",
        "retention_days": 30,
    }
    path.with_suffix(".json").write_text(dumps(receipt), encoding="utf-8")
    cutoff = current - timedelta(days=30)
    removed = 0
    for candidate in settings.backups.glob("literature-*.sqlite3"):
        try:
            timestamp = datetime.strptime(candidate.name.split("-")[1], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        except (ValueError, IndexError):
            continue
        if timestamp < cutoff and candidate.parent.resolve() == settings.backups.resolve():
            candidate.unlink()
            candidate.with_suffix(".json").unlink(missing_ok=True)
            removed += 1
    return {**receipt, "removed_old_backups": removed}
