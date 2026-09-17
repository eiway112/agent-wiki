#!/usr/bin/env python3
import argparse
import hashlib
import json
import sys
from pathlib import Path

from release_contract import release_descriptor

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
CONTENT_ROOTS = {"原始采集", "知识库"}


def load_json(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label}不可读取: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label}必须是 JSON 对象")
    return value


def relative_path(root: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label}必须是非空相对路径")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label}包含非法路径")
    resolved = (root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label}越出实例根目录") from exc
    if path.parts and path.parts[0] in CONTENT_ROOTS:
        raise ValueError(f"{label}不得指向知识内容目录")
    return resolved


def validate(instance_path: Path) -> dict:
    instance_path = instance_path.resolve()
    manifest = load_json(instance_path, "实例 manifest")
    if manifest.get("format") != "agent-wiki-instance/v1":
        raise ValueError("不支持的实例 manifest 格式")

    root = instance_path.parents[2]
    layout = manifest.get("layout")
    if not isinstance(layout, dict) or layout.get("config") != "程序文件/配置":
        raise ValueError("实例 manifest 的 layout.config 必须为 程序文件/配置")
    config_dir = relative_path(root, layout["config"], "layout.config")
    if instance_path.parent != config_dir:
        raise ValueError("实例 manifest 必须位于 layout.config 目录")

    distribution = manifest.get("distribution")
    if not isinstance(distribution, dict):
        raise ValueError("实例 manifest 缺少 distribution")
    source = distribution.get("source")
    if not isinstance(source, str) or Path(source).resolve() != PACKAGE_ROOT:
        raise ValueError("实例 distribution.source 与执行的发行源不一致")
    lock_path = relative_path(root, distribution.get("lock"), "distribution.lock")
    lock = load_json(lock_path, "发行锁")
    release = release_descriptor(PACKAGE_ROOT)
    if lock != {
        "format": "agent-wiki-release-lock/v1",
        "source_path": str(PACKAGE_ROOT),
        "release_id": release["release_id"],
    }:
        raise ValueError("发行锁与源仓发行身份不一致")

    policy_info = manifest.get("policy")
    if not isinstance(policy_info, dict):
        raise ValueError("实例 manifest 缺少 policy")
    policy_path = relative_path(root, policy_info.get("path"), "policy.path")
    policy_bytes = policy_path.read_bytes()
    policy_hash = hashlib.sha256(policy_bytes).hexdigest()
    if policy_hash != policy_info.get("sha256"):
        raise ValueError("策略文件哈希与实例 manifest 不一致")
    policy = load_json(policy_path, "实例策略")
    policy_id = policy_info.get("id")
    if policy.get("id") != policy_id or policy.get("version") != policy_info.get("version"):
        raise ValueError("策略身份与实例 manifest 不一致")
    source_policy = PACKAGE_ROOT / "policies" / f"{policy_id}.json"
    if not source_policy.is_file() or source_policy.read_bytes() != policy_bytes:
        raise ValueError("实例策略与发行源策略不一致")

    return {
        "status": "PASS",
        "release_id": release["release_id"],
        "checked": [
            "release-manifest include files",
            "instance manifest",
            "release lock",
            "instance policy",
            "source policy",
        ],
        "content_roots_read": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 agent-wiki 实例发行锁；不读取知识内容")
    parser.add_argument("--instance", type=Path, required=True)
    parser.add_argument("--report", choices=["text", "json"], default="text")
    args = parser.parse_args()
    try:
        report = validate(args.instance)
    except ValueError as exc:
        if args.report == "json":
            print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    if args.report == "json":
        print(json.dumps(report, ensure_ascii=False))
    else:
        print(f"PASS: {report['release_id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
