# Agent Wiki — 智能体知识库运营工作流

把外部知识转化为智能体运行时可调用的行为规则（Memory/规范/Skill）的完整方法论，以 Qoder Agent Skill 形式交付。灵感来自 Andrej Karpathy 的 LLM Wiki 设计，经 26+ 条真实入库记录验证。

**知识库不是收藏夹，是智能体的能力增长引擎。**

## 核心机制

- **三层架构**：Raw Sources（原始采集，只读不可变）→ The Wiki（LLM 维护的派生内容）→ The Schema（人机共维的规范与配置）
- **三操作**：Ingest（采集入库，8 步清单）/ Query（检索回填，让探索产生复利）/ Lint（六维体检）
- **角色分离**：Planner（人工定目标）/ Generator（LLM 执行）/ Evaluator（治具裁定）——**模型不得给自己打分**
- **采集前价值契约**：三问先行，价值判定不达标即显式中止，不强行入库
- **蒸馏三色标记**：🟢 已落地 / 🟡 部分落地 / 🔵 参考索引——每条知识必须回答"能否改变智能体的行为决策"
- **采集引擎抽象**：AutoCLI / WebFetch / 公开 API / 手动粘贴可互换，入库后要求完全一致
- **Harness 递减**：治具规则随模型进步单调递减，删掉不再产生真实信号的规则

## 快速开始

1. 将 `SKILL.md` 复制到你的 Qoder 技能目录：
   - 个人级：`~/.qoder/skills/agent-wiki/SKILL.md`
   - 项目级：`<项目>/.qoder/skills/agent-wiki/SKILL.md`
2. 初始化知识库目录结构：

```
<知识库根目录>/
├── 原始采集/（文章/讨论/视频）    ← Raw Sources，采集后只读
├── 知识库/（目录.md、操作日志.md） ← The Wiki
└── 程序文件/配置/来源白名单.json   ← The Schema（可选）
```

3. 运行 Evaluator 示例验证环境（对 `examples/` 应输出 PASS）：

```bash
python scripts/validate.py examples
```

4. 开始第一次 Ingest：让智能体按 SKILL.md 的 8 步清单执行，或参照 `examples/` 中的样本文件。

## Evaluator 示例（scripts/validate.py）

零依赖（仅 Python 3 标准库），覆盖 Lint 六维：

| 维度 | 判定 |
|---|---|
| 元数据完整性（URL/采集时间/采集命令） | ERROR |
| 编码正确性（UTF-8、U+FFFD、双重编码签名） | ERROR |
| 格式规范性（H1 开头、`---` 分隔、JSON `_metadata`） | ERROR |
| 命名规范（`{source}_{topic}_{date}`） | WARN |
| 交叉引用（目录.md 链接可达） | ERROR |
| 来源白名单（URL 域名匹配） | WARN |

退出码：0 = PASS（无 ERROR），1 = FAIL。WARN 不阻塞但应定期审视（Harness 递减）。

## 目录结构

```
agent-wiki/
├── SKILL.md              ← 技能主体（复制到技能目录即用）
├── README.md
├── LICENSE               ← MIT
├── scripts/
│   └── validate.py       ← Evaluator 零依赖示例
└── examples/             ← 最小可跑通样本知识库
    ├── 原始采集/文章/
    ├── 知识库/目录.md
    └── 程序文件/配置/来源白名单.json
```

## 设计原则

- **真实执行结果是唯一验收标准**：治具裁定优先于生成者自述
- **可复现**：`采集命令` 字段如实记录实际引擎与降级路径
- **平台无关**：核心流程不绑定任何采集工具与智能体平台；蒸馏落地映射到各平台自身的记忆机制

## License

MIT — 见 [LICENSE](LICENSE)。
