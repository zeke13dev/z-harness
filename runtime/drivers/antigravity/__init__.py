# runtime/drivers/antigravity/__init__.py

# C1 interface conformance: AntigravityDriver implements the C1 HostDriver ABC
# at runtime.dispatch.driver. Public surface is dispatch(prompt: str) -> Iterator[dict].
# Full HostDriver wiring (init/dispatch returning DispatchHandle/teardown) is a follow-up.

from runtime.drivers.antigravity.driver import AntigravityDriver, DriverDispatchError, DriverConstraintError
from runtime.drivers.antigravity.preflight import DriverUnavailableError

__all__ = [
    "AntigravityDriver",
    "DriverUnavailableError",
    "DriverDispatchError",
    "DriverConstraintError",
]
