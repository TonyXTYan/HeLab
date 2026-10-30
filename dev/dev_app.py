"""Build ``HeLab-dev.app``: a small macOS app stub that runs this checkout's HeLab from source.

A source run (``venv/bin/helab``) is a bare python process with no bundle ID, so computer-use
tools (``app_*``) can't target it and screenshots hide its window. This stub gives it one: its
executable is a shell script that ``cd``s to the checkout and ``exec``s
``venv/bin/python -m helab "$@"``, and ``exec`` keeps the process LaunchServices started, so the
python process (HeLab's GUI) is the bundle's: ``lsappinfo``, ``osascript`` and ``app_*`` find it by
``au.edu.anu.he-bec-lab.dev``, never the release's ``au.edu.anu.he-bec-lab``.

    python dev/dev_app.py [--env-file .ai/local/floor-env.sh] [--tag NAME] [--out PATH]
    open ".ai/local/HeLab-dev.app" [--args --geometry 1600x928+0+39]
    lsappinfo info -app au.edu.anu.he-bec-lab.dev

- Standard library only, no helab import; writes only the stub (default
  ``.ai/local/HeLab-dev.app``, gitignored) and registers it with LaunchServices.
- ``open`` starts the app with launchd's environment, not the shell's: ``--env-file`` names a file
  the stub sources first (a floor's ``.ai/local/floor-env.sh``, so it never uses Tony's settings and
  cache), or pass ``open --env NAME=VALUE``.
- Arguments after ``open --args`` reach HeLab. While the app runs, ``open`` only brings it forward
  (its arguments are dropped); ``open -n`` starts another instance.
- Each stub names its checkout (Get Info, ``HeLabCheckout`` in Info.plist). Two checkouts' stubs with
  the default ID share it, so ``open -b`` and ``lsappinfo -app`` pick one: give the second a
  ``--tag`` (ID ``au.edu.anu.he-bec-lab.dev.<tag>``, name and file ``HeLab-dev-<tag>``).
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
RELEASE_ID = "au.edu.anu.he-bec-lab"
DEV_ID = RELEASE_ID + ".dev"
# The name LaunchServices shows (``lsappinfo``, window owners) is the bundle's file name, so the stub is
# written as ``<NAME>.app`` and Info.plist says the same.
NAME = "HeLab-dev"
EXECUTABLE = "HeLab-dev"
ICON = ROOT / "helab" / "resources" / "ai-icon.icns"
MARKER = "HeLabCheckout"  # Info.plist key: the checkout the stub runs (and what marks a stub of ours).
LSREGISTER = ("/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/"
              "Support/lsregister")

# The executable. ``-psn_…`` (a process serial number some launchers still pass) is dropped: HeLab
# would take it for its own argument. ``HELAB_DEV_APP_NO_ALERT`` set: no alert without a venv (tests).
LAUNCHER = """#!/bin/sh
# {name}: runs HeLab from the checkout {checkout} (made by dev/dev_app.py).
CHECKOUT={checkout_q}
PYTHON="$CHECKOUT/venv/bin/python"
{env_line}
if [ ! -x "$PYTHON" ]; then
    echo "{name}: $PYTHON not found: set up that checkout's venv (README)" >&2
    [ -n "$HELAB_DEV_APP_NO_ALERT" ] || /usr/bin/osascript -e "display alert \\"{name}\\" message \\"$PYTHON not found: set up that checkout's venv (README).\\"" >/dev/null 2>&1
    exit 1
fi
for arg do
    shift
    case $arg in
        -psn_*) ;;
        *) set -- "$@" "$arg" ;;
    esac
done
cd "$CHECKOUT" || exit 1
exec "$PYTHON" -m helab "$@"
"""


def version(checkout: Path) -> str:
    """The checkout's version (``helab/_version.py``), read as text; "0" if it can't be read."""
    try:
        text = (checkout / "helab" / "_version.py").read_text(encoding="utf-8")
    except OSError:
        return "0"
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    return match.group(1) if match else "0"


def identity(tag: str) -> tuple[str, str]:
    """The bundle ID and name for ``tag`` ("": the default ones)."""
    if not tag:
        return DEV_ID, NAME
    if not re.fullmatch(r"[A-Za-z0-9-]+", tag):
        raise ValueError(f"--tag {tag!r}: letters, digits and '-' only (it goes into the bundle ID)")
    return f"{DEV_ID}.{tag}", f"{NAME}-{tag}"


def info_plist(checkout: Path, bundle_id: str, name: str, env_file: str) -> dict[str, object]:
    if bundle_id == RELEASE_ID:
        raise ValueError(f"{RELEASE_ID} is the release's bundle ID")
    found = version(checkout)
    return {
        "CFBundleIdentifier": bundle_id,
        "CFBundleName": name,
        "CFBundleDisplayName": name,
        "CFBundleExecutable": EXECUTABLE,
        "CFBundlePackageType": "APPL",
        "CFBundleIconFile": ICON.name,
        "CFBundleShortVersionString": found,
        "CFBundleVersion": found,
        "CFBundleGetInfoString": f"{name}: runs {checkout}",
        "NSHighResolutionCapable": True,
        MARKER: str(checkout),
        "HeLabEnvFile": env_file,
    }


def launcher(checkout: Path, name: str, env_file: str) -> str:
    env_line = (f"set -a; . {shlex.quote(env_file)} || exit 1; set +a" if env_file
                else "# (No --env-file: HeLab's own settings, cache and app folders.)")
    return LAUNCHER.format(name=name, checkout=checkout, checkout_q=shlex.quote(str(checkout)), env_line=env_line)


def is_stub(app: Path) -> bool:
    """Whether ``app`` is a stub this tool made (so it may be replaced)."""
    try:
        with open(app / "Contents" / "Info.plist", "rb") as file:
            return MARKER in plistlib.load(file)
    except (OSError, plistlib.InvalidFileException, ValueError):
        return False


def build(out: Path, checkout: Path = ROOT, tag: str = "", env_file: str = "") -> Path:
    """Write the stub at ``out`` (replacing a stub of ours there, nothing else) and return it."""
    bundle_id, name = identity(tag)
    if env_file:
        env_file = str(Path(env_file).expanduser().resolve())
        if not os.path.isfile(env_file):
            raise ValueError(f"--env-file {env_file}: no such file")
    if out.exists() and not is_stub(out):
        raise ValueError(f"{out} exists and isn't a stub made by this tool: not replaced")
    out.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".dev-app-", dir=out.parent))
    try:
        app = staging / out.name
        macos = app / "Contents" / "MacOS"
        resources = app / "Contents" / "Resources"
        macos.mkdir(parents=True)
        resources.mkdir()
        with open(app / "Contents" / "Info.plist", "wb") as file:
            plistlib.dump(info_plist(checkout, bundle_id, name, env_file), file)
        (app / "Contents" / "PkgInfo").write_text("APPL????", encoding="ascii")
        script = macos / EXECUTABLE
        script.write_text(launcher(checkout, name, env_file), encoding="utf-8", newline="\n")
        script.chmod(0o755)
        if ICON.is_file():
            shutil.copyfile(ICON, resources / ICON.name)
        if out.exists():
            shutil.rmtree(out)
        app.rename(out)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return out


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--out", type=Path, help="the folder to write the stub in (default .ai/local)")
    parser.add_argument("--tag", default="", help="a second stub's ID and name: au.edu.anu.he-bec-lab.dev.<tag>")
    parser.add_argument("--env-file", default="", help="a shell file of exports the stub sources before HeLab "
                                                       "starts (e.g. .ai/local/floor-env.sh)")
    args = parser.parse_args(argv)
    if sys.platform != "darwin":
        print("dev_app: macOS only (an .app bundle)", file=sys.stderr)
        return 2
    try:
        app = build((args.out or ROOT / ".ai" / "local").resolve() / f"{identity(args.tag)[1]}.app", ROOT, args.tag,
                    args.env_file)
    except ValueError as exc:
        print(f"dev_app: {exc}", file=sys.stderr)
        return 1
    if os.path.exists(LSREGISTER):  # (So ``open -b`` finds it at once; ``open <path>`` would register it too.)
        subprocess.run([LSREGISTER, "-f", str(app)], check=False)
    bundle_id, _ = identity(args.tag)
    print(f"{app}: {bundle_id}, runs {ROOT}")
    print(f"  open {shlex.quote(str(app))} --args …   |   lsappinfo info -app {bundle_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
