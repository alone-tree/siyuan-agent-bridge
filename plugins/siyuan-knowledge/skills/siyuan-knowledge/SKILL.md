---
name: siyuan-knowledge
description: Use when the user asks to read, search, consult, or update their private SiYuan notes, notebook, personal knowledge base, prior materials, writing archive, research archive, or project context. Triggers when the agent needs durable personal context from SiYuan or when the user mentions 思源, 笔记本, 知识库, 笔记, 资料, 旧文档, or previous notes.
---

# SiYuan Knowledge

Use the private SiYuan knowledge base through the MCP tools. Do not improvise a file scan.

## Mandatory Startup

1. Call `siyuan_start` first. It checks SiYuan and returns existing top-level guidance; it does not refresh indexes.
2. Read the returned startup packet.
3. Follow `knowledge_base/guide.md` before opening notebook maps.
4. Use `knowledge_base/overview.md` to choose relevant notebooks.
5. Use `siyuan_list_documents` only for relevant notebooks.
6. Use `siyuan_read_document` only when a specific document is worth deep reading.

If MCP tools are unavailable, use the fallback command from the repository root:

```bash
python -m source_code start
```

## Tool Use

- `siyuan_start`: check SiYuan connectivity and return the startup packet. Always call first.
- `siyuan_refresh_index`: refresh safe indexes only when the user asks, the index is missing, or the index is clearly stale.
- `siyuan_list_notebooks`: list visible notebooks from the safe index.
- `siyuan_list_documents`: read an existing notebook map; do not rescan SiYuan.
- `siyuan_find_documents`: find candidate visible documents by keyword.
- `siyuan_read_document`: read a selected visible document as Markdown.
- `siyuan_propose_guide_update`: save a suggested guide improvement without changing the guide.
- `siyuan_apply_guide_update`: update `knowledge_base/guide.md` only after explicit user approval.

## Safety Rules

- Do not modify SiYuan notes.
- Do not call SiYuan write APIs.
- Do not read `config.local.json` unless the user explicitly asks.
- Do not expose hidden notebook or document names from privacy files unless the user explicitly asks.
- Do not scan all of `knowledge_base/tree.md` by default. Use overview and notebook maps first.
- Do not refresh or rebuild maps by default.
- Put derived analysis and drafts in `ai_workspace/`.
