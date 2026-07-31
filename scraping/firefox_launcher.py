"""Resilient launcher for Playwright's persistent Firefox context.

A persistent Firefox profile can only be opened by one process at a time — the
scraper launches with ``-no-remote``. The failure this guards against is the
common one: the scraper is **already running**, so a second launch on the same
profile finds it in use, opens nothing, and Firefox exits 0 — which Playwright
surfaces as ``Failed to launch the browser process`` buried under an unrelated
``shader-cache`` graphics warning. (Exit 0 is the tell: a missing binary or a
crash gives a non-zero code; exit 0 right after launch means Firefox started,
couldn't take the profile, and quit cleanly.)

``launch_persistent_firefox``:

  * **detects an already-running instance up front** — a Firefox process whose
    command line names *this* profile — and fails fast with one clear message
    (:class:`FirefoxProfileInUseError`), instead of thrashing through retries or
    killing the live run;
  * otherwise launches, and on failure escalates gently: clear the stale lock
    files a *killed* run leaves behind, then — only as a last resort, and only
    when the caller permits it — rename the profile aside so Playwright can
    recreate it.

Nothing here ever does a blanket ``taskkill /IM firefox.exe`` (that would close
the user's ordinary browsing session), nothing kills a healthy running instance,
and nothing deletes profile data.
"""

import logging
import os
import subprocess
import time

logger = logging.getLogger(__name__)

# Lock files Firefox writes into a profile while running; a clean shutdown
# removes them, a kill does not. ``parent.lock`` is the Windows name,
# ``.parentlock`` / ``lock`` the POSIX ones — we clear all three so the routine
# is correct regardless of who left the profile behind.
_PROFILE_LOCK_FILES = ("parent.lock", ".parentlock", "lock")


class FirefoxProfileInUseError(RuntimeError):
    """The profile is already open in another Firefox instance (scraper running).

    A subclass of ``RuntimeError`` so existing broad handlers still catch it,
    while callers that want to show a friendly "already running" message can
    catch it specifically.
    """


def _short(exc):
    """First line of an exception message.

    Playwright appends the entire browser log to its launch errors; echoing that
    on every retry is exactly the wall of noise we want to avoid.
    """
    text = str(exc).strip()
    return text.splitlines()[0] if text else repr(exc)


def profile_holder_pids(user_data_dir):
    """PIDs of Firefox processes whose command line references this profile.

    Read-only — this is how we tell "already running" apart from a genuinely
    broken profile. Matches on the specific profile path (never a blanket firefox
    match), preferring ``psutil`` and falling back to a PowerShell
    ``Get-CimInstance Win32_Process`` query (never the removed ``wmic``).
    """
    target = os.path.normcase(os.path.abspath(user_data_dir))
    pids = _holder_pids_psutil(target)
    if pids is None:                          # psutil not installed
        pids = _holder_pids_powershell(user_data_dir)
    return pids


def _holder_pids_psutil(target):
    """psutil implementation of :func:`profile_holder_pids`; ``target`` is the
    normcased absolute profile path. Returns ``None`` when psutil is absent."""
    try:
        import psutil
    except ImportError:
        return None
    pids = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if "firefox" not in (proc.info.get("name") or "").lower():
                continue
            cmdline = os.path.normcase(" ".join(proc.info.get("cmdline") or []))
            if target in cmdline:
                pids.append(proc.info["pid"])
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return pids


def _holder_pids_powershell(user_data_dir):
    """PowerShell fallback for :func:`profile_holder_pids` (no psutil)."""
    # -like matches the profile path as a wildcard body; backslashes are literal
    # in -like and a Windows profile path has no *,?,[ so it is used verbatim.
    pattern = user_data_dir.replace("'", "''")
    script = (
        "$ErrorActionPreference='SilentlyContinue';"
        "Get-CimInstance Win32_Process -Filter \"Name = 'firefox.exe'\" | "
        "Where-Object { $_.CommandLine -like '*" + pattern + "*' } | "
        "ForEach-Object { $_.ProcessId }"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("PowerShell profile-holder query failed: %s", exc)
        return []
    return [int(tok) for tok in result.stdout.split() if tok.strip().isdigit()]


def _clear_locks(user_data_dir):
    """Delete stale Firefox lock files left by a killed (not closed) run.

    Returns the number removed.
    """
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
    logger.warning("Reset Firefox profile as a last resort: moved %s -> %s; the "
                   "realtor.ca session will be rebuilt on the next run.",
                   user_data_dir, dest)
    return dest


def launch_persistent_firefox(firefox, user_data_dir, allow_profile_reset=True,
                              detect_running=True, **launch_kwargs):
    """Launch a persistent Firefox context, recovering from the usual reasons a
    Windows persistent profile won't open.

    ``firefox`` is a Playwright ``BrowserType`` (i.e. ``playwright.firefox``).
    ``launch_kwargs`` pass straight through to ``launch_persistent_context``
    (headless, viewport, user_agent, proxy, prefs, …) — nothing is hardcoded
    here. Flow:

      * ``detect_running`` (default True): if a Firefox process already holds
        this profile, raise :class:`FirefoxProfileInUseError` immediately — a
        persistent profile can't be opened twice, and the running instance is
        left untouched. Pass ``False`` on an internal relaunch that has just
        closed its own context (so it can't false-positive on itself).
      * launch as-is;
      * on failure, clear stale lock files and relaunch;
      * on failure, and only when ``allow_profile_reset`` is True, rename the
        profile aside (last resort) and relaunch once.

    Raises ``RuntimeError`` (chained to the last underlying error, with the
    profile path in the message) if it still can't launch.
    """
    os.makedirs(user_data_dir, exist_ok=True)

    if detect_running:
        holders = profile_holder_pids(user_data_dir)
        if holders:
            raise FirefoxProfileInUseError(
                "The realtor.ca scraper looks like it's already running: Firefox "
                "%s already has the profile %s open. A persistent Firefox profile "
                "can't be opened twice — close that run before starting another. "
                "(If you're sure nothing is running, those are leftover processes "
                "from a run that didn't shut down cleanly; end them and retry.)"
                % (", ".join("pid=%d" % p for p in holders), user_data_dir))

    def _try_launch():
        return firefox.launch_persistent_context(user_data_dir=user_data_dir,
                                                 **launch_kwargs)

    # 1) Launch as-is.
    try:
        return _try_launch()
    except Exception as exc:
        last_err = exc
        logger.warning("Firefox launch failed; clearing stale locks and "
                       "retrying: %s", _short(exc))

    # 2) Clear stale lock files (left by a killed, not cleanly closed, run).
    _clear_locks(user_data_dir)
    try:
        return _try_launch()
    except Exception as exc:
        last_err = exc
        logger.warning("Firefox relaunch after clearing locks failed: %s",
                       _short(exc))

    # 3) Last resort: reset the profile, if the caller permits it.
    if not allow_profile_reset:
        raise RuntimeError(
            "Could not launch persistent Firefox at %s (stale locks were cleared). "
            "Automatic profile reset is off (allow_profile_reset=False), so your "
            "realtor.ca session is left intact. Last error: %s"
            % (user_data_dir, _short(last_err))) from last_err

    _quarantine_profile(user_data_dir)
    os.makedirs(user_data_dir, exist_ok=True)
    try:
        return _try_launch()
    except Exception as exc:
        raise RuntimeError(
            "Could not launch persistent Firefox at %s even after resetting the "
            "profile. Last error: %s" % (user_data_dir, _short(exc))) from exc
