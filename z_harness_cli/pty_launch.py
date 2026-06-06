"""PTY passthrough launch primitive — D12 / F5 spec.

Spawns an interactive command in its own process group so the child
fully owns the terminal (colors, prompts, streaming).

Public surface
--------------
pty_launch(argv, env, cwd, cleanup) -> int

macOS / Linux only. On Windows (os.name == 'nt' or missing 'pty' module)
raises PTYUnsupportedError at import time OR at call time so callers can
catch it before dispatching.
"""

from __future__ import annotations

import os
import signal
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Platform guard — surface a clear error early.
# ---------------------------------------------------------------------------

class PTYUnsupportedError(NotImplementedError):
    """Raised on platforms where PTY launch is not supported (Windows)."""


def _assert_pty_available() -> None:
    """Raise PTYUnsupportedError on unsupported platforms."""
    if os.name == "nt":
        raise PTYUnsupportedError(
            "PTY passthrough launch is not supported on Windows. "
            "z-harness v1 supports macOS and Linux only."
        )
    try:
        import pty  # noqa: F401 — just probing availability
    except ImportError as exc:
        raise PTYUnsupportedError(
            "The 'pty' module is not available on this platform. "
            "PTY passthrough launch requires macOS or Linux."
        ) from exc


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def pty_launch(
    argv: list[str],
    env: dict[str, str],
    cwd: Path,
    cleanup: Optional[Callable[[], None]] = None,
) -> int:
    """Spawn *argv* in its own process group via a real PTY.

    The child process inherits the calling process's controlling terminal
    (stdin/stdout/stderr all connected through the PTY master), so it can
    render colors, prompts, and interactive TUI widgets exactly as if the
    user launched it directly.

    Parameters
    ----------
    argv:
        Command + arguments, e.g. ``["claude", "--project", "."]``.
    env:
        Full environment mapping for the child.  Typically built by
        ``env_bundle.resolve_env()`` merged over ``os.environ``.
    cwd:
        Working directory for the child process.
    cleanup:
        Optional zero-argument callable invoked once after the child exits
        (normally, on signal, or after a force-kill).  Called with SIGINT
        and SIGTERM **blocked** in the parent so the callback cannot be
        interrupted by a second signal.  Must be idempotent.

    Returns
    -------
    int
        The child's exit code (0 = success).

    Raises
    ------
    PTYUnsupportedError
        On Windows or any platform that lacks the ``pty`` stdlib module.
    """
    _assert_pty_available()

    import pty  # noqa: PLC0415 — deferred; safe after _assert_pty_available

    # We cannot use pty.spawn() because it doesn't support a custom cwd or
    # environment, and it doesn't give us a child PID to forward signals to.
    # Instead we fork+exec:
    #   parent: holds the PTY master fd, drives I/O, handles signals.
    #   child:  opens the PTY slave as its controlling terminal, exec's argv.
    #
    # The I/O relay loop copies bytes in both directions (master<->stdio) so
    # the parent terminal and the child PTY stay in sync.

    master_fd, slave_fd = pty.openpty()

    child_pid = os.fork()

    if child_pid == 0:
        # ---- child process ---------------------------------------------------
        # Close the master end; we only use the slave inside the child.
        os.close(master_fd)

        # Start a new session so the child becomes a process-group leader and
        # the slave PTY becomes its controlling terminal.
        os.setsid()

        # Make slave_fd the controlling terminal via TIOCSCTTY.
        import fcntl  # noqa: PLC0415
        import termios  # noqa: PLC0415
        try:
            fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
        except OSError:
            pass  # Some kernels set it automatically via setsid+open.

        # Wire slave_fd to all three std streams.
        for fd_target in (0, 1, 2):
            if slave_fd != fd_target:
                os.dup2(slave_fd, fd_target)
        if slave_fd > 2:
            os.close(slave_fd)

        # Change to the requested working directory.
        os.chdir(cwd)

        # exec — replaces the child process image; no return on success.
        os.execvpe(argv[0], argv, env)

        # If execvpe fails, exit the child immediately to avoid a second
        # cleanup run in the forked image.
        os._exit(127)  # noqa: SLF001

    # ---- parent process ------------------------------------------------------
    # Close the slave end; only the child needs it.
    os.close(slave_fd)

    # reap_result is a one-element list used as a mutable out-parameter so
    # _run_parent (via _wait_or_kill) can store the reaped exit code when it
    # reaps the child itself (interrupted path).  If it stays empty, the
    # normal-exit path below does the single reap instead.
    reap_result: list[int] = []

    try:
        _run_parent(master_fd=master_fd, child_pid=child_pid,
                    reap_result=reap_result)  # cleanup NOT passed; deferred to finally below

        # Normal-exit path: child not yet reaped by _wait_or_kill.
        if not reap_result:
            _, status = os.waitpid(child_pid, 0)
            reap_result.append(os.waitstatus_to_exitcode(status))
    finally:
        # BLOCKER 1: cleanup ALWAYS runs, regardless of relay exceptions,
        # late KeyboardInterrupt, or ChildProcessError from waitpid.
        _run_cleanup(cleanup)

    return reap_result[0]


# ---------------------------------------------------------------------------
# Parent-side I/O relay + signal handling
# ---------------------------------------------------------------------------

# Timeout in seconds before we force-kill the child after SIGINT/SIGTERM.
_KILL_TIMEOUT_S = 30


def _run_parent(
    master_fd: int,
    child_pid: int,
    reap_result: list[int],
) -> None:
    """Drive the I/O relay loop and install signal handlers.

    Blocks until the child exits (normally or via signal).  Does NOT call
    cleanup — that is deferred to *pty_launch* so it always runs after
    waitpid regardless of the exit path.

    If the interrupted path reaps the child via _wait_or_kill, the exit code
    is appended to *reap_result* so pty_launch can skip the second waitpid.
    """
    import select  # noqa: PLC0415

    # ---- terminal size forwarding -------------------------------------------
    # Copy the current terminal dimensions into the PTY so the child sees the
    # correct window size from the start.
    _sync_winsize(master_fd)

    # ---- signal handling -----------------------------------------------------
    # Keep a flag so the relay loop knows a signal was received.
    interrupted: list[int] = []  # mutable sentinel; 0 = SIGINT, 1 = SIGTERM

    original_sigint = signal.getsignal(signal.SIGINT)
    original_sigterm = signal.getsignal(signal.SIGTERM)
    original_sigwinch = signal.getsignal(signal.SIGWINCH)

    def _on_sigint(signum: int, frame: object) -> None:
        interrupted.append(signum)
        # Forward to the child's process group.
        try:
            os.killpg(os.getpgid(child_pid), signal.SIGINT)
        except ProcessLookupError:
            pass

    def _on_sigterm(signum: int, frame: object) -> None:
        interrupted.append(signum)
        try:
            os.killpg(os.getpgid(child_pid), signal.SIGTERM)
        except ProcessLookupError:
            pass

    def _on_sigwinch(signum: int, frame: object) -> None:
        _sync_winsize(master_fd)

    signal.signal(signal.SIGINT, _on_sigint)
    signal.signal(signal.SIGTERM, _on_sigterm)
    signal.signal(signal.SIGWINCH, _on_sigwinch)

    # ---- I/O relay loop ------------------------------------------------------
    # Relay bytes between the PTY master and the controlling terminal
    # (stdin/stdout) until the child closes its end of the PTY.
    stdin_fd = sys.stdin.fileno()
    stdout_fd = sys.stdout.fileno()

    # Put stdin in raw mode so keystrokes go straight to the PTY.
    import termios as _termios  # noqa: PLC0415
    try:
        old_attrs = _termios.tcgetattr(stdin_fd)
        import tty as _tty  # noqa: PLC0415
        _tty.setraw(stdin_fd)
        stdin_in_raw = True
    except _termios.error:
        # stdin is not a tty (e.g., piped input in tests) — still relay.
        old_attrs = None
        stdin_in_raw = False

    try:
        while True:
            # Use a short timeout so we can react to the interrupted flag.
            try:
                rlist, _, _ = select.select([master_fd, stdin_fd], [], [], 0.05)
            except (ValueError, OSError):
                # master_fd closed — child exited.
                break
            except InterruptedError:
                # A signal arrived between select calls; the handler ran.
                if interrupted:
                    # BLOCKER 2: single reap via _wait_or_kill; result stored
                    # in reap_result so pty_launch does NOT waitpid again.
                    reap_result.append(_wait_or_kill(child_pid))
                break

            if master_fd in rlist:
                try:
                    data = os.read(master_fd, 4096)
                    if data:
                        os.write(stdout_fd, data)
                    else:
                        break  # EOF from child.
                except OSError:
                    break  # PTY closed.

            if stdin_fd in rlist:
                try:
                    data = os.read(stdin_fd, 4096)
                    if data:
                        os.write(master_fd, data)
                except OSError:
                    break

            if interrupted:
                # BLOCKER 2: single reap via _wait_or_kill; result stored in
                # reap_result so pty_launch does NOT waitpid again.
                reap_result.append(_wait_or_kill(child_pid))
                break
    finally:
        # Restore terminal state regardless of how we exit.
        if stdin_in_raw and old_attrs is not None:
            try:
                _termios.tcsetattr(stdin_fd, _termios.TCSADRAIN, old_attrs)
            except _termios.error:
                pass

        # Restore original signal handlers.
        signal.signal(signal.SIGINT, original_sigint)
        signal.signal(signal.SIGTERM, original_sigterm)
        signal.signal(signal.SIGWINCH, original_sigwinch)

        try:
            os.close(master_fd)
        except OSError:
            pass


def _wait_or_kill(child_pid: int) -> int:
    """Wait up to _KILL_TIMEOUT_S for child to exit; force-kill if it doesn't.

    Returns the child's exit code.  This function is the single reap point
    for the interrupted path — callers must not waitpid(child_pid) again.

    BLOCKER 2 / MAJOR 3: exactly one waitpid reaps the child.  After SIGKILL
    we block-wait until reaped so no zombie is left behind.
    """
    import time  # noqa: PLC0415

    deadline = time.monotonic() + _KILL_TIMEOUT_S
    while time.monotonic() < deadline:
        try:
            pid, status = os.waitpid(child_pid, os.WNOHANG)
            if pid != 0:
                # Child exited and is now reaped.
                return os.waitstatus_to_exitcode(status)
        except ChildProcessError:
            # Already reaped by someone else (shouldn't happen, but be safe).
            return -1
        time.sleep(0.1)

    # 30 s elapsed — force-kill the whole process group.
    try:
        os.killpg(os.getpgid(child_pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass

    # MAJOR 3: reap the child after SIGKILL so no zombie is left.  Retry
    # until waitpid succeeds (the kernel may not deliver SIGKILL instantly).
    while True:
        try:
            pid, status = os.waitpid(child_pid, 0)
            return os.waitstatus_to_exitcode(status)
        except ChildProcessError:
            # Already gone — treat as killed.
            return -signal.SIGKILL


def _run_cleanup(cleanup: Optional[Callable[[], None]]) -> None:
    """Invoke *cleanup* with SIGINT and SIGTERM blocked (no double-cleanup).

    MAJOR 4: uses pthread_sigmask (SIG_BLOCK) to defer signals rather than
    SIG_IGN (which discards them).  Falls back to SIG_IGN if pthread_sigmask
    is unavailable (unlikely on any POSIX platform we support).
    """
    if cleanup is None:
        return

    _BLOCK_SET = {signal.SIGINT, signal.SIGTERM}

    # Prefer pthread_sigmask so pending signals are deferred, not discarded.
    if hasattr(signal, "pthread_sigmask"):
        old_mask = signal.pthread_sigmask(signal.SIG_BLOCK, _BLOCK_SET)
        try:
            cleanup()
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, old_mask)
    else:
        # Fallback for platforms without pthread_sigmask.
        old_sigint = signal.signal(signal.SIGINT, signal.SIG_IGN)
        old_sigterm = signal.signal(signal.SIGTERM, signal.SIG_IGN)
        try:
            cleanup()
        finally:
            signal.signal(signal.SIGINT, old_sigint)
            signal.signal(signal.SIGTERM, old_sigterm)


def _sync_winsize(master_fd: int) -> None:
    """Copy the real terminal's window size into the PTY master."""
    try:
        import fcntl  # noqa: PLC0415
        import struct  # noqa: PLC0415
        import termios  # noqa: PLC0415

        # Query current window size from stdout.
        packed = fcntl.ioctl(sys.stdout.fileno(), termios.TIOCGWINSZ, b"\x00" * 8)
        rows, cols, xpix, ypix = struct.unpack("HHHH", packed)
        # Apply to the PTY master so the child sees the right dimensions.
        winsize = struct.pack("HHHH", rows, cols, xpix, ypix)
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
    except OSError:
        pass  # Not a tty or not supported — non-fatal.
