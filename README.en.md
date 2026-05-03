# SiYuan Agent Bridge

[中文说明](README.md)

SiYuan Agent Bridge is a private, local-first adapter that lets external AI agents use your SiYuan notes as a structured personal knowledge base, with write support on explicit user confirmation.

It is not a SiYuan plugin, not a public package, and not a vector-search system. Your notes stay in SiYuan. This project creates safe indexes and exposes them to AI agents through MCP tools and a Skill workflow.

## Current Capabilities

- Scans SiYuan notebooks and the full document tree, including child documents. Closed notebooks are automatically opened during scan and restored afterwards.
- Hides notebooks, single documents, or document subtrees through `siyuan.ignore.local.json`.
- Temporarily opens hidden items through `siyuan.allow.local.json`.
- Generates safe indexes, overview files, and notebook maps under `knowledge_base/`.
- Computes full-document word counts from exported Markdown for visible documents, so agents can use length as an importance signal.
- Provides MCP tools for Claude Code, Codex, OpenCode, and similar agents.
- Paginates long documents by display block windows with `block_limit` and `token_budget`.
- Automatically extracts attachments (images, PDFs, spreadsheets, etc.) referenced in documents to `ai_workspace/` so AI can read them alongside the text. Original Markdown references are preserved unchanged.
- Supports CC Switch skill import and MCP registration.

## Normal Workflow

Most of the time, the human user does not need to use the command line.

You mainly maintain:

- `knowledge_base/guide.md`: the curated reading guide for AI agents.
- `siyuan.ignore.local.json`: long-term hide rules.
- `siyuan.allow.local.json`: temporary allow rules.
- `ai_workspace/`: agent-generated analysis, task context, drafts, and outputs.

Typical flow:

1. Write notes in SiYuan as usual.
2. To hide content, tell the AI: "hide notebook XX" or "hide document XX". For documents, use the document ID rather than the title, since titles can be duplicated but IDs cannot.
3. The AI adds the specified content to the hide rules. From the AI's perspective, hidden content is nearly non-existent.

**Current privacy limitation:** Hidden documents do not appear in the document tree, search returns no results, and direct reading by document ID returns "not found." However, if a visible document references a hidden document (e.g., block ID or document ID in a link), the reference trace remains visible. In extreme cases, an AI could obtain the document ID and un-hide the content on its own. There is currently no perfect solution for this; a future graphical interface may move hide controls entirely to the human side, removing all privacy-related APIs from AI access (not yet implemented).

## Agent Startup

When MCP is available, the agent should call:

```text
siyuan_start
```

This refreshes the safe index and returns the startup packet with the notebook overview table, index.md (when it exists), START_HERE.md, and guide.md.

If MCP is unavailable, register or repair the MCP server first. The Python CLI is only a developer diagnostic interface, not the normal AI entrypoint.

## MCP Tools

The MCP server provides these tools (default read-only, write on explicit confirmation):

- `siyuan_start`: refresh the safe index and return the startup packet with notebook overview table, index.md (when it exists), START_HERE.md, and guide.md. Always call first.
- `siyuan_refresh_index`: refresh safe indexes mid-session when the user explicitly asks. Also cleans `ai_workspace/` (preserves README.md).
- `siyuan_list`: list visible notebooks (no args) or return the document tree for one notebook (with `notebook_id`), including word counts and update times.
- `siyuan_find_documents`: search through SiYuan search APIs, then apply privacy rules before returning results. Supports 4 modes (`keyword`/`query`/`regex`/`sql`), 2 scopes (`headings`/`full`), and optional notebook filters.
- `siyuan_read_document`: read a visible document with outline (heading→block position mapping). Default block window mode (`block_limit=200`, `token_budget=50000`) returns complete consecutive blocks without mid-character truncation. Use `block_start=N` for pagination. `include_block_ids=true` enables reference reading with block ID HTML comments for cross-document block references and precise edit targeting. Attachments (images, PDFs, spreadsheets, etc.) are automatically extracted to `ai_workspace/`, preserving original references unchanged.
- `siyuan_create_document`: create a new document in a visible notebook. Creates a SiYuan workspace snapshot before writing; refuses if the snapshot fails. Requires `confirmed=true`. User can manually roll back via SiYuan snapshots.
- `siyuan_edit_document`: edit a visible document using `old_text` → `new_text` text anchors. `old_text=""` appends to the end; `new_text=""` deletes matching text. Only single-block edits supported; cross-block text requires multiple calls. Creates a snapshot before writing. Requires `confirmed=true`.
- `siyuan_propose_guide_update`: save a proposed guide update in `ai_workspace/`.
- `siyuan_apply_guide_update`: update `knowledge_base/guide.md` only after explicit user approval (requires `confirmed=true`).
- `siyuan_privacy`: manage persistent hide rules. `action="hide"` or `"unhide"`, requires `confirmed=true`. Hiding a `document` hides that document and all child documents.
- `siyuan_temporary_allow`: manage temporary allow rules. `action="open"` (expires in N minutes, requires `confirmed=true`), `action="close"` (clear all). Temporarily allowing a `document` allows that document and all child documents.

## Long Documents

Long documents are returned with block window pagination. The default window is 200 display blocks with a 50,000 token budget. Use `block_start=N` to page forward, and adjust the window with `block_limit` (1–1000) and `token_budget` (1,000–200,000).

`siyuan_read_document` always returns the document outline first (heading→block position mapping). When headings are fewer than 5 and total blocks exceed 100, a window preview with snippets every 50 blocks is included.

## Ignore Rules

Open:

```text
siyuan.ignore.local.json
```

Hide a notebook:

```json
{
  "scope": "notebook",
  "name": "Notebook Name",
  "reason": "Hide this notebook."
}
```

Hide one document:

```json
{
  "scope": "document",
  "id": "document-id",
  "reason": "Hide exactly this document."
}
```

Hide one document and all child documents:

```json
{
  "scope": "subtree",
  "id": "root-document-id",
  "reason": "Hide this document and all children."
}
```

After editing, ask the AI agent to refresh the index. Previously visible documents that now match ignore rules are removed from the regenerated `knowledge_base/` index.

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
  AGENTS.md                  # Rules for AI agents
  START_HERE.md              # Agent entrypoint
  README.md                  # Chinese documentation (main)
  README.en.md               # English documentation
  config.example.json        # Config example
  config.local.json          # Local token, ignored by Git
  siyuan.ignore.local.json   # Long-term hide rules
  siyuan.allow.local.json    # Temporary allow rules
  source_code/               # Python tool code
  plugins/siyuan-agent-bridge/  # Skill and MCP plugin materials
  knowledge_base/            # Generated safe indexes
  ai_workspace/              # Agent workspace
  tests/                     # Tests
```

Main generated files:

- `knowledge_base/guide.md`: human-maintained knowledge-base guide.
- `knowledge_base/tree.md`: two-layer document tree (notebook overview table + per-notebook document trees). Agents should not scan the full layer 2 by default.
- `knowledge_base/docs.jsonl`: document-level structured data (AI should not read directly).
- `knowledge_base/notebooks.json`: notebook index.

Main code modules:

- `source_code/client.py`: read-only SiYuan API client.
- `source_code/indexer.py`: scanning and index generation.
- `source_code/ignore.py`: privacy ignore and temporary allow rules.
- `source_code/cli.py`: developer diagnostic entrypoint.
- `source_code/mcp_server.py`: MCP stdio server.

## Privacy Model

This project is designed as a private project.

- Do not commit tokens.
- Do not publish `knowledge_base/` or `ai_workspace/` unless personal content has been cleaned.
- Agents should not read `config.local.json`, `siyuan.ignore.local.json`, or `siyuan.allow.local.json` unless explicitly asked.
- Agents must not call low-level SiYuan write APIs directly. Use `siyuan_create_document` or `siyuan_edit_document` only when the user explicitly requests writing.
- Write tools require `confirmed=true`. A SiYuan workspace snapshot is created before every write; if the snapshot fails, the write is refused.

If this project ever becomes public, redesign the privacy model and remove personal note indexes and workspace material first.
