"""icond_backend.py — KDE Plasma layout backend for icond.

HOW KDE STORES THE DESKTOP ICON LAYOUT
--------------------------------------
Unlike Windows (where a COM/shell API moves icon handles), Plasma persists
the entire desktop layout — containments, FolderView plasmoid, icon grid
positions and widget placements — in one INI-style file:

    ~/.config/plasma-org.kde.plasma.desktop-appletsrc

So the reliable, version-agnostic strategy is:

1. Stop plasmashell FIRST (otherwise it may overwrite our changes on exit,
   because plasmashell flushes its own config state when it shuts down).
2. Take a rolling safety backup of the current file.
3. Atomically replace the file with the snapshot's stored content.
4. Start plasmashell again — the desktop redraws with the restored layout.

This works on X11 and Wayland, and does not depend on Plasma-specific
internal key names that can shift between Plasma 5 and Plasma 6.
"""

import datetime
import glob
import os
import shutil
import subprocess
import time

CONFIG_HOME = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
APPLETSRC = os.path.join(CONFIG_HOME, "plasma-org.kde.plasma.desktop-appletsrc")

#: how many rolling safety backups to keep (newest kept, older pruned)
BACKUP_KEEP = 10


class IcondError(Exception):
    """Raised for any fatal backend problem worth surfacing in the GUI."""


def is_plasma_session() -> bool:
    """True if the current session is KDE Plasma.

    Checked in order of reliability:
      1. XDG_CURRENT_DESKTOP mentions 'kde' or 'plasma'
         (KDE Neon reports 'KDE'; some distros report 'plasma' or 'KDE:GNOME')
      2. KDEFULL_SESSION / KDE_SESSION_VERSION are set (set by startkde/plasmastart)
      3. plasmashell is running AND the appletsrc config file exists
    """
    xdg = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    if "kde" in xdg or "plasma" in xdg:
        return True
    if os.environ.get("KDE_FULL_SESSION") or os.environ.get("KDEFULL_SESSION"):
        return True
    if os.environ.get("KDE_SESSION_VERSION"):
        return True
    r = subprocess.run(["pgrep", "-x", "plasmashell"], check=False,
                       capture_output=True)
    if r.returncode == 0 and os.path.isfile(APPLETSRC):
        return True
    return False


def appletsrc_path() -> str:
    return APPLETSRC


def snapshot_appletsrc(path: str = APPLETSRC) -> str:
    """Read the current Plasma desktop config as text."""
    if not os.path.isfile(path):
        raise IcondError(
            f"Plasma config not found at {path}. "
            "Are you running this on a KDE Plasma session?"
        )
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _plasmashell_state() -> str | None:
    """Return 'systemd', 'direct' or None depending on how plasmashell runs."""
    r = subprocess.run(
        ["systemctl", "--user", "is-active", "--quiet", "plasma-plasmashell.service"],
        check=False,
        capture_output=True,
    )
    if r.returncode == 0:
        return "systemd"
    r2 = subprocess.run(["pgrep", "-x", "plasmashell"], check=False)
    return "direct" if r2.returncode == 0 else None


def _stop_plasmashell() -> None:
    state = _plasmashell_state()
    if state is None:
        return
    if state == "systemd":
        subprocess.run(
            ["systemctl", "--user", "stop", "plasma-plasmashell.service"],
            check=False,
        )
    else:
        subprocess.run(["pkill", "-x", "plasmashell"], check=False)
    # Wait until it is really gone so it cannot race us and rewrite the file.
    for _ in range(75):  # up to ~15 s
        if _plasmashell_state() is None:
            break
        time.sleep(0.2)


def _start_plasmashell() -> None:
    if _plasmashell_state() is not None:
        return
    r = subprocess.run(
        ["systemctl", "--user", "start", "plasma-plasmashell.service"],
        check=False,
    )
    if r.returncode != 0:
        # Very old/odd setups: launch it directly, detached.
        subprocess.Popen(["plasmashell"], start_new_session=True)


def _backup_current(path: str) -> str | None:
    """Copy the current config to a timestamped rolling backup."""
    if not os.path.isfile(path):
        return None
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = f"{path}.icond-{stamp}.bak"
    shutil.copy2(path, bak)
    olds = sorted(glob.glob(f"{path}.icond-*.bak"))
    for old in olds[:-BACKUP_KEEP]:
        try:
            os.remove(old)
        except OSError:
            pass
    return bak


def _atomic_write(path: str, text: str) -> None:
    tmp = f"{path}.icond-tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def restore_appletsrc(content: str, path: str = APPLETSRC) -> str | None:
    """Stop plasmashell, swap the config, restart plasmashell.

    Returns the path of the safety backup taken before the swap
    (so the GUI can tell the user where their prior layout went).
    """
    if not content or not content.strip():
        raise IcondError("Refusing to restore: profile content is empty.")
    _stop_plasmashell()
    # Give any late shutdown flush a beat to finish before we swap files.
    time.sleep(1.0)
    bak = _backup_current(path)
    _atomic_write(path, content)
    _start_plasmashell()
    return bak
