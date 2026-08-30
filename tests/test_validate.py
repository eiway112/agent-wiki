#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/validate.py 的红绿双向回归治具。

正向：examples/ 须判 PASS（退出码 0）。
反向：结构层七维各造一次违规，须被判 ERROR（退出码 1）且报出对应维度——
      只会亮绿灯的治具等于没有治具。
豁免项：命名与来源白名单属 WARN，违规时退出码仍须为 0，防门禁把常态豁免误判为失败。

零依赖（仅标准库）。跑法：
    python -m unittest discover -s tests -v
    python tests/test_validate.py
夹具写在仓库内 .tmp/，不污染系统临时目录，用例结束即删。
"""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATOR = REPO_ROOT / "scripts" / "validate.py"
EXAMPLES = REPO_ROOT / "examples"
TMP_ROOT = REPO_ROOT / ".tmp" / "lint-fixtures"

WHITELIST = """{
  "_说明": "测试夹具白名单",
  "sources": [{"name": "GitHub（示例）", "type": "browser", "domains": ["github.com"]}]
}
"""

# 一份七维全过的原始采集条目，作为各反向用例的单点扰动基线
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

GOOD_CARD = """# 夹具蒸馏卡

---
- 落地状态: 🟢 已落地
---

## 规则

规则正文。

## 适用边界

前提：仅适用于零依赖治具可裁定的结构特征。

## 来源指针

- 原始采集/文章/sample_good_20260630.md
"""

GOOD_INDEX = """# 目录

- [夹具条目](../原始采集/文章/sample_good_20260630.md)
"""


def run_validator(root: Path):
    proc = subprocess.run(
        [sys.executable, str(VALIDATOR), str(root)],
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
