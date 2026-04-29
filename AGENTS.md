# Agent Instructions

This is a private, read-only adapter for using the owner's SiYuan notes as an AI knowledge base.

The owner usually does not use the command line directly. Treat CLI commands as agent/developer tools. Human-facing privacy changes are usually made by editing `siyuan.ignore.local.json`.

## Reading Order

1. Read `kb_cache/guide.md` first.
2. Read `kb_cache/tree.md` to inspect the note structure.
3. Use `python -m siyuan_kb find <keyword>` to locate candidate documents.
4. Use `python -m siyuan_kb read <doc-id>` when full document Markdown is needed.
5. Put derived analysis, task context, drafts, and outputs in `ai_workspace/`.
6. If the owner says they changed the SiYuan ignore file, run `python -m siyuan_kb refresh` before reading indexes.

## Hard Rules

- Do not modify SiYuan notes.
- Do not call SiYuan write APIs.
- Do not commit or print API tokens.
- Do not read `config.local.json`, `siyuan.ignore.local.json`, or `siyuan.allow.local.json` unless the user explicitly asks.
- Do not run `python -m siyuan_kb ignore allow ...` unless the user explicitly asks to temporarily open hidden notes.
- Do not expose hidden notebook/document names from local privacy files unless the user explicitly asks.
- Treat `kb_cache/` and `ai_workspace/` as private personal data.

## Useful Commands

```bash
python -m siyuan_kb doctor
python -m siyuan_kb notebooks
python -m siyuan_kb refresh
python -m siyuan_kb tree
python -m siyuan_kb find <keyword>
python -m siyuan_kb read <doc-id>
python -m siyuan_kb ignore status
```
