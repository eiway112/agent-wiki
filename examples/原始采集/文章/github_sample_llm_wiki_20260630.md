# LLM Wiki 模式示例条目

**By:** Sample Author
**Site:** GitHub（示例）
**Published:** 2026-06-30
**URL:** <https://github.com/example/llm-wiki-sample>
**采集时间:** 2026-06-30T10:00:00+08:00
**采集命令:** 手动粘贴（示例数据；实际采集时如实记录引擎与命令，含降级切换）
**原始来源:** github.com/example/llm-wiki-sample（示例来源）

---

这是 agent-wiki 的最小样本条目，用于演示原始采集文件的标准结构：

1. 以 H1 标题开头；
2. 元数据块包含必需字段（URL、采集时间、采集命令）与建议字段（By、Site、Published、原始来源）；
3. 元数据与正文之间以 `---` 分隔；
4. 文件命名遵循 `{source}_{topic}_{date}.{ext}`（本文件：github_sample_llm_wiki_20260630.md）；
5. 入库后本文件只读，不再修改——派生内容一律写入 `知识库/`。

运行 `python scripts/validate.py examples`，本文件应通过全部六维校验。
