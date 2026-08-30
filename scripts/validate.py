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

退出码: 0 = PASS（无 ERROR），1 = FAIL。WARN 不阻塞。
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
    p = root / WHITELIST_REL
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        domains = set()
        for s in d.get("sources", []):
            domains.update(s.get("domains", []))
        return domains
    except (json.JSONDecodeError, OSError):
        return None


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
        # 维度 4：命名（知识库结构化文件豁免）
        if is_raw and not NAME_RE.match(fp.name):
            warns.append(f"{rel}: 命名 — 不符合 {{source}}_{{topic}}_{{date}}.{{ext}}")
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

    whitelist = load_whitelist(root)
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
    if errors:
        print(f"结果: FAIL ({len(errors)} 个错误)", file=out)
        return 1
    print("结果: PASS (所有校验通过)", file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
