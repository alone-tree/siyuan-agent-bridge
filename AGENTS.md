# Agent Instructions

This is a private, read-only adapter for using the owner's SiYuan notes as an AI knowledge base.

The product interface is MCP + Skill. Treat CLI commands as developer diagnostics only. Human-facing privacy changes are usually made by editing `siyuan.ignore.local.json`.

## Reading Order

1. Read `START_HERE.md` first.
2. Use MCP tool `siyuan_start`; it refreshes the safe index and returns the notebook overview table, START_HERE.md, and guide.md.
3. If MCP is unavailable, tell the user the SiYuan knowledge MCP is not registered or not reachable.
4. Read the startup packet before opening broad maps.
5. Use the notebook overview table from `siyuan_start` to choose relevant notebooks.
6. Use `siyuan_list` (with `notebook_id`) for one notebook's document tree.
7. Use MCP `siyuan_read_document` when full document Markdown is needed. The tool always returns the outline; long documents return one chunk at a time. Use `chunk=0` for the first chunk or `chunk=N` to jump to a specific chunk.
9. Put derived analysis, task context, drafts, and outputs in `ai_workspace/`.

## Hard Rules

- Do not modify SiYuan notes.
- Do not call SiYuan write APIs.
- Do not commit or print API tokens.
- Do not read `config.local.json`, `siyuan.ignore.local.json`, or `siyuan.allow.local.json` unless the user explicitly asks.
- Do not run `python -m source_code ignore allow ...` unless the user explicitly asks to temporarily open hidden notes.
- Do not expose hidden notebook/document names from local privacy files unless the user explicitly asks.
- Treat `knowledge_base/` and `ai_workspace/` as private personal data.
- Do not scan all of `knowledge_base/tree.md` by default.
- Do not refresh or rebuild indexes mid-session unless the user explicitly asks. `siyuan_start` already refreshes on startup.
- Do not force long documents into one response. Use the `chunk` parameter on `siyuan_read_document` to avoid MCP/client truncation.

## Developer Diagnostic Commands

```bash
python -m source_code doctor
python -m source_code notebooks
python -m source_code start
python -m source_code refresh
python -m source_code tree
python -m source_code find <keyword>
python -m source_code read <doc-id>
python -m source_code ignore status
```

## MCP Tools

- `siyuan_start`: refresh the safe index and return the startup packet with notebook overview table, START_HERE.md, and guide.md. Always call first.
- `siyuan_refresh_index`: explicit mid-session index refresh (siyuan_start already refreshes on startup).
- `siyuan_list`: list visible notebooks (no args) or document tree for one notebook (with `notebook_id`), includes word counts and update times.
- `siyuan_find_documents`: search safe-index titles/paths/tags plus live SiYuan block content when available, with 4 modes (`keyword`/`query`/`regex`/`sql`), 2 scopes (`headings`/`full`), optional notebook filter.
- `siyuan_read_document`: read a document with outline (heading→chunk mapping). Short docs return full text; long docs return one chunk at a time via `chunk` parameter.
- `siyuan_propose_guide_update`: save proposed guide changes in `ai_workspace/`.
- `siyuan_apply_guide_update`: update `knowledge_base/guide.md` only after explicit user approval.
