import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "scripts"))
from release_contract import portability_violations, release_descriptor, release_snapshot  # noqa: E402
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

    def initialize(self, init=INIT, root=None, adapter="qoder"):
        return subprocess.run([
            "python", str(init), "--root", str(root or self.root), "--policy", "core",
            "--adapter", adapter,
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

    def test_lock_passes_after_package_path_change(self):
        # F1 回归：异机/异路径携带实例只要 release_id 相同须 PASS；
        # 旧判据把锁绑死 init 时包路径，携带实例在此必败
        release_a = self.base / "release-a"
        build = subprocess.run(["python", str(BUILD), "--output", str(release_a)],
                               capture_output=True, text=True, encoding="utf-8", env=ENV)
        self.assertEqual(build.returncode, 0, build.stderr)
        instance = self.base / "carried-instance"
        initialize = self.initialize(release_a / "scripts" / "init_instance.py", instance)
        self.assertEqual(initialize.returncode, 0, initialize.stderr)
        release_b = self.base / "release-b"
        shutil.copytree(release_a, release_b)
        manifest = instance / "程序文件" / "配置" / "agent-wiki-instance.json"
        lock = self.lock_check(release_b / "scripts" / "validate_release_lock.py", manifest)
        self.assertEqual(lock.returncode, 0, lock.stderr)

    def test_old_lock_with_source_path_is_tolerated_with_migration_note(self):
        self.assertEqual(self.initialize().returncode, 0)
        lock_path = self.root / "程序文件" / "配置" / "agent-wiki-release.lock.json"
        data = json.loads(lock_path.read_text(encoding="utf-8"))
        data["source_path"] = "/old/machine/package"
        lock_path.write_text(json.dumps(data), encoding="utf-8")
        result = self.lock_check()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(any("source_path" in n for n in report["migration_notes"]))
        text = subprocess.run(
            ["python", str(LOCK_VALIDATE), "--instance", str(self.manifest_path)],
            capture_output=True, text=True, encoding="utf-8", env=ENV)
        self.assertIn("[MIGRATION]", text.stdout)

    def test_new_lock_carries_no_source_path(self):
        self.assertEqual(self.initialize().returncode, 0)
        lock = json.loads(
            (self.root / "程序文件" / "配置" / "agent-wiki-release.lock.json").read_text(encoding="utf-8"))
        self.assertEqual({"format", "release_id"}, set(lock))

    def test_init_plain_adapter_renders_template_and_capability(self):
        root = self.base / "plain-instance"
        result = self.initialize(root=root, adapter="plain")
        self.assertEqual(result.returncode, 0, result.stderr)
        surface = json.loads(
            (root / "程序文件" / "配置" / "注入面.json").read_text(encoding="utf-8"))
        self.assertFalse(surface["platform_capability"]["auto_injection"])
        paths = [s["path"] for s in surface["surfaces"]]
        self.assertIn(str(self.user_memory.resolve()), paths)
        for text in paths:
            self.assertNotIn("<", text, "占位符残留即注入面不可达，不得静默发行")
        manifest = json.loads(
            (root / "程序文件" / "配置" / "agent-wiki-instance.json").read_text(encoding="utf-8"))
        self.assertEqual("plain", manifest["adapter"]["id"])
        self.assertEqual(manifest["capabilities"], surface["platform_capability"])

    def test_plain_adapter_instance_caps_warm_end_to_end(self):
        # F2 完整性：第二适配器 auto_injection=false → init 后治具把 memory 指针封顶
        # WARM，证明适配器层真数据驱动、诚实降级通路端到端可达
        from test_validate import ADOPTED_CARD, GOOD_INDEX, GOOD_LOG, GOOD_RAW_MD
        root = self.base / "plain-instance"
        initialize = self.initialize(root=root, adapter="plain")
        self.assertEqual(initialize.returncode, 0, initialize.stderr)
        config = root / "程序文件" / "配置"
        (config / "来源白名单.json").write_text(
            json.dumps({"sources": [{"name": "github", "domains": ["github.com"]}]}, ensure_ascii=False),
            encoding="utf-8")
        (root / "原始采集" / "文章" / "sample_good_20260630.md").write_text(GOOD_RAW_MD, encoding="utf-8")
        (root / "知识库" / "蒸馏卡_fix_20260630.md").write_text(ADOPTED_CARD, encoding="utf-8")
        (root / "知识库" / "目录.md").write_text(
            GOOD_INDEX + "- [落地卡](蒸馏卡_fix_20260630.md)\n", encoding="utf-8")
        (root / "知识库" / "操作日志.md").write_text(GOOD_LOG, encoding="utf-8")
        (self.user_memory / "feedback-fix.md").write_text("# fix\n\n规则正文。\n", encoding="utf-8")
        (self.user_memory / "MEMORY.md").write_text("- [fix](feedback-fix.md)\n", encoding="utf-8")
        refresh = subprocess.run(
            ["python", str(VALIDATE), str(root), "--refresh-landing-ledger"],
            capture_output=True, text=True, encoding="utf-8", env=ENV)
        self.assertEqual(refresh.returncode, 0, refresh.stderr + "\n" + refresh.stdout)
        ledger = (root / "知识库" / "落地台账.md").read_text(encoding="utf-8")
        self.assertIn("verdict=WARM", ledger)
        self.assertIn("按需", ledger)
        self.assertNotIn("verdict=HOT", ledger, "auto_injection=false 时 HOT 不可达，台账不得高判")

    def test_unknown_adapter_rejected(self):
        result = self.initialize(root=self.base / "x-instance", adapter="nosuch")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid choice", result.stderr)

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


class PackagePortabilityGuardTest(unittest.TestCase):
    """随包文件混入机器局部指向即构建被拒：跨平台/异机/异用户宣称须有机检兜底，不靠人记得扫。

    负向注入取两层：守卫函数逐类探针须命中（防空跑）；整包复制后污染副本、
    跑副本自带构建器须拒绝（build_release 的 PACKAGE_ROOT 恒为自身所在包，
    对假包注入不走构建路径，属测试缺陷而非守卫缺陷）。
    """

    def setUp(self):
        fixture_root = PACKAGE_ROOT / ".tmp" / "portability-guard-fixtures"
        fixture_root.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=fixture_root)
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.include = json.loads(
            (PACKAGE_ROOT / "release-manifest.json").read_text(encoding="utf-8"))["include"]

    def copied_package(self) -> Path:
        package = self.base / "package"
        for rel in self.include:
            target = package / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((PACKAGE_ROOT / rel).read_bytes())
        return package

    def test_current_package_has_no_machine_local_pointer(self):
        _, files = release_snapshot(PACKAGE_ROOT)
        self.assertEqual([], portability_violations(files))

    def test_violations_flag_each_machine_local_pattern(self):
        # 负向注入：逐类探针须命中，否则守卫空跑
        cases = {
            "盘符路径": b"# t\nsee C:\\Users\\x\\notes\n",
            "macOS 用户主目录": b"# t\nsee /Users/alice/x\n",
            "POSIX 用户主目录": b"# t\nsee /home/bob/y\n",
        }
        for label, payload in cases.items():
            with self.subTest(label=label):
                hits = portability_violations({"payload.md": payload})
                self.assertEqual([f"payload.md: {label}"], hits)

    def test_violations_flag_current_username(self):
        user = getpass.getuser()
        if len(user) < 3:
            self.skipTest("当前用户名过短，探针不启用")
        hits = portability_violations({"payload.md": f"# t\nowner: {user}\n".encode("utf-8")})
        self.assertEqual(["payload.md: 当前用户名"], hits)

    def test_violations_ignore_protocol_prefix(self):
        # 负向守卫：http(s):// 等合法内容不得误伤，否则盘符判据过宽、构建不可用
        self.assertEqual([], portability_violations({"payload.md": b"# t\n<https://example.org/a>\n"}))

    def test_build_refuses_tainted_package_copy(self):
        package = self.copied_package()
        skill = package / "SKILL.md"
        skill.write_bytes(skill.read_bytes() + b"\nsee C:\\Users\\x\\notes\n")
        result = subprocess.run(
            ["python", str(package / "scripts" / "build_release.py"), "--output", str(self.base / "out")],
            capture_output=True, text=True, encoding="utf-8", env=ENV)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("机器局部指向", result.stderr)
        self.assertFalse((self.base / "out" / "release.json").exists())


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

    def test_all_adapter_files_shipped(self):
        # 适配器或其模板漏列 include 即静默不发行：消费端按 SKILL.md 选适配器时声明即死引用
        adapters_root = PACKAGE_ROOT / "adapters"
        adapter_dirs = sorted(p for p in adapters_root.iterdir() if p.is_dir())
        self.assertTrue(adapter_dirs)
        for adapter_dir in adapter_dirs:
            adapter_rel = f"adapters/{adapter_dir.name}/adapter.json"
            self.assertIn(adapter_rel, self.include, f"{adapter_rel} 漏列即适配器静默不发行")
            adapter = json.loads((PACKAGE_ROOT / adapter_rel).read_text(encoding="utf-8"))
            template = adapter["injection_surface_template"]
            self.assertIn(template, self.include, f"{template} 漏列即注入面模板静默不发行")

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
