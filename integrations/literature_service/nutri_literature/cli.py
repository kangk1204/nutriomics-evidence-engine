import argparse
from contextlib import ExitStack
import getpass
import json
import sys
from pathlib import Path
from .settings import Settings
from .db import connect, dumps, initialize
from .locking import lock


def main():
    parser = argparse.ArgumentParser(description="Heuristic literature service; no LLM inference")
    parser.add_argument("--home", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    for name in ["collect", "reconcile"]:
        command = sub.add_parser(name)
        command.add_argument("--topic")
    command = sub.add_parser("process")
    command.add_argument("--stage", choices=["oa", "extract"])
    command.add_argument("--limit", type=int, default=100)
    command = sub.add_parser("worker")
    command.add_argument("--stage", choices=["oa", "extract"], required=True)
    for name in [
        "report",
        "backup",
        "tick",
        "oa-recheck",
        "reprocess",
        "update-hgnc",
        "status",
        "health-check",
        "soak-status",
    ]:
        sub.add_parser(name)
    command = sub.add_parser("create-account")
    command.add_argument("username")
    command = sub.add_parser("reset-password")
    command.add_argument("username")
    command = sub.add_parser("prepare-gold")
    command.add_argument("--n", type=int, default=200)
    command = sub.add_parser("predict-gold", aliases=["rerun-predictions"])
    command.add_argument("input_path", type=Path, help="Pinned frozen_inputs.json; gold labels are never read")
    command = sub.add_parser("evaluate")
    command.add_argument("gold_path", type=Path)
    command.add_argument("--prediction-run", type=Path)
    command.add_argument("--split", choices=["development", "heldout", "both"], default="both")
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.home:
        settings = Settings(args.home, settings.config)
    initialize(settings)
    from . import collection, pipeline

    if args.command in ["collect", "reconcile"]:
        with lock(settings.home / "locks" / "collection.lock"):
            result = collection.collect(settings, args.command == "reconcile", args.topic)
    elif args.command in ["process", "worker"]:
        with ExitStack() as stack:
            for stage in [args.stage] if args.stage else ["extract", "oa"]:
                stack.enter_context(lock(settings.home / "locks" / ("worker-" + stage + ".lock")))
            result = (
                pipeline.worker(settings, args.stage)
                if args.command == "worker"
                else pipeline.process(settings, args.stage, args.limit)
            )
    elif args.command == "oa-recheck":
        result = pipeline.requeue_oa(settings)
    elif args.command == "reprocess":
        result = pipeline.reprocess(settings)
    elif args.command == "update-hgnc":
        from .dictionaries import update_hgnc

        result = update_hgnc(settings)
        pipeline.reprocess(settings)
    elif args.command in ["create-account", "reset-password"]:
        from .auth import create_account, reset_password

        first = getpass.getpass("New reviewer password: ")
        if first != getpass.getpass("Repeat password: "):
            parser.error("Passwords do not match")
        (create_account if args.command == "create-account" else reset_password)(
            settings, args.username, first
        )
        result = {"account_operation": args.command, "username": args.username}
    elif args.command in ["report", "backup"]:
        from .reporting import generate_report, backup

        result = generate_report(settings) if args.command == "report" else backup(settings)
    elif args.command == "tick":
        from .scheduler import tick

        with lock(settings.home / "locks" / "tick.lock"):
            result = tick(settings)
    elif args.command == "prepare-gold":
        from .evaluation import prepare_gold

        result = prepare_gold(settings, n=args.n)
    elif args.command in ["predict-gold", "rerun-predictions"]:
        from .evaluation import predict_gold

        result = predict_gold(settings, args.input_path)
    elif args.command == "evaluate":
        from .evaluation import evaluate

        result = evaluate(settings, args.gold_path, prediction_run=args.prediction_run, split=args.split)
    elif args.command in ["health-check", "soak-status"]:
        from .monitor import check, status

        result = check(settings) if args.command == "health-check" else status(settings)
    elif args.command == "status":
        with connect(settings) as con:
            result = {
                table: con.execute("SELECT count(*) FROM " + table).fetchone()[0]
                for table in [
                    "papers",
                    "sources",
                    "extractions",
                    "mentions",
                    "assertions",
                    "reviews",
                    "reports",
                ]
            }
            result["queue"] = [
                dict(r)
                for r in con.execute("SELECT stage,status,count(*) AS count FROM queue GROUP BY stage,status")
            ]
            result["last_runs"] = [
                dict(r) for r in con.execute("SELECT * FROM runs ORDER BY started_at DESC LIMIT 8")
            ]
            result["scientific_accuracy"] = "pending expert gold annotation"
    else:
        result = {"initialized": str(settings.database)}
    print(dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
