"""Unit tests for the build guard against a mod shipped without its DOTS codegen.

The failure this guards against is silent at build time: the mod compiles, the
build reports success, and the game throws "This method should have been
replaced by codegen" the first time the system runs. So the case that matters
most is the one where the compiled assembly says codegen exists and the built
mod carries none -- that must fail, and every other case must pass, because a
guard that fails mods without systems would be switched off within a week.

`DevFlags.generated.cs` gets its own test because it is the near miss: a file a
mod keeps in its own `Generated/` folder, shipped beside the codegen, whose name
ends in `.cs` and contains "generated". It is not codegen and must not count as
such, or a mod with dev flags and a dropped `.g.cs` would pass.
"""

import os
import re
from pathlib import Path

import check_dots_codegen as cdc
import pytest

UTILS = Path(__file__).resolve().parent.parent


def _script_assemblies() -> Path | None:
    """The SDK clone's compiled assemblies: $SDK_PATH, else the nearest ancestor's clone.

    Walking up rather than looking beside utils/ keeps this working from a
    worktree under .worktrees/, which has no SDK clone of its own.
    """
    candidates = [Path(os.environ["SDK_PATH"])] if os.environ.get("SDK_PATH") else []
    candidates += [parent / "CoreKeeperModSDK" for parent in UTILS.parents]
    for sdk in candidates:
        if (sdk / "Library" / "ScriptAssemblies").is_dir():
            return sdk / "Library" / "ScriptAssemblies"
    return None


MARKER_DLL = b"MZ\x90\x00...DOTSCompilerGeneratedAttribute\x00Unity.Entities\x00..."
PLAIN_DLL = b"MZ\x90\x00...HarmonyPatch\x00PugMod\x00..."


def write_dll(tmp_path, content):
    """A stand-in for Library/ScriptAssemblies/SomeMod.dll with the given bytes."""
    dll = tmp_path / "Library" / "ScriptAssemblies" / "SomeMod.dll"
    dll.parent.mkdir(parents=True)
    dll.write_bytes(content)
    return dll


def content_dir(tmp_path, *generated):
    """A built mod's content folder, with the named files under Scripts/Generated/."""
    root = tmp_path / "install" / "SomeMod"
    (root / "Scripts").mkdir(parents=True)
    (root / "Scripts" / "SomeSystem.cs").write_text("// mod source\n")
    if generated:
        (root / "Scripts" / "Generated").mkdir()
        for name in generated:
            (root / "Scripts" / "Generated" / name).write_text("// generated\n")
    return root


def test_missing_assembly_warns_and_passes(tmp_path):
    """An assembly not named after MOD_NAME is a reason to look, not to fail a build."""
    code, message = cdc.check(tmp_path / "Nope.dll", content_dir(tmp_path))

    assert code == 0
    assert "not found" in message


def test_assembly_without_codegen_passes(tmp_path):
    """A mod without DOTS systems needs no generated files and must not be failed."""
    code, _ = cdc.check(write_dll(tmp_path, PLAIN_DLL), content_dir(tmp_path))

    assert code == 0


def test_codegen_with_generated_file_passes(tmp_path):
    """Codegen in the assembly and a shipped .g.cs is the healthy case."""
    dll = write_dll(tmp_path, MARKER_DLL)
    code, message = cdc.check(dll, content_dir(tmp_path, "SomeSystem__System_123.g.cs"))

    assert code == 0
    assert "1 generated file" in message


def test_codegen_without_generated_file_fails(tmp_path):
    """The guarded failure: the assembly has codegen, the built mod none."""
    code, message = cdc.check(write_dll(tmp_path, MARKER_DLL), content_dir(tmp_path))

    assert code == 1
    assert "replaced by codegen" in message


def test_devflags_file_is_not_codegen(tmp_path):
    """A mod's own Generated/ file must not stand in for missing codegen."""
    dll = write_dll(tmp_path, MARKER_DLL)
    code, _ = cdc.check(dll, content_dir(tmp_path, "DevFlags.generated.cs"))

    assert code == 1


def test_main_maps_failure_to_nonzero(tmp_path, capsys):
    """The CLI reports the failure on stderr with a nonzero code build.sh can act on."""
    dll = write_dll(tmp_path, MARKER_DLL)

    assert cdc.main(["check_dots_codegen.py", str(dll), str(content_dir(tmp_path))]) == 1
    assert "replaced by codegen" in capsys.readouterr().err


def test_main_rejects_wrong_usage(capsys):
    """Wrong arguments are a usage error, distinct from a failed check."""
    assert cdc.main(["check_dots_codegen.py"]) == 2
    assert "usage" in capsys.readouterr().err


def test_unreadable_assembly_fails(tmp_path):
    """An assembly that exists but cannot be read must not pass as 'not found'."""
    dll = write_dll(tmp_path, MARKER_DLL)
    dll.chmod(0)
    try:
        code, message = cdc.check(dll, content_dir(tmp_path, "SomeSystem__System_123.g.cs"))
    finally:
        dll.chmod(0o600)

    assert code == 1
    assert "cannot read" in message


def test_publish_helper_uses_the_same_rule():
    """The C# copy in CLIPublishHelper.cs must look for the same marker and files.

    The rule exists twice -- build.sh runs this script, a publish runs the C# --
    and each suite would stay green if only one of them changed.
    """
    source = (UTILS / "CLIPublishHelper.cs").read_text()

    marker = re.search(r'MarkerText = "([^"]+)"', source)
    pattern = re.search(r'GeneratedPattern = "([^"]+)"', source)
    assert marker and marker.group(1).encode() == cdc.MARKER
    assert pattern and pattern.group(1) == cdc.GENERATED_PATTERN


@pytest.mark.parametrize(
    ("mod", "has_codegen"), [("MapMarkersEnhanced", True), ("DisableDurability", False)]
)
def test_marker_matches_a_real_unity_assembly(mod, has_codegen):
    """The marker must still be what Unity's Entities compiler actually emits.

    Every other test feeds made-up bytes, so a renamed attribute in an Entities
    update would leave them green while the guard waved every mod through.
    MapMarkersEnhanced has a DOTS system and DisableDurability none; skipped in a
    checkout without a built SDK clone beside it.
    """
    assemblies = _script_assemblies()
    dll = assemblies / f"{mod}.dll" if assemblies else Path(f"{mod}.dll")
    if not dll.exists():
        pytest.skip(f"no compiled {dll.name} in this checkout")

    assert (cdc.MARKER in dll.read_bytes()) is has_codegen
