#!/usr/bin/env python3
import argparse
import json
import shutil
from pathlib import Path

from release_contract import load_release_manifest, release_descriptor

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="构建不含实例内容的 agent-wiki 发行包")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error("输出目录必须为空；构建器不会覆盖已有技能包")
    output.mkdir(parents=True, exist_ok=True)

    manifest = load_release_manifest(PACKAGE_ROOT)
    for entry in manifest["include"]:
        source = PACKAGE_ROOT / entry
        target = output / entry
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    release = release_descriptor(PACKAGE_ROOT)
    (output / "release.json").write_text(
        json.dumps(release, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output / "release.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
