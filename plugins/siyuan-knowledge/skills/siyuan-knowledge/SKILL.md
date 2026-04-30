---
name: siyuan-knowledge
description: Use when the user asks to read, search, consult, or update their private SiYuan notes, notebook, personal knowledge base, prior materials, writing archive, research archive, or project context. Triggers when the agent needs durable personal context from SiYuan or when the user mentions 思源, 笔记本, 知识库, 笔记, 资料, 旧文档, previous notes, or prior materials.
---

# SiYuan Knowledge

Use the private SiYuan knowledge base through the MCP tools. Do not improvise a file scan.

Local project root: `D:\Github\siyuan-enhance`.

## Mandatory Startup

1. Call `siyuan_start` first. It checks SiYuan and returns existing top-level guidance; it does not refresh indexes.
2. Read the returned startup packet.
3. Follow `knowledge_base/guide.md` before opening notebook maps.
4. Use `knowledge_base/overview.md` to choose relevant notebooks.
5. Use `siyuan_list_documents` only for relevant notebooks.
6. Use `siyuan_read_document` only when a specific document is worth deep reading.
7. For long or image-heavy documents, use `siyuan_describe_document_chunks` first, then read only the needed chunks with `siyuan_read_document_chunk`.

If MCP tools are unavailable, use the fallback command from the repository root:

```bash
python -m source_code start
```

If the current working directory is not the local project root, run the fallback from `D:\Github\siyuan-enhance`.

## Tool Use

- `siyuan_start`: check SiYuan connectivity and return the startup packet. Always call first.
- `siyuan_refresh_index`: refresh safe indexes only when the user asks, the index is missing, or the index is clearly stale.
- `siyuan_list_notebooks`: list visible notebooks from the safe index.
- `siyuan_list_documents`: read an existing notebook map; do not rescan SiYuan.
- `siyuan_find_documents`: find candidate visible documents by keyword.
- `siyuan_read_document`: read a selected visible document as Markdown preview; long documents are chunked to avoid truncation.
- `siyuan_describe_document_chunks`: inspect a long document's chunk map before deep reading. Default chunk size is 10,000 characters; adjust with `max_chars` when needed.
- `siyuan_read_document_chunk`: read one numbered chunk while preserving text and image references in context.
- `siyuan_propose_guide_update`: save a suggested guide improvement without changing the guide.
- `siyuan_apply_guide_update`: update `knowledge_base/guide.md` only after explicit user approval.

## Safety Rules

- Do not modify SiYuan notes.
- Do not call SiYuan write APIs.
- Do not read `config.local.json` unless the user explicitly asks.
- Do not expose hidden notebook or document names from privacy files unless the user explicitly asks.
- Do not scan all of `knowledge_base/tree.md` by default. Use overview and notebook maps first.
- Do not refresh or rebuild maps by default.
- Do not force long documents into one response. Use chunk tools to avoid MCP/client truncation.
- Preserve mixed text/image context. If a chunk contains image references, read the surrounding text with the image reference.
- Put derived analysis and drafts in `ai_workspace/`.
