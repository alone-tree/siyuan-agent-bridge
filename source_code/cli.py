from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Sequence

from .client import SiYuanApiError, SiYuanClient, SiYuanConnectionError
from .config import DEFAULT_URLS, Config, Profile, detect_active_profile, load_config
from .ignore import (
    filter_documents,
    filter_notebooks,
    load_privacy_rules,
)
from .indexer import (
    DOCS_SQL,
    KNOWLEDGE_BASE_DIR,
    build_notebook_overview,
    find_documents,
    load_docs,
    normalize_documents,
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
        prog="python -m source_code",
        description="Private read-only adapter for using SiYuan as an AI knowledge base.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Check SiYuan API connectivity.")
    doctor.set_defaults(func=cmd_doctor)

    notebooks = sub.add_parser("notebooks", help="List SiYuan notebooks.")
    notebooks.set_defaults(func=cmd_notebooks)

    start = sub.add_parser("start", help="Check SiYuan and print the AI startup packet without refreshing indexes.")
    start.set_defaults(func=cmd_start)

    refresh = sub.add_parser("refresh", help="Refresh local knowledge-base indexes.")
    refresh.set_defaults(func=cmd_refresh)

    backup = sub.add_parser("backup", help="Create a SiYuan workspace snapshot.")
    backup.add_argument("--memo", default="")
    backup.add_argument("--tag", action="append", default=[])
    backup.set_defaults(func=cmd_backup)

    snapshots = sub.add_parser("snapshots", help="List recent SiYuan workspace snapshots.")
    snapshots.add_argument("--page", type=int, default=1)
    snapshots.add_argument("--limit", type=int, default=10)
    snapshots.set_defaults(func=cmd_snapshots)

    tree = sub.add_parser("tree", help="Print knowledge_base/tree.md.")
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
    if not config.profiles:
        print("No profiles or siyuan_token found in config.local.json.")
        print("Trying without a token in case SiYuan auth is disabled.")
        client = SiYuanClient(DEFAULT_URLS[0], timeout=3.0)
        try:
            version = client.version()
        except (SiYuanConnectionError, SiYuanApiError) as exc:
            print(f"[fail] {DEFAULT_URLS[0]}: {exc}")
            return 1
        print(f"[ok] {DEFAULT_URLS[0]} SiYuan version: {version}")
        return 0

    for profile in config.profiles:
        for url in DEFAULT_URLS:
            client = SiYuanClient(url, token=profile.token, timeout=3.0)
            try:
                version = client.version()
            except SiYuanConnectionError as exc:
                print(f"[fail] {profile.name} ({url}): connection failed: {exc}")
                continue
            except SiYuanApiError as exc:
                if exc.status in (401, 403) or "token" in str(exc).casefold():
                    print(f"[fail] {profile.name} ({url}): token rejected: {exc}")
                else:
                    print(f"[fail] {profile.name} ({url}): API error: {exc}")
                continue

            print(f"[ok] {profile.name} ({url}) SiYuan version: {version}")
            return 0

    print("No configured SiYuan workspace responded.", file=sys.stderr)
    return 1


def cmd_notebooks(_args: argparse.Namespace, config: Config) -> int:
    client = get_working_client(config)
    notebooks = filter_notebooks(client.list_notebooks(), load_privacy_rules(config.root))
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
    print(format_refresh_summary(result))
    print(f"Cache: {result.cache_dir}")
    return 0


def cmd_backup(args: argparse.Namespace, config: Config) -> int:
    _profile, client = detect_active_profile(config)
    memo = args.memo.strip() or f"siyuan-agent-bridge manual backup {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    snapshot = client.create_snapshot(memo)
    print("Created SiYuan workspace snapshot.")
    print(f"Endpoint: {client.base_url}")
    print(f"Snapshot ID: {snapshot.get('id', '')}")
    print(f"Created: {snapshot.get('created', '')}")
    print(f"Memo: {memo}")
    return 0


def cmd_snapshots(args: argparse.Namespace, config: Config) -> int:
    if args.page <= 0:
        raise ValueError("--page must be greater than 0")
    if args.limit <= 0:
        raise ValueError("--limit must be greater than 0")
    client = get_working_client(config)
    data = client.get_repo_snapshots(page=args.page)
    snapshots = data.get("snapshots", [])
    if not isinstance(snapshots, list):
        raise SiYuanApiError("Unexpected repo snapshots list shape")
    print(f"Endpoint: {client.base_url}")
    print(f"Snapshots page {args.page} | total: {data.get('totalCount', '')} | pages: {data.get('pageCount', '')}")
    for item in snapshots[: args.limit]:
        if not isinstance(item, dict):
            continue
        print(
            f"{item.get('id', '')}\t{item.get('hCreated') or item.get('created', '')}\t"
            f"{item.get('hSize') or item.get('size', '')}\t{item.get('memo', '')}\t{item.get('tag', '')}"
        )
    return 0


def cmd_start(_args: argparse.Namespace, config: Config) -> int:
    profile, client = detect_active_profile(config)
    refresh_index(client, config.root)
    version = client.version()
    print(render_start_packet(config.root, profile.name, version))
    return 0


def cmd_tree(_args: argparse.Namespace, config: Config) -> int:
    path = config.root / KNOWLEDGE_BASE_DIR / "tree.md"
    if not path.exists():
        print("knowledge_base/tree.md does not exist. Run `python -m source_code refresh` first.", file=sys.stderr)
        return 1
    print(path.read_text(encoding="utf-8"), end="")
    return 0


def cmd_find(args: argparse.Namespace, config: Config) -> int:
    docs = load_docs(config.root)
    privacy = load_privacy_rules(config.root)
    docs = filter_documents(docs, privacy)
    if not docs:
        print("No local index found. Run `python -m source_code refresh` first.", file=sys.stderr)
        return 1
    matches = find_documents(docs, args.keyword, limit=max(args.limit, 1))
    if not matches:
        print("No matching documents.")
        return 1
    print_document_candidates(matches)
    return 0


def cmd_read(args: argparse.Namespace, config: Config) -> int:
    docs = filter_documents(load_docs(config.root), load_privacy_rules(config.root))
    status, matches = resolve_document(docs, args.locator)

    if status in ("missing", "no_index"):
        print(
            "No matching visible document. It may be hidden, not indexed, or the locator is wrong.",
            file=sys.stderr,
        )
        return 1

    if status == "ambiguous":
        print("Locator matched multiple documents. Use one exact document id:", file=sys.stderr)
        print_document_candidates(matches, file=sys.stderr)
        return 1

    block_id = matches[0]["id"] if status == "ok" else args.locator
    client = get_working_client(config)
    print(client.export_markdown(block_id), end="")
    return 0


def get_working_client(config: Config) -> SiYuanClient:
    _profile, client = detect_active_profile(config)
    return client


def load_live_docs(client: SiYuanClient) -> list[dict[str, object]]:
    notebooks = client.list_notebooks()
    return normalize_documents(client.query_sql(DOCS_SQL), notebooks)


def print_document_candidates(matches: list[dict[str, object]], *, file=sys.stdout) -> None:
    for doc in matches:
        tags = doc.get("tags") or []
        tag_text = f" tags:{','.join(str(tag) for tag in tags)}" if tags else ""
        print(
            f"{doc.get('id', '')}\t{doc.get('notebook_name', '')}\t{doc.get('hpath', '')}{tag_text}",
            file=file,
        )


def format_refresh_summary(result: object) -> str:
    return (
        "Scanned "
        f"{result.total_document_count} documents from {result.total_notebook_count} notebooks. "
        f"Visible: {result.document_count} documents from {result.notebook_count} notebooks. "
        f"Hidden: {result.hidden_document_count} documents from {result.hidden_notebook_count} notebooks."
    )


def render_start_packet(root: Path, profile_name: str, version: str) -> str:
    base = root / KNOWLEDGE_BASE_DIR
    start_here = read_optional_text(root / "START_HERE.md")
    guide = read_optional_text(base / "guide.md")
    index_md = read_optional_text(base / "index.md")
    overview = build_notebook_overview(root)
    parts: list[str] = [
        "# 思源桥启动包",
        "",
        f"思源连接：正常，版本 {version}",
        f"已连接工作空间：{profile_name}",
        "",
        overview,
    ]
    if index_md:
        parts.extend([
            "",
            "## 语义索引 (index.md)",
            "",
            index_md.strip(),
        ])
    else:
        parts.extend([
            "",
            "> 当前没有导航索引。如果你希望 AI 更快速地定位到相关内容，可以告诉 AI 先快速扫一遍我的笔记本结构，创建一个导航索引。之后每次新会话启动，AI 都能直接拿到这份导航。",
        ])
    parts.extend([
        "",
        "## 启动流程",
        "",
        "1. 先使用本启动包。",
        "2. 如果上面提供了 index.md，使用其快速导航表定位相关笔记本。",
        "3. 遵循 `knowledge_base/guide.md` 中的持久偏好。",
        "4. 使用笔记本概览表选择相关笔记本。",
        "5. 使用 `siyuan_list`（带 `notebook_id`）查看单个笔记本的文档树。",
        "6. 使用 `siyuan_read_document` 阅读文档。",
        "7. 仅在用户明确要求刷新时，使用 `siyuan_refresh_index` 刷新。",
        "",
        "## 从这里开始",
        "",
        start_here.strip() if start_here else "（缺少 START_HERE.md）",
        "",
        "## 指南",
        "",
        guide.strip() if guide else "（缺少 guide.md）",
        "",
    ])
    return "\n".join(parts)


def read_optional_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def format_api_error(exc: SiYuanApiError) -> str:
    if exc.status in (401, 403) or "token" in str(exc).casefold():
        return f"SiYuan API token was rejected or is missing: {exc}"
    return f"SiYuan API error: {exc}"
