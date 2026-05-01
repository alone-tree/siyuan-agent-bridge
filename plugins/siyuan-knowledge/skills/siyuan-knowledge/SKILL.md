---
name: siyuan-knowledge
description: Use when the user wants to read or search their private SiYuan notes (思源笔记). Triggers on mentions of 思源, 知识库, or when the agent needs personal context from the user's notes.
---

# SiYuan Knowledge

Access the user's private SiYuan knowledge base through MCP tools. Never scan the filesystem for note content.

Local project root: `D:\Github\siyuan-enhance`.

## Mandatory Startup

1. Call `siyuan_start` first. It refreshes the safe index and returns the notebook overview table, START_HERE.md, and guide.md.
2. Read the returned startup packet.
3. Follow `knowledge_base/guide.md` for durable preferences.
4. Use the notebook overview table to choose relevant notebooks.
5. Use `siyuan_list_documents` for the notebook's document tree.
6. Use `siyuan_read_document` when a document is worth deep reading. It always returns the outline (heading→chunk map). Long documents return one chunk at a time — use `chunk=0` for the first chunk or `chunk=N` to jump to a specific section.

If MCP tools are unavailable, run the fallback from the repository root:

```bash
python -m source_code start
```

## Tool Use

- `siyuan_start`: refresh the safe index and return the startup packet with notebook overview table, START_HERE.md, and guide.md. Always call first.
- `siyuan_refresh_index`: refresh safe indexes only when the user explicitly asks for a mid-session refresh.
- `siyuan_list_notebooks`: list visible notebooks from the safe index.
- `siyuan_list_documents`: return the document tree for one notebook with word counts and update times.
- `siyuan_find_documents`: search the knowledge base. 4 modes — `keyword` (space-separated AND), `query` (FTS5 AND/OR/NOT/`"phrase"`/`prefix*`), `regex` (Go RE2), `sql` (direct SQL, needs admin). Scope: `headings` (titles + headings) or `full` (all block text). Filter with `notebooks` parameter.
- `siyuan_read_document`: read a document as Markdown. Always returns the outline (heading→chunk mapping). Short docs (≤max_chars) return full text. Long docs return outline + one chunk — use `chunk=0` for the first chunk or `chunk=N` to jump to a specific chunk.
- `siyuan_propose_guide_update`: save a suggested guide improvement in `ai_workspace/` without modifying the guide.
- `siyuan_apply_guide_update`: update `knowledge_base/guide.md` only after explicit user approval.

## Safety Rules

- Do not modify SiYuan notes.
- Do not call SiYuan write APIs.
- Do not read `config.local.json` unless the user explicitly asks.
- Do not expose hidden notebook or document names unless the user explicitly asks.
- Do not scan all of `knowledge_base/tree.md` — use the notebook overview table from `siyuan_start`.
- Do not force long documents into one response — use the `chunk` parameter on `siyuan_read_document`.
- Put derived analysis and drafts in `ai_workspace/`.
