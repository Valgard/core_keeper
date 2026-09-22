#!/usr/bin/env python3
"""Export the game's assets with AssetRipper, in the shape the Mod SDK imports.

The SDK's "Update Assets" step wants an AssetRipper export, and getting one that
it accepts has two traps that this script exists to close.

**The content moved.** Until 1.2.1.5 everything sat in `resources.assets`, so
exporting that one file was the whole job. Since 1.3 it is largely in
Addressables: `StreamingAssets/aa` holds hundreds of megabytes across hundreds of
bundles. Export without it and you get roughly an eighth of the assets -- correct
directory layout, correct file types, no error, no warning. A grep for a 1.3
prefab then comes back empty and reads exactly like "does not exist".

**Scope has to be narrowed by hand.** Loading a single `.assets` file gives
"Unknown scripting backend" and no field names; loading the installation pulls in
everything, including ~70 MB of Windows patcher binaries under StreamingAssets.
So this builds a throwaway `CoreKeeper_Data/` out of *symlinks* -- the content
layers and nothing else -- and hands AssetRipper that. It recognises the `*_Data`
structure and loads the assemblies through the Mono backend, which is what
resolves MonoBehaviour fields to real names.

What this does NOT do: import anything into the SDK. That is a button in the Mod
SDK window, and it is on you to press it. This only produces the folder it asks
for, and checks that the folder is actually usable -- because the importer
skips a missing source folder silently and reports success either way.

Note the result is a *full* export. The stripped data dump used for grepping the
game is a different artifact from the same tool: it deletes `Plugins/` and
`StreamingAssets/`, which are precisely what the SDK importer needs.

Usage:
    uv run utils/export_game_assets.py <target-dir>
    uv run utils/export_game_assets.py <target-dir> --force      # overwrite
    uv run utils/export_game_assets.py <target-dir> --keep-scope # keep the symlink tree

Environment:
    CK_BOTTLE_PATH   CrossOver bottle holding the game (repo-wide convention)
    CK_GAME_DIR      the game directory itself; overrides the path built from the bottle
    ASSETRIPPER_DIR  directory holding the AssetRipper.GUI.Free binary
"""

import argparse
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_BOTTLE = (
    Path.home() / "Library/Application Support/CrossOver/Bottles/Core Keeper"
)
GAME_SUBPATH = "drive_c/Program Files (x86)/Steam/steamapps/common/Core Keeper"
DEFAULT_ASSETRIPPER = Path.home() / "Projects/checkouts/_tools/AssetRipper"

# The content layers, relative to <game>/CoreKeeper_Data. Everything else is left
# out on purpose: StreamingAssets as a whole would drag in the Windows patcher.
SCOPE = [
    "resources.assets",
    "resources.assets.resS",
    "globalgamemanagers",
    "globalgamemanagers.assets",
    "globalgamemanagers.assets.resS",
    "Managed",
    "StreamingAssets/aa",
]

# What the SDK importer reads, relative to <export>/ExportedProject/Assets.
# Sources it cannot find are skipped without a word, so the export is checked
# against this list rather than trusted.
SDK_EXPECTS = [
    "Data",
    "Art",
    "Sprite",
    "Texture2D",
    "GameObject",
    "Shader",
    "Material",
    "AnimationClip",
    "AnimatorController",
    "MonoBehaviour",
    "Plugins",
]
SDK_REQUIRES_FILE = "Resources/I2Languages.asset"  # missing -> importer throws


def game_dir() -> Path:
    if env := os.environ.get("CK_GAME_DIR"):
        return Path(env)
    bottle = Path(os.environ.get("CK_BOTTLE_PATH", DEFAULT_BOTTLE))
    return bottle / GAME_SUBPATH


def assetripper_binary() -> Path:
    root = Path(os.environ.get("ASSETRIPPER_DIR", DEFAULT_ASSETRIPPER))
    return root / "AssetRipper.GUI.Free"


def build_scope(data_dir: Path, scope_root: Path) -> list[str]:
    """Symlink the content layers into a throwaway CoreKeeper_Data. Returns what is missing."""
    target = scope_root / "CoreKeeper_Data"
    target.mkdir(parents=True)
    missing = []
    for rel in SCOPE:
        src = data_dir / rel
        if not src.exists():
            missing.append(rel)
            continue
        dst = target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.symlink_to(src)
    return missing


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def post(port: int, endpoint: str, **fields) -> None:
    """POST form fields. The endpoint is positional so a field may be named `path`."""
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{endpoint}", data=data, method="POST"
    )
    with urllib.request.urlopen(req, timeout=900):
        pass


def wait_for_api(port: int, proc: subprocess.Popen, seconds: int = 60) -> None:
    for _ in range(seconds):
        if proc.poll() is not None:
            raise RuntimeError(f"AssetRipper exited early (code {proc.returncode})")
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/openapi.json", timeout=2
            ):
                return
        except (urllib.error.URLError, OSError, TimeoutError):
            time.sleep(1)
    raise RuntimeError(f"AssetRipper did not answer on port {port} within {seconds}s")


def verify_export(export_dir: Path) -> tuple[list[str], list[str]]:
    """-> (blocking problems, warnings). The importer's own preconditions."""
    blocking, warnings = [], []
    assets = export_dir / "ExportedProject" / "Assets"
    if not assets.is_dir():
        blocking.append(f"{assets} fehlt — der SDK-Dialog lehnt den Ordner ab")
        return blocking, warnings
    if (
        not (assets / SDK_REQUIRES_FILE).exists()
        or not (assets / (SDK_REQUIRES_FILE + ".meta")).exists()
    ):
        blocking.append(
            f"{SDK_REQUIRES_FILE} (+ .meta) fehlt — der Import bricht mit FileNotFoundException ab"
        )
    for folder in SDK_EXPECTS:
        if not (assets / folder).is_dir():
            warnings.append(
                f"{folder}/ fehlt — der Importer überspringt es KOMMENTARLOS"
            )
    return blocking, warnings


def report_counts(export_dir: Path) -> None:
    """Print how many files landed in the largest folders.

    No threshold is applied, deliberately: the right number changes with every
    game version, so a hard-coded one would age into a false alarm. The figure
    that matters is the comparison against the previous export -- an order of
    magnitude down means the Addressables layer did not come along, which is the
    failure this script exists to prevent and which nothing else reports.
    """
    assets = export_dir / "ExportedProject" / "Assets"
    print("\nUmfang (zum Vergleich mit dem vorigen Export):")
    for folder in ("Sprite", "Texture2D", "GameObject", "Data", "Material"):
        d = assets / folder
        n = sum(1 for _ in d.rglob("*") if _.is_file()) if d.is_dir() else 0
        print(f"  {folder:<14} {n:>7}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("target", type=Path, help="directory to export into")
    ap.add_argument("--force", action="store_true", help="overwrite a non-empty target")
    ap.add_argument(
        "--keep-scope", action="store_true", help="keep the symlink tree for inspection"
    )
    ap.add_argument(
        "--port", type=int, help="port for AssetRipper (default: a free one)"
    )
    args = ap.parse_args()

    data_dir = game_dir() / "CoreKeeper_Data"
    if not data_dir.is_dir():
        print(f"Spieldaten nicht gefunden: {data_dir}", file=sys.stderr)
        print("Setze CK_GAME_DIR oder CK_BOTTLE_PATH.", file=sys.stderr)
        return 2
    binary = assetripper_binary()
    if not binary.is_file():
        print(f"AssetRipper nicht gefunden: {binary}", file=sys.stderr)
        print("Setze ASSETRIPPER_DIR.", file=sys.stderr)
        return 2

    target = args.target.expanduser().resolve()
    if target.exists() and any(target.iterdir()):
        if not args.force:
            print(
                f"Ziel ist nicht leer: {target}   (--force zum Überschreiben)",
                file=sys.stderr,
            )
            return 2
        # Only ever remove a directory the caller named as the target.
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)

    scope_root = Path(tempfile.mkdtemp(prefix="ck-scope-"))
    port = args.port or free_port()
    proc = None
    try:
        missing = build_scope(data_dir, scope_root)
        if missing:
            print(
                f"⚠ nicht im Spielverzeichnis gefunden: {', '.join(missing)}",
                file=sys.stderr,
            )
            if "StreamingAssets/aa" in missing:
                print(
                    "  Ohne StreamingAssets/aa liefert der Export seit 1.3 nur einen Bruchteil.",
                    file=sys.stderr,
                )
        print(
            f"Scope:  {scope_root / 'CoreKeeper_Data'}  ({len(SCOPE) - len(missing)}/{len(SCOPE)} Schichten)"
        )

        print(f"Start:  {binary.name} headless auf Port {port}")
        proc = subprocess.Popen(
            [str(binary), "--headless", "--port", str(port)],
            cwd=binary.parent,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        wait_for_api(port, proc)

        t0 = time.time()
        print("Laden:  POST /LoadFolder …")
        post(port, "/LoadFolder", path=str(scope_root / "CoreKeeper_Data"))
        print(f"        geladen ({time.time() - t0:.0f}s)")

        t1 = time.time()
        print(f"Export: POST /Export/UnityProject -> {target}")
        post(port, "/Export/UnityProject", path=str(target))
        print(f"        fertig ({time.time() - t1:.0f}s)")
    finally:
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
        if args.keep_scope:
            print(f"Scope behalten: {scope_root}")
        else:
            shutil.rmtree(scope_root, ignore_errors=True)

    blocking, warnings = verify_export(target)
    print()
    for w in warnings:
        print(f"⚠ {w}")
    for b in blocking:
        print(f"✗ {b}")
    if blocking:
        print("\nDer Export ist so NICHT im SDK importierbar.")
        return 1
    print("✓ Export entspricht dem, was der SDK-Import liest.")
    report_counts(target)
    print(f"\nIm Mod-SDK-Fenster diesen Ordner wählen:\n  {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
