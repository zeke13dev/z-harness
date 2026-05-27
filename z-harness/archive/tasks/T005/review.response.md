527:            "usage: config.py <get|export-env|ensure-defaults|explain|should-notify> [args...]",
539:    elif subcommand == "ensure-defaults":
540:        cmd_ensure_defaults(args)
548:            "valid: get, export-env, ensure-defaults, explain, should-notify",

exec
/bin/zsh -lc "sed -n '520,580p' scripts/config.py" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) < 2:
        print(
            "usage: config.py <get|export-env|ensure-defaults|explain|should-notify> [args...]",
            file=sys.stderr,
        )
        sys.exit(2)

    subcommand = sys.argv[1]
    args = sys.argv[2:]

    if subcommand == "get":
        cmd_get(args)
    elif subcommand == "export-env":
        cmd_export_env(args)
    elif subcommand == "ensure-defaults":
        cmd_ensure_defaults(args)
    elif subcommand == "explain":
        cmd_explain(args)
    elif subcommand == "should-notify":
        cmd_should_notify(args)
    else:
        print(
            f"[config] unknown subcommand {subcommand!r}; "
            "valid: get, export-env, ensure-defaults, explain, should-notify",
            file=sys.stderr,
        )
        sys.exit(2)


if __name__ == "__main__":
    main()

codex
A few gaps are emerging in the tests rather than the implementation: several checks assert side effects that correlate with the behavior but do not prove the specified observable contract. I’m doing one more pass for exact exit-code and isolation holes before I write the findings.
exec
/bin/zsh -lc "find . -maxdepth 3 -path '*/.z-harness/config.toml' -print" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
exec
/bin/zsh -lc "rg -n \"assertEqual\\(r\\.returncode|run\\(\\[\\\"export-env|mtime|source|schema_version|malformed|global\" scripts/test_config.py" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
37:    # Detach from real global config
60:def write_global_config(xdg: str, content: str) -> str:
94:        self.assertEqual(r.returncode, 0)
99:        self.assertEqual(r.returncode, 0)
102:    def test_get_schema_version_exits_3(self):
103:        r = run(["get", "schema_version"], env=self.env)
104:        self.assertEqual(r.returncode, 3)
121:        self.assertEqual(r.returncode, 0)
129:        self.assertEqual(r.returncode, 0)
137:        self.assertEqual(r.returncode, 2)
141:    """Repo-local config (layer 3) overrides global + defaults."""
161:        self.assertEqual(r.returncode, 0)
164:    def test_explain_shows_source_repo(self):
166:        self.assertEqual(r.returncode, 0)
167:        self.assertIn("source:", r.stdout)
175:        self.assertEqual(r.returncode, 0)
178:    def test_explain_env_source_over_repo(self):
182:        self.assertEqual(r.returncode, 0)
198:        self.assertEqual(r.returncode, 3)
202:        self.assertEqual(r.returncode, 3)
219:        self.assertEqual(r.returncode, 0, f"should-notify exited {r.returncode} for level={level} event={event}")
256:            self.assertEqual(r.returncode, 2)
280:        self.assertEqual(r.returncode, 0)
289:        # File should not have been re-written (check mtime consistency)
296:        self.assertEqual(r.returncode, 4)
300:    def test_malformed_toml_exits_4_not_overwritten(self):
304:        mtime_before = self.cfg_path.stat().st_mtime
306:        self.assertEqual(r.returncode, 4)
307:        mtime_after = self.cfg_path.stat().st_mtime
308:        self.assertEqual(mtime_before, mtime_after, "File was modified despite malformed TOML")
328:        self.assertEqual(r.returncode, 2)
330:    def test_global_invalid_value_warns_and_falls_back(self):
331:        write_global_config(self.xdg, '[notify]\nlevel = "loud"\n')
333:        self.assertEqual(r.returncode, 0)
337:    def test_schema_version_2_exits_2_with_file_name(self):
338:        repo_cfg = write_repo_config(self.repo, 'schema_version = 2\n[notify]\nlevel = "off"\n')
343:        self.assertEqual(r.returncode, 2)
346:    def test_malformed_toml_repo_exits_2_with_line_info(self):
352:        self.assertEqual(r.returncode, 2)
371:        self.assertEqual(r.returncode, 2)
400:        run(["export-env"], env={
408:        run(["export-env"], env={
415:        run(["export-env"], env={
423:        run(["export-env"], env={"XDG_CONFIG_HOME": self.xdg})
454:    """eval export-env sets expected vars but not schema_version."""
464:        r = run(["export-env"], env={"XDG_CONFIG_HOME": self.xdg})
465:        self.assertEqual(r.returncode, 0)
489:        self.assertEqual(r.returncode, 0, f"bash exited {r.returncode}; stderr={r.stderr!r}")

exec
/bin/zsh -lc 'rg -n "log-event|events|config_resolved|Z_HARNESS_RUN|TMPDIR|tempfile.gettempdir" -S .' in /Users/zeke/dev/z-harness
 succeeded in 104ms:
codex
- **Major, `scripts/test_config.py:164`:** `explain notify.level` is supposed to show source `repo`, but the test only checks for `"source:"` and `".z-harness"`, so an implementation that prints a path instead of the required source label passes. Assert the exact source contract, e.g. a regex for `source:\s*repo\b` or parse the source field.

- **Major, `scripts/test_config.py:178`:** The env-over-repo explain test only checks that `"env"` appears anywhere in stdout, so it does not prove the resolved source is env or that repo was displaced. Assert the exact source field and expected env var, e.g. `source: env Z_HARNESS_NOTIFY_LEVEL`.

- **Major, `scripts/test_config.py:400`:** The event de-dup tests never inspect emitted events, only the O_EXCL stamp side effect, so they pass even if `log-event.sh` is missing, never called, or emits the wrong event kind/count. Run from an isolated temp repo or slug, inspect the expected `events.jsonl`, and assert first call adds exactly one `config_resolved`, second adds zero, and no-run adds zero.

- **Major, `scripts/test_config.py:400`, `scripts/test_config.py:408`, `scripts/test_config.py:415`, `scripts/test_config.py:423`:** These `export-env` calls do not assert the actual return code, and the second de-dup test can create the sentinel itself even if the first command failed. Assert `returncode == 0` for every subprocess before checking side effects.

- **Major, `scripts/test_config.py:78`:** Baseline/default tests run with the test process’s current repo discovery, so a real `.z-harness/config.toml` in `/Users/zeke/dev/z-harness` can silently override defaults despite the hermetic XDG fixture. Run default/global-only tests with `cwd` set to a fresh non-git temp directory with no `.z-harness`, and reserve explicit `Z_HARNESS_REPO_CONFIG` only for repo-local tests.

- **Major, `scripts/test_config.py:285`:** The second `ensure-defaults` test claims to verify the file is unchanged but only checks that it exists, so a rewrite that preserves valid content or changes comments would pass. Capture the file bytes and metadata after the first invocation, then assert bytes are identical after the second invocation.

- **Major, `scripts/test_config.py:300`:** The malformed TOML non-overwrite check relies only on `mtime`, which can miss rewrites on coarse timestamp filesystems or same-tick writes. Assert the file bytes still equal the original malformed content, and also check the actionable stderr message.

- **Major, `scripts/test_config.py:337`:** `schema_version = 2` is only tested for repo-local config, but the criterion says any layer; a broken global schema hard-fail would not be caught. Add a global config case asserting exit 2 and stderr naming the global file.

- **Major, `scripts/test_config.py:346`:** Malformed TOML is only tested for repo-local config, but the criterion says malformed TOML at any layer. Add a global malformed TOML case asserting exit 2 and parser line/column details.
tokens used
33,279
- **Major, `scripts/test_config.py:164`:** `explain notify.level` is supposed to show source `repo`, but the test only checks for `"source:"` and `".z-harness"`, so an implementation that prints a path instead of the required source label passes. Assert the exact source contract, e.g. a regex for `source:\s*repo\b` or parse the source field.

- **Major, `scripts/test_config.py:178`:** The env-over-repo explain test only checks that `"env"` appears anywhere in stdout, so it does not prove the resolved source is env or that repo was displaced. Assert the exact source field and expected env var, e.g. `source: env Z_HARNESS_NOTIFY_LEVEL`.

- **Major, `scripts/test_config.py:400`:** The event de-dup tests never inspect emitted events, only the O_EXCL stamp side effect, so they pass even if `log-event.sh` is missing, never called, or emits the wrong event kind/count. Run from an isolated temp repo or slug, inspect the expected `events.jsonl`, and assert first call adds exactly one `config_resolved`, second adds zero, and no-run adds zero.

- **Major, `scripts/test_config.py:400`, `scripts/test_config.py:408`, `scripts/test_config.py:415`, `scripts/test_config.py:423`:** These `export-env` calls do not assert the actual return code, and the second de-dup test can create the sentinel itself even if the first command failed. Assert `returncode == 0` for every subprocess before checking side effects.

- **Major, `scripts/test_config.py:78`:** Baseline/default tests run with the test process’s current repo discovery, so a real `.z-harness/config.toml` in `/Users/zeke/dev/z-harness` can silently override defaults despite the hermetic XDG fixture. Run default/global-only tests with `cwd` set to a fresh non-git temp directory with no `.z-harness`, and reserve explicit `Z_HARNESS_REPO_CONFIG` only for repo-local tests.

- **Major, `scripts/test_config.py:285`:** The second `ensure-defaults` test claims to verify the file is unchanged but only checks that it exists, so a rewrite that preserves valid content or changes comments would pass. Capture the file bytes and metadata after the first invocation, then assert bytes are identical after the second invocation.

- **Major, `scripts/test_config.py:300`:** The malformed TOML non-overwrite check relies only on `mtime`, which can miss rewrites on coarse timestamp filesystems or same-tick writes. Assert the file bytes still equal the original malformed content, and also check the actionable stderr message.

- **Major, `scripts/test_config.py:337`:** `schema_version = 2` is only tested for repo-local config, but the criterion says any layer; a broken global schema hard-fail would not be caught. Add a global config case asserting exit 2 and stderr naming the global file.

- **Major, `scripts/test_config.py:346`:** Malformed TOML is only tested for repo-local config, but the criterion says malformed TOML at any layer. Add a global malformed TOML case asserting exit 2 and parser line/column details.
