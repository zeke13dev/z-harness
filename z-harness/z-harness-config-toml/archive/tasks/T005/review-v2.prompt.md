You are reviewing code that Claude just wrote for task T005: scripts/config.py smoke tests

Review Round 2 — focus narrowly on whether the prior 9 findings were addressed; do NOT re-flag issues outside the delta.

**Prior findings (v1):**
1. explain repo source assertion too loose (substring only).
2. explain env source assertion too loose; needs to check env var name.
3. Event de-dup only checks stamp file, not events.jsonl payload.
4. returncode==0 not asserted before side-effect checks.
5. Baseline tests run with repo cwd, could pick up future .z-harness/config.toml.
6. ensure-defaults idempotency uses existence, not byte equality.
7. Malformed TOML non-overwrite uses mtime (fragile).
8. schema_version mismatch only tested in repo layer.
9. Malformed TOML only tested in repo layer.

**Implementer's claims:**
1. Tightened to assert full `source: /path/to/.z-harness/config.toml`.
2. Tightened to assert `source: env Z_HARNESS_NOTIFY_LEVEL`.
3. De-dup tests init a real git repo so log-event.sh writes events.jsonl; assert event count and payload (values/sources).
4. Added `assertEqual(r.returncode, 0)` before side-effect checks.
5. New `make_isolation_dir()` helper; non-git temp dir used as cwd in all baseline/env/unknown/should-notify/ensure-defaults tests.
6. Byte equality for ensure-defaults idempotency.
7. Byte equality for malformed-TOML non-overwrite.
8. Added `test_schema_version_2_global_exits_2_with_file_path`.
9. Added `test_malformed_toml_global_exits_2_with_line_info`.

**Delta (v2):**
(contains additions to test_config.py; 45 tests now, was 41)

---

Scrutinize this code **strictly against the 9 prior findings**. Answer:

1. Did the implementer actually fix each finding, or just claim it?
2. Are the fixes correct and complete?
3. Did the fixes introduce new bugs?
4. Are the new tests real (not no-ops)?

Report only **blockers and majors**. For each:
- Which prior finding (by number) it relates to
- The problem (1 sentence)
- The fix (1 sentence)

Output under 6000 characters. Do not re-state code already in the diff. Focus on whether claims match reality.

---

DELTA:

```diff
--- z-harness/z-harness-config-toml/archive/tasks/T005/diff-v1.patch	2026-05-27 11:41:47
+++ z-harness/z-harness-config-toml/archive/tasks/T005/diff.patch	2026-05-27 11:45:45
@@ -1,9 +1,9 @@
 diff --git a/scripts/test_config.py b/scripts/test_config.py
 new file mode 100755
-index 0000000..b005ccd
+index 0000000..f013e71
 --- /dev/null
 +++ b/scripts/test_config.py
-@@ -0,0 +1,499 @@
+@@ -0,0 +1,632 @@
 +#!/usr/bin/env python3
 +"""
 +test_config.py — End-to-end smoke tests for scripts/config.py.
@@ -12,8 +12,11 @@
 +    python3 scripts/test_config.py
 +
 +Each test uses a hermetic XDG_CONFIG_HOME (mkdtemp) to avoid touching
-+the developer's real ~/.config/z-harness/.
++the developer's real ~/.config/z-harness/.  Tests that need "no repo config"
++run subprocesses from a fresh non-git temp dir so the git-rev-parse fallback
++does not pick up any .z-harness/config.toml from the z-harness repo itself.
 +"""
++import json
 +import os
 +import subprocess
 +import sys
@@ -63,6 +66,16 @@
 +    return tempfile.mkdtemp(prefix="z-harness-test-xdg-")
 +
 +
++def make_isolation_dir() -> str:
++    """Return a fresh non-git temp dir for subprocess cwd.
++
++    This prevents the git-rev-parse fallback in _repo_config_path() from
++    walking up to the z-harness repo and picking up any .z-harness/config.toml
++    that might be present there now or in the future.
++    """
++    return tempfile.mkdtemp(prefix="z-harness-test-cwd-")
++
++
 +def write_global_config(xdg: str, content: str) -> str:
 +    """Write content to $XDG_CONFIG_HOME/z-harness/config.toml. Returns path."""
 +    cfg_dir = Path(xdg) / "z-harness"
@@ -90,23 +103,25 @@
 +
 +    def setUp(self):
 +        self.xdg = make_xdg()
++        self.cwd = make_isolation_dir()
 +        self.env = {"XDG_CONFIG_HOME": self.xdg}
 +
 +    def tearDown(self):
 +        shutil.rmtree(self.xdg, ignore_errors=True)
++        shutil.rmtree(self.cwd, ignore_errors=True)
 +
 +    def test_get_notify_level_default(self):
-+        r = run(["get", "notify.level"], env=self.env)
++        r = run(["get", "notify.level"], env=self.env, cwd=self.cwd)
 +        self.assertEqual(r.returncode, 0)
 +        self.assertEqual(r.stdout.strip(), "approval_only")
 +
 +    def test_get_docs_always_apply_default(self):
-+        r = run(["get", "docs.always_apply"], env=self.env)
++        r = run(["get", "docs.always_apply"], env=self.env, cwd=self.cwd)
 +        self.assertEqual(r.returncode, 0)
 +        self.assertEqual(r.stdout.strip(), "always")
 +
 +    def test_get_schema_version_exits_3(self):
-+        r = run(["get", "schema_version"], env=self.env)
++        r = run(["get", "schema_version"], env=self.env, cwd=self.cwd)
 +        self.assertEqual(r.returncode, 3)
 +
 +
@@ -115,15 +130,17 @@
 +
 +    def setUp(self):
 +        self.xdg = make_xdg()
++        self.cwd = make_isolation_dir()
 +
 +    def tearDown(self):
 +        shutil.rmtree(self.xdg, ignore_errors=True)
++        shutil.rmtree(self.cwd, ignore_errors=True)
 +
 +    def test_env_off_overrides(self):
 +        r = run(["get", "notify.level"], env={
 +            "XDG_CONFIG_HOME": self.xdg,
 +            "Z_HARNESS_NOTIFY_LEVEL": "off",
-+        })
++        }, cwd=self.cwd)
 +        self.assertEqual(r.returncode, 0)
 +        self.assertEqual(r.stdout.strip(), "off")
 +
@@ -131,7 +148,7 @@
 +        r = run(["get", "notify.level"], env={
 +            "XDG_CONFIG_HOME": self.xdg,
 +            "Z_HARNESS_NOTIFY_LEVEL": "",
-+        })
++        }, cwd=self.cwd)
 +        self.assertEqual(r.returncode, 0)
 +        self.assertEqual(r.stdout.strip(), "approval_only")
 +
@@ -139,7 +156,7 @@
 +        r = run(["get", "notify.level"], env={
 +            "XDG_CONFIG_HOME": self.xdg,
 +            "Z_HARNESS_NOTIFY_LEVEL": "loud",
-+        })
++        }, cwd=self.cwd)
 +        self.assertEqual(r.returncode, 2)
 +
 +
@@ -168,10 +185,14 @@
 +        self.assertEqual(r.stdout.strip(), "off")
 +
 +    def test_explain_shows_source_repo(self):
++        """explain prints the full repo config file path as source label."""
 +        r = run(["explain", "notify.level"], env=self.env)
 +        self.assertEqual(r.returncode, 0)
++        # Output format: notify.level = "off"   (source: /path/to/.z-harness/config.toml)
 +        self.assertIn("source:", r.stdout)
-+        # Source should reference the repo config path
++        # The source label is the full path to the repo config file
++        self.assertIn(self.repo_cfg, r.stdout)
++        # Must contain the .z-harness component of the path
 +        self.assertIn(".z-harness", r.stdout)
 +
 +    def test_env_takes_precedence_over_repo(self):
@@ -182,11 +203,15 @@
 +        self.assertEqual(r.stdout.strip(), "all")
 +
 +    def test_explain_env_source_over_repo(self):
++        """explain emits 'source: env Z_HARNESS_NOTIFY_LEVEL' when env overrides repo."""
 +        env = dict(self.env)
 +        env["Z_HARNESS_NOTIFY_LEVEL"] = "all"
 +        r = run(["explain", "notify.level"], env=env)
 +        self.assertEqual(r.returncode, 0)
-+        self.assertIn("env", r.stdout.lower())
++        # The source label is "env Z_HARNESS_NOTIFY_LEVEL" (exact env var name included)
++        self.assertIn("source:", r.stdout)
++        self.assertIn("env", r.stdout)
++        self.assertIn("Z_HARNESS_NOTIFY_LEVEL", r.stdout)
 +
 +
 +class TestUnknownKeys(unittest.TestCase):
@@ -194,17 +219,19 @@
 +
 +    def setUp(self):
 +        self.xdg = make_xdg()
++        self.cwd = make_isolation_dir()
 +        self.env = {"XDG_CONFIG_HOME": self.xdg}
 +
 +    def tearDown(self):
 +        shutil.rmtree(self.xdg, ignore_errors=True)
++        shutil.rmtree(self.cwd, ignore_errors=True)
 +
 +    def test_get_typo_exits_3(self):
-+        r = run(["get", "notify.lvel"], env=self.env)
++        r = run(["get", "notify.lvel"], env=self.env, cwd=self.cwd)
 +        self.assertEqual(r.returncode, 3)
 +
 +    def test_explain_typo_exits_3(self):
-+        r = run(["explain", "notify.lvel"], env=self.env)
++        r = run(["explain", "notify.lvel"], env=self.env, cwd=self.cwd)
 +        self.assertEqual(r.returncode, 3)
 +
 +
@@ -213,15 +240,17 @@
 +
 +    def setUp(self):
 +        self.xdg = make_xdg()
++        self.cwd = make_isolation_dir()
 +
 +    def tearDown(self):
 +        shutil.rmtree(self.xdg, ignore_errors=True)
++        shutil.rmtree(self.cwd, ignore_errors=True)
 +
 +    def _sn(self, level: str, event: str) -> str:
 +        env = {"XDG_CONFIG_HOME": self.xdg}
 +        if level != "approval_only":  # approval_only is the default
 +            env["Z_HARNESS_NOTIFY_LEVEL"] = level
-+        r = run(["should-notify", "--event", event], env=env)
++        r = run(["should-notify", "--event", event], env=env, cwd=self.cwd)
 +        self.assertEqual(r.returncode, 0, f"should-notify exited {r.returncode} for level={level} event={event}")
 +        return r.stdout.strip()
 +
@@ -257,8 +286,9 @@
 +
 +    def test_typo_event_exits_2_with_allowlist(self):
 +        xdg = make_xdg()
++        cwd = make_isolation_dir()
 +        try:
-+            r = run(["should-notify", "--event", "failre"], env={"XDG_CONFIG_HOME": xdg})
++            r = run(["should-notify", "--event", "failre"], env={"XDG_CONFIG_HOME": xdg}, cwd=cwd)
 +            self.assertEqual(r.returncode, 2)
 +            # stderr should mention the allowlist
 +            combined = r.stderr + r.stdout
@@ -268,6 +298,7 @@
 +            )
 +        finally:
 +            shutil.rmtree(xdg, ignore_errors=True)
++            shutil.rmtree(cwd, ignore_errors=True)
 +
 +
 +class TestEnsureDefaults(unittest.TestCase):
@@ -275,43 +306,49 @@
 +
 +    def setUp(self):
 +        self.xdg = make_xdg()
++        self.cwd = make_isolation_dir()
 +        self.env = {"XDG_CONFIG_HOME": self.xdg}
 +        self.cfg_path = Path(self.xdg) / "z-harness" / "config.toml"
 +
 +    def tearDown(self):
 +        shutil.rmtree(self.xdg, ignore_errors=True)
++        shutil.rmtree(self.cwd, ignore_errors=True)
 +
 +    def test_creates_file_on_empty_xdg(self):
-+        r = run(["ensure-defaults"], env=self.env)
++        r = run(["ensure-defaults"], env=self.env, cwd=self.cwd)
 +        self.assertEqual(r.returncode, 0)
 +        self.assertIn("created", r.stdout)
 +        self.assertTrue(self.cfg_path.exists())
 +
-+    def test_second_invocation_prints_exists(self):
-+        run(["ensure-defaults"], env=self.env)
-+        r2 = run(["ensure-defaults"], env=self.env)
++    def test_second_invocation_prints_exists_bytes_unchanged(self):
++        """Second invocation must print 'exists' and leave file byte-identical."""
++        r1 = run(["ensure-defaults"], env=self.env, cwd=self.cwd)
++        self.assertEqual(r1.returncode, 0)
++        bytes_after_first = self.cfg_path.read_bytes()
++        r2 = run(["ensure-defaults"], env=self.env, cwd=self.cwd)
 +        self.assertEqual(r2.returncode, 0)
 +        self.assertIn("exists", r2.stdout)
-+        # File should not have been re-written (check mtime consistency)
-+        self.assertTrue(self.cfg_path.exists())
++        self.assertEqual(self.cfg_path.read_bytes(), bytes_after_first,
++                         "File bytes changed on second invocation")
 +
 +    def test_zero_byte_file_exits_4_not_overwritten(self):
 +        self.cfg_path.parent.mkdir(parents=True, exist_ok=True)
 +        self.cfg_path.write_text("")
-+        r = run(["ensure-defaults"], env=self.env)
++        r = run(["ensure-defaults"], env=self.env, cwd=self.cwd)
 +        self.assertEqual(r.returncode, 4)
 +        # File must still be empty (not overwritten)
 +        self.assertEqual(self.cfg_path.stat().st_size, 0)
 +
-+    def test_malformed_toml_exits_4_not_overwritten(self):
++    def test_malformed_toml_exits_4_bytes_unchanged(self):
++        """ensure-defaults must not overwrite a malformed file; byte equality check."""
 +        self.cfg_path.parent.mkdir(parents=True, exist_ok=True)
 +        bad = 'notify.level = \n'
 +        self.cfg_path.write_text(bad)
-+        mtime_before = self.cfg_path.stat().st_mtime
-+        r = run(["ensure-defaults"], env=self.env)
++        original_bytes = self.cfg_path.read_bytes()
++        r = run(["ensure-defaults"], env=self.env, cwd=self.cwd)
 +        self.assertEqual(r.returncode, 4)
-+        mtime_after = self.cfg_path.stat().st_mtime
-+        self.assertEqual(mtime_before, mtime_after, "File was modified despite malformed TOML")
++        self.assertEqual(self.cfg_path.read_bytes(), original_bytes,
++                         "File was modified despite malformed TOML")
 +
 +
 +class TestTomlSchemaErrors(unittest.TestCase):
@@ -320,10 +357,12 @@
 +    def setUp(self):
 +        self.xdg = make_xdg()
 +        self.repo = tempfile.mkdtemp(prefix="z-harness-test-repo-")
++        self.cwd = make_isolation_dir()
 +
 +    def tearDown(self):
 +        shutil.rmtree(self.xdg, ignore_errors=True)
 +        shutil.rmtree(self.repo, ignore_errors=True)
++        shutil.rmtree(self.cwd, ignore_errors=True)
 +
 +    def test_repo_local_invalid_value_exits_2(self):
 +        repo_cfg = write_repo_config(self.repo, '[notify]\nlevel = "loud"\n')
@@ -335,12 +374,14 @@
 +
 +    def test_global_invalid_value_warns_and_falls_back(self):
 +        write_global_config(self.xdg, '[notify]\nlevel = "loud"\n')
-+        r = run(["get", "notify.level"], env={"XDG_CONFIG_HOME": self.xdg})
++        r = run(["get", "notify.level"], env={"XDG_CONFIG_HOME": self.xdg},
++                cwd=self.cwd)
 +        self.assertEqual(r.returncode, 0)
 +        self.assertEqual(r.stdout.strip(), "approval_only")
 +        self.assertIn("WARNING", r.stderr)
 +
-+    def test_schema_version_2_exits_2_with_file_name(self):
++    def test_schema_version_2_repo_exits_2_with_file_name(self):
++        """schema_version=2 in REPO config exits 2 with the file path in stderr."""
 +        repo_cfg = write_repo_config(self.repo, 'schema_version = 2\n[notify]\nlevel = "off"\n')
 +        r = run(["get", "notify.level"], env={
 +            "XDG_CONFIG_HOME": self.xdg,
@@ -349,6 +390,17 @@
 +        self.assertEqual(r.returncode, 2)
 +        self.assertIn(".z-harness", r.stderr)
 +
++    def test_schema_version_2_global_exits_2_with_file_path(self):
++        """schema_version=2 in GLOBAL config exits 2 with the global file path in stderr."""
++        global_cfg_path = write_global_config(
++            self.xdg, 'schema_version = 2\n[notify]\nlevel = "off"\n'
++        )
++        r = run(["get", "notify.level"], env={"XDG_CONFIG_HOME": self.xdg},
++                cwd=self.cwd)
++        self.assertEqual(r.returncode, 2)
++        self.assertIn(global_cfg_path, r.stderr,
++                      f"Expected global config path {global_cfg_path!r} in stderr: {r.stderr!r}")
++
 +    def test_malformed_toml_repo_exits_2_with_line_info(self):
 +        repo_cfg = write_repo_config(self.repo, 'notify.level = \n')
 +        r = run(["get", "notify.level"], env={
@@ -359,7 +411,18 @@
 +        # tomllib errors include line/col info
 +        self.assertRegex(r.stderr, r"(?i)(line|col|parse|error)")
 +
++    def test_malformed_toml_global_exits_2_with_line_info(self):
++        """Malformed TOML in GLOBAL config exits 2 with parser line/column info in stderr."""
++        global_cfg_path = write_global_config(self.xdg, 'notify.level = \n')
++        r = run(["get", "notify.level"], env={"XDG_CONFIG_HOME": self.xdg},
++                cwd=self.cwd)
++        self.assertEqual(r.returncode, 2)
++        self.assertRegex(r.stderr, r"(?i)(line|col|parse|error)",
++                         f"Expected line/col in stderr; got: {r.stderr!r}")
++        # stderr should also name the global file path
++        self.assertIn(global_cfg_path, r.stderr)
 +
++
 +class TestExplicitOverridePath(unittest.TestCase):
 +    """Z_HARNESS_REPO_CONFIG pointing to nonexistent path."""
 +
@@ -378,58 +441,125 @@
 +
 +
 +class TestEventDedup(unittest.TestCase):
-+    """export-env event de-dup via Z_HARNESS_RUN."""
++    """export-env event de-dup via Z_HARNESS_RUN.
 +
++    Tests verify both the O_EXCL stamp file AND the events.jsonl archive to
++    ensure (a) first call writes exactly one config_resolved event, (b) second
++    call writes zero additional events, (c) no-$Z_HARNESS_RUN writes zero events.
++
++    The log-event.sh script requires a git repo context (git rev-parse) to
++    locate the events.jsonl path, so we init a bare git repo for each test.
++    """
++
 +    def setUp(self):
 +        self.xdg = make_xdg()
-+        self.run_id = "test-run-dedup-99999"
++        self.run_id = f"test-run-dedup-{os.getpid()}"
++        # Create a temporary git repo so log-event.sh can write events.jsonl
++        self.git_repo = tempfile.mkdtemp(prefix="z-harness-test-gitrepo-")
++        subprocess.run(["git", "init", "--quiet", self.git_repo], check=True)
 +        # Clean up any leftover stamp from prior test runs
-+        stamp = os.path.join(tempfile.gettempdir(), f"z-harness-config-resolved-{self.run_id}")
-+        try:
++        stamp = self._stamp_path()
++        if os.path.exists(stamp):
 +            os.unlink(stamp)
-+        except FileNotFoundError:
-+            pass
 +
 +    def tearDown(self):
 +        shutil.rmtree(self.xdg, ignore_errors=True)
-+        stamp = os.path.join(tempfile.gettempdir(), f"z-harness-config-resolved-{self.run_id}")
-+        try:
++        shutil.rmtree(self.git_repo, ignore_errors=True)
++        stamp = self._stamp_path()
++        if os.path.exists(stamp):
 +            os.unlink(stamp)
-+        except FileNotFoundError:
-+            pass
 +
++    def _stamp_path(self) -> str:
++        return os.path.join(tempfile.gettempdir(), f"z-harness-config-resolved-{self.run_id}")
++
 +    def _stamp_exists(self) -> bool:
-+        stamp = os.path.join(tempfile.gettempdir(), f"z-harness-config-resolved-{self.run_id}")
-+        return os.path.exists(stamp)
++        return os.path.exists(self._stamp_path())
 +
++    def _events_jsonl_path(self) -> Path:
++        return Path(self.git_repo) / "z-harness" / "archive" / self.run_id / "events.jsonl"
++
++    def _read_config_resolved_events(self) -> list:
++        """Return list of config_resolved events from the run's events.jsonl."""
++        p = self._events_jsonl_path()
++        if not p.exists():
++            return []
++        events = []
++        for line in p.read_text().splitlines():
++            line = line.strip()
++            if not line:
++                continue
++            obj = json.loads(line)
++            if obj.get("kind") == "config_resolved":
++                events.append(obj)
++        return events
++
 +    def test_first_export_env_creates_stamp(self):
-+        run(["export-env"], env={
++        r = run(["export-env"], env={
 +            "XDG_CONFIG_HOME": self.xdg,
 +            "Z_HARNESS_RUN": self.run_id,
-+        })
++        }, cwd=self.git_repo)
++        self.assertEqual(r.returncode, 0)
 +        self.assertTrue(self._stamp_exists())
 +
++    def test_first_export_env_writes_exactly_one_event(self):
++        """First export-env call writes exactly one config_resolved event with values+sources."""
++        r = run(["export-env"], env={
++            "XDG_CONFIG_HOME": self.xdg,
++            "Z_HARNESS_RUN": self.run_id,
++        }, cwd=self.git_repo)
++        self.assertEqual(r.returncode, 0)
++        events = self._read_config_resolved_events()
++        self.assertEqual(len(events), 1, f"Expected 1 config_resolved event, got {len(events)}: {events}")
++        event = events[0]
++        self.assertIn("values", event, "config_resolved event missing 'values' key")
++        self.assertIn("sources", event, "config_resolved event missing 'sources' key")
++        # Payload accuracy: defaults expected when no config files are present
++        self.assertEqual(event["values"].get("notify.level"), "approval_only")
++        self.assertEqual(event["sources"].get("notify.level"), "defaults")
++
 +    def test_second_export_env_same_run_blocked_by_excl(self):
-+        # First call creates the stamp
-+        run(["export-env"], env={
++        """Second export-env call with same Z_HARNESS_RUN adds zero events."""
++        # First call creates the stamp and emits the event
++        r1 = run(["export-env"], env={
 +            "XDG_CONFIG_HOME": self.xdg,
 +            "Z_HARNESS_RUN": self.run_id,
-+        })
-+        # Manually write something into the stamp to detect any overwrite
-+        stamp_path = os.path.join(tempfile.gettempdir(), f"z-harness-config-resolved-{self.run_id}")
-+        Path(stamp_path).write_text("SENTINEL")
-+        run(["export-env"], env={
++        }, cwd=self.git_repo)
++        self.assertEqual(r1.returncode, 0)
++        events_after_first = self._read_config_resolved_events()
++        self.assertEqual(len(events_after_first), 1)
++
++        # Manually write a sentinel to the stamp to detect any re-open
++        Path(self._stamp_path()).write_text("SENTINEL")
++
++        # Second call — should be blocked
++        r2 = run(["export-env"], env={
 +            "XDG_CONFIG_HOME": self.xdg,
 +            "Z_HARNESS_RUN": self.run_id,
-+        })
-+        # Stamp should still contain "SENTINEL" (not re-opened)
-+        self.assertEqual(Path(stamp_path).read_text(), "SENTINEL")
++        }, cwd=self.git_repo)
++        self.assertEqual(r2.returncode, 0)
 +
++        # Stamp must still contain "SENTINEL" (not re-opened)
++        self.assertEqual(Path(self._stamp_path()).read_text(), "SENTINEL")
++        # events.jsonl must still have exactly 1 config_resolved event (zero added)
++        events_after_second = self._read_config_resolved_events()
++        self.assertEqual(len(events_after_second), 1,
++                         f"Second call added events; total now: {events_after_second}")
++
 +    def test_without_run_no_stamp(self):
-+        run(["export-env"], env={"XDG_CONFIG_HOME": self.xdg})
++        """Without Z_HARNESS_RUN, no stamp file is created."""
++        r = run(["export-env"], env={"XDG_CONFIG_HOME": self.xdg}, cwd=self.git_repo)
++        self.assertEqual(r.returncode, 0)
 +        self.assertFalse(self._stamp_exists())
 +
++    def test_without_run_no_event(self):
++        """Without Z_HARNESS_RUN, no config_resolved event is emitted."""
++        r = run(["export-env"], env={"XDG_CONFIG_HOME": self.xdg}, cwd=self.git_repo)
++        self.assertEqual(r.returncode, 0)
++        events = self._read_config_resolved_events()
++        self.assertEqual(len(events), 0,
++                         f"Expected 0 events without Z_HARNESS_RUN, got: {events}")
 +
++
 +class TestDottedToEnvPureFunction(unittest.TestCase):
 +    """Direct unit tests for _dotted_to_env."""
 +
@@ -461,13 +591,15 @@
 +
 +    def setUp(self):
 +        self.xdg = make_xdg()
++        self.cwd = make_isolation_dir()
 +
 +    def tearDown(self):
 +        shutil.rmtree(self.xdg, ignore_errors=True)
++        shutil.rmtree(self.cwd, ignore_errors=True)
 +
 +    def test_eval_sets_notify_and_docs_not_schema(self):
 +        # Run export-env and capture the output
-+        r = run(["export-env"], env={"XDG_CONFIG_HOME": self.xdg})
++        r = run(["export-env"], env={"XDG_CONFIG_HOME": self.xdg}, cwd=self.cwd)
 +        self.assertEqual(r.returncode, 0)
 +        output = r.stdout
 +        self.assertIn("Z_HARNESS_NOTIFY_LEVEL", output)
@@ -491,6 +623,7 @@
 +            capture_output=True,
 +            text=True,
 +            env=env,
++            cwd=self.cwd,
 +        )
 +        self.assertEqual(r.returncode, 0, f"bash exited {r.returncode}; stderr={r.stderr!r}")
 +        self.assertIn("NOTIFY=approval_only", r.stdout)
```
