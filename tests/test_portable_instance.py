import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "scripts"))
from release_contract import release_descriptor  # noqa: E402
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}
INIT = PACKAGE_ROOT / "scripts" / "init_instance.py"
BUILD = PACKAGE_ROOT / "scripts" / "build_release.py"
VALIDATE = PACKAGE_ROOT / "scripts" / "validate.py"
LOCK_VALIDATE = PACKAGE_ROOT / "scripts" / "validate_release_lock.py"


class PortableInstanceTest(unittest.TestCase):
    def setUp(self):
        fixture_root = PACKAGE_ROOT / ".tmp" / "portable-instance-fixtures"
        fixture_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=fixture_root)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.user_memory = self.base / "user-memory"
        self.project_memory = self.base / "project-memory"
        self.user_memory.mkdir()
        self.project_memory.mkdir()
        (self.user_memory / "MEMORY.md").write_text("# user\n", encoding="utf-8")
        (self.project_memory / "MEMORY.md").write_text("# project\n", encoding="utf-8")
        self.root = self.base / "instance"

    def initialize(self, init=INIT, root=None):
        return subprocess.run([
            "python", str(init), "--root", str(root or self.root), "--policy", "core",
            "--user-memory-dir", str(self.user_memory),
            "--project-memory-dir", str(self.project_memory),
            "--source-domain", "example.org",
        ], capture_output=True, text=True, encoding="utf-8", env=ENV)

    @property
    def manifest_path(self):
        return self.root / "程序文件" / "配置" / "agent-wiki-instance.json"

    def lock_check(self, validator=LOCK_VALIDATE, manifest=None):
        return subprocess.run([
            "python", str(validator), "--instance", str(manifest or self.manifest_path), "--report", "json",
        ], capture_output=True, text=True, encoding="utf-8", env=ENV)

    def test_empty_instance_passes_core_policy_and_release_lock(self):
        self.assertEqual(self.initialize().returncode, 0)
        result = subprocess.run([
            "python", str(VALIDATE), str(self.root), "--refresh-landing-ledger",
        ], capture_output=True, text=True, encoding="utf-8", env=ENV)
        self.assertEqual(result.returncode, 0, result.stderr + "\n" + result.stdout)
        lock = self.lock_check()
        self.assertEqual(lock.returncode, 0, lock.stderr)
        report = json.loads(lock.stdout)
        self.assertEqual(report["content_roots_read"], [])

    def test_release_lock_does_not_require_knowledge_directories(self):
        self.assertEqual(self.initialize().returncode, 0)
        for name in ("原始采集", "知识库"):
            target = self.root / name
            for path in sorted(target.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
                else:
                    path.rmdir()
            target.rmdir()
        result = self.lock_check()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_policy_hash_tampering_is_rejected(self):
        self.assertEqual(self.initialize().returncode, 0)
        policy = self.root / "程序文件" / "配置" / "agent-wiki-policy.json"
        policy.write_text("{}\n", encoding="utf-8")
        result = self.lock_check()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["status"], "FAIL")

    def test_release_lock_tampering_is_rejected(self):
        self.assertEqual(self.initialize().returncode, 0)
        lock = self.root / "程序文件" / "配置" / "agent-wiki-release.lock.json"
        data = json.loads(lock.read_text(encoding="utf-8"))
        data["release_id"] = "0" * 64
        lock.write_text(json.dumps(data), encoding="utf-8")
        result = self.lock_check()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["status"], "FAIL")

    def test_initializer_refuses_nonempty_root(self):
        self.root.mkdir()
        (self.root / "foreign-content.md").write_text("must not be touched", encoding="utf-8")
        result = self.initialize()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("必须为空", result.stderr)
        self.assertTrue((self.root / "foreign-content.md").is_file())

    def test_release_build_is_content_free_and_runnable(self):
        release = self.base / "release"
        build = subprocess.run(["python", str(BUILD), "--output", str(release)], capture_output=True, text=True, encoding="utf-8", env=ENV)
        self.assertEqual(build.returncode, 0, build.stderr)
        self.assertTrue((release / "release.json").is_file())
        for forbidden in ("原始采集", "知识库", ".qoder", "memory"):
            self.assertFalse((release / forbidden).exists())

        instance = self.base / "released-instance"
        initialize = self.initialize(release / "scripts" / "init_instance.py", instance)
        self.assertEqual(initialize.returncode, 0, initialize.stderr)
        lock_validator = release / "scripts" / "validate_release_lock.py"
        manifest = instance / "程序文件" / "配置" / "agent-wiki-instance.json"
        lock = self.lock_check(lock_validator, manifest)
        self.assertEqual(lock.returncode, 0, lock.stderr)

        (release / "policies" / "core.json").write_text("{}\n", encoding="utf-8")
        tampered = self.lock_check(lock_validator, manifest)
        self.assertNotEqual(tampered.returncode, 0)
        self.assertEqual(json.loads(tampered.stdout)["status"], "FAIL")

    def test_release_build_refuses_existing_output_directory(self):
        release = self.base / "release"
        release.mkdir()
        result = subprocess.run(["python", str(BUILD), "--output", str(release)],
                                capture_output=True, text=True, encoding="utf-8", env=ENV)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((release / "release.json").exists())

    def test_release_build_refuses_output_link(self):
        sentinel = self.base / "sentinel"
        sentinel.mkdir()
        release = self.base / "release"
        try:
            release.symlink_to(sentinel, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"当前平台无法创建目录符号链接: {exc}")
        result = subprocess.run(["python", str(BUILD), "--output", str(release)],
                                capture_output=True, text=True, encoding="utf-8", env=ENV)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((sentinel / "release.json").exists())

    def test_lock_survives_source_checkout_eol_change(self):
        # 跨机模拟：实例在 CRLF 形态的源仓检出下初始化，校验发生在同内容 LF 形态检出下；零内容漂移须 PASS
        release = self.base / "release"
        build = subprocess.run(["python", str(BUILD), "--output", str(release)], capture_output=True, text=True, encoding="utf-8", env=ENV)
        self.assertEqual(build.returncode, 0, build.stderr)
        policy = release / "policies" / "core.json"
        policy.write_bytes(policy.read_bytes().replace(b"\n", b"\r\n"))
        instance = self.base / "released-instance"
        initialize = self.initialize(release / "scripts" / "init_instance.py", instance)
        self.assertEqual(initialize.returncode, 0, initialize.stderr)
        policy.write_bytes(policy.read_bytes().replace(b"\r\n", b"\n"))
        manifest = instance / "程序文件" / "配置" / "agent-wiki-instance.json"
        lock = self.lock_check(release / "scripts" / "validate_release_lock.py", manifest)
        self.assertEqual(lock.returncode, 0, lock.stderr)


class ReleaseManifestSelfConsistencyTest(unittest.TestCase):
    """发行清单是手工枚举的白名单：漏列即静默不发行，故须有机核守卫而非靠记得。"""

    MUST_SHIP = ("SKILL.md", "LICENSE.md")
    REF_RE = re.compile(r"`([^`\s]+)`|\]\(([^)\s]+)\)")

    def setUp(self):
        manifest = json.loads((PACKAGE_ROOT / "release-manifest.json").read_text(encoding="utf-8"))
        self.include = set(manifest["include"])
        self.content_roots = set(manifest.get("exclude_content_roots", []))

    def unshipped_pointers(self, include):
        dead = []
        for rel in sorted(include):
            path = PACKAGE_ROOT / rel
            if path.suffix != ".md":
                continue
            for backtick, link in self.REF_RE.findall(path.read_text(encoding="utf-8")):
                token = (backtick or link).strip("./")
                if not token or "{" in token:
                    continue
                target = PACKAGE_ROOT / token
                if target.is_file():
                    if token not in include:
                        dead.append(f"{rel} -> {token}")
                elif target.is_dir():
                    # 目录形自指：包内该目录须至少存在一个发行物，否则宣称即死引用；
                    # 实例内容根是架构概念而非包内指针，豁免。
                    if token in self.content_roots:
                        continue
                    if not any(i == token or i.startswith(token + "/") for i in include):
                        dead.append(f"{rel} -> {token}/")
        return dead

    def test_release_contract_refuses_linked_source_file(self):
        fixture_root = PACKAGE_ROOT / ".tmp" / "release-contract-fixtures"
        fixture_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=fixture_root) as temporary:
            package = Path(temporary) / "package"
            package.mkdir()
            (package / "release-manifest.json").write_text(
                json.dumps({"format": "agent-wiki-release/v1", "version": "1", "include": ["payload.md"]}),
                encoding="utf-8")
            sentinel = Path(temporary) / "outside.md"
            sentinel.write_text("must not ship", encoding="utf-8")
            try:
                (package / "payload.md").symlink_to(sentinel)
            except OSError as exc:
                self.skipTest(f"当前平台无法创建文件符号链接: {exc}")
            with self.assertRaises(ValueError):
                release_descriptor(package)

    def test_must_ship_files_are_included(self):
        for name in self.MUST_SHIP:
            self.assertIn(name, self.include, f"{name} 属必发物，漏列 include 即静默不发行")

    def test_shipped_docs_point_only_to_shipped_paths(self):
        self.assertEqual(
            [], self.unshipped_pointers(self.include),
            "发行文档正文指向仓内存在但未发行的路径，包内即死链")

    def test_guard_fails_on_dropped_include_entry(self):
        # 负向注入：摘掉一项发行物，守卫须报出指向它的死链，否则本守卫为空跑
        shrunk = set(self.include)
        shrunk.discard("references/rule-template.md")
        self.assertIn(
            "SKILL.md -> references/rule-template.md",
            self.unshipped_pointers(shrunk))

    def test_examples_tree_fully_shipped(self):
        # SKILL.md 宣称 examples/ 为可跑最小样本：全树漏列即静默不发行，宣称在包内即死引用
        shipped = {p.relative_to(PACKAGE_ROOT).as_posix()
                   for p in (PACKAGE_ROOT / "examples").rglob("*") if p.is_file()}
        self.assertTrue(shipped)
        self.assertEqual(set(), shipped - self.include)

    def test_guard_fails_on_dropped_examples_directory(self):
        # 负向注入：摘光 examples/ 发行物，目录形自指须报死链，否则目录形判据为空跑
        shrunk = {i for i in self.include if not i.startswith("examples/")}
        self.assertIn("SKILL.md -> examples/", self.unshipped_pointers(shrunk))


class ReleaseIdentityEolInvarianceTest(unittest.TestCase):
    """release_id 须为提交内容的纯函数：同内容不同换行形态产出同一身份，否则跨机零内容漂移误报锁不一致。"""

    def setUp(self):
        fixture_root = PACKAGE_ROOT / ".tmp" / "release-contract-fixtures"
        fixture_root.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=fixture_root)
        self.addCleanup(temporary.cleanup)
        self.package = Path(temporary.name) / "package"
        self.package.mkdir()
        (self.package / "release-manifest.json").write_text(
            json.dumps({"format": "agent-wiki-release/v1", "version": "1", "include": ["payload.md"]}),
            encoding="utf-8")

    def descriptor_id(self, payload: bytes) -> str:
        (self.package / "payload.md").write_bytes(payload)
        return release_descriptor(self.package)["release_id"]

    def test_release_id_invariant_across_line_endings(self):
        lf = self.descriptor_id("# t\nline one\nline two\n".encode("utf-8"))
        crlf = self.descriptor_id("# t\r\nline one\r\nline two\r\n".encode("utf-8"))
        mixed = self.descriptor_id("# t\r\nline one\nline two\r\n".encode("utf-8"))
        self.assertEqual(lf, crlf)
        self.assertEqual(lf, mixed)

    def test_release_id_still_tracks_content(self):
        # 负向守卫：归一不得抹平真实内容差异，否则不变性恒真、测试空跑
        base = self.descriptor_id("# t\nline one\n".encode("utf-8"))
        changed = self.descriptor_id("# t\nline 1\n".encode("utf-8"))
        self.assertNotEqual(base, changed)


if __name__ == "__main__":
    unittest.main()
