# Start Here For SiYuan Knowledge

This repository contains a private SiYuan knowledge-base adapter.

If you are an AI agent and the user asks you to use their notes, personal knowledge base, SiYuan, notebook, prior materials, writing archive, research archive, or project context, use the SiYuan knowledge workflow.

## Mandatory Startup

1. Do not scan the repository looking for note content.
2. Start with the MCP tool `siyuan_start`. It refreshes the safe index and returns the notebook overview table, index.md (when it exists), START_HERE.md, and guide.md.
3. If MCP is unavailable, tell the user the SiYuan knowledge MCP is not registered or not reachable. Do not fall back to scanning files.
4. Read the returned startup packet before using any other note content.
5. Use the notebook overview table from `siyuan_start` to choose relevant notebooks.
6. Use `siyuan_list` (with `notebook_id`) for one notebook's document tree.
7. Read full documents only when needed. Prefer MCP `siyuan_read_document`. The tool always returns the outline; long documents return one chunk at a time. Use `chunk=0` for the first chunk or `chunk=N` to jump to a specific chunk.
8. Use `siyuan_refresh_index` mid-session only when the user explicitly asks to refresh.

## Safety Rules

- Do not modify SiYuan notes.
- Do not call SiYuan write APIs.
- Do not read `config.local.json` unless the user explicitly asks.
- Do not expose hidden notebook/document names from privacy files unless the user explicitly asks.
- Do not update `knowledge_base/guide.md` unless the user explicitly asks.
- Preserve mixed text/image context. Do not pull images out of a document without also reading nearby text.
