"""
timeout.py — TimeoutReaper context manager and DispatchTimeoutError.

Usage:
    with TimeoutReaper(proc, timeout_s=60):
        proc.wait()
    # If proc.wait() returns within timeout_s, no exception is raised.
    # If the timeout fires, DispatchTimeoutError is raised and the process
    # is terminated (SIGTERM, then SIGKILL after 5 s if still alive).
"""

import subprocess
import threading


class DispatchTimeoutError(Exception):
    """Raised when a subprocess exceeds its allotted timeout."""

    def __init__(self, timeout_s: int, pid: int) -> None:
        self.timeout_s = timeout_s
        self.pid = pid
        super().__init__(
            f"Process {pid} did not complete within {timeout_s} second(s)"
        )


class TimeoutReaper:
    """Context manager that enforces a wall-clock timeout on a Popen instance.

    When the wrapped block exits normally (no exception) the timer is
    cancelled and nothing further happens.

    If the timeout fires before the wrapped block finishes:
      - The timer thread sends SIGTERM directly to the process, unblocking
        any proc.wait() call in any thread (no _thread.interrupt_main needed).
      - __exit__ detects the timeout, reaps the process if still alive, then
        raises DispatchTimeoutError.

    Reaping sequence (when proc is still alive at __exit__ time):
      1. Send SIGTERM (idempotent — may already have been sent by _on_timeout).
      2. Wait up to 5 seconds for the process to exit.
      3. If still alive after 5 seconds, send SIGKILL and wait again (no
         second timeout — kill is unmissable per POSIX).
    """

    def __init__(self, proc: subprocess.Popen, timeout_s: int) -> None:
        self.proc = proc
        self.timeout_s = timeout_s
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()
        self._timed_out = False

    def __enter__(self) -> "TimeoutReaper":
        self._timed_out = False
        self._timer = threading.Timer(self.timeout_s, self._on_timeout)
        self._timer.daemon = True
        self._timer.start()
        return self

    def _on_timeout(self) -> None:
        """Runs on the timer thread when timeout_s elapses."""
        with self._lock:
            # Only declare timeout if the process is still running.
            if self.proc.poll() is not None:
                return
            self._timed_out = True
            # Send SIGTERM directly — this unblocks proc.wait() in any thread.
            try:
                self.proc.terminate()
            except OSError:
                # Process exited between poll() and terminate(); not a timeout.
                self._timed_out = False

    def __exit__(
        self,
        exc_type: type | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> bool:
        # Cancel the timer if it hasn't fired yet.
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

        with self._lock:
            timed_out = self._timed_out
            proc_still_alive = self.proc.poll() is None

        if proc_still_alive:
            self._reap()

        if timed_out:
            raise DispatchTimeoutError(self.timeout_s, self.proc.pid)

        # Do not suppress other exceptions.
        return False

    def _reap(self) -> None:
        """Send SIGTERM; wait up to 5 s; send SIGKILL if still alive."""
        proc = self.proc

        try:
            proc.terminate()  # SIGTERM (idempotent if already sent)
        except OSError:
            # Process exited between the alive check and terminate().
            pass

        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            # Still alive after exactly 5 s — escalate to SIGKILL.
            try:
                proc.kill()  # SIGKILL
            except OSError:
                pass
            # Wait with no timeout — kill is unmissable per POSIX.
            proc.wait()
