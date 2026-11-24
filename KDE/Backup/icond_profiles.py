"""icond_profiles.py — named layout profiles for icond.

Profiles are stored under ~/.local/share/icond/profiles/<name>.kdl
(".kdl" = Konfig Desktop Layout). Each file holds:

  - the exact text of plasma-org.kde.plasma.desktop-appletsrc at save time
  - the monitor geometry / resolution fingerprint it was saved under

Choose a directory WITHOUT spaces in the name when creating profiles.
"""

import json
import os
import re

DATA_HOME = os.environ.get(
    "XDG_DATA_HOME", os.path.expanduser("~/.local/share")
)
PROFILE_DIR = os.path.join(DATA_HOME, "icond", "profiles")

SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


class ProfileError(Exception):
    pass


def _safe(name: str) -> str:
    if not name or not SAFE_NAME.match(name):
        raise ProfileError(
            f"Invalid profile name '{name}'. "
            "Use letters, numbers, dots, dashes or underscores only."
        )
    if name.startswith("."):
        raise ProfileError("Profile names cannot start with a dot.")
    return name


def ensure_dir() -> str:
    os.makedirs(PROFILE_DIR, exist_ok=True)
    return PROFILE_DIR


def list_profiles() -> list[dict]:
    """Return profile metadata dicts sorted by save time (newest first)."""
    ensure_dir()
    out = []
    for fn in os.listdir(PROFILE_DIR):
        if not fn.endswith(".kdl"):
            continue
        p = os.path.join(PROFILE_DIR, fn)
        try:
            with open(p, "r", encoding="utf-8") as fh:
                doc = json.load(fh)
            out.append({
                "name": doc.get("name", fn[:-4]),
                "resolution": doc.get("resolution", "?"),
                "geometry": doc.get("geometry", ""),
                "saved_at": doc.get("saved_at", ""),
                "path": p,
            })
        except (OSError, ValueError):
            # Corrupt/unreadable profiles are skipped, never crash the GUI.
            continue
    out.sort(key=lambda d: d["saved_at"], reverse=True)
    return out


def save_profile(name: str, appletsrc_text: str, resolution: str,
                 geometry: str) -> str:
    """Persist a named profile. Returns the profile file path."""
    name = _safe(name)
    ensure_dir()
    doc = {
        "name": name,
        "resolution": resolution,
        "geometry": geometry,
        "saved_at": datetime_utcnow_iso(),
        "appletsrc": appletsrc_text,
    }
    tmp = os.path.join(PROFILE_DIR, f"{name}.kdl.tmp")
    dst = os.path.join(PROFILE_DIR, f"{name}.kdl")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
    os.replace(tmp, dst)
    return dst


def load_profile(name: str) -> dict:
    """Load a profile by name. Raises ProfileError if missing/corrupt."""
    name = _safe(name)
    p = os.path.join(PROFILE_DIR, f"{name}.kdl")
    if not os.path.isfile(p):
        raise ProfileError(f"No profile named '{name}' exists.")
    try:
        with open(p, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except ValueError as exc:
        raise ProfileError(f"Profile '{name}' is corrupt: {exc}") from exc
    if not doc.get("appletsrc"):
        raise ProfileError(f"Profile '{name}' has no layout data.")
    return doc


def delete_profile(name: str) -> None:
    name = _safe(name)
    p = os.path.join(PROFILE_DIR, f"{name}.kdl")
    if os.path.isfile(p):
        os.remove(p)


def rename_profile(old: str, new: str) -> str:
    old, new = _safe(old), _safe(new)
    src = os.path.join(PROFILE_DIR, f"{old}.kdl")
    dst = os.path.join(PROFILE_DIR, f"{new}.kdl")
    if not os.path.isfile(src):
        raise ProfileError(f"No profile named '{old}' exists.")
    if os.path.isfile(dst):
        raise ProfileError(f"A profile named '{new}' already exists.")
    os.rename(src, dst)
    # also rename the appletsrc-inside note
    try:
        with open(dst, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
        doc["name"] = new
        with open(dst, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)
    except (OSError, ValueError):
        pass
    return dst


def datetime_utcnow_iso() -> str:
    import datetime
    return datetime.datetime.now().isoformat(timespec="seconds")
