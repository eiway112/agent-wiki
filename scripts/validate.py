#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""agent-wiki Evaluator 示例：知识库七维校验治具（零依赖，仅标准库）

用法:
    python scripts/validate.py <知识库根目录>

七维校验（结构层；判断层回测见 SKILL.md Lint 第 8 维，治具不覆盖）:
    1. 元数据完整性 — 原始采集文件须含 URL/采集时间/采集命令      (ERROR)
    2. 编码正确性   — UTF-8 可解码、无 U+FFFD、无双重编码签名      (ERROR)
    3. 格式规范性   — Markdown H1 开头、--- 分隔；JSON 须有 _metadata (ERROR)
    4. 命名规范     — 原始采集遵循 {source}_{topic}_{date}.{ext}   (WARN)
    5. 交叉引用     — Wiki 页面 Markdown 相对链接可达              (ERROR)
    6. 来源白名单   — 原始采集 URL 域名属于白名单                  (WARN)
    7. 蒸馏卡规范性 — 蒸馏卡必含非空「适用边界」「来源指针」章节    (ERROR)

退出码: 0 = 无 ERROR 且无必需检查被跳过，1 = FAIL。WARN 不阻塞。
结果标签: 全维执行且无 ERROR → PASS；有可选检查被跳过且无 ERROR → PASS_WITH_SKIP
（附覆盖率与 skip 原因，不得表述为全维通过）；有 ERROR 或必需检查被跳过 → FAIL。
角色分离: 本脚本只做裁定，不修改任何文件。
"""

import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

RAW_DIR = "原始采集"
WIKI_DIR = "知识库"
WHITELIST_REL = Path("程序文件") / "配置" / "来源白名单.json"

REQUIRED_META = ("URL", "采集时间", "采集命令")
BINARY_EXTENSIONS = {
    ".mp3", ".mp4", ".wav", ".m4a", ".flac", ".aac",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp",
    ".pdf", ".zip",
}
# GB18030 双重编码常见签名（随真实数据校准，遵循 Harness 递减原则增删）
MOJIBAKE_SIGNS = set("瀹浠涓鏃鑷鐢鍑鍒銆锛鈥鑻鑺搷浣绋搴")
NAME_RE = re.compile(r"^[a-z]+_.+_\d{8}\.\w+$")
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)#\s][^)]*)\)")
CARD_PREFIX = "蒸馏卡_"
CARD_REQUIRED_SECTIONS = ("适用边界", "来源指针")


def card_section_body(content: str, name: str):
    """返回蒸馏卡 `## name` 章节的正文（strip 后）；章节缺失返回 None。"""
    m = re.search(rf"^##\s*{name}\s*$", content, re.M)
    if not m:
        return None
    rest = content[m.end():]
    nxt = re.search(r"^##\s", rest, re.M)
    return (rest[: nxt.start()] if nxt else rest).strip()


def load_whitelist(root: Path):
    """返回 (域名集合或 None, 跳过原因或 None)。

    跳过必须显式记账：白名单缺失时维度 6 整体不执行，调用方须把原因计入
    skip_reasons 并在汇总中输出覆盖率，禁止静默算 PASS（2026-09-15 整改，
    对应第三方审计「SKIP 被汇总为 PASS」发现）。
    """
    p = root / WHITELIST_REL
    if not p.exists():
        return None, "source_allowlist_missing"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        domains = set()
        for s in d.get("sources", []):
            domains.update(s.get("domains", []))
        if not domains:
            return None, "source_allowlist_empty"
        return domains, None
    except (json.JSONDecodeError, OSError):
        return None, "source_allowlist_unparsable"


def check_file(fp: Path, root: Path, whitelist, errors, warns):
    rel = fp.relative_to(root)
    parts = rel.parts
    is_raw = parts and parts[0] == RAW_DIR
    is_wiki = parts and parts[0] == WIKI_DIR
    suffix = fp.suffix.lower()

    # 二进制豁免文本校验
    if suffix in BINARY_EXTENSIONS:
        print(f"  [SKIP] {rel}（二进制）")
        return

    raw_bytes = fp.read_bytes()
    try:
        content = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        errors.append(f"{rel}: 编码 — 无法按 UTF-8 解码")
        return

    # 维度 2：编码
    if "\ufffd" in content:
        errors.append(f"{rel}: 编码 — 含替换字符 U+FFFD")
    sig_hits = sum(1 for ch in content if ch in MOJIBAKE_SIGNS)
    if sig_hits > 5:
        errors.append(f"{rel}: 编码 — 疑似 GB18030 双重编码乱码（签名命中 {sig_hits}）")

    # 维度 4：命名（知识库结构化文件豁免；二进制已在函数开头跳过）
    if is_raw and not NAME_RE.match(fp.name):
        warns.append(f"{rel}: 命名 — 不符合 {{source}}_{{topic}}_{{date}}.{{ext}}")

    if suffix == ".md":
        # 维度 3：格式（仅原始采集强制 H1 + 分隔线；Wiki 结构化页面豁免）
        if is_raw:
            if not content.lstrip().startswith("# "):
                errors.append(f"{rel}: 格式 — Markdown 须以 H1 开头")
            if "---" not in content[:2000]:
                errors.append(f"{rel}: 格式 — 元数据与正文须以 --- 分隔（前 2000 字符内）")
            # 维度 1：元数据
            for field in REQUIRED_META:
                if field not in content:
                    errors.append(f"{rel}: 元数据 — 缺少必需字段「{field}」")
            # 维度 6：来源白名单
            m = re.search(r"https?://[^\s<>)\]]+", content[:2000])
            if whitelist is not None and m:
                host = urlparse(m.group(0)).netloc.lower()
                if not any(host == d or host.endswith("." + d) for d in whitelist):
                    warns.append(f"{rel}: 来源 — URL 域名 {host} 不在白名单")
        # 维度 5：交叉引用（Wiki 页面的相对链接）
        if is_wiki:
            for target in LINK_RE.findall(content):
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                if not (fp.parent / target).resolve().exists():
                    errors.append(f"{rel}: 交叉引用 — 断链 [{target}]")
        # 维度 7：蒸馏卡规范性（语义要求下沉为结构特征，治具裁定）
        if fp.name.startswith(CARD_PREFIX):
            for sec in CARD_REQUIRED_SECTIONS:
                body = card_section_body(content, sec)
                if body is None:
                    errors.append(f"{rel}: 蒸馏卡 — 缺少必需章节「{sec}」")
                elif not body:
                    errors.append(f"{rel}: 蒸馏卡 — 章节「{sec}」为空")
    elif suffix == ".json":
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            errors.append(f"{rel}: 格式 — JSON 解析失败: {e}")
            return
        if is_raw and not (isinstance(data, dict) and "_metadata" in data):
            errors.append(f"{rel}: 格式 — 原始采集 JSON 须含 _metadata 字段")


def main():
    # 统一输出流：Windows 控制台/管道默认非 UTF-8，重配置编码后所有 print 共用同一缓冲，
    # 避免自建 TextIOWrapper 与 sys.stdout 争用 fd 导致部分报告行丢失
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    out = sys.stdout
    if len(sys.argv) < 2:
        print("用法: python scripts/validate.py <知识库根目录>", file=out)
        return 1
    root = Path(sys.argv[1]).resolve()
    if not root.is_dir():
        print(f"目录不存在: {root}", file=out)
        return 1

    whitelist, wl_skip = load_whitelist(root)
    # 跳过记账：维度名 → 是否必需（必需=该维度在本脚本口径下可判 ERROR）。
    # 本脚本维度 6「来源白名单」为 WARN 级，属可选检查；跳过它不得静默算 PASS，
    # 但也不升级为 FAIL（必需检查被跳过才 FAIL，见汇总段）。
    skip_reasons = []
    if wl_skip:
        skip_reasons.append(f"dimension_6_source_allowlist:{wl_skip}")
    required_checks = 7
    skipped_checks = 1 if wl_skip else 0
    executed_checks = required_checks - skipped_checks
    required_skipped = []  # 本脚本无 ERROR 级维度可被跳过；保留位供未来维度接入

    errors, warns = [], []
    files = sorted(
        p for p in root.rglob("*")
        if p.is_file() and ".git" not in p.parts
        and p.suffix.lower() in {".md", ".json"} | BINARY_EXTENSIONS
    )
    print(f"校验目标: {root}（{len(files)} 个文件，白名单{'已加载' if whitelist else '未配置/跳过'}）", file=out)
    for fp in files:
        check_file(fp, root, whitelist, errors, warns)

    for w in warns:
        print(f"  [WARN] {w}", file=out)
    for e in errors:
        print(f"  [ERROR] {e}", file=out)
    print("=" * 60, file=out)
    print(f"总问题数: {len(errors) + len(warns)} (ERROR: {len(errors)}, WARN: {len(warns)})", file=out)
    coverage = executed_checks / required_checks
    print(
        f"覆盖率: required={required_checks} executed={executed_checks} "
        f"skipped={skipped_checks} coverage_ratio={coverage:.3f}", file=out
    )
    for reason in skip_reasons:
        print(f"  [SKIP] {reason}", file=out)
    if errors:
        print(f"结果: FAIL ({len(errors)} 个错误)", file=out)
        return 1
    if required_skipped:
        print(f"结果: FAIL (必需检查被跳过: {', '.join(required_skipped)})", file=out)
        return 1
    if skipped_checks:
        print(f"结果: PASS_WITH_SKIP (coverage {executed_checks}/{required_checks}，非全维通过)", file=out)
        return 0
    print("结果: PASS (所有校验通过)", file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
