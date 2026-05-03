# SiYuan Agent Bridge

[中文说明](README.md)

SiYuan Agent Bridge is a private, local-first adapter that lets external AI agents use your SiYuan notes as a structured personal knowledge base, with write support on explicit user confirmation.

It is not a SiYuan plugin, not a public package, and not a vector-search system. Your notes stay in SiYuan. This project creates safe indexes and exposes them to AI agents through MCP tools and a Skill workflow.

## Current Capabilities

- Scans SiYuan notebooks and the full document tree, including child documents. Closed notebooks are automatically opened during scan and restored afterwards. The core design rationale: closing a notebook reflects human convenience, not data importance.
- Privacy rules are fully maintained by the user in the SiYuan system notebook `思源代理桥` / `SiYuan Agent Bridge` via the `隐私规则` / `Privacy Rules` document using Markdown tables. Supports hiding entire notebooks (by ID or name), single documents, or document subtrees. AI cannot read, search, or edit the Privacy Rules document.
- After editing the Privacy Rules document, tell the AI "refresh" to apply changes. To temporarily allow hidden content, change the `Hide` column to `no`, then back to `yes` when done.
- Generates safe indexes under `knowledge_base/`, all data filtered through privacy rules.
- Computes block counts and character counts for visible documents, so agents can use document scale as an importance signal.
- Provides 9 MCP tools for Claude Code, Codex, and similar agents to read and write SiYuan content within safe index boundaries.
- Paginates long documents by display block windows with `block_limit` and `token_budget`, without mid-character truncation.
- Automatically extracts attachments (images, PDFs, spreadsheets, etc.) referenced in documents to `ai_workspace/`, preserving original references unchanged.
- Supports CC Switch skill import and MCP registration.

## Normal Workflow

Most of the time, the human user does not need to use the command line.

You mainly maintain:

- `AI 使用指南` / `AI Guide` in the SiYuan system notebook: your persistent preferences and important notebook guidance for AI, editable in SiYuan's UI.
- `隐私规则` / `Privacy Rules` in the SiYuan system notebook: hide rules maintained via Markdown tables.
- `ai_workspace/`: agent-generated analysis, task context, drafts, and outputs.

Typical flow:

1. Write notes in SiYuan as usual.
2. In SiYuan, open the `思源代理桥` / `SiYuan Agent Bridge` notebook, edit the `隐私规则` / `Privacy Rules` document's tables, and set `Hide` to `yes` for content you want to hide.
3. Tell the AI "refresh the index" — hidden content takes effect from the next session.

## Agent Startup

When MCP is available, the agent should call:

```text
siyuan_start
```

This tool:

- Refreshes the safe index.
- Checks if the SiYuan local service is available.
- Ensures the system notebook `思源代理桥` / `SiYuan Agent Bridge` and its four system documents are ready.
- Returns the startup packet: notebook overview table, Workspace Index (if exists), AI Guide, privacy rules status, and language preference.

If MCP is unavailable, register or repair the MCP server first. The Python CLI is only a developer diagnostic interface, not the normal AI entrypoint.

## MCP Tools

The MCP server provides 9 tools (default read-only, write on explicit confirmation):

- `siyuan_start`: refresh the safe index and return the startup packet with notebook overview table, Workspace Index (if exists), AI Guide, privacy rules status, and language preference. Always call first.
- `siyuan_refresh_index`: manually refresh the safe index and clean `ai_workspace/` (preserves README.md).
- `siyuan_list`: list visible notebooks (no args) or return the document tree for one notebook (with `notebook_id` or `notebook_name`), including word counts, block counts, and update times.
- `siyuan_find_documents`: search through SiYuan search APIs, then apply privacy rules before returning results. Supports 4 modes (`keyword`/`query`/`regex`/`sql`), 2 scopes (`headings`/`full`), and optional notebook filters. Reopens closed notebooks during search.
- `siyuan_read_document`: read a visible document with outline (heading→block position mapping). Default block window mode (`block_limit=200`, `token_budget=50000`) returns complete consecutive blocks without mid-character truncation. Use `block_start=N` for pagination. `include_block_ids=true` enables reference reading with block ID HTML comments for cross-document block references and precise edit targeting. Attachments are automatically extracted to `ai_workspace/attachments/`.
- `siyuan_create_document`: create a new document in a visible notebook. Creates a SiYuan workspace snapshot before writing; refuses if the snapshot fails. Requires `confirmed=true`. User can manually roll back via SiYuan snapshots.
- `siyuan_edit_document`: edit a visible document using `old_text` → `new_text` text anchors. `old_text=""` appends to the end; `new_text=""` deletes matching text. Only single-block edits supported; cross-block text returns an error and requires multiple calls. Creates a snapshot before writing. Requires `confirmed=true`.
- `siyuan_propose_guide_update`: save a proposed guide update in `ai_workspace/`.
- `siyuan_apply_guide_update`: update the `AI 使用指南` / `AI Guide` in the SiYuan system notebook only after explicit user approval (requires `confirmed=true`).

## Long Documents

Long documents are returned with block window pagination. The default window is 200 display blocks with a 50,000 token budget. Use `block_start=N` to page forward, and adjust the window with `block_limit` (1–1000) and `token_budget` (1,000–200,000).

`siyuan_read_document` always returns the document outline first (heading→block position mapping). When headings are fewer than 5 and total blocks exceed 100, a window preview with snippets every 50 blocks is included.

## Privacy Rules

Privacy rules are fully maintained by the user in SiYuan's UI, stored in the system notebook `思源代理桥` / `SiYuan Agent Bridge` → `隐私规则` / `Privacy Rules` document, using Markdown tables.

Two tables:

- `## Hide Notebooks` / `## 隐藏笔记本`: Hide entire notebooks by Notebook ID (preferred) or Notebook Name.
- `## Hide Documents` / `## 隐藏文档`: Hide documents by Document ID (exact match), including all child documents.

Set `Hide` to `yes` to enable, `no` to disable. The Reason column is for human reference only.

After editing the Privacy Rules document, tell the AI "refresh" to apply changes. To temporarily allow hidden content, change the `Hide` column to `no`, then back to `yes` when done.

> AI cannot read, search, edit, or summarize the Privacy Rules document. It is hardcoded as isolated from AI access.

## System Notebook

The `思源代理桥` / `SiYuan Agent Bridge` notebook is automatically created and maintained in SiYuan, containing four system documents:

| Document | Description |
|------|------|
| `AI 使用指南` / `AI Guide` | Persistent AI usage rules and preferences, editable by user in SiYuan's UI. Created if missing; never overwritten. |
| `工作空间索引` / `Workspace Index` | AI-generated semantic navigation index. Never auto-created. Built and updated by the `siyuan-index-builder` skill. |
| `关于思源代理桥` / `About SiYuan Agent Bridge` | Human-readable tool introduction. Auto-overwritten when template version changes. |
| `隐私规则` / `Privacy Rules` | Human-maintained hide rules configuration. Parsed internally by MCP; AI cannot read. |

## CC Switch

Package the skill zip with:

```bash
python pack_skill.py
```

The zip is generated in the `dist/` directory.

For MCP registration, use this custom stdio config:

```json
{
  "type": "stdio",
  "command": "python",
  "args": [
    "D:\\Github\\siyuan-agent-bridge\\plugins\\siyuan-agent-bridge\\scripts\\run_mcp.py"
  ],
  "env": {
    "PYTHONUTF8": "1"
  }
}
```

Reference files:

```text
dist/siyuan-agent-bridge-mcp.json
dist/siyuan-agent-bridge-mcp-deeplink.txt
```

## Project Structure

```text
siyuan-agent-bridge/
  AGENTS.md                  # Developer guide (for maintainers)
  README.md                  # Chinese documentation (main)
  README.en.md               # English documentation
  config.example.json        # Config example
  config.local.json          # Local token, ignored by Git
  source_code/               # Python tool code
    client.py                #   SiYuan API client (read/write)
    indexer.py               #   Index generation (tree.md + docs.jsonl)
    ignore.py                #   Privacy rules parsing (Markdown tables) and filtering
    i18n.py                  #   Multi-language resolution, system name mapping, default templates
    agent_notebook.py        #   System notebook service layer
    cli.py                   #   Developer diagnostic entrypoint
    mcp_server.py            #   MCP stdio server (9 tools)
  plugins/siyuan-agent-bridge/     # Skill and MCP plugin materials
  knowledge_base/            # Generated safe indexes (tree.md, docs.jsonl, notebooks.json, privacy_rules.json)
  ai_workspace/              # Agent workspace (analysis, drafts, attachments)
  tests/                     # Tests
  dist/                      # Distribution artifacts (Skill zip + MCP config)
```

Main generated files:

- `knowledge_base/tree.md`: two-layer document tree (notebook overview table + per-notebook document trees). Generated by code, overwritten on each refresh.
- `knowledge_base/docs.jsonl`: document-level structured data (AI should not read directly).
- `knowledge_base/notebooks.json`: notebook index.
- `knowledge_base/privacy_rules.json`: privacy rules cache, parsed from SiYuan Markdown tables, overwritten on each refresh.

> The master copies of AI Guide and Workspace Index live in the SiYuan system notebook and follow workspace switching. Local `knowledge_base/` files are index caches, not user preferences or navigation indexes.

## Privacy Model

This project is designed as a private project.

- Do not commit tokens.
- Do not publish `knowledge_base/` or `ai_workspace/` unless personal content has been cleaned.
- Agents should not read `config.local.json` unless explicitly asked.
- Agents must not read, search, edit, or summarize the Privacy Rules document.
- Agents must not call low-level SiYuan write APIs directly. Use `siyuan_create_document` or `siyuan_edit_document` only when the user explicitly requests writing.
- Write tools require `confirmed=true`. A SiYuan workspace snapshot is created before every write; if the snapshot fails, the write is refused.

If this project ever becomes public, redesign the privacy model and remove personal note indexes and workspace material first.
