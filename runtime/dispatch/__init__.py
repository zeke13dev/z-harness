"""
runtime.dispatch
================

In-process dispatcher layer for z-harness.

Public surface
--------------
- :class:`~runtime.dispatch.driver.HostDriver` — abstract base class for all
  host drivers.
- :class:`~runtime.dispatch.driver.DispatchHandle` — opaque streaming handle
  returned by :meth:`~runtime.dispatch.driver.HostDriver.dispatch`.

Downstream clusters (C2-C5) implement :class:`HostDriver` to provide
host-specific command execution.  The dispatcher (``dispatcher.py``) consumes
:class:`DispatchHandle` without knowing the underlying transport or output
format.
"""

from runtime.dispatch.driver import DispatchHandle, HostDriver

__all__ = ["HostDriver", "DispatchHandle"]
