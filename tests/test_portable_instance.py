import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
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


if __name__ == "__main__":
    unittest.main()
