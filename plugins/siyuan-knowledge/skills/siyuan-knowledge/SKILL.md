---
name: siyuan-knowledge
description: Use when the user wants to read or search their private SiYuan notes (思源笔记). Triggers on mentions of 思源, 知识库, or when the agent needs personal context from the user's notes.
---

# SiYuan Knowledge

Access the user's private SiYuan knowledge base through MCP tools. Never scan the filesystem for note content.

Local project root: `D:\Github\siyuan-enhance`.

## Mandatory Startup

1. Call `siyuan_start` first. It refreshes the safe index and returns the startup packet: notebook overview table, index.md (if it exists), START_HERE.md, and guide.md.
2. Read the returned startup packet.
3. **Use index.md as your primary navigation map.** When it's included in the startup packet, its 快速导航 (quick navigation) table maps user-intent topics directly to notebooks. Use this before scanning the full notebook overview table. The per-notebook sections give structural summaries and AI-written descriptions — trust them to decide where to search.
4. **If index.md was not included**, the startup packet will include a hint that no navigation index exists. If the user's request involves broad exploration or you need to navigate many notebooks, suggest: "我可以先快速扫一遍你的笔记本结构，创建一个导航索引，之后每次新会话都能更快定位。"
5. Follow `knowledge_base/guide.md` for durable preferences.
6. Use the notebook overview table to identify relevant notebooks by scale (docs count, word count, recency).
7. Use `siyuan_list_documents` for one notebook's document tree.
8. Use `siyuan_read_document` when a document is worth deep reading. It always returns the outline (heading→chunk map). Long documents return one chunk at a time — use `chunk=0` for the first chunk or `chunk=N` to jump to a specific section.

If MCP tools are unavailable, tell the user the SiYuan knowledge MCP is not registered or not reachable. Do not scan local files for note content.

## Tool Use

- `siyuan_start`: refresh the safe index and return the startup packet: notebook overview table, index.md (AI-generated semantic navigation map, when it exists), START_HERE.md, and guide.md. Always call first.
- `index.md`: part of the startup packet returned by `siyuan_start`. It is an AI-generated navigation index with a 快速导航 (quick routing) table and per-notebook summaries. Use it as your primary navigation map. It may become stale between sessions — if it contradicts tree.md, tree.md wins. When index.md is absent, the startup packet suggests offering to create one.
- `siyuan_refresh_index`: refresh safe indexes only when the user explicitly asks for a mid-session refresh.
- `siyuan_list_notebooks`: list visible notebooks from the safe index.
- `siyuan_list_documents`: return the document tree for one notebook with word counts and update times.
- `siyuan_find_documents`: search the knowledge base. It uses the safe local index for titles, paths, tags, and notebook names, and live SiYuan search for block content when available. 4 modes — `keyword` (space-separated AND), `query` (AND/OR/NOT/`"phrase"`/`prefix*`), `regex`, `sql` (direct SQL, needs admin). Scope: `headings` (titles + headings) or `full` (all block text). Filter with `notebooks` parameter.
- `siyuan_read_document`: read a document as Markdown. Always returns the outline (heading→chunk mapping). Short docs (≤max_chars) return full text. Long docs return outline + one chunk — use `chunk=0` for the first chunk or `chunk=N` to jump to a specific chunk.
- `siyuan_propose_guide_update`: save a suggested guide improvement in `ai_workspace/` without modifying the guide.
- `siyuan_apply_guide_update`: update `knowledge_base/guide.md` only after explicit user approval.
- `siyuan_hide`: hide a notebook, document, or document subtree from the safe index. Requires `confirmed=true`. Persists across sessions.
- `siyuan_unhide`: remove a persistent hide rule and refresh the index. Requires `confirmed=true`.
- `siyuan_temporary_allow`: temporarily allow a hidden item to appear in searches. Takes `minutes` (default 60). Does not refresh the index.
- `siyuan_close_temporary_allow`: immediately clear all temporary allow rules. Hidden items are closed again.

## Safety Rules

- Do not modify SiYuan notes.
- Do not call SiYuan write APIs.
- Do not read `config.local.json` unless the user explicitly asks.
- Do not expose hidden notebook or document names unless the user explicitly asks.
- Do not scan all of `knowledge_base/tree.md` — use the notebook overview table from `siyuan_start`.
- Do not force long documents into one response — use the `chunk` parameter on `siyuan_read_document`.
- Put derived analysis and drafts in `ai_workspace/`.
- Always require `confirmed=true` for `siyuan_hide` and `siyuan_unhide`; never auto-confirm.
