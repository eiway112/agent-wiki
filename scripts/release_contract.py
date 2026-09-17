#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_release_manifest(package_root: Path) -> dict:
    path = package_root / "release-manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"发行清单不可读取: {exc}") from exc
    if manifest.get("format") != "agent-wiki-release/v1":
        raise ValueError("不支持的发行 manifest 格式")
    if not isinstance(manifest.get("version"), str) or not manifest["version"]:
        raise ValueError("发行清单缺少版本号")
    if not isinstance(manifest.get("include"), list) or not manifest["include"]:
        raise ValueError("发行清单必须包含非空 include")
    return manifest


def release_files(package_root: Path, manifest: dict) -> dict[str, str]:
    excluded = set(manifest.get("exclude_content_roots", []))
    files = {}
    for entry in manifest["include"]:
        relative = Path(entry)
        if not isinstance(entry, str) or relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"发行清单包含非法路径: {entry}")
        if relative.parts and relative.parts[0] in excluded:
            raise ValueError(f"发行清单不得包含内容根目录: {entry}")
        key = relative.as_posix()
        if key in files:
            raise ValueError(f"发行清单存在重复文件: {entry}")
        source = package_root / relative
        if not source.is_file():
            raise ValueError(f"发行清单文件不存在: {entry}")
        files[key] = sha256(source)
    return files


def release_descriptor(package_root: Path) -> dict:
    manifest = load_release_manifest(package_root)
    descriptor = {
        "format": manifest["format"],
        "version": manifest["version"],
        "files": release_files(package_root, manifest),
        "content_excluded": manifest.get("exclude_content_roots", []),
    }
    encoded = json.dumps(descriptor, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    descriptor["release_id"] = hashlib.sha256(encoded).hexdigest()
    return descriptor
