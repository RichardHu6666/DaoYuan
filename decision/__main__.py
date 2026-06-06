from __future__ import annotations

import argparse
import asyncio
import json
import sys

from .client_manager import ClientManager
from .jiaowu_real_test import (
    DEFAULT_REPORT_DIR,
    DEFAULT_SOURCE_DB,
    DEFAULT_TARGET_DB,
    backfill_embeddings_in_db,
    prepare_jiaowu_test_db,
    run_jiaowu_t2t_suite,
)
from .preflight import run_preflight


DEFAULT_SERVICE_HOST = "127.0.0.1"
DEFAULT_SERVICE_PORT = 8000


async def _run(user_id: str, instruct: str) -> str:
    manager = ClientManager()
    try:
        client = await manager.get_client(user_id)
        return await client.respond(instruct)
    finally:
        await manager.close()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and not argv[0].startswith("-") and argv[0] not in {
        "respond",
        "check",
        "prepare-jiaowu-test-db",
        "run-jiaowu-test",
        "backfill-embeddings",
        "serve",
    }:
        argv = ["respond", *argv]

    parser = argparse.ArgumentParser(prog="decision", description="Jarvis decision-layer debug entrypoint.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    respond_parser = subparsers.add_parser("respond", help="Run a debug decision response.")
    respond_parser.add_argument("user_id")
    respond_parser.add_argument("instruct")

    check_parser = subparsers.add_parser("check", help="Run preflight code checks before real data is ready.")
    check_parser.add_argument("--runtime", action="store_true", help="Also validate runtime paths and env readiness.")
    check_parser.add_argument("--json", action="store_true", help="Print the preflight report as JSON.")

    prepare_parser = subparsers.add_parser(
        "prepare-jiaowu-test-db",
        help="Copy jiaowu.db into a test DB, seed fixtures, and generate embeddings.",
    )
    prepare_parser.add_argument("--source-db", default=DEFAULT_SOURCE_DB)
    prepare_parser.add_argument("--target-db", default=DEFAULT_TARGET_DB)
    prepare_parser.add_argument("--force-rebuild-embeddings", action="store_true")
    prepare_parser.add_argument("--json", action="store_true", help="Print the preparation report as JSON.")

    run_parser = subparsers.add_parser(
        "run-jiaowu-test",
        help="Prepare the jiaowu decision test DB and run the full T2T + client/client manager validation suite.",
    )
    run_parser.add_argument("--source-db", default=DEFAULT_SOURCE_DB)
    run_parser.add_argument("--target-db", default=DEFAULT_TARGET_DB)
    run_parser.add_argument("--report-dir", default=DEFAULT_REPORT_DIR)
    run_parser.add_argument("--force-rebuild-embeddings", action="store_true")
    run_parser.add_argument("--json", action="store_true", help="Print the suite report as JSON.")

    backfill_parser = subparsers.add_parser(
        "backfill-embeddings",
        help="Generate and write embeddings in place for the target decision database.",
    )
    backfill_parser.add_argument("--db-path", required=True)
    backfill_parser.add_argument("--force-rebuild-embeddings", action="store_true")
    backfill_parser.add_argument("--json", action="store_true", help="Print the backfill report as JSON.")

    serve_parser = subparsers.add_parser(
        "serve",
        help="Run the long-lived FastAPI decision service with a shared ClientManager.",
    )
    serve_parser.add_argument("--host", default=DEFAULT_SERVICE_HOST)
    serve_parser.add_argument("--port", type=int, default=DEFAULT_SERVICE_PORT)
    serve_parser.add_argument("--db-path", default=None, help="Optional override for DECISION_DB_PATH.")

    args = parser.parse_args(argv)
    if args.command == "respond":
        print(asyncio.run(_run(args.user_id, args.instruct)))
        return 0

    if args.command == "check":
        report = run_preflight(include_runtime=args.runtime)
        print(report.to_json() if args.json else report.to_text())
        return 0 if report.ok else 1

    if args.command == "prepare-jiaowu-test-db":
        report = prepare_jiaowu_test_db(
            source_db=args.source_db,
            target_db=args.target_db,
            force_rebuild_embeddings=args.force_rebuild_embeddings,
        )
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    if args.command == "backfill-embeddings":
        report = backfill_embeddings_in_db(
            db_path=args.db_path,
            force_rebuild_embeddings=args.force_rebuild_embeddings,
        )
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    if args.command == "serve":
        from .service import run_service

        run_service(host=args.host, port=args.port, db_path=args.db_path)
        return 0

    suite_report = asyncio.run(
        run_jiaowu_t2t_suite(
            source_db=args.source_db,
            target_db=args.target_db,
            report_dir=args.report_dir,
            force_rebuild_embeddings=args.force_rebuild_embeddings,
        )
    )
    if args.json:
        print(json.dumps(suite_report, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(suite_report["summary"], ensure_ascii=False, indent=2))
        print(json.dumps(suite_report["report_paths"], ensure_ascii=False, indent=2))
    return 0 if suite_report["summary"]["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
