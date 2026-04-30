# Start Here For SiYuan Knowledge

This repository contains a private SiYuan knowledge-base adapter.

If you are an AI agent and the user asks you to use their notes, personal knowledge base, SiYuan, notebook, prior materials, writing archive, research archive, or project context, use the SiYuan knowledge workflow.

## Mandatory Startup

1. Do not scan the repository looking for note content.
2. Start with the MCP tool `siyuan_start` when available. It checks SiYuan and returns existing top-level guidance.
3. If MCP is unavailable, run `python -m source_code start` from this repository root.
4. Read the returned startup packet before using any other note content.
5. Use `knowledge_base/overview.md` to choose relevant notebooks.
6. Use `knowledge_base/notebooks/<notebook-id>.md` only for relevant notebook maps.
7. Read full documents only when needed. Prefer MCP `siyuan_read_document`.
8. For long or image-heavy documents, call `siyuan_describe_document_chunks`, then read specific chunks with `siyuan_read_document_chunk`.
9. Do not refresh/rebuild indexes unless the user asks, the index is missing, or the index is clearly stale.

## Safety Rules

- Do not modify SiYuan notes.
- Do not call SiYuan write APIs.
- Do not read `config.local.json` unless the user explicitly asks.
- Do not expose hidden notebook/document names from privacy files unless the user explicitly asks.
- Do not update `knowledge_base/guide.md` unless the user explicitly asks.
- Preserve mixed text/image context. Do not pull images out of a document without also reading nearby text.
