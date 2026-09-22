#!/usr/bin/env python3
import argparse
import hashlib
import json
import sys
from pathlib import Path

from release_contract import canonical_bytes, release_descriptor

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
CONTENT_ROOTS = {"原始采集", "知识库"}
# release.json 由 build_release 成功时才落盘，故它的有无即「已构建发行副本 / 源仓工作树」
# 的机检标记。发行身份本身始终按 include 清单重算（release_descriptor 不读该文件）。
RELEASE_MARKER = "release.json"


def package_kind(root: Path) -> str:
    return "built-release" if (root / RELEASE_MARKER).is_file() else "source-working-tree"


def compared_against() -> dict:
    return {"path": str(PACKAGE_ROOT), "kind": package_kind(PACKAGE_ROOT)}


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
        inside = resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label}越出实例根目录") from exc
    # 首段检查必须对解析后的真实归属做：符号链接/重解析点的原始路径落在配置目录，
    # resolve() 后却可掉进 知识库/ ——只查原始首段时「不读取知识内容」承诺被绕过。
    for candidate in (path, inside):
        if candidate.parts and candidate.parts[0] in CONTENT_ROOTS:
            raise ValueError(f"{label}不得指向知识内容目录（含经链接解析后落入者）")
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
    lock_path = relative_path(root, distribution.get("lock"), "distribution.lock")
    lock = load_json(lock_path, "发行锁")
    release = release_descriptor(PACKAGE_ROOT)
    kind = package_kind(PACKAGE_ROOT)
    if lock.get("format") != "agent-wiki-release-lock/v1":
        raise ValueError("不支持的发行锁格式")
    if lock.get("release_id") != release["release_id"]:
        detail = (f"锁 {lock.get('release_id')}，比对对象 {release['release_id']}"
                  f"（{kind}: {PACKAGE_ROOT}）")
        if kind == "source-working-tree":
            # 不一致仍照实报 FAIL（检测力不降级），但归因不给：工作树不是发行物，
            # 它与锁不同只证明「尚未构建/交付」，锁钉的是发行副本身份，就只有发行
            # 副本能裁定锁是否失效——判据与约束必须同层。
            raise ValueError(
                "发行锁与本次比对对象的发行身份不一致: " + detail
                + "。本次比对对象是源仓工作树而非发行副本，此不一致无从裁定实例锁是否失效"
                "（工作树领先于实例所用副本属交付前常态）；要判锁是否失效，请从该实例实际"
                "使用的发行副本重跑本校验器。")
        raise ValueError("发行锁与本发行副本的发行身份不一致: " + detail)
    migration_notes = []
    if "source_path" in lock:
        migration_notes.append(
            "发行锁仍带 source_path（旧格式机器局部键，已不参与校验）："
            "建议手工删除该键或重建实例")

    policy_info = manifest.get("policy")
    if not isinstance(policy_info, dict):
        raise ValueError("实例 manifest 缺少 policy")
    policy_path = relative_path(root, policy_info.get("path"), "policy.path")
    policy_bytes = canonical_bytes(policy_path.read_bytes())
    policy_hash = hashlib.sha256(policy_bytes).hexdigest()
    if policy_hash != policy_info.get("sha256"):
        raise ValueError("策略文件哈希与实例 manifest 不一致")
    policy = load_json(policy_path, "实例策略")
    policy_id = policy_info.get("id")
    if policy.get("id") != policy_id or policy.get("version") != policy_info.get("version"):
        raise ValueError("策略身份与实例 manifest 不一致")
    policy_rel = f"policies/{policy_id}.json"
    if policy_rel not in release["files"]:
        raise ValueError(f"实例策略不在发行清单内: {policy_rel}")
    if release["files"][policy_rel] != policy_hash:
        raise ValueError("实例策略与发行源策略不一致")

    return {
        "status": "PASS",
        "release_id": release["release_id"],
        "compared_against": {"path": str(PACKAGE_ROOT), "kind": kind},
        "checked": [
            "release-manifest include files",
            "instance manifest",
            "release lock",
            "instance policy",
            "release files map",
        ],
        "migration_notes": migration_notes,
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
        # 报告自带比对对象：任何 FAIL 结论都可被追溯到「拿哪份包比的呢」，
        # 拿源仓工作树比出来的不一致因此无法被抄成实例锁失效。
        payload = {"status": "FAIL", "error": str(exc), "compared_against": compared_against()}
        if args.report == "json":
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    if args.report == "json":
        print(json.dumps(report, ensure_ascii=False))
    else:
        print(f"PASS: {report['release_id']}")
        compared = report["compared_against"]
        print(f"  比对对象: {compared['kind']} {compared['path']}")
        for note in report["migration_notes"]:
            print(f"  [MIGRATION] {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
