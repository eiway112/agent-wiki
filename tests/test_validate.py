#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/validate.py 的红绿双向回归治具。

正向：examples/ 须判 PASS（退出码 0）。
反向：十一维各造一次违规，须被判 ERROR（退出码 1）且报出对应维度——
      只会亮绿灯的治具等于没有治具。
豁免项：命名与来源白名单属 WARN，违规时退出码仍须为 0，防门禁把常态豁免误判为失败。
采用门控：维度 8（落地台账一致性）/维度 9（目录台账一致性）仅在「注入面.json 存在
      或任一蒸馏卡携带『- 落地指针:』字段」时生效；未采用记 SKIP(not_adopted)，不报 ERROR。
维度 10（🟢 回测到期）：夹具卡的合格回测锚点按运行日动态生成——写死日期会让夹具
      随时间自然到期，红绿信号退化为日历函数；反向用例反过来构造超窗日期。
维度 11（归因命中字段）：WARN 级，日志缺失记 SKIP 而非静默 PASS。

零依赖（仅标准库）。跑法：
    python -m unittest discover -s tests -v
    python tests/test_validate.py
夹具写在仓库内 .tmp/，不污染系统临时目录，用例结束即删。
"""

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATOR = REPO_ROOT / "scripts" / "validate.py"
EXAMPLES = REPO_ROOT / "examples"
TMP_ROOT = REPO_ROOT / ".tmp" / "lint-fixtures"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import validate  # noqa: E402  只为读取维度登记表：测试里手抄计数就是第二份漂移副本

# 维度 10 的时间基准：一切夹具日期相对运行日生成
TODAY = date.today()
WINDOW_DAYS = validate.GREEN_BACKTEST_WINDOW_DAYS


def days_ago(n: int) -> str:
    return (TODAY - timedelta(days=n)).isoformat()


def qualified_backtest(n: int = 0) -> str:
    """三要素齐全的一条回测记录（n = 距今天数）。"""
    return (f"- {days_ago(n)} | 执行者：独立评审者（非本卡 Generator）"
            f" | 历史任务标识：夹具基线 {days_ago(n)} | 结论：保留\n")


WHITELIST = """{
  "_说明": "测试夹具白名单",
  "sources": [{"name": "GitHub（示例）", "type": "browser", "domains": ["github.com"]}]
}
"""

# 一份十一维全过的原始采集条目，作为各反向用例的单点扰动基线
GOOD_RAW_MD = """# 夹具条目

**URL:** <https://github.com/example/fixture>
**采集时间:** 2026-06-30T10:00:00+08:00
**采集命令:** 手动粘贴（夹具）
**原始来源:** github.com/example/fixture（夹具）

---

## 正文

正文内容。
"""

GOOD_RAW_JSON = """{
  "_metadata": {
    "source": "github",
    "URL": "https://github.com/example/fixture",
    "采集时间": "2026-06-30T10:00:00+08:00",
    "采集命令": "公开API（夹具）"
  },
  "items": [{"id": 1}]
}
"""

GOOD_CARD = f"""# 夹具蒸馏卡

---
- 落地状态: 🟢 已落地
---

## 规则

规则正文。

## 适用边界

前提：仅适用于零依赖治具可裁定的结构特征。

## 来源指针

- 原始采集/文章/sample_good_20260630.md

## 回测记录

{qualified_backtest()}"""

GOOD_INDEX = """# 目录

- [夹具条目](../原始采集/文章/sample_good_20260630.md)
"""

# 基线操作日志：三类操作各带非空「**命中:**」字段，使维度 11 在基线上执行而非 SKIP
GOOD_LOG = f"""# 操作日志

## [{days_ago(1)}] ingest | 夹具条目入库

- **命中:** 无命中（夹具库无 🟢 集，缺"入库价值判定"类规则）

## [{days_ago(0)}] lint | 夹具全量体检

- **命中:** 命中 夹具基线规则——按合格回测三要素改写夹具卡回测行
"""

# 采用态蒸馏卡：携带「- 落地指针:」字段，指向注入面声明的 memory 载体
ADOPTED_CARD = f"""# 夹具落地卡

---
- 落地状态: 🟢 已落地
- 落地指针: memory:feedback-fix.md
---

## 规则

规则正文。

## 适用边界

前提：仅适用于零依赖治具可裁定的结构特征。

## 来源指针

- 原始采集/文章/sample_good_20260630.md

## 回测记录

{qualified_backtest()}"""


def run_validator(root: Path, *extra: str):
    proc = subprocess.run(
        [sys.executable, str(VALIDATOR), str(root), *extra],
        capture_output=True, text=True, encoding="utf-8",
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


class FixtureCase(unittest.TestCase):
    """每个用例得到一份干净的基线知识库，只扰动被检验的那一维。"""

    def setUp(self):
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix="case-", dir=str(TMP_ROOT)))
        (self.root / "程序文件" / "配置").mkdir(parents=True)
        (self.root / "原始采集" / "文章").mkdir(parents=True)
        (self.root / "知识库").mkdir(parents=True)
        self.write("程序文件/配置/来源白名单.json", WHITELIST)
        self.write("原始采集/文章/sample_good_20260630.md", GOOD_RAW_MD)
        self.write("原始采集/文章/sample_data_20260630.json", GOOD_RAW_JSON)
        self.write("知识库/目录.md", GOOD_INDEX)
        self.write("知识库/操作日志.md", GOOD_LOG)
        self.write("知识库/蒸馏卡_fixture_20260630.md", GOOD_CARD)
        rc, out = run_validator(self.root)
        self.assertEqual(0, rc, f"基线夹具本身不干净，反向用例会失去意义：\n{out}")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def write(self, rel: str, text: str):
        fp = self.root / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(text, encoding="utf-8")
        return fp

    def assertError(self, rel: str, text: str, dimension: str):
        self.write(rel, text)
        rc, out = run_validator(self.root)
        self.assertEqual(1, rc, f"{rel} 的{dimension}违规未被拦下（退出码仍为 0）：\n{out}")
        self.assertIn(dimension, out, f"{rel} 未按{dimension}报错：\n{out}")

    def assertWarnOnly(self, rel: str, text: str, marker: str):
        self.write(rel, text)
        rc, out = run_validator(self.root)
        self.assertIn(marker, out, f"{rel} 未产生预期 WARN：\n{out}")
        self.assertEqual(0, rc, f"WARN 不应阻塞门禁，却返回非 0：\n{out}")


class TestPositiveBaseline(FixtureCase):

    def test_clean_fixture_passes(self):
        rc, out = run_validator(self.root)
        self.assertEqual(0, rc, out)
        self.assertIn("结果: PASS", out)

    def test_shipped_examples_pass(self):
        rc, out = run_validator(EXAMPLES)
        self.assertEqual(0, rc, f"仓库自带的 examples/ 应判 PASS：\n{out}")

    def test_coverage_denominator_comes_from_dimension_registry(self):
        rc, out = run_validator(self.root)
        self.assertEqual(0, rc, out)
        self.assertIn(f"required={len(validate.DIMENSIONS)}", out)

    def test_dimension_registry_matches_module_docstring(self):
        # 「被调用但不在任何账上」的维度使覆盖率账从完备枚举退化为部分枚举：
        # 登记表与 docstring 清单须逐项对齐，任一侧漏登记本用例即红
        listed = re.findall(r"^\s+(\d+)\. ", validate.__doc__, re.M)
        self.assertEqual([str(n) for n, _ in validate.DIMENSIONS], listed)


class TestNegativeDimensions(FixtureCase):

    def test_d1_missing_required_metadata_field(self):
        body = GOOD_RAW_MD.replace("**采集命令:** 手动粘贴（夹具）\n", "")
        self.assertError("原始采集/文章/sample_good_20260630.md", body, "元数据")

    def test_d2_replacement_character(self):
        self.assertError("原始采集/文章/sample_good_20260630.md",
                         GOOD_RAW_MD + "\n损坏字符 \ufffd 占位\n", "编码")

    def test_d2_double_encoded_mojibake(self):
        self.assertError("原始采集/文章/sample_good_20260630.md",
                         GOOD_RAW_MD + "\n签名串 瀹浠涓鑷鐢鍑鍒\n", "编码")

    def test_d3_markdown_without_h1(self):
        # 元数据块写在 H1 之前：真实发生过的偏差形态
        head, _, tail = GOOD_RAW_MD.partition("\n\n")
        self.assertError("原始采集/文章/sample_good_20260630.md",
                         tail.rstrip() + "\n\n" + head + "\n", "格式")

    def test_d3_markdown_without_separator(self):
        self.assertError("原始采集/文章/sample_good_20260630.md",
                         GOOD_RAW_MD.replace("\n---\n", "\n"), "格式")

    def test_d3_json_without_metadata_envelope(self):
        self.assertError("原始采集/文章/sample_data_20260630.json",
                         '[{"id": 1}, {"id": 2}]', "_metadata")

    def test_d3_json_unparseable(self):
        self.assertError("原始采集/文章/sample_data_20260630.json",
                         '{"_metadata": ', "JSON")

    def test_d5_broken_cross_reference(self):
        self.assertError("知识库/目录.md",
                         GOOD_INDEX + "- [断链](../原始采集/文章/missing_thing_20260630.md)\n",
                         "断链")

    def test_d7_card_missing_required_section(self):
        self.assertError("知识库/蒸馏卡_fixture_20260630.md",
                         GOOD_CARD.replace("## 来源指针", "## 其他"), "蒸馏卡")

    def test_d7_card_empty_required_section(self):
        body = GOOD_CARD.replace("前提：仅适用于零依赖治具可裁定的结构特征。", "")
        self.assertError("知识库/蒸馏卡_fixture_20260630.md", body, "为空")

    def test_d1_prose_mention_of_fields_is_not_registration(self):
        # 旧版全文子串检出：正文提一嘴三个字段名即可满足「元数据完整」——须拦下
        body = GOOD_RAW_MD.replace("**采集命令:** 手动粘贴（夹具）\n", "")
        body = body.replace("正文内容。",
                            "正文提到了 URL、采集时间、采集命令 三个词，但元数据区缺字段。")
        self.assertError("原始采集/文章/sample_good_20260630.md", body, "元数据")

    def test_d1_field_present_with_empty_value_errors(self):
        body = GOOD_RAW_MD.replace("**采集命令:** 手动粘贴（夹具）", "**采集命令:**")
        self.assertError("原始采集/文章/sample_good_20260630.md", body, "值为空")

    def test_d3_json_empty_metadata_envelope_errors(self):
        # `{"_metadata": {}}` 曾直接过关：空信封不证明任何来源登记
        self.assertError("原始采集/文章/sample_data_20260630.json",
                         '{"_metadata": {}}\n', "_metadata")

    def test_d1_json_metadata_missing_required_key_errors(self):
        body = GOOD_RAW_JSON.replace('"采集命令": "公开API（夹具）"', '"site": "github"')
        self.assertError("原始采集/文章/sample_data_20260630.json", body, "元数据")


class TestNonBlockingExemptions(FixtureCase):

    def test_d4_naming_is_warn_not_error(self):
        self.assertWarnOnly("原始采集/文章/no_date_suffix.md", GOOD_RAW_MD, "命名")

    def test_d4_naming_also_covers_raw_json(self):
        # 命名维度曾嵌在 .md 分支内，原始采集 JSON 逃逸该维度
        (self.root / "原始采集" / "文章" / "sample_data_20260630.json").unlink()
        self.assertWarnOnly("原始采集/文章/data_nodate.json", GOOD_RAW_JSON, "命名")

    def test_d6_unlisted_domain_is_warn_not_error(self):
        body = GOOD_RAW_MD.replace("https://github.com/example/fixture>",
                                   "https://evil.example.org/x>")
        self.assertWarnOnly("原始采集/文章/sample_good_20260630.md", body, "不在白名单")

    def test_binary_files_are_exempt_from_text_checks(self):
        (self.root / "原始采集" / "视频").mkdir(parents=True, exist_ok=True)
        (self.root / "原始采集" / "视频" / "sample_audio_20260630.mp3").write_bytes(b"\xff\xf1\x90\x00binary")
        rc, out = run_validator(self.root)
        self.assertEqual(0, rc, f"二进制应豁免文本校验，却被判失败：\n{out}")
        self.assertIn("[SKIP]", out)


class TestGreenBacktestStaleness(FixtureCase):
    """维度 10：🟢 到期由机器算日期锚点；补合格回测与诚实降级是两个等价出口。"""

    CARD = "知识库/蒸馏卡_fixture_20260630.md"

    def card_with(self, record: str, status: str = "🟢") -> str:
        body = GOOD_CARD.replace(qualified_backtest(), record)
        return body.replace("- 落地状态: 🟢 已落地", f"- 落地状态: {status} 夹具状态")

    def test_overdue_green_card_errors(self):
        self.assertError(self.CARD, self.card_with(qualified_backtest(WINDOW_DAYS + 1)),
                         "回测到期")

    def test_window_boundary_is_not_overdue(self):
        self.write(self.CARD, self.card_with(qualified_backtest(WINDOW_DAYS)))
        rc, out = run_validator(self.root)
        self.assertEqual(0, rc, f"窗口边界内的合格回测不应判到期：\n{out}")
        self.assertNotIn("回测到期", out)

    def test_dated_todo_does_not_reset_anchor(self):
        # 「有日期、无三要素」的一行曾可清零到期数：治具须按内容判，不按有没有写字判
        self.assertError(self.CARD, self.card_with(f"- {days_ago(0)} 待补回测\n"), "回测到期")

    def test_t0_self_check_is_not_a_backtest(self):
        record = qualified_backtest().replace("| 执行者", "| 落地自查（t0） | 执行者", 1)
        self.assertError(self.CARD, self.card_with(record), "回测到期")

    def test_missing_backtest_section_is_not_an_exemption(self):
        body = self.card_with("").replace("## 回测记录", "## 其他")
        self.assertError(self.CARD, body, "回测到期")

    def test_downgrade_remains_a_valid_exit(self):
        self.write(self.CARD, self.card_with("- 未回测，按诚实降级处理。\n", status="🟡"))
        rc, out = run_validator(self.root)
        self.assertEqual(0, rc, f"降级应是合法出口，却被判失败：\n{out}")
        self.assertNotIn("回测到期", out)

    def test_green_without_usable_anchor_is_warn_only(self):
        # 卡名无日期且无合格记录：不可判 ≠ 通过，须现身为 WARN 而非静默留在不可判区
        self.assertWarnOnly("知识库/蒸馏卡_无日期.md", self.card_with("- 未回测\n"),
                            "无可解日期锚点")

    def test_fenced_example_is_not_a_backtest_record(self):
        # 真实回测已过期，围栏里再贴一条「回测格式示例」不得把到期数清零为 0 天
        record = (qualified_backtest(WINDOW_DAYS + 1)
                  + "\n```markdown\n" + qualified_backtest(0) + "```\n")
        self.assertError(self.CARD, self.card_with(record), "回测到期")

    def test_empty_executor_cannot_swallow_next_field(self):
        # 无字段分隔符的一行里，空「执行者:」曾吞并紧随的「历史任务标识」值充当自身
        record = f"- {days_ago(0)} 执行者： 历史任务标识：任务X 结论：保留\n"
        self.assertError(self.CARD, self.card_with(record), "回测到期")

    def test_fullwidth_pipe_separated_record_counts(self):
        # 正向守卫：全角｜同为合法字段边界，否则严格化会误杀模板教出来的记录格式
        record = qualified_backtest().replace(" | ", " ｜ ")
        self.write(self.CARD, self.card_with(record))
        rc, out = run_validator(self.root)
        self.assertEqual(0, rc, f"全角分隔的合格记录被误判无效：\n{out}")
        self.assertNotIn("回测到期", out)


class TestAttributionHitField(FixtureCase):
    """维度 11：只裁字段有无与非空，WARN 不阻塞；日志缺失记 SKIP 而非静默 PASS。"""

    LOG = "知识库/操作日志.md"

    def entry(self, tail: str, kind: str = "query") -> str:
        return GOOD_LOG + f"\n## [{days_ago(0)}] {kind} | 追加条目\n{tail}"

    def test_missing_field_is_warn_not_error(self):
        self.assertWarnOnly(self.LOG, self.entry("查了，但没记命中。\n"), "归因命中")

    def test_empty_field_is_not_a_record(self):
        for field in ("**命中:**", "**命中：**", "**命中**:", "**命中**："):
            with self.subTest(field=field):
                self.assertWarnOnly(self.LOG, self.entry(f"- {field}   \n"), "归因命中")

    def test_prose_mention_is_not_a_record(self):
        self.assertWarnOnly(
            self.LOG, self.entry("按规范要求填写 **命中:** 字段，但此处并未登记。\n"),
            "归因命中")

    def test_fenced_example_cannot_substitute(self):
        for fence in ("```", "~~~~"):
            with self.subTest(fence=fence):
                body = self.entry(f"{fence}text\n**命中:** 无命中（示例）\n{fence}\n")
                self.assertWarnOnly(self.LOG, body, "归因命中")

    def test_three_legal_value_forms_pass(self):
        for value in ("命中 夹具基线规则——改为先核验三要素",
                      "无命中（缺「入库价值判定」类规则）",
                      "不适用：纯转录，无决策点"):
            with self.subTest(value=value):
                self.write(self.LOG, self.entry(f"- **命中:** {value}\n"))
                rc, out = run_validator(self.root)
                self.assertEqual(0, rc, out)
                self.assertNotIn("归因命中", out)

    def test_other_entry_cannot_supply_missing_field(self):
        body = (f"# 操作日志\n\n## [{days_ago(0)}] query | 第一项\n无字段\n"
                f"\n## [{days_ago(0)}] lint | 第二项\n- **命中:** 无命中（缺规则）\n")
        self.write(self.LOG, body)
        rc, out = run_validator(self.root)
        self.assertEqual(0, rc, out)
        self.assertIn("query 条目缺非空", out)
        self.assertNotIn("lint 条目缺非空", out)

    def test_unrelated_later_section_cannot_backfill(self):
        # 条目之后的无关同级章节（附录/说明段）里的字段曾替缺字段条目补上登记
        body = (GOOD_LOG + f"\n## [{days_ago(0)}] query | 缺字段条目\n执行了检索但未记命中。\n"
                f"\n## 附录：字段书写规范\n- **命中:** 无命中（这里是示例说明，不是登记）\n")
        self.write(self.LOG, body)
        rc, out = run_validator(self.root)
        self.assertEqual(0, rc, out)
        self.assertIn("query 条目缺非空", out)

    def test_missing_log_is_skip_not_silent_pass(self):
        (self.root / "知识库" / "操作日志.md").unlink()
        rc, out = run_validator(self.root)
        self.assertEqual(0, rc, out)
        self.assertIn("dimension_11_attribution_hit:操作日志.md_missing", out)
        self.assertIn("PASS_WITH_SKIP", out)


class TestAdoptionGate(FixtureCase):
    """未采用注入面机制的库：维度 8/9 记 SKIP(not_adopted)，不得报 ERROR。"""

    def test_unadopted_skips_dims_8_9_without_error(self):
        rc, out = run_validator(self.root)
        self.assertEqual(0, rc, f"未采用机制不应失败：\n{out}")
        self.assertIn("dimension_8_landing_ledger:not_adopted", out)
        self.assertIn("dimension_9_index_ledger:not_adopted", out)
        self.assertIn("PASS_WITH_SKIP", out)

    def test_unadopted_missing_ledger_warns_migration_hint(self):
        # 未采用旧实例：台账缺失不得沉默——WARN 迁移提示，但不得升 ERROR（门控初衷）
        ledger = self.root / "知识库" / "落地台账.md"
        if ledger.exists():
            ledger.unlink()
        rc, out = run_validator(self.root)
        self.assertEqual(0, rc, f"迁移提示为 WARN 级，不应失败：\n{out}")
        self.assertIn("台账缺失（机制未采用，迁移提示）", out)
        self.assertIn("--refresh-landing-ledger", out)
        self.assertIn("PASS_WITH_SKIP", out)

    def test_unadopted_refresh_generates_ledger_and_silences_hint(self):
        # refresh 不受门控：未采用旧实例可自救生成台账；生成后提示消失（防误报守卫）
        ledger = self.root / "知识库" / "落地台账.md"
        if ledger.exists():
            ledger.unlink()
        rc, out = run_validator(self.root, "--refresh-landing-ledger")
        self.assertEqual(0, rc, f"未采用实例跑 refresh 应可用：\n{out}")
        self.assertIn("[WRITE]", out)
        self.assertTrue(ledger.exists(), "refresh 应在未采用态下生成台账")
        rc, out = run_validator(self.root)
        self.assertEqual(0, rc, out)
        self.assertNotIn("迁移提示", out)
        self.assertIn("dimension_8_landing_ledger:not_adopted", out)


class AdoptedFixtureCase(FixtureCase):
    """采用态基线：注入面可达 + 带落地指针的 🟢 卡 + 已刷新台账，门禁全维 PASS。"""

    def setUp(self):
        super().setUp()
        # 基线卡未携带落地指针；采用态下它会触发 MISSING_FIELD，故替换为采用态卡
        (self.root / "知识库" / "蒸馏卡_fixture_20260630.md").unlink()
        mem = self.root / "程序文件" / "记忆" / "user"
        mem.mkdir(parents=True, exist_ok=True)
        (mem / "feedback-fix.md").write_text("# fix\n\n规则正文。\n", encoding="utf-8")
        (mem / "MEMORY.md").write_text("- [fix](feedback-fix.md)\n", encoding="utf-8")
        self.surface = {
            "platform_capability": {"auto_injection": True},
            "surfaces": [
                {"kind": "memory_dir", "scope": "user", "path": mem.as_posix()},
                {"kind": "memory_index", "scope": "user",
                 "path": (mem / "MEMORY.md").as_posix()},
            ],
            "hot_layer_cap": {"user": 40},
            "degradation": {"auto_injection_false": "HOT 不可达，memory 指针封顶 WARM"},
        }
        self.write_surface(self.surface)
        self.card_rel = "知识库/蒸馏卡_fix_20260630.md"
        self.write(self.card_rel, ADOPTED_CARD)
        self.write("知识库/目录.md", GOOD_INDEX + "- [落地卡](蒸馏卡_fix_20260630.md)\n")
        rc, out = run_validator(self.root, "--refresh-landing-ledger")
        self.assertEqual(0, rc, f"采用态基线刷新台账后应无 ERROR：\n{out}")
        rc, out = run_validator(self.root)
        self.assertEqual(0, rc, f"采用态基线本身不干净：\n{out}")
        self.assertIn("结果: PASS", out)

    def write_surface(self, surface):
        fp = self.root / "程序文件" / "配置" / "注入面.json"
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(json.dumps(surface, ensure_ascii=False, indent=2), encoding="utf-8")
        return fp

    def read_ledger(self):
        return (self.root / "知识库" / "落地台账.md").read_text(encoding="utf-8")

    def test_adopted_clean_passes_full(self):
        rc, out = run_validator(self.root)
        self.assertEqual(0, rc, out)
        self.assertIn("结果: PASS (所有校验通过)", out)

    def test_d8_missing_pointer_field_errors(self):
        self.write(self.card_rel, ADOPTED_CARD.replace("- 落地指针: memory:feedback-fix.md\n", ""))
        rc, out = run_validator(self.root)
        self.assertEqual(1, rc, out)
        self.assertIn("缺少「- 落地指针:」字段", out)

    def test_d8_invalid_pointer_syntax_errors(self):
        self.write(self.card_rel, ADOPTED_CARD.replace("memory:feedback-fix.md", "garbage"))
        rc, out = run_validator(self.root)
        self.assertEqual(1, rc, out)
        self.assertIn("落地指针语法无效", out)

    def test_d8_orphaned_pointer_under_green_errors(self):
        self.write(self.card_rel, ADOPTED_CARD.replace("feedback-fix.md", "nonexistent.md"))
        rc, out = run_validator(self.root)
        self.assertEqual(1, rc, out)
        self.assertIn("无存活落地载体", out)

    def test_d8_missing_ledger_errors(self):
        (self.root / "知识库" / "落地台账.md").unlink()
        rc, out = run_validator(self.root)
        self.assertEqual(1, rc, out)
        self.assertIn("落地台账缺失", out)

    def test_d8_refresh_regenerates_ledger(self):
        (self.root / "知识库" / "落地台账.md").unlink()
        rc, out = run_validator(self.root, "--refresh-landing-ledger")
        self.assertEqual(0, rc, out)
        ledger = self.read_ledger()
        self.assertIn("<!-- MACHINE-READABLE BEGIN -->", ledger)
        self.assertIn("verdict=HOT", ledger)

    def test_d8_refresh_refuses_linked_ledger(self):
        ledger = self.root / "知识库" / "落地台账.md"
        ledger.unlink()
        sentinel = self.root.parent / "outside-ledger.md"
        sentinel.write_text("must not change", encoding="utf-8")
        try:
            ledger.symlink_to(sentinel)
        except OSError as exc:
            self.skipTest(f"当前平台无法创建文件符号链接: {exc}")
        rc, out = run_validator(self.root, "--refresh-landing-ledger")
        self.assertEqual(1, rc, out)
        self.assertIn("安全写入被拒绝", out)
        self.assertEqual("must not change", sentinel.read_text(encoding="utf-8"))

    def test_d8_auto_injection_false_caps_warm(self):
        # 平台无常驻注入能力：HOT 不可达，memory 指针封顶 WARM——能力边界非缺陷，不得 ERROR
        self.surface["platform_capability"]["auto_injection"] = False
        self.write_surface(self.surface)
        rc, out = run_validator(self.root, "--refresh-landing-ledger")
        self.assertEqual(0, rc, out)
        self.assertIn("verdict=WARM", self.read_ledger())
        rc, out = run_validator(self.root)
        self.assertEqual(0, rc, f"封顶温层不应失败：\n{out}")
        self.assertIn("按需", self.read_ledger())

    def test_d8_missing_platform_capability_caps_warm_with_migration_hint(self):
        # 迁移期旧实例无 platform_capability 声明：保守封顶 WARM＋WARN 迁移提示，
        # 既不静默高判 HOT，也不沉默封顶
        del self.surface["platform_capability"]
        self.write_surface(self.surface)
        rc, out = run_validator(self.root, "--refresh-landing-ledger")
        self.assertEqual(0, rc, out)
        self.assertIn("verdict=WARM", self.read_ledger())
        rc, out = run_validator(self.root)
        self.assertEqual(0, rc, f"缺声明保守封顶不应失败：\n{out}")
        self.assertIn("[WARN]", out)
        self.assertIn("缺 platform_capability 声明", out)

    def test_d8_platform_capability_present_silences_migration_hint(self):
        # 负向守卫：声明存在时迁移提示不得出现，否则提示恒在、失去迁移指引力
        rc, out = run_validator(self.root)
        self.assertEqual(0, rc, out)
        self.assertNotIn("缺 platform_capability 声明", out)

    def test_d8_unreachable_surface_degrades_to_warn(self):
        # 注入面声明的 memory_dir 不可达（平台迁移）：UNVERIFIED + WARN，不得假 ERROR
        self.surface["surfaces"][0]["path"] = (self.root / "程序文件" / "记忆" / "gone").as_posix()
        self.write_surface(self.surface)
        rc, out = run_validator(self.root)
        self.assertEqual(0, rc, f"注入面不可达应降级为 WARN，却失败：\n{out}")
        self.assertIn("注入面不可达", out)
        self.assertIn("dimension_8_injection_surface:unreachable", out)

    def test_d9_index_ahead_of_ledger_errors(self):
        # 维度 9 反向：新卡入库并在目录.md 建立引用，但台账未刷新——目录引用了台账中
        # 不存在的卡，须 ERROR。维度 8 对此卡另报「台账未收录」（见
        # TestLandingLedgerDrift），本用例锚定维度 9 的文案不随之漂移。
        self.write("知识库/蒸馏卡_new_20260630.md", ADOPTED_CARD)
        self.write("知识库/目录.md",
                   GOOD_INDEX + "- [落地卡](蒸馏卡_fix_20260630.md)\n"
                   + "- [新卡](蒸馏卡_new_20260630.md)\n")
        rc, out = run_validator(self.root)
        self.assertEqual(1, rc, f"目录超前于台账应判 ERROR，却放行：\n{out}")
        self.assertIn("目录台账一致性", out)
        self.assertIn("但台账中不存在", out)

    def test_d8_required_read_file_is_warm(self):
        required = self.root / "程序文件" / "必读规范.md"
        required.write_text("# 必读\n", encoding="utf-8")
        self.surface["required_read_paths"] = [required.as_posix()]
        self.write_surface(self.surface)
        self.write(self.card_rel, ADOPTED_CARD.replace(
            "memory:feedback-fix.md", f"file:{required.as_posix()}"))
        rc, out = run_validator(self.root, "--refresh-landing-ledger")
        self.assertEqual(0, rc, out)
        self.assertIn("verdict=WARM", self.read_ledger())
        self.assertIn("layer=必读面", self.read_ledger())

    def test_d8_unlisted_file_is_doc_and_caps_green(self):
        document = self.root / "知识库" / "说明.md"
        document.write_text("# 说明\n", encoding="utf-8")
        yellow_card = ADOPTED_CARD.replace("🟢", "🟡").replace(
            "memory:feedback-fix.md", f"file:{document.as_posix()}")
        self.write(self.card_rel, yellow_card)
        rc, out = run_validator(self.root, "--refresh-landing-ledger")
        self.assertEqual(0, rc, out)
        self.assertIn("verdict=DOC", self.read_ledger())
        self.assertIn("layer=翻阅面", self.read_ledger())

        self.write(self.card_rel, yellow_card.replace("🟡", "🟢"))
        rc, out = run_validator(self.root)
        self.assertEqual(1, rc, out)
        self.assertIn("最强 file: 载体仍为翻阅面文档", out)


class TestCrossReferenceBoundary(FixtureCase):
    """维度 5 补充：锚点不是路径、必需入口不缺位、孤儿页可见。"""

    def test_anchor_link_is_not_a_broken_link(self):
        # `卡名.md#适用边界` 是合法章节引用，曾被整串当文件名判断链
        self.write("知识库/目录.md",
                   GOOD_INDEX + "- [夹具卡边界](蒸馏卡_fixture_20260630.md#适用边界)\n")
        rc, out = run_validator(self.root)
        self.assertEqual(0, rc, f"章节锚点引用被误判断链：\n{out}")
        self.assertNotIn("断链", out)

    def test_missing_index_md_is_reported_not_silently_skipped(self):
        # 旧注释称「目录.md 缺失由交叉引用检查报告」而对面没有实现——静默 return
        (self.root / "知识库" / "目录.md").unlink()
        rc, out = run_validator(self.root)
        self.assertEqual(1, rc, f"目录.md 缺失被静默放过：\n{out}")
        self.assertIn("必需入口", out)

    def test_unreferenced_page_surfaces_as_orphan_warn(self):
        body = "# 回填页\n\n一次 Query 的好答案。\n"
        self.assertWarnOnly("知识库/回填页.md", body, "孤儿页面")


class TestLandingLedgerDrift(AdoptedFixtureCase):
    """维度 8 反向：台账是 Query 第 1 步的规则集来源——状态漂移、未收录、幽灵行
    都会让降级规则继续以硬约束身份被消费，不能只比 verdict。"""

    CARD = "知识库/蒸馏卡_fix_20260630.md"

    def test_status_downgrade_without_refresh_errors(self):
        card = self.root / "知识库" / "蒸馏卡_fix_20260630.md"
        card.write_text(
            card.read_text(encoding="utf-8").replace("- 落地状态: 🟢", "- 落地状态: 🟡"),
            encoding="utf-8")
        rc, out = run_validator(self.root)
        self.assertEqual(1, rc, f"卡已降级 🟡 而台账仍记 🟢，未被发现：\n{out}")
        self.assertIn("台账状态 🟢 与卡内 🟡 不一致", out)

    def test_status_drift_resolved_by_refresh(self):
        # 修复路径可用性：刷新并提交后错误须消失，否则判据不可执行
        card = self.root / "知识库" / "蒸馏卡_fix_20260630.md"
        card.write_text(
            card.read_text(encoding="utf-8").replace("- 落地状态: 🟢", "- 落地状态: 🟡"),
            encoding="utf-8")
        rc, out = run_validator(self.root, "--refresh-landing-ledger")
        self.assertEqual(0, rc, out)
        self.assertIn("status=🟡", self.read_ledger())
        rc, out = run_validator(self.root)
        self.assertEqual(0, rc, f"刷新后状态漂移提示未消除：\n{out}")
        self.assertNotIn("台账状态", out)

    def test_new_card_absent_from_ledger_errors(self):
        self.write("知识库/蒸馏卡_new2_20260630.md", ADOPTED_CARD)
        rc, out = run_validator(self.root)
        self.assertEqual(1, rc, f"新卡未入台账被静默放过：\n{out}")
        self.assertIn("台账未收录该卡", out)

    def test_deleted_card_leaves_ghost_row_error(self):
        (self.root / "知识库" / "蒸馏卡_fix_20260630.md").unlink()
        self.write("知识库/目录.md", GOOD_INDEX)
        rc, out = run_validator(self.root)
        self.assertEqual(1, rc, f"卡已删除但台账仍记录，未被发现：\n{out}")
        self.assertIn("已无此文件", out)

    def test_pointer_delimiter_only_is_invalid_not_crash(self):
        # `- 落地指针: ;` 解析出空列表，旧版 min([]) 直接 ValueError 中断
        self.write(self.CARD,
                   ADOPTED_CARD.replace("- 落地指针: memory:feedback-fix.md",
                                        "- 落地指针: ;"))
        rc, out = run_validator(self.root)
        self.assertEqual(1, rc, f"异常输入应判规范 ERROR：\n{out}")
        self.assertIn("语法无效", out)
        self.assertNotIn("Traceback", out)

    def test_index_mention_is_not_index_reference(self):
        # 索引仅提到 `feedback-fix.md.old`（子串含 feedback-fix.md）不得判 HOT
        mem = self.root / "程序文件" / "记忆" / "user"
        (mem / "feedback-fix.md.old").write_text("# stale\n", encoding="utf-8")
        (mem / "MEMORY.md").write_text(
            "- [废弃备份，勿引用](feedback-fix.md.old)\n", encoding="utf-8")
        rc, out = run_validator(self.root, "--refresh-landing-ledger")
        self.assertEqual(0, rc, out)
        ledger = self.read_ledger()
        self.assertIn("verdict=WARM", ledger)
        self.assertNotIn("verdict=HOT", ledger, "提及不等于索引引用，HOT 判定失真")


if __name__ == "__main__":
    unittest.main(verbosity=2)
