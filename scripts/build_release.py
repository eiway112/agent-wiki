#!/usr/bin/env python3
import argparse
import json
import os
import stat
from pathlib import Path

from release_contract import release_descriptor_from_snapshot, release_snapshot

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def _exists_or_link(path: Path) -> bool:
    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    return True


def _assert_plain_directory_chain(path: Path, label: str):
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            info = os.lstat(current)
        except OSError as exc:
            raise ValueError(f"{label}不可读取: {current}: {exc}") from exc
        if stat.S_ISLNK(info.st_mode) or bool(
                getattr(info, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
            raise ValueError(f"{label}不得经由符号链接或重解析点: {current}")
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError(f"{label}必须是目录: {current}")


def _write_new(path: Path, content: bytes):
    with path.open("xb") as handle:
        handle.write(content)


def main() -> int:
    parser = argparse.ArgumentParser(description="构建不含实例内容的 agent-wiki 发行包")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    output = args.output.absolute()
    if _exists_or_link(output):
        parser.error("输出目录必须不存在；构建器不会覆盖已有技能包")
    if not output.parent.is_dir():
        parser.error("输出目录的父目录必须已存在")
    try:
        _assert_plain_directory_chain(output.parent, "输出目录父路径")
        manifest, files = release_snapshot(PACKAGE_ROOT)
        output.mkdir()
        for entry, content in files.items():
            target = output / entry
            target.parent.mkdir(parents=True, exist_ok=True)
            _assert_plain_directory_chain(target.parent, "发行输出路径")
            _write_new(target, content)
        release = release_descriptor_from_snapshot(manifest, files)
        _write_new(output / "release.json", (
            json.dumps(release, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(output / "release.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
