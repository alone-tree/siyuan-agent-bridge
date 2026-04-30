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
7. Use MCP `siyuan_read_document` when full document Markdown is needed.
8. For long or image-heavy documents, use `siyuan_describe_document_chunks` first, then `siyuan_read_document_chunk`.
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
- Do not refresh or rebuild indexes unless the user asks, the index is missing, or it is clearly stale.
- Do not force long documents into one response. Use chunk tools to avoid MCP/client truncation.
- Preserve mixed text/image context. If a chunk contains image references, read the surrounding text with the image reference.

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

## MCP Tools

- `siyuan_start`: startup packet and connectivity check.
- `siyuan_refresh_index`: explicit safe index refresh.
- `siyuan_list_notebooks`: visible notebooks from the safe index.
- `siyuan_list_documents`: existing notebook map.
- `siyuan_find_documents`: keyword search over visible document metadata.
- `siyuan_read_document`: document preview; long documents return chunk guidance.
- `siyuan_describe_document_chunks`: chunk map for long documents.
- `siyuan_read_document_chunk`: one numbered chunk, preserving text and image references.
- `siyuan_propose_guide_update`: save proposed guide changes in `ai_workspace/`.
- `siyuan_apply_guide_update`: update `knowledge_base/guide.md` only after explicit user approval.
