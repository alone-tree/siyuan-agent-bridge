from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from .client import SiYuanApiError, SiYuanClient, SiYuanConnectionError
from .config import Config, load_config
from .indexer import (
    KB_CACHE_DIR,
    find_documents,
    load_docs,
    refresh_index,
    resolve_document,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config(Path.cwd())

    try:
        return int(args.func(args, config))
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except SiYuanConnectionError as exc:
        print(f"Connection failed: {exc}", file=sys.stderr)
        return 2
    except SiYuanApiError as exc:
        print(format_api_error(exc), file=sys.stderr)
        return 3
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m siyuan_kb",
        description="Private read-only adapter for using SiYuan as an AI knowledge base.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Check SiYuan API connectivity.")
    doctor.set_defaults(func=cmd_doctor)

    notebooks = sub.add_parser("notebooks", help="List SiYuan notebooks.")
    notebooks.set_defaults(func=cmd_notebooks)

    refresh = sub.add_parser("refresh", help="Refresh local knowledge-base indexes.")
    refresh.set_defaults(func=cmd_refresh)

    tree = sub.add_parser("tree", help="Print kb_cache/tree.md.")
    tree.set_defaults(func=cmd_tree)

    find = sub.add_parser("find", help="Find documents by title, path, notebook, tag, or id.")
    find.add_argument("keyword")
    find.add_argument("--limit", type=int, default=20)
    find.set_defaults(func=cmd_find)

    read = sub.add_parser("read", help="Read one SiYuan document as Markdown.")
    read.add_argument("locator", help="Document id, exact hpath, title, or unique partial match.")
    read.set_defaults(func=cmd_read)

    return parser


def cmd_doctor(_args: argparse.Namespace, config: Config) -> int:
    if not config.token:
        print("No SIYUAN_TOKEN or config.local.json siyuan_token found.")
        print("Trying without a token in case SiYuan auth is disabled.")

    last_error: Exception | None = None
    for url in config.urls:
        client = SiYuanClient(url, token=config.token, timeout=3.0)
        try:
            version = client.version()
        except SiYuanConnectionError as exc:
            last_error = exc
            print(f"[fail] {url} connection failed: {exc}")
            continue
        except SiYuanApiError as exc:
            last_error = exc
            if exc.status in (401, 403) or "token" in str(exc).casefold():
                print(f"[fail] {url} token rejected or missing: {exc}")
            else:
                print(f"[fail] {url} API error: {exc}")
            continue

        print(f"[ok] {url} SiYuan version: {version}")
        return 0

    if last_error:
        print("No configured SiYuan endpoint worked.", file=sys.stderr)
    return 1


def cmd_notebooks(_args: argparse.Namespace, config: Config) -> int:
    client = get_working_client(config)
    notebooks = client.list_notebooks()
    if not notebooks:
        print("No notebooks returned by SiYuan.")
        return 0
    for item in notebooks:
        notebook_id = item.get("id", "")
        name = item.get("name", "")
        closed = " closed" if item.get("closed") else ""
        print(f"{notebook_id}\t{name}{closed}")
    return 0


def cmd_refresh(_args: argparse.Namespace, config: Config) -> int:
    client = get_working_client(config)
    result = refresh_index(client, config.root)
    print(f"Refreshed {result.document_count} documents from {result.notebook_count} notebooks.")
    print(f"Cache: {result.cache_dir}")
    return 0


def cmd_tree(_args: argparse.Namespace, config: Config) -> int:
    path = config.root / KB_CACHE_DIR / "tree.md"
    if not path.exists():
        print("kb_cache/tree.md does not exist. Run `python -m siyuan_kb refresh` first.", file=sys.stderr)
        return 1
    print(path.read_text(encoding="utf-8"), end="")
    return 0


def cmd_find(args: argparse.Namespace, config: Config) -> int:
    docs = load_docs(config.root)
    if not docs:
        print("No local index found. Run `python -m siyuan_kb refresh` first.", file=sys.stderr)
        return 1
    matches = find_documents(docs, args.keyword, limit=max(args.limit, 1))
    if not matches:
        print("No matching documents.")
        return 1
    print_document_candidates(matches)
    return 0


def cmd_read(args: argparse.Namespace, config: Config) -> int:
    docs = load_docs(config.root)
    status, matches = resolve_document(docs, args.locator)

    if status == "ambiguous":
        print("Locator matched multiple documents. Use one exact document id:", file=sys.stderr)
        print_document_candidates(matches, file=sys.stderr)
        return 1

    if status == "missing":
        print("No matching document in local index. Run `python -m siyuan_kb refresh` or use an exact id.", file=sys.stderr)
        return 1

    block_id = matches[0]["id"] if status == "ok" else args.locator
    client = get_working_client(config)
    print(client.export_markdown(block_id), end="")
    return 0


def get_working_client(config: Config) -> SiYuanClient:
    errors: list[str] = []
    for url in config.urls:
        client = SiYuanClient(url, token=config.token)
        try:
            client.version()
            return client
        except (SiYuanConnectionError, SiYuanApiError) as exc:
            errors.append(f"{url}: {exc}")
    raise SiYuanConnectionError("; ".join(errors) or "No SiYuan URLs configured")


def print_document_candidates(matches: list[dict[str, object]], *, file=sys.stdout) -> None:
    for doc in matches:
        tags = doc.get("tags") or []
        tag_text = f" tags:{','.join(str(tag) for tag in tags)}" if tags else ""
        print(
            f"{doc.get('id', '')}\t{doc.get('notebook_name', '')}\t{doc.get('hpath', '')}{tag_text}",
            file=file,
        )


def format_api_error(exc: SiYuanApiError) -> str:
    if exc.status in (401, 403) or "token" in str(exc).casefold():
        return f"SiYuan API token was rejected or is missing: {exc}"
    return f"SiYuan API error: {exc}"
