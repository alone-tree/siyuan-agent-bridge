# SiYuan Enhance

[中文说明](README.zh-CN.md)

SiYuan Enhance is a private, local-first adapter that lets external AI agents read your SiYuan notes as a structured personal knowledge base.

It is not a SiYuan plugin, not a public project, and not a vector-search system. Your notes stay in SiYuan; this tool creates structured read-only indexes and gives AI agents a controlled way to inspect relevant notes.

## Normal Human Workflow

Most of the time, you do not need to use the command line yourself.

You mainly maintain these local files:

- `knowledge_base/guide.md`: the high-level reading guide for AI agents.
- `siyuan.ignore.local.json`: long-term privacy rules for hidden notebooks and documents, syncable through the repository.
- `siyuan.allow.local.json`: temporary allow rules, syncable through the repository.
- `ai_workspace/`: agent-generated analysis, context, drafts, and outputs.

Typical workflow:

1. You write notes in SiYuan as usual.
2. If something should be hidden, open `siyuan.ignore.local.json` and copy one of the templates into the `ignore` array.
3. Tell the AI agent: “I changed the SiYuan ignore file; refresh the knowledge-base index.”
4. The AI agent refreshes the safe index.
5. After that, the AI only sees the visible part of your note structure.

When using another AI tool, tell it:

```text
Read D:\Github\siyuan-enhance\START_HERE.md first.
If MCP tools are available, call siyuan_start first. It checks SiYuan and returns existing top-level guidance without refreshing indexes.
If MCP is unavailable, run python -m source_code start in D:\Github\siyuan-enhance.
```

## How It Works

SiYuan stores notes locally and exposes a local HTTP API, usually at:

```text
http://127.0.0.1:6806
```

This tool uses read-only API calls to:

- scan notebooks and document structure;
- remove anything matched by `siyuan.ignore.local.json`;
- generate AI-readable index files such as `knowledge_base/tree.md` and `knowledge_base/docs.jsonl`.
- generate startup overview `knowledge_base/overview.md`.
- generate per-notebook maps in `knowledge_base/notebooks/<notebook-id>.md`.

The AI does not need to ingest every note at once. It reads the structure first, then opens specific documents only when needed.

## Ignore Rules

Open:

```text
siyuan.ignore.local.json
```

The file contains copyable templates. The program only reads the `ignore` array; other fields are documentation.

Hide a notebook by name:

```json
{
  "scope": "notebook",
  "name": "Notebook Name",
  "reason": "Hide this notebook."
}
```

Hide one document by id:

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

After editing the file, ask the AI agent to refresh the index. Previously visible documents that now match ignore rules are removed from the regenerated cache.

## Temporary Access

Temporary access is mostly for AI agents.

If you need to temporarily open hidden content, tell the agent something like:

```text
Temporarily allow this document for 30 minutes: <doc-id>
```

or:

```text
Temporarily allow this notebook for 1 hour: <notebook name>
```

The agent writes or reads a time-limited rule in `siyuan.allow.local.json`. It expires automatically and does not rewrite the long-lived `knowledge_base/` index.

## Project Structure

```text
siyuan-enhance/
  AGENTS.md                 # Rules for AI agents
  README.md                 # English documentation
  README.zh-CN.md           # Chinese documentation
  config.example.json       # Config example
  config.local.json         # Local token, ignored by Git
  siyuan.ignore.local.json  # Long-term hide rules, syncable through Git
  siyuan.allow.local.json   # Temporary allow rules, syncable through Git
  source_code/                # Python tool code
  knowledge_base/           # Generated knowledge-base indexes
  ai_workspace/             # Agent workspace
  tests/                    # Tests
```

Main generated files:

- `knowledge_base/guide.md`: human-maintained knowledge-base guide.
- `knowledge_base/overview.md`: startup overview for AI agents.
- `knowledge_base/tree.md`: AI-readable document tree.
- `knowledge_base/docs.jsonl`: document-level index.
- `knowledge_base/notebooks.json`: notebook index.
- `knowledge_base/notebooks/`: per-notebook document maps.

Main code modules:

- `source_code/client.py`: read-only SiYuan API client.
- `source_code/indexer.py`: scanning and index generation.
- `source_code/ignore.py`: privacy ignore and temporary allow rules.
- `source_code/cli.py`: command-line entrypoint for agents/developers.

## Agent Workflow

AI agents should:

1. Read `START_HERE.md`.
2. Prefer MCP tool `siyuan_start`; it only checks connectivity and returns existing top-level indexes.
3. If MCP is unavailable, run `python -m source_code start`.
4. Use the startup packet and `knowledge_base/overview.md` to choose relevant notebooks.
5. Read `knowledge_base/notebooks/<notebook-id>.md` only when relevant.
6. Read specific documents by document id when needed.
7. Put derived work in `ai_workspace/`.
8. Refresh the index only if you say the ignore file changed, the index is missing, or it is clearly stale.

Agents should not read `config.local.json`, `siyuan.ignore.local.json`, or `siyuan.allow.local.json` unless you explicitly ask.

## Privacy Model

This project is designed as a private project.

- `config.local.json` is ignored by Git.
- `siyuan.ignore.local.json` may be tracked to sync visibility rules across devices.
- `siyuan.allow.local.json` may be tracked to sync temporary access rules across devices.
- `knowledge_base/` and `ai_workspace/` are not ignored because this repository is currently private.

If this project is ever made public, review the privacy model first and remove personal note content and agent workspace material.
