"""Read-only all-row graph coverage and provenance-preserving food trace audit."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import time


def audit(path, output):
    if output.exists():
        raise FileExistsError("Use a new audit output")
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    db.execute("BEGIN")
    deadline = time.monotonic() + 180
    db.set_progress_handler(lambda: time.monotonic() > deadline, 10000)
    scalar = lambda sql: db.execute(sql).fetchone()[0]
    checks = {
        "orphan_edge_nodes": scalar("SELECT count(*) FROM edge e LEFT JOIN node a ON a.id=e.subject LEFT JOIN node b ON b.id=e.object WHERE a.id IS NULL OR b.id IS NULL"),
        "edges_without_source": scalar("SELECT count(*) FROM edge e WHERE NOT EXISTS(SELECT 1 FROM edge_source s WHERE s.edge_id=e.id)"),
        "orphan_citations": scalar("SELECT count(*) FROM citation c LEFT JOIN edge e ON e.id=c.edge_id WHERE e.id IS NULL"),
        "measurement_missing_unit": scalar("SELECT count(*) FROM measurement WHERE unit IS NULL OR unit=''"),
        "measurement_missing_basis": scalar("SELECT count(*) FROM measurement WHERE basis=''"),
        "negative_measurement_amount": scalar("SELECT count(*) FROM measurement WHERE amount<0"),
        "measurement_orphan_source_or_nodes": scalar("SELECT count(*) FROM measurement m LEFT JOIN source s ON s.id=m.source_id LEFT JOIN node f ON f.id=m.food LEFT JOIN node n ON n.id=m.nutrient WHERE s.id IS NULL OR f.id IS NULL OR n.id IS NULL"),
        "invalid_pmid_syntax": scalar("SELECT count(*) FROM citation WHERE pmid='' OR pmid GLOB '*[^0-9]*'"),
    }
    counts = {t: scalar("SELECT count(*) FROM " + t) for t in ("source", "node", "edge", "citation", "measurement", "identifier_mapping")}
    source_profiles = []
    for row in db.execute("SELECT * FROM source ORDER BY id").fetchall():
        meta = json.loads(row["metadata_json"])
        source_profiles.append({"id": row["id"], "source": meta.get("source", meta.get("filename", meta.get("file", row["id"]))),
                                "sha256": meta.get("sha256"), "url": meta.get("url", meta.get("source_url")),
                                "version": meta.get("version"), "rights": meta.get("rights", meta.get("terms")),
                                "edge_count": db.execute("SELECT count(*) FROM edge_source WHERE source_id=?", (row["id"],)).fetchone()[0],
                                "measurement_count": db.execute("SELECT count(*) FROM measurement WHERE source_id=?", (row["id"],)).fetchone()[0],
                                "mapping_count": db.execute("SELECT count(*) FROM identifier_mapping WHERE source_id=?", (row["id"],)).fetchone()[0]})
    structures = {"chemical_nodes": scalar("SELECT count(*) FROM node WHERE kind='chemical'"),
                  "full_inchikey_present": scalar("SELECT count(*) FROM node WHERE kind='chemical' AND json_extract(metadata_json,'$.full_inchikey') IS NOT NULL"),
                  "exact_structure_crossrefs": scalar("SELECT count(*) FROM identifier_mapping WHERE relation='exact_structure'")}
    structures["without_full_inchikey"] = structures["chemical_nodes"] - structures["full_inchikey_present"]
    # A DB-level reported identifier bridge is a separate edge in the trace;
    # it is never upgraded to exact-structure equivalence or direct binding.
    traces = []
    sql = """SELECT f.id food_id,f.name food_name,c.id compound_id,c.name compound_name,
      x.id bridge_edge,g.id gene_id,g.name gene_name,m.amount,m.unit,m.basis,m.id measurement_id,
      m.source_id composition_source,ge.id gene_edge,de.id disease_edge,ge.taxon
      FROM measurement m JOIN node f ON f.id=m.food JOIN node c ON c.id=m.nutrient
      JOIN edge x ON x.subject=c.id AND x.relation='source_identifier_cross_reference'
      JOIN edge ge ON ge.subject=x.object AND ge.relation='chemical_gene_influence'
      JOIN node g ON g.id=ge.object
      JOIN edge de ON de.subject=g.id AND de.object='MESH:D006973' AND de.tier='curated'
      WHERE c.kind='chemical' AND m.amount>0 AND ge.taxon IN ('9606','NCBITaxon:9606')
      ORDER BY m.id,ge.id,de.id LIMIT 6"""
    for row in db.execute(sql):
        trace = dict(row)
        trace["steps"] = []
        for key in ("bridge_edge", "gene_edge", "disease_edge"):
            identifier = trace[key]
            edge = dict(db.execute("SELECT * FROM edge WHERE id=?", (identifier,)).fetchone())
            edge["context"] = json.loads(edge.pop("context_json"))
            edge["source_ids"] = [r[0] for r in db.execute("SELECT source_id FROM edge_source WHERE edge_id=? ORDER BY source_id", (identifier,))]
            edge["pmids"] = [r[0] for r in db.execute("SELECT pmid FROM citation WHERE edge_id=? ORDER BY pmid", (identifier,))]
            trace["steps"].append(edge)
        trace["interpretation"] = "Measured food composition + source-reported identifier link + CTD molecular influence + curated gene-disease evidence. Not measured Kd, same-person multiomics, causation or food efficacy."
        traces.append(trace)
    signature_groups = scalar("SELECT count(*) FROM (SELECT food,nutrient,amount,unit,basis,status,source_id,count(*) n FROM measurement GROUP BY food,nutrient,amount,unit,basis,status,source_id HAVING n>1)")
    result = {"generated_utc": datetime.now(timezone.utc).isoformat(), "path": str(path), "counts": counts,
              "all_row_checks": checks, "scope": "Full selected graph rows in one read-only transaction; not the separate large operational DB",
              "sources": source_profiles, "structure_coverage": structures,
              "measurement_same_value_signature_groups": signature_groups,
              "signature_interpretation": "Potential repeated measurements, not automatically independent experiments or removable duplicates; inspect raw provenance",
              "relations": [dict(r) for r in db.execute("SELECT relation,tier,count(*) n FROM edge GROUP BY relation,tier ORDER BY relation,tier")],
              "traces": traces, "clinical_or_food_efficacy_model_validated": False,
              "foreign_key_errors": [list(r) for r in db.execute("PRAGMA foreign_key_check")],
              "source_missing_sha256": sum(not p["sha256"] for p in source_profiles),
              "source_missing_url": sum(not p["url"] for p in source_profiles),
              "regulatory_annotation_count": scalar("SELECT count(*) FROM regulatory_annotation")
              if scalar("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='regulatory_annotation'") else 0}
    db.close()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"counts": counts, "checks": checks, "structures": structures, "traces": len(traces)}), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("database", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    audit(a.database, a.output)
