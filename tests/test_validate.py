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
        # 不存在的卡，须 ERROR。维度 8 对「台账缺该行」不反应（漂移检查仅在 committed
        # 行存在时触发），故此扰动单点落在维度 9。
        self.write("知识库/蒸馏卡_new_20260630.md", ADOPTED_CARD)
        self.write("知识库/目录.md",
                   GOOD_INDEX + "- [落地卡](蒸馏卡_fix_20260630.md)\n"
                   + "- [新卡](蒸馏卡_new_20260630.md)\n")
        rc, out = run_validator(self.root)
        self.assertEqual(1, rc, f"目录超前于台账应判 ERROR，却放行：\n{out}")
        self.assertIn("目录台账一致性", out)
        self.assertIn("但台账中不存在", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
