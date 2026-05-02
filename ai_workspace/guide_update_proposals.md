
## long-document-reading-workflow

建议在 guide.md 的 Recurring Workflows 中补充一条长文档读取流程：遇到电话会议记录、报告、访谈等长文档时，先用 siyuan_read_document 设置较小 max_chars 读取 chunk=0，查看返回的大纲、总 chunks 数和标题到 chunk 的映射；需要深入时再按 chunk=N 跳转，不要一次性要求完整长文档。注意文档树里的字数可能只反映安全索引或标题摘要，不能单独用来判断正文长度。

## 测试提议

test-proposal
