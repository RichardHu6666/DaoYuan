from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .deepseek_client import DeepSeekPreflightError
from .jiaowu_db_migrator import JiaowuDbMigrator
from .models import default_app_paths
from .pipeline import DataCleanPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="data-clean", description="Standalone school_event_table cleaning and ingest app.")
    parser.add_argument("--main-db", help="Override the target school_event_table SQLite path.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    one_parser = subparsers.add_parser("process-one", help="Process one RawPage file or page_id.")
    one_parser.add_argument("--input-file", help="Path to one RawPage JSON file.")
    one_parser.add_argument("--page-id", help="Find one RawPage by page_id in shared input.")
    one_parser.add_argument("--json", action="store_true")

    batch_parser = subparsers.add_parser("process-batch", help="Process a batch from shared input.")
    batch_parser.add_argument("--source", choices=["wechat", "jwc", "open_web"])
    batch_parser.add_argument("--limit", type=int)
    batch_parser.add_argument("--json", action="store_true")

    jwc_one = subparsers.add_parser("process-jwc-db-one", help="Process one JWC DB record.")
    jwc_one.add_argument("--record-id", type=int, required=True)
    jwc_one.add_argument("--json", action="store_true")

    jwc_batch = subparsers.add_parser("process-jwc-db-batch", help="Process a batch from the JWC source DB.")
    jwc_batch.add_argument("--limit", type=int)
    jwc_batch.add_argument("--offset", type=int, default=0)
    jwc_batch.add_argument("--concurrency", type=int, default=100)
    jwc_batch.add_argument("--include-completed", action="store_true")
    jwc_batch.add_argument("--no-progress", action="store_true")
    jwc_batch.add_argument("--json", action="store_true")

    migrate_jiaowu = subparsers.add_parser("migrate-jiaowu-db", help="Migrate cleaned events from jiaowu.db to the main DB.")
    migrate_jiaowu.add_argument("--source-db", default="/root/rivermind-data/database/jiaowu.db")
    migrate_jiaowu.add_argument("--limit", type=int)
    migrate_jiaowu.add_argument("--offset", type=int, default=0)
    migrate_jiaowu.add_argument("--no-progress", action="store_true")
    migrate_jiaowu.add_argument("--json", action="store_true")

    wechat_one = subparsers.add_parser("process-wechat-db-one", help="Process one WeChat article from account.sqlite3.")
    wechat_one.add_argument("--account", help="WeChat account identifier: display_name, alias, input_name, or account_dir.")
    wechat_one.add_argument("--account-dir", help="Exact WeChat account_dir for debugging.")
    wechat_one.add_argument("--article-id", type=int, required=True)
    wechat_one.add_argument("--json", action="store_true")

    wechat_account = subparsers.add_parser("process-wechat-db-account", help="Process one WeChat account batch.")
    wechat_account.add_argument("--account", help="WeChat account identifier: display_name, alias, input_name, or account_dir.")
    wechat_account.add_argument("--account-dir", help="Exact WeChat account_dir for debugging.")
    wechat_account.add_argument("--limit", type=int)
    wechat_account.add_argument("--offset", type=int, default=0)
    wechat_account.add_argument("--concurrency", type=int, default=300)
    wechat_account.add_argument("--include-completed", action="store_true")
    wechat_account.add_argument("--no-progress", action="store_true")
    wechat_account.add_argument("--json", action="store_true")

    wechat_batch = subparsers.add_parser("process-wechat-db-batch", help="Process a WeChat batch file.")
    wechat_batch.add_argument("--batch-file", required=True, help="One WeChat account identifier per line.")
    wechat_batch.add_argument("--concurrency", type=int, default=300)
    wechat_batch.add_argument("--include-completed", action="store_true")
    wechat_batch.add_argument("--no-progress", action="store_true")
    wechat_batch.add_argument("--json", action="store_true")

    check_remote = subparsers.add_parser("check-remote-llm", help="Run remote LLM preflight for WeChat batch processing.")
    check_remote.add_argument("--json", action="store_true")

    reset_wechat = subparsers.add_parser("reset-wechat-batch", help="Reset WeChat batch state and target DB.")
    reset_wechat.add_argument("--batch-file", required=True, help="One WeChat account identifier per line.")
    reset_wechat.add_argument("--keep-main-db", action="store_true", help="Keep the current target DB file.")
    reset_wechat.add_argument("--json", action="store_true")

    retry_parser = subparsers.add_parser("retry-manual", help="Retry manual review items.")
    retry_parser.add_argument("--review-id")
    retry_parser.add_argument("--all-pending", action="store_true")
    retry_parser.add_argument("--source-type", choices=["wechat_db", "jwc_db", "raw_page"])
    retry_parser.add_argument("--reason-code")
    retry_parser.add_argument("--json", action="store_true")

    show_manual = subparsers.add_parser("show-manual", help="Show manual review items.")
    show_manual.add_argument("--status", default="pending")
    show_manual.add_argument("--source-type", choices=["wechat_db", "jwc_db", "raw_page"])
    show_manual.add_argument("--reason-code")
    show_manual.add_argument("--json", action="store_true")

    show_status = subparsers.add_parser("show-status", help="Show sidecar summary.")
    show_status.add_argument("--json", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    paths = default_app_paths()
    if args.main_db:
        paths.main_db_path = Path(args.main_db)
    paths.ensure()
    pipeline = DataCleanPipeline(paths=paths)

    try:
        if args.command == "process-one":
            if bool(args.input_file) == bool(args.page_id):
                parser.error("process-one requires exactly one of --input-file or --page-id")
            if args.input_file:
                return _emit(pipeline.process_input_file(args.input_file), as_json=args.json)
            return _emit(pipeline.process_page_id(args.page_id), as_json=args.json)

        if args.command == "process-batch":
            return _emit(pipeline.process_batch(source=args.source, limit=args.limit), as_json=args.json)

        if args.command == "process-jwc-db-one":
            return _emit(pipeline.process_jwc_db_one(record_id=args.record_id), as_json=args.json)

        if args.command == "process-jwc-db-batch":
            progress_callback = None if args.no_progress else _build_progress_reporter()
            return _emit(
                pipeline.process_jwc_db_batch(
                    limit=args.limit,
                    offset=args.offset,
                    concurrency=args.concurrency,
                    include_completed=args.include_completed,
                    progress_callback=progress_callback,
                ),
                as_json=args.json,
            )

        if args.command == "migrate-jiaowu-db":
            progress_callback = None if args.no_progress else _build_progress_reporter()
            migrator = JiaowuDbMigrator(paths=paths)
            return _emit(
                migrator.migrate(
                    source_db=args.source_db,
                    limit=args.limit,
                    offset=args.offset,
                    progress_callback=progress_callback,
                ),
                as_json=args.json,
            )

        if args.command == "process-wechat-db-one":
            account_identifier, account_dir = _select_account_target(parser, args)
            return _emit(
                pipeline.process_wechat_db_one(
                    article_id=args.article_id,
                    account_identifier=account_identifier,
                    account_dir=account_dir,
                ),
                as_json=args.json,
            )

        if args.command == "process-wechat-db-account":
            account_identifier, account_dir = _select_account_target(parser, args)
            progress_callback = None if args.no_progress else _build_progress_reporter()
            return _emit(
                pipeline.process_wechat_db_account(
                    account_identifier=account_identifier,
                    account_dir=account_dir,
                    limit=args.limit,
                    offset=args.offset,
                    concurrency=args.concurrency,
                    include_completed=args.include_completed,
                    progress_callback=progress_callback,
                ),
                as_json=args.json,
            )

        if args.command == "process-wechat-db-batch":
            progress_callback = None if args.no_progress else _build_progress_reporter()
            return _emit(
                pipeline.process_wechat_db_batch(
                    batch_file=args.batch_file,
                    concurrency=args.concurrency,
                    include_completed=args.include_completed,
                    progress_callback=progress_callback,
                ),
                as_json=args.json,
            )

        if args.command == "check-remote-llm":
            return _emit(pipeline.ensure_wechat_batch_remote_llm(), as_json=args.json)

        if args.command == "reset-wechat-batch":
            return _emit(
                pipeline.reset_wechat_batch(
                    batch_file=args.batch_file,
                    drop_main_db=not args.keep_main_db,
                ),
                as_json=args.json,
            )

        if args.command == "retry-manual":
            if not args.review_id and not args.all_pending:
                parser.error("retry-manual requires --review-id or --all-pending")
            return _emit(
                pipeline.retry_manual(
                    review_id=args.review_id,
                    all_pending=args.all_pending,
                    source_type=args.source_type,
                    reason_code=args.reason_code,
                ),
                as_json=args.json,
            )

        if args.command == "show-manual":
            return _emit(
                {
                    "items": pipeline.show_manual(
                        status=args.status,
                        source_type=args.source_type,
                        reason_code=args.reason_code,
                    )
                },
                as_json=args.json,
            )

        if args.command == "show-status":
            return _emit(pipeline.show_status(), as_json=args.json)
    except DeepSeekPreflightError as exc:
        print(f"remote_llm_preflight_failed: {exc}", file=sys.stderr)
        return 2

    return 0


def _emit(payload: dict, *, as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if "status" in payload:
        print(f"status: {payload['status']}")
        if payload.get("page_id"):
            print(f"page_id: {payload['page_id']}")
        if payload.get("article_id"):
            print(f"article_id: {payload['article_id']}")
        if payload.get("record_id"):
            print(f"record_id: {payload['record_id']}")
        if payload.get("account_dir"):
            print(f"account_dir: {payload['account_dir']}")
        if payload.get("review_id"):
            print(f"review_id: {payload['review_id']}")
        return 0

    if "processed" in payload:
        print(f"processed: {payload['processed']}")
        if payload.get("skipped") is not None:
            print(f"skipped: {payload['skipped']}")
        if payload.get("counts"):
            for key, value in payload["counts"].items():
                print(f"{key}: {value}")
        return 0

    if "available" in payload:
        print(f"available: {payload['available']}")
        print(f"enabled: {payload.get('enabled')}")
        print(f"api_key_present: {payload.get('api_key_present')}")
        print(f"base_url: {payload.get('base_url')}")
        print(f"model: {payload.get('model')}")
        print(f"model_llm1: {payload.get('model_llm1')}")
        print(f"model_llm2: {payload.get('model_llm2')}")
        print(f"model_llm3: {payload.get('model_llm3')}")
        print(f"latency_ms: {payload.get('latency_ms')}")
        return 0

    if "items" in payload:
        print(f"manual_items: {len(payload['items'])}")
        return 0

    for key, value in payload.items():
        print(f"{key}: {value}")
    return 0


def _build_progress_reporter():
    def report(event: dict) -> None:
        kind = str(event.get("event") or "")
        if kind == "wechat_batch_start":
            print(
                (
                    f"[wechat-batch] start accounts_total={event.get('accounts_total', 0)} "
                    f"concurrency={event.get('concurrency', 0)} batch_file={event.get('batch_file', '')}"
                ),
                file=sys.stderr,
                flush=True,
            )
            return

        if kind == "wechat_batch_account":
            print(
                (
                    f"[wechat-batch] queued {event.get('account_index', 0)}/{event.get('accounts_total', 0)} "
                    f"name={event.get('account_name', '')} dir={event.get('account_dir', '')} "
                    f"concurrency={event.get('concurrency', 0)}"
                ),
                file=sys.stderr,
                flush=True,
            )
            return

        if kind == "wechat_account_start":
            print(
                (
                    f"[wechat-account] start name={event.get('account_name', '')} "
                    f"dir={event.get('account_dir', '')} total={event.get('total', 0)} "
                    f"skipped={event.get('skipped', 0)} concurrency={event.get('concurrency', 0)}"
                ),
                file=sys.stderr,
                flush=True,
            )
            return

        if kind == "wechat_account_progress":
            counts = event.get("counts", {})
            suffix = ""
            if event.get("reason_code"):
                suffix += f" reason_code={event.get('reason_code', '')}"
            if event.get("error"):
                suffix += f" error={event.get('error', '')}"
            print(
                (
                    f"[wechat-account] {event.get('completed', 0)}/{event.get('total', 0)} "
                    f"name={event.get('account_name', '')} status={event.get('status', '')} "
                    f"page_id={event.get('page_id', '')} article_id={event.get('article_id', '')} "
                    f"concurrency={event.get('concurrency', 0)} "
                    f"stored={counts.get('stored', 0)} duplicate={counts.get('duplicate', 0)} "
                    f"manual_review={counts.get('manual_review', 0)} failed={counts.get('failed', 0)}"
                    f"{suffix}"
                ),
                file=sys.stderr,
                flush=True,
            )
            return

        if kind == "wechat_account_end":
            counts = event.get("counts", {})
            print(
                (
                    f"[wechat-account] done name={event.get('account_name', '')} "
                    f"processed={event.get('processed', 0)} skipped={event.get('skipped', 0)} "
                    f"concurrency={event.get('concurrency', 0)} "
                    f"stored={counts.get('stored', 0)} duplicate={counts.get('duplicate', 0)} "
                    f"manual_review={counts.get('manual_review', 0)} failed={counts.get('failed', 0)}"
                ),
                file=sys.stderr,
                flush=True,
            )
            return

        if kind == "wechat_batch_end":
            counts = event.get("counts", {})
            print(
                (
                    f"[wechat-batch] done processed={event.get('processed', 0)} "
                    f"skipped={event.get('skipped', 0)} accounts_total={event.get('accounts_total', 0)} "
                    f"concurrency={event.get('concurrency', 0)} "
                    f"stored={counts.get('stored', 0)} duplicate={counts.get('duplicate', 0)} "
                    f"manual_review={counts.get('manual_review', 0)} failed={counts.get('failed', 0)}"
                ),
                file=sys.stderr,
                flush=True,
            )
            return

        if kind == "start":
            print(
                (
                    f"[progress] start total={event.get('total', 0)} "
                    f"skipped={event.get('skipped', 0)} "
                    f"concurrency={event.get('concurrency', 0)}"
                ),
                file=sys.stderr,
                flush=True,
            )
            return

        if kind == "progress":
            counts = event.get("counts", {})
            print(
                (
                    f"[progress] {event.get('completed', 0)}/{event.get('total', 0)} "
                    f"status={event.get('status', '')} "
                    f"page_id={event.get('page_id', '')} "
                    f"record_id={event.get('record_id', '')} "
                    f"stored={counts.get('stored', 0)} "
                    f"duplicate={counts.get('duplicate', 0)} "
                    f"manual_review={counts.get('manual_review', 0)} "
                    f"failed={counts.get('failed', 0)}"
                ),
                file=sys.stderr,
                flush=True,
            )
            return

        if kind == "end":
            counts = event.get("counts", {})
            print(
                (
                    f"[progress] done processed={event.get('processed', 0)} "
                    f"skipped={event.get('skipped', 0)} "
                    f"concurrency={event.get('concurrency', 0)} "
                    f"stored={counts.get('stored', 0)} "
                    f"duplicate={counts.get('duplicate', 0)} "
                    f"manual_review={counts.get('manual_review', 0)} "
                    f"failed={counts.get('failed', 0)}"
                ),
                file=sys.stderr,
                flush=True,
            )

    return report


def _select_account_target(parser: argparse.ArgumentParser, args) -> tuple[str | None, str | None]:
    if bool(args.account) == bool(args.account_dir):
        parser.error(f"{args.command} requires exactly one of --account or --account-dir")
    return args.account, args.account_dir
