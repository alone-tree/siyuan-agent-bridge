from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from .client import SiYuanApiError, SiYuanClient, SiYuanConnectionError
from .config import Config, load_config
from .ignore import (
    IGNORE_FILE,
    add_persistent_ignore,
    close_temporary_allow,
    filter_documents,
    filter_notebooks,
    initialize_ignore_files,
    load_privacy_rules,
    load_temporary_allow,
    make_temporary_allow,
    make_privacy_rule,
    remove_persistent_ignore,
    write_temporary_allow,
)
from .indexer import (
    DOCS_SQL,
    KNOWLEDGE_BASE_DIR,
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

    refresh = sub.add_parser("refresh", help="Refresh local knowledge-base indexes.")
    refresh.set_defaults(func=cmd_refresh)

    tree = sub.add_parser("tree", help="Print knowledge_base/tree.md.")
    tree.set_defaults(func=cmd_tree)

    find = sub.add_parser("find", help="Find documents by title, path, notebook, tag, or id.")
    find.add_argument("keyword")
    find.add_argument("--limit", type=int, default=20)
    find.set_defaults(func=cmd_find)

    read = sub.add_parser("read", help="Read one SiYuan document as Markdown.")
    read.add_argument("locator", help="Document id, exact hpath, title, or unique partial match.")
    read.set_defaults(func=cmd_read)

    hide = sub.add_parser("hide", help="Hide a notebook, document, or document subtree, then refresh indexes.")
    hide.add_argument("scope", choices=("notebook", "document", "subtree"))
    hide.add_argument("locator", help="Notebook name/id, document id, exact hpath, title, or unique partial match.")
    hide.add_argument("--reason", default="")
    hide.set_defaults(func=cmd_hide)

    unhide = sub.add_parser("unhide", help="Remove a persistent hide rule, then refresh indexes.")
    unhide.add_argument("scope", choices=("notebook", "document", "subtree"))
    unhide.add_argument("locator", help="Notebook name/id, document id, exact hpath, title, or unique partial match.")
    unhide.set_defaults(func=cmd_unhide)

    allow = sub.add_parser("allow", help="Temporarily allow a hidden notebook, document, or subtree.")
    allow.add_argument("scope", choices=("notebook", "document", "subtree"))
    allow.add_argument("locator", help="Notebook name/id, document id, exact hpath, title, or unique partial match.")
    allow.add_argument("--minutes", type=int, default=60)
    allow.add_argument("--reason", default="")
    allow.set_defaults(func=cmd_allow)

    ignore = sub.add_parser("ignore", help="Manage local privacy ignore and temporary allow rules.")
    ignore_sub = ignore.add_subparsers(dest="ignore_command", required=True)

    ignore_init = ignore_sub.add_parser("init", help="Create local ignore files if missing.")
    ignore_init.set_defaults(func=cmd_ignore_init)

    ignore_status = ignore_sub.add_parser("status", help="Show ignore and temporary allow status.")
    ignore_status.add_argument("--verbose", action="store_true", help="Print rule details.")
    ignore_status.set_defaults(func=cmd_ignore_status)

    ignore_allow = ignore_sub.add_parser("allow", help="Temporarily allow an ignored notebook/document/subtree.")
    ignore_allow.add_argument("locator", help="Notebook id, document id, exact hpath, title, or unique partial match.")
    ignore_allow.add_argument("--scope", choices=("notebook", "document", "subtree"), default="document")
    ignore_allow.add_argument("--minutes", type=int, default=60)
    ignore_allow.add_argument("--reason", default="")
    ignore_allow.set_defaults(func=cmd_ignore_allow)

    ignore_close = ignore_sub.add_parser("close", help="Clear all temporary allow rules immediately.")
    ignore_close.set_defaults(func=cmd_ignore_close)

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
    print(
        "Scanned "
        f"{result.total_document_count} documents from {result.total_notebook_count} notebooks. "
        f"Visible: {result.document_count} documents from {result.notebook_count} notebooks. "
        f"Hidden: {result.hidden_document_count} documents from {result.hidden_notebook_count} notebooks."
    )
    print(f"Cache: {result.cache_dir}")
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
    if privacy.allow:
        client = get_working_client(config)
        docs = filter_documents(load_live_docs(client), privacy)
    else:
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
        client = get_working_client(config)
        privacy = load_privacy_rules(config.root)
        if privacy.allow:
            live_docs = filter_documents(load_live_docs(client), privacy)
            status, matches = resolve_document(live_docs, args.locator)
        if status in ("missing", "no_index"):
            print(
                "No matching visible document. It may be hidden by ignore, not indexed, or the locator is wrong.",
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


def cmd_ignore_init(_args: argparse.Namespace, config: Config) -> int:
    created, local_path, example_path = initialize_ignore_files(config.root)
    state = "Created" if created else "Already exists"
    print(f"{state}: {local_path}")
    print(f"Example: {example_path}")
    print("After editing ignore rules, run `python -m source_code refresh`.")
    return 0


def cmd_ignore_status(args: argparse.Namespace, config: Config) -> int:
    privacy = load_privacy_rules(config.root)
    all_temp = load_temporary_allow(config.root)
    active_temp = [rule for rule in all_temp if rule in privacy.allow]
    expired_temp = len(all_temp) - len(active_temp)
    print(f"Ignore file: {config.root / IGNORE_FILE}")
    print(f"Persistent ignore rules: {len(privacy.ignore)}")
    print(f"Active temporary allow rules: {len(active_temp)}")
    print(f"Expired temporary allow rules: {expired_temp}")
    if args.verbose:
        print("")
        print("Persistent ignore:")
        print_rule_list(privacy.ignore)
        print("")
        print("Active temporary allow:")
        print_rule_list(active_temp)
    return 0


def cmd_ignore_allow(args: argparse.Namespace, config: Config) -> int:
    return add_temporary_allow(args.scope, args.locator, args.minutes, args.reason, config)


def cmd_allow(args: argparse.Namespace, config: Config) -> int:
    return add_temporary_allow(args.scope, args.locator, args.minutes, args.reason, config)


def add_temporary_allow(scope: str, locator: str, minutes: int, reason: str, config: Config) -> int:
    if minutes <= 0:
        raise ValueError("--minutes must be greater than 0")

    client = get_working_client(config)
    resolved = resolve_privacy_locator(client, scope, locator)
    rule = make_temporary_allow(
        scope,
        locator,
        minutes=minutes,
        reason=reason,
        resolved=resolved,
    )
    existing = load_temporary_allow(config.root)
    existing.append(rule)
    write_temporary_allow(config.root, existing)
    print(f"Temporary allow added for {scope}. Expires in {minutes} minutes.")
    print("This does not rewrite knowledge_base. The item will be hidden again automatically after expiry.")
    return 0


def cmd_ignore_close(_args: argparse.Namespace, config: Config) -> int:
    count = close_temporary_allow(config.root)
    print(f"Cleared {count} temporary allow rule(s). Hidden items are closed again.")
    return 0


def cmd_hide(args: argparse.Namespace, config: Config) -> int:
    initialize_ignore_files(config.root)
    client = get_working_client(config)
    resolved = resolve_privacy_locator(client, args.scope, args.locator)
    rule = make_privacy_rule(args.scope, args.locator, reason=args.reason, resolved=resolved)
    added = add_persistent_ignore(config.root, rule)
    if added:
        print(f"Added hide rule for {args.scope}: {describe_rule(rule)}")
    else:
        print(f"Hide rule already exists for {args.scope}: {describe_rule(rule)}")
    result = refresh_index(client, config.root)
    print(
        f"Refreshed safe index. Visible: {result.document_count}/{result.total_document_count} documents. "
        f"Hidden: {result.hidden_document_count}."
    )
    return 0


def cmd_unhide(args: argparse.Namespace, config: Config) -> int:
    client = get_working_client(config)
    resolved = resolve_privacy_locator(client, args.scope, args.locator)
    rule = make_privacy_rule(args.scope, args.locator, resolved=resolved)
    removed = remove_persistent_ignore(config.root, rule)
    if removed:
        print(f"Removed {removed} hide rule(s) for {args.scope}: {describe_rule(rule)}")
    else:
        print(f"No matching hide rule found for {args.scope}: {describe_rule(rule)}")
    result = refresh_index(client, config.root)
    print(
        f"Refreshed safe index. Visible: {result.document_count}/{result.total_document_count} documents. "
        f"Hidden: {result.hidden_document_count}."
    )
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


def load_live_docs(client: SiYuanClient) -> list[dict[str, object]]:
    notebooks = client.list_notebooks()
    return normalize_documents(client.query_sql(DOCS_SQL), notebooks)


def resolve_privacy_locator(client: SiYuanClient, scope: str, locator: str) -> dict[str, object] | None:
    if scope == "notebook":
        notebooks = client.list_notebooks()
        matches = [item for item in notebooks if str(item.get("id", "")) == locator]
        if not matches:
            matches = [item for item in notebooks if str(item.get("name", "")).casefold() == locator.casefold()]
        if not matches:
            matches = [item for item in notebooks if locator.casefold() in str(item.get("name", "")).casefold()]
        if len(matches) > 1:
            print("Locator matched multiple notebooks. Use the exact notebook id or full name:", file=sys.stderr)
            for notebook in matches:
                print(f"{notebook.get('id', '')}\t{notebook.get('name', '')}", file=sys.stderr)
            raise ValueError("Notebook locator is ambiguous")
        if matches:
            notebook = matches[0]
            return {
                "id": notebook.get("id"),
                "notebook_id": notebook.get("id"),
                "notebook_name": notebook.get("name"),
                "title": notebook.get("name"),
            }
        raise ValueError(f"No notebook matched: {locator}")

    docs = load_live_docs(client)
    status, matches = resolve_document(docs, locator)
    if status == "ambiguous":
        print("Locator matched multiple live documents. Use one exact document id:", file=sys.stderr)
        print_document_candidates(matches, file=sys.stderr)
        raise ValueError("Temporary allow locator is ambiguous")
    if status == "ok":
        return matches[0]
    raise ValueError(f"No document matched: {locator}")


def print_document_candidates(matches: list[dict[str, object]], *, file=sys.stdout) -> None:
    for doc in matches:
        tags = doc.get("tags") or []
        tag_text = f" tags:{','.join(str(tag) for tag in tags)}" if tags else ""
        print(
            f"{doc.get('id', '')}\t{doc.get('notebook_name', '')}\t{doc.get('hpath', '')}{tag_text}",
            file=file,
        )


def print_rule_list(rules: list[dict[str, object]]) -> None:
    if not rules:
        print("- none")
        return
    for rule in rules:
        scope = rule.get("scope") or rule.get("type") or "unknown"
        target = rule.get("id") or rule.get("hpath") or rule.get("notebook_id") or rule.get("name") or "unknown"
        expires = f" expires:{rule.get('expires_at')}" if rule.get("expires_at") else ""
        print(f"- {scope}: {target}{expires}")


def describe_rule(rule: dict[str, object]) -> str:
    return str(rule.get("name") or rule.get("title") or rule.get("hpath") or rule.get("id") or rule.get("notebook_id") or "unknown")


def format_api_error(exc: SiYuanApiError) -> str:
    if exc.status in (401, 403) or "token" in str(exc).casefold():
        return f"SiYuan API token was rejected or is missing: {exc}"
    return f"SiYuan API error: {exc}"
