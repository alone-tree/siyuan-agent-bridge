---
name: siyuan-index-builder
description: 创建和更新思源知识库的结构化索引文件 knowledge_base/index.md。当用户提到"创建索引"、"更新索引"、"建索引"、"重建索引"、"刷新索引"、"index"，或希望 AI 快速定位知识库中的相关文档时使用此 skill。
---

# SiYuan Index Builder

Build and maintain `knowledge_base/index.md` — a path-first, human-annotated
navigation index that lets AI agents locate relevant documents without scanning
every notebook map. The index prioritizes document paths (which are objective
and complete) over themes (which are fuzzy and incomplete).

## Prerequisites

- The `siyuan-knowledge` MCP tools must be available. If they are not, tell the
  user to register the MCP server first.
- `knowledge_base/tree.md` and `knowledge_base/docs.jsonl` must exist. If the safe
  index has never been generated, ask the user to run `siyuan_refresh_index`
  first.

## Workflow

### Reading depth — follow the user's instruction

The user may specify how thoroughly you should read before writing the index:

- **快速 (quick, default)**: Read one hub document per notebook (if one exists —
  look for documents whose title contains "index", "必读", "概述", "项目背景",
  "README", or that sit at the root of a major subtree). Write a 1-sentence
  summary for each hub you read. Do not read leaf documents. This mode is for
  getting a structural overview fast.

- **详细 (thorough)**: For each notebook, read the hub document plus 2–4
  additional documents that appear important (top-level documents, documents
  with broad-scope titles, heavily nested subtree roots). Write 1–2 sentence
  summaries for each document you read. This mode is for building a rich,
  annotated index.

If the user does not specify, default to **快速**. You may ask: "要我快速扫一遍结构就建索引，还是深入读一些重点文档再建？"

Titles alone are not enough to judge a document's content. Always read before
you summarize. A document titled "REITs" might be a 3000-word analysis or a
one-line bookmark — you cannot tell from the path.

### Step 1 — Survey the structure

Call `siyuan_start` to get the notebook overview table (tree.md layer 1). Identify:

- Which notebooks have documents (>0 visible).
- Document counts and word counts per notebook — large notebooks need more structural summary,
  small ones can list documents more directly.

### Step 2 — Read notebook maps and hub documents

For each visible notebook with >0 documents, call `siyuan_list_documents`
with its notebook ID. As you read the map, classify the internal structure:

- **Deep tree**: 3+ path levels, regular sub-structures (e.g., companies under
  sectors, each with sub-pages). Summarize the *structure pattern* rather than
  listing every leaf document.
- **Flat collection**: Most documents at root or one level deep. List key
  documents directly.
- **Hub with spokes**: A root index document followed by child documents.
  Note the hub.

After classifying, **read hub documents** according to the reading depth the
user specified. Use `siyuan_read_document` with the document ID. The tool returns
the document outline first, then the content. For long documents, `chunk=0`
(default) returns the first chunk — a preview is enough for index purposes. Use
`chunk=N` to jump to specific sections if needed.

### Step 3 — Generate index.md

Write the index to `knowledge_base/index.md` using your standard file tools
(Write, Edit). Follow this template:

```markdown
# Knowledge Base Index
> Generated YYYY-MM-DD | Update: tell AI "更新索引" or "rebuild the index"

## Quick Route
| Question area | Notebook(s) |
|--------------|-------------|
| ...           | ...         |

## Notebook Name (N docs)

> Structure: one-line description of how this notebook is organized
> Priority: (leave empty — the user fills this in)

### /path/to/key/subtree

- `doc-id` Doc Title
  - AI summary: 1–2 sentence digest of what this document covers
- `doc-id` Another Doc
```

Rules for filling the template:

**Quick Route table**
- Infer entries from notebook names and top-level paths.
- Be conservative. Only add an entry when the mapping is clear. A wrong route
  is worse than no route.
- Leave obvious gaps — the user will fill them.

**Structure lines**
- One sentence describing how the notebook is organized.
- For deep trees: "Five top-level sections (一数据中心, 二芯片, 三光模块公司,
  四上游, 五政策), each with company sub-pages and daily news."
- For flat collections: "Independent articles at root, no deep hierarchy."

**Priority lines**
- Always write `> Priority: ` empty. Never fill it in.
- If the user later adds a priority annotation, you must preserve it verbatim
  during updates. Human priorities are the only part of the index you cannot
  modify.

**AI summary lines**
- You have already read hub documents in Step 2. Write a summary for each
  document you read. If you went deeper than hubs (in 详细 mode), summarize
  those too.
- Never guess content from the title alone. A title like "REITs" could be a
  3000-word analysis or a one-line bookmark. If you have not read it, leave
  the summary line out.
- Keep summaries to 1–2 sentences. They are signposts, not book reports.
- During updates, refresh summaries for documents whose content has changed.

**Document selection**
- For notebooks with ≤20 docs: list every document.
- For notebooks with >20 docs: group by path and list only representative or
  hub documents. Describe the pattern ("财报电话会记录 × 12 篇") rather than
  listing every leaf.
- Documents that serve as structural hubs (index pages, project overviews) get
  priority for listing and annotation.

**Length budget**
- Keep the entire index under **300 lines**. If it grows longer, summarize
  more aggressively at the path level.
- If a notebook has >100 docs, its section should be no more than 30–40 lines.
  Focus entirely on the structure pattern and a handful of key documents.

### Step 4 — Report to the user

After writing `index.md`, tell the user:

1. What structural patterns you found across their notebooks.
2. Which notebooks you summarized at path level vs. document level.
3. The 3–5 most important-looking hub documents you encountered.
4. The line count of the generated index (for the user's awareness).
5. Ask: "Does the structure look right? Which paths or documents should I mark as priority? If you want more detailed summaries for specific documents, tell me and I'll read them deeper."

### Step 5 — Handle user feedback

The user may respond with:
- "Mark /some/path as priority" → add `> Priority: high` to that section.
- "Read document X and annotate it" → read it with `siyuan_read_document`, add
  an AI summary.
- "That path is actually about Y, not X" → fix the structure description.
- "Don't include notebook Z" → remove that section.

Apply each change and confirm what you updated.

## Update Workflow

When the user asks to update the index:

1. If the index may be stale, call `siyuan_refresh_index` first.
2. Call `siyuan_start` to get the current notebook overview table and detect new or removed notebooks.
3. For notebooks that may have changed, use `siyuan_list_documents` with their notebook ID.
4. For any new or likely-changed documents, read them with
   `siyuan_read_document` to produce or refresh summaries. Do not rewrite
   summaries for unchanged documents — only update what is stale.
5. Update `knowledge_base/index.md`:
   - Add new documents or paths discovered, with summaries.
   - Remove entries for deleted documents.
   - Refresh AI summaries for documents you confirmed have changed.
   - **Preserve every human-written line**: priority annotations, user
     corrections, and any text the user added. Your job is to update the
     machine-generated parts, not to rewrite the human contributions.
6. Report what changed and the new line count.

## Safety Rules

- Do not modify SiYuan notes.
- Do not call SiYuan write APIs.
- Do not read hidden documents or notebooks. Work only from visible safe indexes.
- Do not overwrite human annotations in `index.md`. Add your updates around them.
- The user's words are the only confirmation needed. "Create index" means create it. "Update index" means update it. No extra approval step.
