"""Resilient launcher for Playwright's persistent Firefox context on Windows.

A persistent Firefox profile fails to open for three well-known reasons, and all
three present the same way: ``launch_persistent_context`` raises after Firefox
*started* and then exited 0 — it launched, couldn't open the profile, found
nothing to do, and quit cleanly (a missing binary or a crash would give a
non-zero code, so exit 0 right after launch is the tell). The three causes:

  1. **Stale lock files** (``parent.lock`` / ``.parentlock`` / ``lock``) left in
     the profile by a run that was *killed* instead of closed.
  2. **An orphaned ``firefox.exe`` still holding the profile.** Under
     ``-no-remote`` the new instance exits rather than attaching to the running
     one.
  3. **A profile built by a different Playwright Firefox revision.** Playwright
     ships a patched Firefox; a profile from another build (or from stock
     Firefox) fails the ``compatibility.ini`` check and Firefox exits silently —
     there is no UI in which to show the error.

``launch_persistent_firefox`` wraps the launch in an escalating recovery routine
that handles 1 and 2, and proactively quarantines a profile whose recorded build
revision no longer matches the installed one (cause 3) instead of burning a
launch attempt on a profile that cannot work.

Everything here is Windows-first (that is where these failures occur) but the
lock-clearing and quarantine steps are harmless on any platform.
"""

import logging
import os
import re
import subprocess
import time

logger = logging.getLogger(__name__)

# Lock files Firefox writes into a profile while running; a clean shutdown
# removes them, a kill does not. ``parent.lock`` is the Windows name,
# ``.parentlock`` / ``lock`` the POSIX ones — we clear all three so the routine
# is correct regardless of who left the profile behind.
_PROFILE_LOCK_FILES = ("parent.lock", ".parentlock", "lock")

# Our own marker file recording which Playwright Firefox build created (or last
# successfully matched) the profile, compared against the installed build on
# startup to catch cause 3 before it wastes a launch attempt.
_REVISION_MARKER = ".playwright_firefox_revision"


def firefox_revision(executable_path):
    """Return the ``firefox-<n>`` build token from a Playwright firefox path.

    Playwright installs each build at
    ``...\\ms-playwright\\firefox-<n>\\firefox\\firefox.exe``. Returns ``""`` when
    the path has no such segment, in which case revision checks are skipped
    (degrade to no proactive quarantine rather than guess).
    """
    m = re.search(r"firefox-(\d+)", executable_path or "")
    return "firefox-" + m.group(1) if m else ""


def _read_marker(user_data_dir):
    """Return the build revision recorded in the profile's marker, or ``""``."""
    try:
        with open(os.path.join(user_data_dir, _REVISION_MARKER),
                  encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def _write_marker(user_data_dir, revision):
    """Record ``revision`` as the build that owns this profile (best effort)."""
    if not revision:
        return
    try:
        with open(os.path.join(user_data_dir, _REVISION_MARKER), "w",
                  encoding="utf-8") as fh:
            fh.write(revision)
    except OSError as exc:
        logger.warning("Could not write profile revision marker: %s", exc)


def _clear_locks(user_data_dir):
    """Delete stale Firefox lock files from the profile. Returns count removed."""
    removed = 0
    for name in _PROFILE_LOCK_FILES:
        path = os.path.join(user_data_dir, name)
        try:
            if os.path.lexists(path):
                os.remove(path)
                removed += 1
                logger.info("Cleared stale Firefox lock file: %s", path)
        except OSError as exc:
            logger.warning("Could not remove lock file %s: %s", path, exc)
    return removed


def _kill_profile_holders(user_data_dir):
    """Kill only Firefox processes whose command line names *this* profile.

    Deliberately never does a blanket ``taskkill /IM firefox.exe`` — that would
    close the user's ordinary browsing session. Matches on the profile path in
    the process command line. Prefers ``psutil``; falls back to a PowerShell
    ``Get-CimInstance Win32_Process`` query (never ``wmic``, which is removed from
    recent Windows). Returns the number of processes killed.
    """
    target = os.path.normcase(os.path.abspath(user_data_dir))
    killed = _kill_holders_psutil(target)
    if killed is None:                       # psutil not installed
        killed = _kill_holders_powershell(user_data_dir)
    if killed:
        time.sleep(1.0)                      # let the OS release the profile's handles
    return killed


def _kill_holders_psutil(target):
    """psutil implementation of :func:`_kill_profile_holders`.

    ``target`` is the normcased absolute profile path. Returns the kill count, or
    ``None`` when psutil is not installed (so the caller can fall back).
    """
    try:
        import psutil
    except ImportError:
        return None
    killed = 0
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            if "firefox" not in (proc.info.get("name") or "").lower():
                continue
            cmdline = os.path.normcase(" ".join(proc.info.get("cmdline") or []))
            if target in cmdline:
                proc.kill()
                killed += 1
                logger.warning("Killed Firefox pid=%s holding profile %s",
                               proc.pid, target)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return killed


def _kill_holders_powershell(user_data_dir):
    """PowerShell fallback for :func:`_kill_profile_holders` (no psutil).

    Uses ``Get-CimInstance Win32_Process`` (``wmic`` is gone from recent Windows)
    to find ``firefox.exe`` processes whose command line contains the profile
    path and stops each by PID. Returns the number killed.
    """
    # -like matches the profile path as a wildcard body; backslashes are literal
    # in -like and a Windows profile path has no *,?,[ so it is used verbatim.
    pattern = user_data_dir.replace("'", "''")
    script = (
        "$ErrorActionPreference='SilentlyContinue';"
        "Get-CimInstance Win32_Process -Filter \"Name = 'firefox.exe'\" | "
        "Where-Object { $_.CommandLine -like '*" + pattern + "*' } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force; $_.ProcessId }"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("PowerShell process-kill fallback failed: %s", exc)
        return 0
    pids = [ln.strip() for ln in (result.stdout or "").splitlines() if ln.strip()]
    for pid in pids:
        logger.warning("Killed Firefox pid=%s holding profile %s (PowerShell)",
                       pid, user_data_dir)
    return len(pids)


def _quarantine_profile(user_data_dir):
    """Rename the profile aside (never delete) so Playwright recreates a fresh one.

    Returns the new path, or ``""`` if there was nothing to move. Deleting would
    destroy cookies and any cleared bot-check state irretrievably; renaming keeps
    it recoverable. Logged at WARNING because the next run must re-clear
    realtor.ca's challenge from scratch.
    """
    if not os.path.isdir(user_data_dir):
        return ""
    dest = "%s.broken-%s" % (user_data_dir, time.strftime("%Y%m%d-%H%M%S"))
    os.rename(user_data_dir, dest)
    logger.warning("Reset Firefox profile: moved %s -> %s; realtor.ca session "
                   "state will be rebuilt on the next run.", user_data_dir, dest)
    return dest


def launch_persistent_firefox(firefox, user_data_dir, allow_profile_reset=True,
                              **launch_kwargs):
    """Launch a persistent Firefox context, recovering automatically from the
    common ways a Windows persistent profile fails to open.

    ``firefox`` is a Playwright ``BrowserType`` (i.e. ``playwright.firefox``).
    ``launch_kwargs`` are passed straight through to ``launch_persistent_context``
    (headless, viewport, user_agent, proxy, prefs, …) — nothing is hardcoded
    here. Escalation on repeated failure:

      1. launch as-is;
      2. clear stale lock files, relaunch;
      3. kill processes holding the profile, clear locks, relaunch;
      4. rename the profile aside and relaunch once.

    Before any of that, if the profile's recorded build revision disagrees with
    the installed Playwright Firefox (cause 3), the profile is quarantined up
    front rather than spending an attempt on a launch that cannot succeed.

    ``allow_profile_reset=False`` forbids the reset (step 4 *and* the proactive
    quarantine): for callers where losing realtor.ca session state is worse than
    failing, the routine raises instead of resetting.

    Raises ``RuntimeError`` (chained to the last underlying error, with the
    profile path in the message) if every step fails.
    """
    os.makedirs(user_data_dir, exist_ok=True)

    installed_rev = firefox_revision(getattr(firefox, "executable_path", "") or "")
    marker_rev = _read_marker(user_data_dir)

    # Proactive cause-3 guard: a profile built by a different Playwright Firefox
    # build exits 0 with no surfaced error. Quarantine it now rather than
    # spending an attempt (and the kill/lock escalations) on a hopeless launch.
    if installed_rev and marker_rev and marker_rev != installed_rev:
        msg = ("Firefox profile %s was built by %s but the installed Playwright "
               "Firefox is %s" % (user_data_dir, marker_rev, installed_rev))
        if not allow_profile_reset:
            raise RuntimeError(msg + "; profile reset is disabled "
                               "(allow_profile_reset=False), refusing to launch.")
        logger.warning("%s; quarantining the profile before launch.", msg)
        _quarantine_profile(user_data_dir)
        os.makedirs(user_data_dir, exist_ok=True)

    def _try_launch():
        ctx = firefox.launch_persistent_context(user_data_dir=user_data_dir,
                                                **launch_kwargs)
        _write_marker(user_data_dir, installed_rev)
        return ctx

    # 1) Launch as-is.
    try:
        return _try_launch()
    except Exception as exc:
        last_err = exc
        logger.warning("Firefox launch attempt 1/3 failed: %s", exc)

    # 2) Clear stale lock files, relaunch.
    _clear_locks(user_data_dir)
    try:
        return _try_launch()
    except Exception as exc:
        last_err = exc
        logger.warning("Firefox launch attempt 2/3 (after clearing locks) "
                       "failed: %s", exc)

    # 3) Kill processes holding the profile, clear locks again, relaunch.
    _kill_profile_holders(user_data_dir)
    _clear_locks(user_data_dir)
    try:
        return _try_launch()
    except Exception as exc:
        last_err = exc
        logger.warning("Firefox launch attempt 3/3 (after killing profile "
                       "holders) failed: %s", exc)

    # 4) Last resort: reset the profile and try once more — unless forbidden.
    if not allow_profile_reset:
        raise RuntimeError(
            "Failed to launch persistent Firefox at %s after 3 attempts; profile "
            "reset is disabled (allow_profile_reset=False). Last error: %s"
            % (user_data_dir, last_err)) from last_err

    _quarantine_profile(user_data_dir)
    os.makedirs(user_data_dir, exist_ok=True)
    try:
        return _try_launch()
    except Exception as exc:
        raise RuntimeError(
            "Failed to launch persistent Firefox at %s after 3 recovery attempts "
            "and a profile reset. Last error: %s" % (user_data_dir, exc)) from exc
