#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""agent-wiki Evaluator 示例：知识库九维校验治具（零依赖，仅标准库）

用法:
    python scripts/validate.py <知识库根目录>
    python scripts/validate.py <知识库根目录> --refresh-landing-ledger

九维校验（结构层；判断层回测见 SKILL.md Lint 第 8 维，治具不覆盖）:
    1. 元数据完整性 — 原始采集文件须含 URL/采集时间/采集命令      (ERROR)
    2. 编码正确性   — UTF-8 可解码、无 U+FFFD、无双重编码签名      (ERROR)
    3. 格式规范性   — Markdown H1 开头、--- 分隔；JSON 须有 _metadata (ERROR)
    4. 命名规范     — 原始采集遵循 {source}_{topic}_{date}.{ext}   (WARN)
    5. 交叉引用     — Wiki 页面 Markdown 相对链接可达              (ERROR)
    6. 来源白名单   — 原始采集 URL 域名属于白名单                  (WARN)
    7. 蒸馏卡规范性 — 蒸馏卡必含非空「适用边界」「来源指针」章节    (ERROR)
    8. 落地台账一致性 — 蒸馏卡落地指针与注入面实况解析              (ERROR/WARN)
    9. 目录台账一致性 — 目录.md 引用的蒸馏卡与落地台账对账          (ERROR/WARN)

维度 8/9 的采用门控（声明决定义务，防跨平台假抽象）:
    知识库声明 程序文件/配置/注入面.json，或任一蒸馏卡携带「- 落地指针:」字段
    → 机制已采用，两维完整校验；两者皆无 → 两维记 SKIP(not_adopted) 并计入
    覆盖率账本，不报 ERROR。技能不假设任何平台具备常驻记忆注入能力。

降级语义（能力边界 ≠ 缺陷）:
    - 注入面路径不可达（平台迁移 / 占位符模板未填）→ 指针解析记 UNVERIFIED，
      维度记 SKIP，🟢 降 WARN「生效状态本次未核实」，不阻断提交；
    - platform_capability.auto_injection=false（平台无常驻注入能力）→ HOT 判定
      不可达，memory 指针封顶 WARM，证据行注明这是能力边界而非缺陷。

落地指针语法（多指针以 "; " 分隔）:
    - 落地指针: memory:<文件名>        → 在注入面声明的 memory_dir 中解析；
                                          同时被 memory_index 引用则为常驻热层
    - 落地指针: file:<绝对路径>[#锚点]  → 存在性解析（规范/Skill 等非驻留载体）
    - 落地指针: none                    → 无载体（🔵 参考索引）
判定阶梯（卡判定取最差指针，注入层级取最强指针）:
    INVALID < ORPHANED < NONE < WARM < HOT；另有 MISSING_FIELD、UNVERIFIED。

退出码: 0 = 无 ERROR 且无必需检查被跳过，1 = FAIL。WARN 不阻塞。
结果标签: 全维执行且无 ERROR → PASS；有可选检查被跳过且无 ERROR → PASS_WITH_SKIP
（附覆盖率与 skip 原因，不得表述为全维通过）；有 ERROR 或必需检查被跳过 → FAIL。
角色分离: 门禁路径只裁定，不修改任何文件；--refresh-landing-ledger 是唯一写
文件动作（生成 知识库/落地台账.md，台账禁止手编）。
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

RAW_DIR = "原始采集"
WIKI_DIR = "知识库"
WHITELIST_REL = Path("程序文件") / "配置" / "来源白名单.json"
SURFACES_REL = Path("程序文件") / "配置" / "注入面.json"
LEDGER_NAME = "落地台账.md"

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
POINTER_LINE_RE = re.compile(r"^-\s*落地指针:\s*(.+?)\s*$", re.M)
CARD_STATUS_RE = re.compile(r"^-\s*落地状态:\s*(🟢|🟡|🔵)", re.M)
VERDICT_RANK = {"INVALID": 0, "ORPHANED": 1, "NONE": 2, "WARM": 3, "HOT": 4}
MACHINE_BLOCK_RE = re.compile(
    r"<!-- MACHINE-READABLE BEGIN -->(.*?)<!-- MACHINE-READABLE END -->", re.S)


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


# ---------- 维度 8/9：注入面、落地指针与台账 ----------

def load_surfaces(root: Path):
    """加载运行时注入面声明（程序文件/配置/注入面.json）。

    注入面是「承担者自描述」文件：技能不假设任何平台路径，热层/温层的真实
    载体由每个实例自行声明。返回 (配置 dict 或 None, 跳过原因或 None)。
    路径不可达（平台迁移或占位符模板未填）时返回 unreachable，指针解析记
    UNVERIFIED 并降为 WARN，而不是让 🟢 在载体消失后继续静默生效。
    """
    p = root / SURFACES_REL
    if not p.exists():
        return None, "config_missing"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None, "config_unparsable"
    dirs = [s.get("path") for s in data.get("surfaces", [])
            if s.get("kind") == "memory_dir"]
    if not dirs or not all(Path(d).is_dir() for d in dirs):
        return data, "unreachable"
    return data, None


def iter_cards(root: Path):
    return sorted((root / WIKI_DIR).glob(CARD_PREFIX + "*.md"))


def mechanism_adopted(root: Path) -> bool:
    """维度 8/9 的采用门控：声明决定义务。

    采用信号 = 注入面.json 存在，或任一蒸馏卡携带「- 落地指针:」字段。
    未采用的知识库（如无热层机制的平台）两维记 SKIP(not_adopted)，不报 ERROR。
    """
    if (root / SURFACES_REL).exists():
        return True
    for c in iter_cards(root):
        try:
            if POINTER_LINE_RE.search(c.read_text(encoding="utf-8-sig")):
                return True
        except OSError:
            continue
    return False


def parse_pointers(content: str):
    """提取 `- 落地指针:` 行；缺失返回 None，`none` 返回 ["none"]。"""
    m = POINTER_LINE_RE.search(content)
    if not m:
        return None
    raw = m.group(1).strip()
    if raw == "none":
        return ["none"]
    return [t.strip() for t in raw.split(";") if t.strip()]


def resolve_pointer(token: str, surfaces: dict):
    """解析单个指针，返回 (判定, 注入层级, 证据)。"""
    if token == "none":
        return "NONE", "-", "声明无载体"
    auto_inject = surfaces.get("platform_capability", {}).get("auto_injection", True)
    if token.startswith("memory:"):
        name = token[len("memory:"):]
        if not name or "/" in name or "\\" in name:
            return "INVALID", "-", f"memory 指针须为纯文件名: {token}"
        for s in surfaces.get("surfaces", []):
            if s.get("kind") != "memory_dir":
                continue
            if (Path(s["path"]) / name).is_file():
                for ix in surfaces.get("surfaces", []):
                    if ix.get("kind") != "memory_index":
                        continue
                    ip = Path(ix["path"])
                    if ip.is_file() and name in ip.read_text(encoding="utf-8"):
                        if not auto_inject:
                            return "WARM", "按需", (
                                f"{name} 存在且被索引引用，但平台无常驻注入能力"
                                "（auto_injection=false），封顶温层——能力边界非缺陷")
                        return "HOT", "常驻", f"{name} 存在且被索引引用"
                return "WARM", "按需", f"{name} 存在但未被索引引用"
        return "ORPHANED", "-", f"所有 memory_dir 中均无 {name}"
    if token.startswith("file:"):
        path = token[len("file:"):].split("#", 1)[0]
        if Path(path).is_file():
            return "WARM", "按需", f"{path} 存在"
        return "ORPHANED", "-", f"{path} 不存在"
    return "INVALID", "-", f"无法识别的指针语法: {token}"


def card_landing_row(card: Path, surfaces) -> dict:
    """计算单张蒸馏卡的落地判定行（只读）。"""
    content = card.read_text(encoding="utf-8-sig")
    status_m = CARD_STATUS_RE.search(content)
    status = status_m.group(1) if status_m else "未标"
    pointers = parse_pointers(content)
    row = {"card": card.name, "status": status, "pointers": pointers,
           "verdict": "UNVERIFIED", "layer": "-", "evidence": ""}
    if pointers is None:
        row["verdict"] = "MISSING_FIELD"
        row["evidence"] = "缺少「- 落地指针:」字段"
        return row
    if surfaces is None:
        row["evidence"] = "注入面不可达，未解析"
        return row
    resolved = [resolve_pointer(t, surfaces) for t in pointers]
    worst = min(resolved, key=lambda v: VERDICT_RANK[v[0]])
    best = max(resolved, key=lambda v: VERDICT_RANK[v[0]])
    row["verdict"] = worst[0]
    row["layer"] = best[1]
    row["evidence"] = "; ".join(f"{t}→{v[0]}" for t, v in zip(pointers, resolved))
    return row


def refresh_landing_ledger(root: Path) -> str:
    """生成仓内 落地台账.md（含机器可读块与膨胀账本），返回注入面跳过原因或空串。

    这是本治具唯一写文件动作；门禁路径不触发，保持只读与提交确定性。
    台账禁止手编——手编即制造第二份漂移副本。
    """
    wiki = root / WIKI_DIR
    surfaces, surf_skip = load_surfaces(root)
    if surf_skip:
        # 注入面缺失/不可解析/载体不可达：一律视为不可核实，指针解析记 UNVERIFIED，
        # 而非让缺失的 memory_dir 把指针误判为 ORPHANED（诚实降级，不制造假 ERROR）。
        surfaces = None
    cards = iter_cards(root)
    rows = [card_landing_row(c, surfaces) for c in cards]

    # 膨胀账本：热层条目数 / 上限 / 孤儿数 / 待回测 🟢 数
    caps = (surfaces or {}).get("hot_layer_cap", {})
    index_lines = []
    over_cap = []
    for s in (surfaces or {}).get("surfaces", []):
        if s.get("kind") != "memory_index":
            continue
        ip = Path(s["path"])
        n = 0
        if ip.is_file():
            n = sum(1 for ln in ip.read_text(encoding="utf-8").splitlines()
                    if ln.startswith("- ["))
        key = s.get("scope", ip.parent.name)
        index_lines.append(f"- 热层条目 {key}: {n}")
        cap = caps.get(key)
        if cap and n > cap:
            over_cap.append(f"{key}={n}>{cap}")
    orphans = [r["card"] for r in rows if r["verdict"] == "ORPHANED"]
    pending_retest = []
    for c in cards:
        body = c.read_text(encoding="utf-8-sig")
        m = CARD_STATUS_RE.search(body)
        if m and m.group(1) == "🟢":
            if card_section_body(body, "回测记录") is None:
                pending_retest.append(c.name)

    lines = [
        "# 落地台账",
        "",
        "> 本文件由 validate.py 生成，禁止手编（手编即制造第二份漂移副本）。",
        "> 刷新命令: python scripts/validate.py <知识库根目录> --refresh-landing-ledger",
        "> 列义: 判定=该卡所有落地指针中最弱一档（保守口径，供台账↔实况漂移检测）；注入层级=最强指针所处实际生效层（常驻=热层/按需=温层）。二者取自同一组指针的不同聚合，故可并存（如判定 WARM、层级 常驻 = 一个指针仅温层、另一个已入热层）。",
        "> 判定档位由弱到强: INVALID(语法无效) < ORPHANED(指针失效) < NONE(声明无载体) < WARM(载体存在未入热层索引) < HOT(载体存在且已入热层索引)；另有 MISSING_FIELD(缺落地指针字段)、UNVERIFIED(注入面不可达未解析)。",
        f"- 生成时间: {datetime.now().isoformat(timespec='seconds')}",
        f"- 注入面可达: {'否（' + surf_skip + '）' if surf_skip else '是'}",
        f"- 孤儿指针数: {len(orphans)}",
        f"- 待回测🟢数: {len(pending_retest)}",
        f"- 热层超限: {'是（' + ', '.join(over_cap) + '）' if over_cap else '否'}",
        *index_lines,
        "",
        "| 蒸馏卡 | 状态 | 判定 | 注入层级 | 证据 |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['card']} | {r['status']} | {r['verdict']} | {r['layer']} | {r['evidence']} |")
    lines += ["", "<!-- MACHINE-READABLE BEGIN -->"]
    lines.append(f"surface_reachable={'no' if surf_skip else 'yes'}")
    for r in rows:
        lines.append(
            f"card={r['card']} status={r['status']} verdict={r['verdict']} "
            f"layer={r['layer']} pointers={'missing' if r['pointers'] is None else ';'.join(r['pointers'])}"
        )
    lines.append("<!-- MACHINE-READABLE END -->")
    (wiki / LEDGER_NAME).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return surf_skip or ""


def check_landing_consistency(root: Path, errors, warns, skip_reasons):
    """维度 8：只读裁定「卡内状态 ↔ 已提交台账 ↔ 注入面实况」三者一致性。

    门禁路径不调用 refresh（保持治具只读、提交确定性）；本函数直接对注入面
    做实况解析，因此平台迁移导致载体消失会在下一次 commit 立即暴露，而不是等 Lint。
    """
    surfaces, surf_skip = load_surfaces(root)
    if surf_skip:
        # 与 refresh_landing_ledger 同口径：注入面不可达即不可核实，指针记 UNVERIFIED，
        # 🟢 降 WARN，而非让缺失的 memory_dir 把指针误判为 ORPHANED 触发假 ERROR。
        surfaces = None
        skip_reasons.append(f"dimension_8_injection_surface:{surf_skip}")
    ledger = root / WIKI_DIR / LEDGER_NAME
    if not ledger.exists():
        errors.append(
            f"{WIKI_DIR}/{LEDGER_NAME}: 落地台账 — 落地台账缺失（注入面机制已采用）；"
            "运行 python scripts/validate.py <知识库根目录> --refresh-landing-ledger 生成并提交")
        return

    # 已提交台账的机器块
    m = MACHINE_BLOCK_RE.search(ledger.read_text(encoding="utf-8"))
    committed = {}
    ledger_reachable = None
    if m:
        for ln in m.group(1).splitlines():
            if ln.startswith("surface_reachable="):
                ledger_reachable = ln.split("=", 1)[1]
            elif ln.startswith("card="):
                kv = dict(p.split("=", 1) for p in ln.split(" ") if "=" in p)
                committed[kv["card"]] = kv

    for card in iter_cards(root):
        row = card_landing_row(card, surfaces)
        rel = f"{WIKI_DIR}/{card.name}"
        if row["verdict"] == "MISSING_FIELD":
            errors.append(
                f"{rel}: 落地台账 — 蒸馏卡缺少「- 落地指针:」字段"
                "（语法: memory:<文件名> / file:<绝对路径> / none，多指针以 ; 分隔）")
            continue
        if row["verdict"] == "INVALID":
            errors.append(f"{rel}: 落地台账 — 落地指针语法无效: {row['evidence']}")
            continue
        if row["verdict"] == "UNVERIFIED":
            # 注入面不可达：不阻断提交，但 🟢 不得继续表述为已核实生效
            if row["status"] == "🟢":
                warns.append(
                    f"{rel}: 落地台账 — 注入面不可达，🟢 生效状态本次未核实"
                    f"（{surf_skip or ''}）")
            continue
        resolved = VERDICT_RANK[
            max((resolve_pointer(t, surfaces) for t in row["pointers"]),
                key=lambda v: VERDICT_RANK[v[0]])[0]]
        if row["status"] == "🟢" and resolved < VERDICT_RANK["WARM"]:
            errors.append(
                f"{rel}: 落地台账 — 标 🟢 但无存活落地载体（判定 {row['verdict']}）；"
                f"{row['evidence']}；降级 🟡 并留 tombstone，或重建载体后刷新台账")
        elif row["status"] == "🟢" and row["verdict"] == "ORPHANED":
            warns.append(
                f"{rel}: 落地台账 — 🟢 含失效指针（另有存活载体）；{row['evidence']}；清理失效指针")
        elif row["status"] == "🔵" and row["pointers"] != ["none"]:
            warns.append(
                f"{rel}: 落地台账 — 🔵 参考索引却声明了落地载体；{row['evidence']}")
        # 台账与实况不一致（含平台迁移后未刷新）
        c = committed.get(card.name)
        if c and surfaces is not None and c.get("verdict") != row["verdict"]:
            errors.append(
                f"{rel}: 落地台账 — 台账判定 {c.get('verdict')} 与注入面实况 "
                f"{row['verdict']} 不一致；运行 --refresh-landing-ledger 刷新台账并提交")
    if ledger_reachable == "yes" and surf_skip:
        warns.append(
            f"{WIKI_DIR}/{LEDGER_NAME}: 落地台账 — 台账生成时注入面可达，本次不可达"
            f"（{surf_skip or ''}）")


def check_index_ledger_consistency(root: Path, errors, warns, skip_reasons):
    """维度 9：目录 ↔ 台账一致性。

    目录.md 中引用的蒸馏卡应在落地台账中存在；台账中的卡应在目录.md 中被引用。
    此维度封堵「目录.md 状态标记是手抄副本，下次降级会再漂移」的缺陷。
    """
    index_file = root / WIKI_DIR / "目录.md"
    ledger_file = root / WIKI_DIR / LEDGER_NAME
    if not index_file.exists():
        return  # 目录.md 缺失由交叉引用检查报告
    if not ledger_file.exists():
        return  # 台账缺失由维度 8 报告

    index_content = index_file.read_text(encoding="utf-8-sig")
    m = MACHINE_BLOCK_RE.search(ledger_file.read_text(encoding="utf-8"))
    ledger_cards = set()
    if m:
        for ln in m.group(1).splitlines():
            if ln.startswith("card="):
                kv = dict(p.split("=", 1) for p in ln.split(" ") if "=" in p)
                if "card" in kv:
                    ledger_cards.add(kv["card"])

    index_cards = set()
    for match in LINK_RE.finditer(index_content):
        card_name = Path(match.group(1)).name
        if card_name.startswith(CARD_PREFIX):
            index_cards.add(card_name)

    for card in sorted(index_cards - ledger_cards):
        errors.append(
            f"{WIKI_DIR}/目录.md: 目录台账一致性 — 目录.md 引用蒸馏卡 {card} 但台账中不存在；"
            "该卡可能未刷新台账或已删除，运行 --refresh-landing-ledger 刷新台账")
    for card in sorted(ledger_cards - index_cards):
        warns.append(
            f"{WIKI_DIR}/{card}: 目录台账一致性 — 蒸馏卡 {card} 在台账中存在但目录.md 未引用；"
            "应在目录.md 中建立引用")


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

    parser = argparse.ArgumentParser(
        description="agent-wiki 知识库治具 — 九维结构校验（含落地台账/目录一致性）")
    parser.add_argument("root", help="知识库根目录")
    parser.add_argument(
        "--refresh-landing-ledger", action="store_true",
        help="重新生成 知识库/落地台账.md（唯一写文件动作；默认门禁路径不触发，保持只读）")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"目录不存在: {root}", file=out)
        return 1

    whitelist, wl_skip = load_whitelist(root)
    # 跳过记账：每条形如 dimension_<n>_<name>:<reason>，覆盖率按冒号前的维度键去重。
    # 本脚本维度 6「来源白名单」与维度 8「注入面可达性」均为 WARN 级可选检查；
    # 跳过它们不得静默算 PASS（计入覆盖率），但不升级为 FAIL（无 ERROR 级维度可被跳过）。
    skip_reasons = []
    if wl_skip:
        skip_reasons.append(f"dimension_6_source_allowlist:{wl_skip}")
    required_checks = 9

    errors, warns = [], []
    files = sorted(
        p for p in root.rglob("*")
        if p.is_file() and ".git" not in p.parts
        and p.suffix.lower() in {".md", ".json"} | BINARY_EXTENSIONS
    )
    print(f"校验目标: {root}（{len(files)} 个文件，白名单{'已加载' if whitelist else '未配置/跳过'}）", file=out)
    for fp in files:
        check_file(fp, root, whitelist, errors, warns)

    # 维度 8/9 采用门控：注入面.json 存在 OR 任一蒸馏卡含「- 落地指针:」字段才生效，
    # 否则记 not_adopted 跳过——防跨平台假抽象（无落地指针约定的库不应被强判 ERROR）。
    if mechanism_adopted(root):
        if args.refresh_landing_ledger:
            refresh_landing_ledger(root)
            print(f"  [WRITE] {WIKI_DIR}/{LEDGER_NAME} 已重新生成", file=out)
        check_landing_consistency(root, errors, warns, skip_reasons)
        check_index_ledger_consistency(root, errors, warns, skip_reasons)
    else:
        skip_reasons.append("dimension_8_landing_ledger:not_adopted")
        skip_reasons.append("dimension_9_index_ledger:not_adopted")

    skipped_dims = {r.split(":")[0] for r in skip_reasons}
    skipped_checks = len(skipped_dims)
    executed_checks = required_checks - skipped_checks
    required_skipped = []  # 本脚本无 ERROR 级维度可被跳过；保留位供未来维度接入

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
