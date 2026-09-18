#!/usr/bin/env python3
import argparse
import hashlib
import json
import uuid
from pathlib import Path

from release_contract import canonical_bytes, release_descriptor

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


def load_adapter(adapter_id: str) -> dict:
    """适配器声明是 capabilities 的唯一机器来源：init 不硬编码任何平台能力字典。"""
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
    return adapter


def qoder_surface(user_memory_dir: Path, project_memory_dir: Path, capabilities: dict) -> dict:
    if not user_memory_dir.is_dir() or not project_memory_dir.is_dir():
        raise ValueError("Qoder user/project memory 目录必须已存在；初始化器不会创建平台记忆目录")
    return {
        "required_read_paths": [],
        "surfaces": [
            {"kind": "memory_dir", "scope": "user", "path": str(user_memory_dir.resolve())},
            {"kind": "memory_index", "scope": "user", "path": str((user_memory_dir / "MEMORY.md").resolve())},
            {"kind": "memory_dir", "scope": "project", "path": str(project_memory_dir.resolve())},
            {"kind": "memory_index", "scope": "project", "path": str((project_memory_dir / "MEMORY.md").resolve())},
        ],
        "hot_layer_cap": {"user": 40, "project": 30},
        "platform_capability": capabilities,
    }


def main():
    parser = argparse.ArgumentParser(description="初始化零内容 agent-wiki 实例")
    parser.add_argument("--root", type=Path, required=True, help="新的空实例根目录")
    parser.add_argument("--policy", default="core", choices=["core", "knowledge-collection-workflow"])
    parser.add_argument("--adapter", default="qoder", choices=["qoder"])
    parser.add_argument("--user-memory-dir", type=Path, required=True)
    parser.add_argument("--project-memory-dir", type=Path, required=True)
    parser.add_argument("--source-domain", action="append", required=True, help="允许采集的来源域名；可重复指定")
    parser.add_argument("--backup-directory", type=Path)
    args = parser.parse_args()

    root = args.root.resolve()
    require_empty_root(root)
    adapter = load_adapter(args.adapter)
    capabilities = adapter["capabilities"]
    policy, policy_bytes = read_policy(args.policy)
    if args.policy == "knowledge-collection-workflow" and not args.backup_directory:
        parser.error("knowledge-collection-workflow 策略需要 --backup-directory")

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
    write_json(config_dir / "注入面.json", qoder_surface(args.user_memory_dir, args.project_memory_dir, capabilities))

    release = release_descriptor(PACKAGE_ROOT)
    lock_path = config_dir / "agent-wiki-release.lock.json"
    write_json(lock_path, {
        "format": "agent-wiki-release-lock/v1",
        "source_path": str(PACKAGE_ROOT),
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
    print(config_dir / "agent-wiki-instance.json")


if __name__ == "__main__":
    main()
