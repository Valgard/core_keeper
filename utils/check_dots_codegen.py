"""Fail a build that ships a mod without the DOTS codegen its systems need.

Why this exists: a mod's DOTS system (`SystemAPI`, `Entities.ForEach`, …) is
compiled twice. Unity's source generators write the real method bodies into
`Temp/GeneratedCode/<Mod>/`, and ModBuilder copies that folder into the built
mod as `Scripts/Generated/*.g.cs`; the loader later swaps those bodies in for
the stubs in the mod's own source. But `Temp` starts empty in every batchmode
session, and the generators only run when Unity recompiles the assembly -- which
it does not do when no source changed since the last build. Such a build reports
success and ships the stubs alone, and the game throws "This method should have
been replaced by codegen" the first time the system runs.

The compiled assembly in `Library/ScriptAssemblies/` tells the two cases apart.
It is the output of the *last* compile, so after a build that did not recompile
it still contains the generated code -- marked with `DOTSCompilerGenerated` --
while the built mod has none. That is exactly the failure, detected without
guessing from source text which constructs trigger generation.

Only `*.g.cs` counts as codegen. A mod may keep its own `Generated/` files
(`DevFlags.generated.cs`), which ship beside the codegen and are not it.

A missing assembly does not fail the build: it means the assembly is not named
after MOD_NAME, which is worth a warning and not worth blocking every build of
that mod.

Usage:
    check_dots_codegen.py <compiled-assembly.dll> <built-mod-content-folder>
Exit codes: 0 fine or not applicable, 1 codegen missing, 2 bad usage.
"""

import sys
from pathlib import Path

MARKER = b"DOTSCompilerGenerated"


def generated_files(content_dir: Path) -> list[Path]:
    """The codegen files the built mod ships, `Scripts/Generated/*.g.cs`."""
    return sorted((content_dir / "Scripts" / "Generated").glob("*.g.cs"))


def check(assembly: Path, content_dir: Path) -> tuple[int, str]:
    """Return (exit code, message) for one built mod."""
    try:
        data = assembly.read_bytes()
    except OSError:
        return 0, f"  ! codegen check skipped: compiled assembly not found at {assembly}"

    if MARKER not in data:
        return 0, "  DOTS codegen: none needed"

    files = generated_files(content_dir)
    if files:
        noun = "file" if len(files) == 1 else "files"
        return 0, f"  DOTS codegen: {len(files)} generated {noun} shipped"

    return 1, (
        f"✗ {assembly.name} contains DOTS codegen, but the built mod ships no "
        f"Scripts/Generated/*.g.cs under {content_dir}.\n"
        "  Unity did not recompile the mod this session, so its source generators did "
        "not run and the game would throw 'This method should have been replaced by "
        "codegen'.\n"
        "  Touch one of the mod's .cs files and build again."
    )


def main(argv: list[str]) -> int:
    """CLI entry point; build.sh turns a nonzero return into its own exit code."""
    if len(argv) != 3:
        print(f"usage: {Path(argv[0]).name} <assembly.dll> <content-folder>", file=sys.stderr)
        return 2
    code, message = check(Path(argv[1]), Path(argv[2]))
    print(message, file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
