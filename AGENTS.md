# Agent Instructions

This is a private, read-only adapter for using the owner's SiYuan notes as an AI knowledge base.

The owner usually does not use the command line directly. Treat CLI commands as agent/developer tools. Human-facing privacy changes are usually made by editing `siyuan.ignore.local.json`.

## Reading Order

1. Read `START_HERE.md` first.
2. Use MCP tool `siyuan_start` when available; it checks SiYuan and returns existing top-level guidance.
3. If MCP is unavailable, run `python -m source_code start`.
4. Read the startup packet before opening broad maps.
5. Use `knowledge_base/overview.md` to choose relevant notebooks.
6. Use `knowledge_base/notebooks/<notebook-id>.md` only for relevant notebooks.
7. Use `python -m source_code read <doc-id>` when full document Markdown is needed.
8. Put derived analysis, task context, drafts, and outputs in `ai_workspace/`.

## Hard Rules

- Do not modify SiYuan notes.
- Do not call SiYuan write APIs.
- Do not commit or print API tokens.
- Do not read `config.local.json`, `siyuan.ignore.local.json`, or `siyuan.allow.local.json` unless the user explicitly asks.
- Do not run `python -m source_code ignore allow ...` unless the user explicitly asks to temporarily open hidden notes.
- Do not expose hidden notebook/document names from local privacy files unless the user explicitly asks.
- Treat `knowledge_base/` and `ai_workspace/` as private personal data.
- Do not scan all of `knowledge_base/tree.md` by default.
- Do not refresh or rebuild indexes unless the user asks, the index is missing, or it is clearly stale.

## Useful Commands

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
