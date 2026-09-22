#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
import uuid
from pathlib import Path

from release_contract import canonical_bytes, release_descriptor
from validate import refresh_landing_ledger

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, value: dict):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def require_empty_root(root: Path):
    if root.exists() and any(root.iterdir()):
        raise ValueError("实例根目录必须为空；初始化器不会接管或覆盖已有实例")
    root.mkdir(parents=True, exist_ok=True)


def read_policy(policy_id: str) -> tuple[dict, bytes]:
    path = PACKAGE_ROOT / "policies" / f"{policy_id}.json"
    try:
        raw = canonical_bytes(path.read_bytes())
        return json.loads(raw.decode("utf-8")), raw
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"策略不可读取: {exc}") from exc


def available_adapters() -> list[str]:
    root = PACKAGE_ROOT / "adapters"
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if (p / "adapter.json").is_file())


def load_adapter(adapter_id: str) -> dict:
    """适配器声明是 capabilities 与注入面模板的唯一机器来源：init 不硬编码任何平台字典或面结构。"""
    path = PACKAGE_ROOT / "adapters" / adapter_id / "adapter.json"
    try:
        adapter = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"适配器不可读取: {exc}") from exc
    if adapter.get("format") != "agent-wiki-adapter/v1" or adapter.get("id") != adapter_id:
        raise ValueError(f"适配器身份与目录不一致: {adapter_id}")
    if not isinstance(adapter.get("capabilities"), dict):
        raise ValueError(f"适配器缺少 capabilities 声明: {adapter_id}")
    if not isinstance(adapter.get("version"), str) or not adapter["version"]:
        raise ValueError(f"适配器缺少版本号: {adapter_id}")
    template = adapter.get("injection_surface_template")
    if not isinstance(template, str) or not template:
        raise ValueError(f"适配器缺少 injection_surface_template 声明: {adapter_id}")
    return adapter


def render_surface(adapter: dict, user_memory_dir: Path, project_memory_dir: Path) -> dict:
    """按适配器模板渲染注入面：占位符以 JSON 转义形态替换，残留占位符即报错而非静默发行不可达面。"""
    if not user_memory_dir.is_dir() or not project_memory_dir.is_dir():
        raise ValueError("user/project memory 目录必须已存在；初始化器不会创建平台记忆目录")
    rel = Path(adapter["injection_surface_template"])
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"适配器模板路径非法: {rel}")
    path = PACKAGE_ROOT / rel
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"适配器模板不可读取: {exc}") from exc
    values = {
        "<USER_MEMORY_DIR>": user_memory_dir.resolve(),
        "<PROJECT_MEMORY_DIR>": project_memory_dir.resolve(),
    }
    for placeholder, value in values.items():
        text = text.replace(placeholder, json.dumps(str(value), ensure_ascii=False)[1:-1])
    if re.search(r"<[A-Z_]+>", text):
        raise ValueError("适配器模板存在未替换占位符")
    try:
        surface = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"适配器模板不是合法 JSON: {exc}") from exc
    if not isinstance(surface, dict):
        raise ValueError("适配器模板必须是 JSON 对象")
    surface["platform_capability"] = adapter["capabilities"]
    return surface


def main():
    parser = argparse.ArgumentParser(description="初始化零内容 agent-wiki 实例")
    parser.add_argument("--root", type=Path, required=True, help="新的空实例根目录")
    parser.add_argument("--policy", default="core", choices=["core", "knowledge-collection-workflow"])
    parser.add_argument("--adapter", default="qoder", choices=available_adapters())
    parser.add_argument("--user-memory-dir", type=Path, required=True)
    parser.add_argument("--project-memory-dir", type=Path, required=True)
    parser.add_argument("--source-domain", action="append", required=True, help="允许采集的来源域名；可重复指定")
    parser.add_argument("--backup-directory", type=Path)
    args = parser.parse_args()

    root = args.root.resolve()
    # 只读预检全部前置（F08）：策略/适配器/记忆目录/模板/发行身份任何一步失败都
    # 不得留下半初始化目录——require_empty_root 拒绝接管非空目录，半途失败会让
    # 同一命令重试必败，用户只能手工清场。
    if args.policy == "knowledge-collection-workflow" and not args.backup_directory:
        parser.error("knowledge-collection-workflow 策略需要 --backup-directory")
    adapter = load_adapter(args.adapter)
    capabilities = adapter["capabilities"]
    policy, policy_bytes = read_policy(args.policy)
    surface = render_surface(adapter, args.user_memory_dir, args.project_memory_dir)
    release = release_descriptor(PACKAGE_ROOT)

    require_empty_root(root)

    raw_dir = root / "原始采集"
    wiki_dir = root / "知识库"
    config_dir = root / "程序文件" / "配置"
    raw_dir.mkdir(parents=True)
    wiki_dir.mkdir()
    config_dir.mkdir(parents=True)
    (raw_dir / "文章").mkdir()
    (raw_dir / "讨论").mkdir()
    (raw_dir / "视频").mkdir()

    policy_target = config_dir / "agent-wiki-policy.json"
    policy_target.write_bytes(policy_bytes)
    write_json(config_dir / "来源白名单.json", {"sources": [{"name": domain, "domains": [domain]} for domain in args.source_domain]})
    write_json(config_dir / "注入面.json", surface)

    lock_path = config_dir / "agent-wiki-release.lock.json"
    write_json(lock_path, {
        "format": "agent-wiki-release-lock/v1",
        "release_id": release["release_id"],
    })
    manifest = {
        "format": "agent-wiki-instance/v1",
        "instance_id": str(uuid.uuid4()),
        "layout": {"raw_sources": "原始采集", "wiki": "知识库", "config": "程序文件/配置", "schema": "项目规范.md"},
        "distribution": {"source": str(PACKAGE_ROOT), "lock": "程序文件/配置/agent-wiki-release.lock.json"},
        "policy": {"id": policy["id"], "version": policy["version"], "path": "程序文件/配置/agent-wiki-policy.json", "sha256": hashlib.sha256(policy_bytes).hexdigest()},
        "adapter": {"id": args.adapter, "version": adapter["version"], "config": "程序文件/配置/注入面.json"},
        "capabilities": capabilities,
        "policy_settings": {},
    }
    if args.backup_directory:
        manifest["policy_settings"] = {"backup": {"bundle_directory": str(args.backup_directory.resolve())}}
    write_json(config_dir / "agent-wiki-instance.json", manifest)

    (root / "项目规范.md").write_text("# Agent Wiki 实例规范\n\n<!-- PENDING-TTL BEGIN -->\n<!-- PENDING-TTL END -->\n", encoding="utf-8")
    (wiki_dir / "目录.md").write_text("# 知识库目录\n\n", encoding="utf-8")
    (wiki_dir / "操作日志.md").write_text("# 操作日志\n\n", encoding="utf-8")
    (wiki_dir / "采集经验.md").write_text("# 采集经验\n\n", encoding="utf-8")
    # 首版落地台账随初始化生成：台账是 Query 第 1 步的规则集来源，也是维度 8 的
    # 必查对象——init 不产它，新实例第一次门禁必 ERROR，恢复只能靠人记得 refresh。
    refresh_landing_ledger(root)
    print(config_dir / "agent-wiki-instance.json")


if __name__ == "__main__":
    main()
