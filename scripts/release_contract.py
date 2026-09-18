#!/usr/bin/env python3
import getpass
import hashlib
import json
import os
import re
import stat
from pathlib import Path


def _is_reparse_point(path: Path) -> bool:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise ValueError(f"路径不可读取: {path}: {exc}") from exc
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def canonical_bytes(data: bytes) -> bytes:
    """发行身份须为提交内容的纯函数：换行归一 LF 后再哈希，否则同一提交在不同 eol 检出下产出不同 release_id。"""
    return data.replace(b"\r\n", b"\n")


def _read_regular_file(path: Path, label: str) -> bytes:
    if _is_reparse_point(path):
        raise ValueError(f"{label}不得为符号链接或重解析点: {path}")
    try:
        info = os.stat(path)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"{label}必须是普通文件: {path}")
        with path.open("rb") as handle:
            return canonical_bytes(handle.read())
    except OSError as exc:
        raise ValueError(f"{label}不可读取: {path}: {exc}") from exc


def _safe_release_file(package_root: Path, entry: object, excluded: set[str]) -> tuple[str, Path]:
    if not isinstance(entry, str):
        raise ValueError(f"发行清单包含非法路径: {entry}")
    relative = Path(entry)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"发行清单包含非法路径: {entry}")
    if relative.parts and relative.parts[0] in excluded:
        raise ValueError(f"发行清单不得包含内容根目录: {entry}")

    current = package_root
    for part in relative.parts:
        current /= part
        if _is_reparse_point(current):
            raise ValueError(f"发行清单文件不得经由符号链接或重解析点: {entry}")
    return relative.as_posix(), current


def load_release_manifest(package_root: Path) -> dict:
    path = package_root / "release-manifest.json"
    try:
        manifest = json.loads(_read_regular_file(path, "发行清单").decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"发行清单不可读取: {exc}") from exc
    if manifest.get("format") != "agent-wiki-release/v1":
        raise ValueError("不支持的发行 manifest 格式")
    if not isinstance(manifest.get("version"), str) or not manifest["version"]:
        raise ValueError("发行清单缺少版本号")
    if not isinstance(manifest.get("include"), list) or not manifest["include"]:
        raise ValueError("发行清单必须包含非空 include")
    return manifest


def release_snapshot(package_root: Path) -> tuple[dict, dict[str, bytes]]:
    manifest = load_release_manifest(package_root)
    excluded = set(manifest.get("exclude_content_roots", []))
    files = {}
    for entry in manifest["include"]:
        key, source = _safe_release_file(package_root, entry, excluded)
        if key in files:
            raise ValueError(f"发行清单存在重复文件: {entry}")
        files[key] = _read_regular_file(source, f"发行清单文件 {entry}")
    return manifest, files


def release_files(package_root: Path, manifest: dict) -> dict[str, str]:
    excluded = set(manifest.get("exclude_content_roots", []))
    files = {}
    for entry in manifest["include"]:
        key, source = _safe_release_file(package_root, entry, excluded)
        if key in files:
            raise ValueError(f"发行清单存在重复文件: {entry}")
        files[key] = hashlib.sha256(_read_regular_file(source, f"发行清单文件 {entry}")).hexdigest()
    return files


def release_descriptor_from_snapshot(manifest: dict, files: dict[str, bytes]) -> dict:
    descriptor = {
        "format": manifest["format"],
        "version": manifest["version"],
        "files": {name: hashlib.sha256(content).hexdigest() for name, content in files.items()},
        "content_excluded": manifest.get("exclude_content_roots", []),
    }
    encoded = json.dumps(descriptor, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    descriptor["release_id"] = hashlib.sha256(encoded).hexdigest()
    return descriptor


def release_descriptor(package_root: Path) -> dict:
    manifest, files = release_snapshot(package_root)
    return release_descriptor_from_snapshot(manifest, files)


# 机器局部指向一旦随包发行，「跨平台/异机/异用户」宣称即假；盘符 lookbehind 排除
# http:// 等协议前缀（冒号前字母的前驱为字母数字时不判）。
# 主目录两探针以拼接拆开连续字面量：本文件自身随包发行，字面量连续即自命中。
_PORTABILITY_PATTERNS = (
    (re.compile(rb"(?<![A-Za-z0-9])[A-Za-z]:[\\/]"), "盘符路径"),
    (re.compile(rb"/" + rb"Users/[^/\s]"), "macOS 用户主目录"),
    (re.compile(rb"/" + rb"home/[^/\s]"), "POSIX 用户主目录"),
)


def portability_violations(files: dict[str, bytes]) -> list[str]:
    """扫随包文件内容，返回机器局部指向命中列表；空列表 = 可移植。"""
    probes = list(_PORTABILITY_PATTERNS)
    user = getpass.getuser()
    if len(user) >= 3:
        probes.append((re.compile(re.escape(user.encode("utf-8"))), "当前用户名"))
    violations = []
    for name in sorted(files):
        content = files[name]
        for pattern, label in probes:
            if pattern.search(content):
                violations.append(f"{name}: {label}")
    return violations
