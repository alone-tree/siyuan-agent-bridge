# SiYuan Enhance

[中文说明](README.zh-CN.md)

SiYuan Enhance is a private, local-first adapter that lets external AI agents use your SiYuan notes as a structured personal knowledge base.

It is not a SiYuan plugin, not a public package, and not a vector-search system. Your notes stay in SiYuan. This project creates safe read-only indexes and exposes them to AI agents through MCP tools and a Skill workflow.

## Current Capabilities

- Scans SiYuan notebooks and the full document tree, including child documents. Closed notebooks are automatically opened during scan and restored afterwards.
- Hides notebooks, single documents, or document subtrees through `siyuan.ignore.local.json`.
- Temporarily opens hidden items through `siyuan.allow.local.json`.
- Generates safe indexes, overview files, and notebook maps under `knowledge_base/`.
- Computes full-document word counts from exported Markdown for visible documents, so agents can use length as an importance signal.
- Provides MCP tools for Claude Code, Codex, OpenCode, and similar agents.
- Chunks long documents. The default chunk size is 10,000 characters and can be adjusted with `max_chars`.
- Preserves Markdown image references inside document chunks, so image-heavy notes keep surrounding text context.
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
2. Edit `siyuan.ignore.local.json` if some content should be hidden.
3. Ask the AI agent to refresh the knowledge-base index.
4. The agent calls `siyuan_refresh_index`.
5. The AI only sees the visible safe index after refresh.

## Agent Startup

When MCP is available, the agent should call:

```text
siyuan_start
```

This refreshes the safe index and returns the startup packet with the notebook overview table, index.md (when it exists), START_HERE.md, and guide.md.

If MCP is unavailable, register or repair the MCP server first. The Python CLI is only a developer diagnostic interface, not the normal AI entrypoint.

## MCP Tools

- `siyuan_start`: refresh the safe index and return the startup packet with notebook overview table, index.md (when it exists), START_HERE.md, and guide.md. Always call first.
- `siyuan_refresh_index`: refresh safe indexes mid-session when the user explicitly asks.
- `siyuan_list`: list visible notebooks (no args) or return the document tree for one notebook (with `notebook_id`), including word counts and update times.
- `siyuan_find_documents`: search safe-index titles/paths/tags plus live SiYuan block content when available, with 4 modes (`keyword`/`query`/`regex`/`sql`), 2 scopes (`headings`/`full`), optional notebook filter.
- `siyuan_read_document`: read a document with outline. Short docs return full text; long docs return one chunk; use `chunk=N` to navigate.
- `siyuan_propose_guide_update`: save a proposed guide update in `ai_workspace/`.
- `siyuan_apply_guide_update`: update `knowledge_base/guide.md` only after explicit user approval (requires `confirmed=true`).
- `siyuan_privacy`: manage persistent hide rules. `action="hide"` or `"unhide"`, requires `confirmed=true`.
- `siyuan_temporary_allow`: manage temporary allow rules. `action="open"` (expires in N minutes) or `"close"` (clear all).

## Long Documents

Long documents are not returned in one large MCP response, because clients and model UIs may truncate the output.

Default chunk size:

```text
10,000 characters
```

Agents can pass `max_chars` to adjust the size. The current range is 2,000 to 30,000 characters.

`siyuan_read_document` always returns the document outline (heading→chunk mapping) first. For long documents, call with `chunk=0` for the first chunk or `chunk=N` to jump to a specific section.

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

The latest skill zip is:

```text
dist/siyuan-knowledge-skill-latest.zip
```

For MCP registration, use this custom stdio config:

```json
{
  "type": "stdio",
  "command": "python",
  "args": [
    "D:\\Github\\siyuan-enhance\\plugins\\siyuan-knowledge\\scripts\\run_mcp.py"
  ],
  "env": {
    "PYTHONUTF8": "1"
  }
}
```

Reference files:

```text
dist/siyuan-knowledge-mcp.json
dist/siyuan-knowledge-mcp-deeplink.txt
```

## Project Structure

```text
siyuan-enhance/
  AGENTS.md                  # Rules for AI agents
  START_HERE.md              # Agent entrypoint
  README.md                  # English documentation
  README.zh-CN.md            # Chinese documentation
  config.example.json        # Config example
  config.local.json          # Local token, ignored by Git
  siyuan.ignore.local.json   # Long-term hide rules
  siyuan.allow.local.json    # Temporary allow rules
  source_code/               # Python tool code
  plugins/siyuan-knowledge/  # Skill and MCP plugin materials
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
- Agents must not modify SiYuan notes or call SiYuan write APIs.

If this project ever becomes public, redesign the privacy model and remove personal note indexes and workspace material first.
