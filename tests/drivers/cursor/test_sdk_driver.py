"""
tests/drivers/cursor/test_sdk_driver.py — Unit tests for runtime/drivers/cursor/sdk_driver.py.

Covers:
  - CursorSDKDriver.init() raises NotImplementedError with the v2 milestone message
  - CursorSDKDriver.dispatch() raises NotImplementedError with the v2 milestone message
  - CursorSDKDriver.teardown() raises NotImplementedError with the v2 milestone message
  - CursorSDKDriver implements the HostDriver ABC (class is instantiable)
  - sdk_driver module does not import @cursor/sdk at module level

Run:
    pytest tests/drivers/cursor/test_sdk_driver.py -v
"""

from __future__ import annotations

import importlib
import sys

import pytest

from runtime.drivers.cursor.sdk_driver import CursorSDKDriver, _NOT_IMPLEMENTED_MSG
from runtime.dispatch.driver import HostDriver

_EXPECTED_MSG = (
    "CursorSDKDriver is not implemented in v1. "
    "See v2 milestone: @cursor/sdk (public beta 2026-04-29). "
    "Use CursorCLIDriver for v1."
)


class TestCursorSDKDriverIsInstantiable:
    """CursorSDKDriver must be importable and instantiable without @cursor/sdk present."""

    def test_instantiable(self):
        driver = CursorSDKDriver()
        assert isinstance(driver, CursorSDKDriver)

    def test_is_host_driver_subclass(self):
        assert issubclass(CursorSDKDriver, HostDriver)

    def test_not_implemented_msg_constant(self):
        assert _NOT_IMPLEMENTED_MSG == _EXPECTED_MSG


class TestCursorSDKDriverInit:
    def test_raises_not_implemented_error(self):
        driver = CursorSDKDriver()
        with pytest.raises(NotImplementedError):
            driver.init({})

    def test_error_message_matches_spec(self):
        driver = CursorSDKDriver()
        with pytest.raises(NotImplementedError, match="CursorSDKDriver is not implemented in v1"):
            driver.init({})

    def test_error_message_references_v2_milestone(self):
        driver = CursorSDKDriver()
        with pytest.raises(NotImplementedError, match=r"@cursor/sdk"):
            driver.init({})

    def test_error_message_refers_to_cli_driver(self):
        driver = CursorSDKDriver()
        with pytest.raises(NotImplementedError, match="CursorCLIDriver"):
            driver.init({})

    def test_full_message(self):
        driver = CursorSDKDriver()
        with pytest.raises(NotImplementedError) as exc_info:
            driver.init({})
        assert str(exc_info.value) == _EXPECTED_MSG


class TestCursorSDKDriverDispatch:
    def test_raises_not_implemented_error(self):
        driver = CursorSDKDriver()
        with pytest.raises(NotImplementedError):
            driver.dispatch("z-ask", ["--model", "claude-opus-4"], {})

    def test_full_message(self):
        driver = CursorSDKDriver()
        with pytest.raises(NotImplementedError) as exc_info:
            driver.dispatch("z-ask", [], {})
        assert str(exc_info.value) == _EXPECTED_MSG


class TestCursorSDKDriverTeardown:
    def test_raises_not_implemented_error(self):
        driver = CursorSDKDriver()
        with pytest.raises(NotImplementedError):
            driver.teardown()

    def test_full_message(self):
        driver = CursorSDKDriver()
        with pytest.raises(NotImplementedError) as exc_info:
            driver.teardown()
        assert str(exc_info.value) == _EXPECTED_MSG


class TestNoSDKImportAtModuleLevel:
    """sdk_driver.py must not import @cursor/sdk at module level.

    This ensures importing the stub does not fail when @cursor/sdk is absent.
    We verify this by removing a fake 'cursor_sdk' from sys.modules (if present),
    then re-importing the module, confirming it succeeds without the package.
    """

    def test_module_importable_without_cursor_sdk(self):
        # Remove the module from the cache to force a fresh import.
        mod_name = "runtime.drivers.cursor.sdk_driver"
        original = sys.modules.pop(mod_name, None)
        # Simulate @cursor/sdk being absent by ensuring it's not in sys.modules.
        cursor_sdk_original = sys.modules.pop("cursor_sdk", None)
        try:
            # This must not raise ImportError even if @cursor/sdk is absent.
            mod = importlib.import_module(mod_name)
            assert hasattr(mod, "CursorSDKDriver")
        except ImportError as exc:
            pytest.fail(f"sdk_driver.py raises ImportError on import when @cursor/sdk absent: {exc}")
        finally:
            # Restore the original modules.
            if original is not None:
                sys.modules[mod_name] = original
            if cursor_sdk_original is not None:
                sys.modules["cursor_sdk"] = cursor_sdk_original
