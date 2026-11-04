"""Create Windows shortcuts for MicroCompta using the app's own icon.

Writes MicroCompta.lnk to the project root, the Desktop and the Start Menu, each pointing
at the project's pythonw.exe so launching shows no console window.

Deadline reminders only fire while the app runs. To have it start with Windows and wait
in the tray, add a shortcut to the Startup folder with --startup.

Run:  .venv/Scripts/python.exe scripts/make_shortcut.py
      .venv/Scripts/python.exe scripts/make_shortcut.py --project-only
      .venv/Scripts/python.exe scripts/make_shortcut.py --startup
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

from microcompta.config import APP_ICO, APP_NAME  # noqa: E402

# PowerShell does the COM work; it avoids a pywin32 dependency just for this.
PS_TEMPLATE = r"""
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut('{lnk}')
$sc.TargetPath       = '{target}'
$sc.Arguments        = '-m microcompta'
$sc.WorkingDirectory = '{workdir}'
$sc.IconLocation     = '{icon}'
$sc.Description      = '{description}'
$sc.WindowStyle      = 1
$sc.Save()
"""


def _pythonw() -> Path:
    """Prefer the venv's windowless interpreter so no console flashes up."""
    for candidate in (
        ROOT / ".venv" / "Scripts" / "pythonw.exe",
        Path(sys.executable).with_name("pythonw.exe"),
    ):
        if candidate.exists():
            return candidate
    return Path(sys.executable)


def make_shortcut(lnk: Path) -> bool:
    script = PS_TEMPLATE.format(
        lnk=str(lnk).replace("'", "''"),
        target=str(_pythonw()).replace("'", "''"),
        workdir=str(ROOT).replace("'", "''"),
        icon=f"{APP_ICO},0".replace("'", "''"),
        description=f"{APP_NAME}: personal accounting for a micro-entrepreneur",
    )
    lnk.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not lnk.exists():
        print(f"  ! failed: {(result.stderr or result.stdout).strip()[:200]}")
        return False
    print(f"  created {lnk}")
    return True


def main() -> int:
    if os.name != "nt":
        print("Shortcuts are Windows-only. On macOS/Linux use ./run.sh.")
        return 1

    project = ROOT / f"{APP_NAME}.lnk"
    appdata = os.environ.get("APPDATA")
    if "--project-only" in sys.argv:
        targets = [project]
    elif "--startup" in sys.argv:
        if not appdata:
            print("APPDATA is not set, so the Startup folder can't be found.")
            return 1
        targets = [Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
                   / "Startup" / f"{APP_NAME}.lnk"]
    else:
        targets = [project, Path(os.path.expanduser("~/Desktop")) / f"{APP_NAME}.lnk"]
        if appdata:
            targets.append(
                Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / f"{APP_NAME}.lnk"
            )
    return 0 if all([make_shortcut(t) for t in targets]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
