# Agent Wiki — 智能体知识库运营工作流

把外部知识转化为智能体运行时可调用的行为规则（Memory/规范/Skill）的完整方法论，以 Qoder Agent Skill 形式交付。灵感来自 Andrej Karpathy 的 LLM Wiki 设计，经 26+ 条真实入库记录验证。

**知识库不是收藏夹，是智能体的能力增长引擎。**

## 核心机制

- **三层架构**：Raw Sources（原始采集，只读不可变）→ The Wiki（LLM 维护的派生内容）→ The Schema（人机共维的规范与配置）
- **三操作**：Ingest（采集入库，0–8 步清单，第 0 步命中预登记）/ Query（**任务必经路径**：开工前检索既有 🟢 规则、交付时登记命中或未命中、好答案回填）/ Lint（结构层九维 + 判断层回测，🟢 回测到期由治具机算）
- **角色分离**：Planner（人工定目标）/ Generator（LLM 执行）/ Evaluator（治具裁定）——**模型不得给自己打分**
- **采集前价值契约**：四问先行（第 4 问重要主题必答：有无反方证据），价值判定不达标即显式中止，不强行入库
- **库健康度看归因率不看采集量**：`命中 : 未命中`（分母＝带 `**命中:**` 字段的条目数）是主指标；采集条目数只度量进料。只在被点名时才查知识库的库，等价于不存在
- **蒸馏三色标记**：🟢 已落地 / 🟡 部分落地 / 🔵 参考索引——每条知识必须回答“能否改变智能体的行为决策”
- **质量过滤器与标记上限**：排他性/生成力两问滤掉常识规则，决定三色标记上限；**适用边界**为 🟢/🟡 必填字段——语义要求下沉为结构特征，治具裁定
- **矛盾处理协议**：时间性演化/领域性差异/本质性张力三型处理，禁止悄悄覆盖
- **蒸馏卡与基线回归**：`references/rule-template.md` 统一三出口形态，examples 基线卡作为方法论迭代的回归基线
- **记忆分层与注入面抽象**：热层（常驻索引）/温层（按需）/冷层（tombstone）三层；落地载体由实例的 `注入面.json` 自描述，技能不硬编码任何平台路径/用户名。蒸馏卡「落地指针」（`memory:`/`file:`/`none`）按判定阶梯 `INVALID<ORPHANED<NONE<WARM<HOT` 机验「状态↔载体↔台账」一致；维度 8/9 采用门控生效，注入面不可达记 `UNVERIFIED`（🟢 降 WARN）、`auto_injection=false` 封顶 `WARM`——把真实能力边界诚实标注，而非假装修复
- **采集引擎抽象**：AutoCLI / WebFetch / 公开 API / 手动粘贴可互换，入库后要求完全一致
- **Harness 递减**：治具规则随模型进步单调递减，删掉不再产生真实信号的规则；新增机制同样受递减约束

## 快速开始

1. 将 `SKILL.md` 复制到你的 Qoder 技能目录：
   - 个人级：`~/.qoder/skills/agent-wiki/SKILL.md`
   - 项目级：`<项目>/.qoder/skills/agent-wiki/SKILL.md`
2. 初始化知识库目录结构：

```
<知识库根目录>/
├── 原始采集/（文章/讨论/视频）    ← Raw Sources，采集后只读
├── 知识库/（目录.md、操作日志.md、落地台账.md←机器生成） ← The Wiki
└── 程序文件/配置/来源白名单.json + 注入面.json   ← The Schema（均可选；注入面启用维度 8/9）
```

3. 运行 Evaluator 示例验证环境（对 `examples/` 应输出 PASS）：

```bash
python scripts/validate.py examples
```

4. 开始第一次 Ingest：让智能体按 SKILL.md 的 8 步清单执行，或参照 `examples/` 中的样本文件。

## Evaluator 示例（scripts/validate.py）

零依赖（仅 Python 3 标准库），覆盖 Lint 结构层九维：

| 维度 | 判定 |
|---|---|
| 元数据完整性（URL/采集时间/采集命令） | ERROR |
| 编码正确性（UTF-8、U+FFFD、双重编码签名） | ERROR |
| 格式规范性（H1 开头、`---` 分隔、JSON `_metadata`） | ERROR |
| 命名规范（`{source}_{topic}_{date}`） | WARN |
| 交叉引用（目录.md 链接可达） | ERROR |
| 来源白名单（URL 域名匹配） | WARN |
| 蒸馏卡规范性（适用边界/来源指针必需且非空） | ERROR |
| 落地台账一致性（状态↔载体↔台账；采用门控生效） | ERROR（缺指针/语法无效/🟢 无存活载体）；注入面不可达 → SKIP + 🟢 降 WARN |
| 目录台账一致性（目录.md ↔ 落地台账；采用门控生效） | ERROR（目录引用卡不在台账）；WARN（台账卡目录未引用） |

退出码：0 = PASS / PASS_WITH_SKIP（有可选检查被跳过，如未采用门控 `not_adopted`、注入面不可达 `unreachable`，附覆盖率与 skip 原因，不表述为全维通过），1 = FAIL（有 ERROR）。WARN 不阻塞但应定期审视（Harness 递减）。`--refresh-landing-ledger` 是治具唯一写文件动作（生成机器可读的 `知识库/落地台账.md`，禁手编），门禁路径只读。

治具自身受红绿双向回归保护（`python tests/test_validate.py`）：正向验 `examples/` 判 PASS，反向按九维各造一次违规验均被拦为 ERROR，并验 WARN 不阻塞、二进制豁免留痕、采用门控 `not_adopted` 跳过、注入面不可达降级 WARN、`auto_injection=false` 封顶 WARM。CI（`.github/workflows/lint.yml`）在 Ubuntu 与 Windows 双平台执行同一套。

## 目录结构

```
agent-wiki/
├── SKILL.md              ← 技能主体（复制到技能目录即用）
├── README.md
├── LICENSE               ← MIT
├── references/
│   └── rule-template.md  ← 蒸馏产物模板（三出口标准形态）
├── scripts/
│   └── validate.py       ← Evaluator 零依赖示例
├── tests/
│   └── test_validate.py  ← 治具自身的红绿双向回归（九维各造一次违规）
└── examples/             ← 最小可跑通样本知识库
    ├── 原始采集/文章/
    ├── 知识库/目录.md + 蒸馏卡基线样张 + 落地台账.md（机器生成）
    └── 程序文件/配置/来源白名单.json + 注入面.json（占位符模板）
```

## 设计原则

- **真实执行结果是唯一验收标准**：治具裁定优先于生成者自述
- **裁定权按成本分层**：结构层（含适用边界等下沉的语义特征）零依赖治具裁定，语义保真由人工回测裁定
- **可复现**：`采集命令` 字段如实记录实际引擎与降级路径
- **平台无关**：核心流程不绑定任何采集工具与智能体平台；蒸馏落地映射到各平台自身的记忆机制

## License

MIT — 见 [LICENSE](LICENSE)。
