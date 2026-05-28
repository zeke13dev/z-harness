"""
test_normalize.py — Unit tests for normalize.py nondeterminism stripper.
"""

import json

import pytest

from tests.conformance.normalize import normalize_artifact_list, normalize_events


# ---------------------------------------------------------------------------
# normalize_events — timestamp stripping
# ---------------------------------------------------------------------------


class TestTimestampStripped:
    def test_iso_timestamp_with_z_suffix(self):
        line = json.dumps({"event": "start", "ts": "2026-05-27T05:05:49Z"})
        result = normalize_events(line)
        obj = json.loads(result)
        assert obj["ts"] == "__TIMESTAMP__"

    def test_iso_timestamp_with_fractional_seconds(self):
        line = json.dumps({"ts": "2026-05-27T05:05:49.123Z"})
        result = normalize_events(line)
        assert "__TIMESTAMP__" in result
        assert "2026-05-27" not in result

    def test_iso_timestamp_with_offset(self):
        line = json.dumps({"ts": "2026-05-27T05:05:49+00:00"})
        result = normalize_events(line)
        assert "__TIMESTAMP__" in result

    def test_timestamp_in_nested_dict(self):
        line = json.dumps({"meta": {"created_at": "2026-01-01T00:00:00Z"}})
        result = normalize_events(line)
        obj = json.loads(result)
        assert obj["meta"]["created_at"] == "__TIMESTAMP__"

    def test_timestamp_in_list_value(self):
        line = json.dumps({"events": ["2026-01-01T00:00:00Z", "other"]})
        result = normalize_events(line)
        obj = json.loads(result)
        assert obj["events"][0] == "__TIMESTAMP__"
        assert obj["events"][1] == "other"


# ---------------------------------------------------------------------------
# normalize_events — run-ID stripping
# ---------------------------------------------------------------------------


class TestRunIdStripped:
    def test_run_id_in_string_value(self):
        line = json.dumps({"run_id": "20260527T050549Z-harness-distribution-strategy"})
        result = normalize_events(line)
        obj = json.loads(result)
        assert obj["run_id"] == "__RUN_ID__"

    def test_run_id_embedded_in_path(self):
        line = json.dumps({"path": "/archive/20260527T050549Z-my-plan/output.json"})
        result = normalize_events(line)
        assert "__RUN_ID__" in result
        assert "20260527T050549Z" not in result

    def test_run_id_replaced_before_timestamp(self):
        # Run-ID contains a timestamp-like prefix; ensure it becomes __RUN_ID__
        # and not a mix of __RUN_ID__ and leftover text.
        line = json.dumps({"id": "20260527T050549Z-plan"})
        result = normalize_events(line)
        obj = json.loads(result)
        # Should be exactly __RUN_ID__, not __RUN_ID__Z-plan or similar.
        assert obj["id"] == "__RUN_ID__"


# ---------------------------------------------------------------------------
# normalize_events — numeric field removal
# ---------------------------------------------------------------------------


class TestNumericFieldRemoved:
    def test_latency_ms_removed(self):
        line = json.dumps({"event": "done", "latency_ms": 42})
        result = normalize_events(line)
        obj = json.loads(result)
        assert "latency_ms" not in obj
        assert obj["event"] == "done"

    def test_duration_ms_removed(self):
        line = json.dumps({"duration_ms": 100, "status": "ok"})
        result = normalize_events(line)
        obj = json.loads(result)
        assert "duration_ms" not in obj

    def test_elapsed_s_removed(self):
        line = json.dumps({"elapsed_s": 1.5})
        result = normalize_events(line)
        obj = json.loads(result)
        assert "elapsed_s" not in obj

    def test_all_numeric_fields_removed(self):
        payload = {
            "event": "end",
            "latency_ms": 1,
            "duration_ms": 2,
            "elapsed_s": 3.0,
            "cache_hit": 4,
            "cache_miss": 5,
            "cached_tokens": 6,
            "input_tokens": 7,
            "output_tokens": 8,
        }
        result = normalize_events(json.dumps(payload))
        obj = json.loads(result)
        assert obj == {"event": "end"}

    def test_numeric_fields_removed_from_nested_dict(self):
        line = json.dumps({"stats": {"latency_ms": 99, "label": "x"}})
        result = normalize_events(line)
        obj = json.loads(result)
        assert "latency_ms" not in obj["stats"]
        assert obj["stats"]["label"] == "x"

    def test_numeric_field_not_replaced_with_sentinel(self):
        # Fields must be removed, not replaced with a placeholder value.
        line = json.dumps({"input_tokens": 1000, "event": "ok"})
        result = normalize_events(line)
        obj = json.loads(result)
        assert "input_tokens" not in obj
        assert "__" not in result or "__" not in json.dumps(obj)  # no sentinel leakage


# ---------------------------------------------------------------------------
# normalize_events — non-JSON line passed through
# ---------------------------------------------------------------------------


class TestNonJsonPassThrough:
    def test_plain_text_line_unchanged(self):
        line = "this is not json"
        result = normalize_events(line)
        assert result == line

    def test_partial_json_line_unchanged(self):
        line = '{"incomplete": '
        result = normalize_events(line)
        assert result == line

    def test_comment_line_unchanged(self):
        line = "# a comment"
        result = normalize_events(line)
        assert result == line

    def test_mixed_jsonl_preserves_non_json(self):
        jsonl = "\n".join(
            [
                json.dumps({"ts": "2026-05-27T00:00:00Z"}),
                "not json at all",
                json.dumps({"event": "end"}),
            ]
        )
        lines = normalize_events(jsonl).splitlines()
        assert lines[1] == "not json at all"
        assert "__TIMESTAMP__" in lines[0]
        assert json.loads(lines[2]) == {"event": "end"}


# ---------------------------------------------------------------------------
# normalize_events — empty input
# ---------------------------------------------------------------------------


class TestEmptyInput:
    def test_empty_string_returns_empty_string(self):
        assert normalize_events("") == ""

    def test_single_newline_input(self):
        # splitlines() on "\n" yields one empty string; joined back it becomes "".
        # This is the correct behavior: a trailing newline is consumed by splitlines.
        result = normalize_events("\n")
        assert result == ""

    def test_whitespace_only_line(self):
        result = normalize_events("   ")
        assert result == "   "


# ---------------------------------------------------------------------------
# normalize_artifact_list — artifact path prefix stripped
# ---------------------------------------------------------------------------


class TestArtifactPathPrefixStripped:
    def test_run_id_segment_removed_from_path(self):
        paths = ["/archive/20260527T050549Z-my-plan/output.txt"]
        result = normalize_artifact_list(paths)
        assert result == ["/archive/output.txt"]

    def test_bare_timestamp_segment_removed(self):
        # Bare YYYYMMDDTHHMMSSZ with no slug also stripped.
        paths = ["/runs/20260527T050549Z/results.json"]
        result = normalize_artifact_list(paths)
        assert result == ["/runs/results.json"]

    def test_prefix_merged_segment_not_stripped(self):
        # Segments like "prefix-20260527T050549Z-foo" do NOT fullmatch and
        # must be left alone.
        paths = ["/data/prefix-20260527T050549Z-foo/file.txt"]
        result = normalize_artifact_list(paths)
        assert result == ["/data/prefix-20260527T050549Z-foo/file.txt"]

    def test_list_is_sorted(self):
        paths = [
            "/z/20260527T050549Z-plan/out.txt",
            "/a/20260527T050549Z-plan/out.txt",
        ]
        result = normalize_artifact_list(paths)
        assert result == sorted(result)

    def test_empty_list_returns_empty_list(self):
        assert normalize_artifact_list([]) == []

    def test_paths_without_run_id_unchanged(self):
        paths = ["/stable/output.txt", "/another/file.json"]
        result = normalize_artifact_list(paths)
        assert result == sorted(paths)

    def test_multiple_run_id_segments_all_stripped(self):
        paths = ["/20260527T050549Z-a/20260601T120000Z-b/file.txt"]
        result = normalize_artifact_list(paths)
        assert result == ["/file.txt"]
