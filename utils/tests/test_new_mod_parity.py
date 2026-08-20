"""Ties new_mod.py to the mod repos it is supposed to produce.

The generator has a thorough unit suite, and that suite structurally cannot see
the failure that actually happened: the generator agreeing with itself while the
family of mod repos moved on. Three conventions had landed in every repo without
it following -- `CK_MODIO_TYPE` (whose absence aborts the publish outright), the
per-mod `requiredOn` choice, and CoreLib's assembly reference -- so a freshly
scaffolded mod built fine and could not ship.

The rule these tests encode: **whatever every mod repo has, the generator must
produce.** Universality is the test's own source of truth, which makes it
self-maintaining in both directions. A convention only some mods adopt (their own
localisation table, an extra pre-commit hook) is that mod's business and stays
invisible here; the moment one lands in all of them, this file goes red until
new_mod.py catches up. So it needs no checklist of conventions -- such a list
would go stale exactly like the ones it exists to replace.

Each test compares at the level on which the repos actually agree, which is not
always byte-identity: `.csharpierrc` is verbatim-identical across the family,
`.pre-commit-config.yaml` is a shared block one mod appends to, the CSharpier pin
is a JSON value inside files that differ in trailing newline, and one asmdef
carries a UTF-8 BOM. Comparing everything byte-for-byte would produce three
false alarms and teach the next reader to distrust this file.

They live in the parent repo because that is where the generator lives, and they
read the sibling mod repos; a checkout without them skips loudly rather than
passing vacuously.
"""

import json
import re

import new_mod as nm
import pytest

# The placeholder every mod's PascalCase name is normalised to, so paths from
# different repos become comparable.
MOD = "<MOD>"

PROBE_KEBAB = "probe-mod"
PROBE_PASCAL = "ProbeMod"

# Prose the generator refuses to template. A static README, listing text or
# forum post would be dead prose in every new mod; all three are written
# from the mod's actual purpose straight after scaffolding, and CLAUDE.md
# comes from `/init` (see the new-ck-mod skill). This is the one hand-kept
# list here, and it is short on purpose -- anything else universal is the
# generator's job.
DELIBERATELY_OMITTED = {
    "README.md",
    "modio-description.md",
    "discord-post.md",
    "CLAUDE.md",
}


def _mod_repos():
    """Every sibling mod repo as an (path, PascalCase MOD_NAME) pair.

    Enumerated live rather than listed: a hardcoded roster of mods is the thing
    this repo has repeatedly found stale. `resolve_mods_dir()` is shared with the
    generator, so this suite finds the family from a worktree too. MOD_NAME is
    read from `.envrc.example` instead of derived from the directory name,
    because `--name` overrides exist (acronym casing) and the derivation would
    then normalise the wrong string.
    """
    mods = []
    for git_entry in sorted(nm.resolve_mods_dir().glob("*/.git")):
        repo = git_entry.parent
        if repo.name == "CoreKeeperModSDK":
            continue
        envrc = repo / ".envrc.example"
        if not envrc.is_file():
            continue
        match = re.search(r'MOD_NAME="([^"]+)"', envrc.read_text())
        if match:
            mods.append((repo, match.group(1)))
    return mods


MODS = _mod_repos()

pytestmark = pytest.mark.skipif(
    len(MODS) < 2,
    reason=(
        f"found {len(MODS)} mod repo(s) beside {nm.resolve_mods_dir()} -- with fewer "
        "than two there is no 'what every mod has' to hold the generator to, so "
        "these parity guards did NOT run"
    ),
)


def _plan(**kw):
    """The generated scaffold as a {relpath: content} dict."""
    kw.setdefault("summary", "x")
    kw.setdefault("dll_names", ["0Harmony.dll"])
    kw.setdefault("fake_mod_id", 1)
    kw.setdefault("required_on", 1)
    kw.setdefault("modio_type", "Other")
    return dict(nm.build_plan(PROBE_KEBAB, **kw))


def _normalise(path, pascal):
    return path.replace(pascal, MOD)


def _read(repo, relpath):
    """A repo file's text, or None. utf-8-sig because one asmdef carries a BOM."""
    target = repo / relpath
    return target.read_text(encoding="utf-8-sig") if target.is_file() else None


def _tracked(repo, pascal):
    """The repo's tracked paths, mod name normalised.

    Through `run_git`, because this suite also runs inside the pre-commit hook,
    where an exported GIT_DIR would make `ls-files` report the committing repo
    instead of *repo*. splitlines(), not split(): candidate logo filenames
    contain spaces.
    """
    proc = nm.run_git(["git", "ls-files"], repo)
    assert proc.returncode == 0, f"git ls-files failed in {repo}: {proc.stderr}"
    return {_normalise(p, pascal) for p in proc.stdout.splitlines()}


def _universal(per_mod):
    """What every mod has — the intersection, and this suite's whole premise."""
    return set.intersection(*per_mod)


def _exports(text):
    return set(re.findall(r"^export ([A-Z_]+)=", text, re.MULTILINE))


def _asset(repo, pascal):
    return _read(repo, f"unity/{pascal}.asset")


def _metadata_keys(text):
    """The keys inside the `metadata:` block (the built ModManifest's fields)."""
    block = re.search(r"\n  metadata:\n((?:    \S.*\n|      .*\n)+)", text)
    assert block, "no metadata: block — the .asset layout changed"
    return set(re.findall(r"^    ([A-Za-z]+):", block.group(1), re.MULTILINE))


def _settings_keys(text):
    """The ModBuilderSettings keys outside `metadata:` (build switches)."""
    return set(re.findall(r"^  ([A-Za-z_]+):", text, re.MULTILINE))


def _runtime_refs(repo, pascal):
    text = _read(repo, f"unity/{pascal}/{pascal}.asmdef")
    return set(json.loads(text)["references"]) if text else None


# --- the suite's own footing ------------------------------------------------


def test_reads_each_repo_not_the_ambient_git_environment(monkeypatch):
    """The pre-commit hook exports GIT_DIR — and git prefers it over cwd.

    Without scrubbing, every `_tracked()` call returned the *committing* repo's
    index, so the universal set became core_keeper's own file list and this suite
    blocked every parent-repo commit with a nonsense message. It did exactly that
    once; this is that failure, pinned.
    """
    repo, pascal = MODS[0]
    baseline = _tracked(repo, pascal)
    git_dir = nm.resolve_mods_dir() / ".git"
    monkeypatch.setenv("GIT_DIR", str(git_dir))
    monkeypatch.setenv("GIT_INDEX_FILE", str(git_dir / "index"))
    assert _tracked(repo, pascal) == baseline


# --- the file set -----------------------------------------------------------


def test_generator_writes_every_file_all_mods_track():
    universal = _universal([_tracked(repo, pascal) for repo, pascal in MODS])
    generated = {_normalise(p, PROBE_PASCAL) for p in _plan()}
    missing = universal - generated - DELIBERATELY_OMITTED
    assert not missing, (
        f"every mod repo tracks {sorted(missing)}, the scaffold does not write "
        "it -- new_mod.py is behind the convention (or the file belongs in "
        "DELIBERATELY_OMITTED, with the reason why)"
    )


# --- the .envrc publish contract --------------------------------------------


def test_generated_envrc_exports_every_universal_variable():
    universal = _universal(
        [_exports(_read(repo, ".envrc.example")) for repo, _ in MODS]
    )
    generated = _exports(_plan()[".envrc.example"])
    missing = universal - generated
    assert not missing, (
        f"every mod repo exports {sorted(missing)}, the generated .envrc does "
        "not -- new_mod.py is behind the convention. CLIPublishHelper reads this "
        "file, so a missing variable can abort the publish rather than the build"
    )


# --- the ModBuilderSettings .asset ------------------------------------------


def test_asset_metadata_keys_match_the_repos():
    universal = _universal([_metadata_keys(_asset(*mod)) for mod in MODS])
    generated = _metadata_keys(_plan()[f"unity/{PROBE_PASCAL}.asset"])
    assert generated == universal, (
        "the generated .asset metadata block no longer matches what every mod "
        f"has: missing {sorted(universal - generated)}, surplus "
        f"{sorted(generated - universal)} — an SDK field was added or removed"
    )


def test_asset_settings_keys_match_the_repos():
    universal = _universal([_settings_keys(_asset(*mod)) for mod in MODS])
    generated = _settings_keys(_plan()[f"unity/{PROBE_PASCAL}.asset"])
    assert generated == universal, (
        "the generated .asset build switches no longer match what every mod "
        f"has: missing {sorted(universal - generated)}, surplus "
        f"{sorted(generated - universal)}"
    )


# --- the runtime asmdef -----------------------------------------------------


def test_runtime_asmdef_covers_every_universal_reference():
    per_mod = [refs for refs in (_runtime_refs(*mod) for mod in MODS) if refs]
    universal = _universal(per_mod)
    generated = set(
        json.loads(_plan()[f"unity/{PROBE_PASCAL}/{PROBE_PASCAL}.asmdef"])["references"]
    )
    missing = universal - generated
    assert not missing, (
        f"every mod's runtime asmdef references {sorted(missing)}, the generated "
        "one does not — a new assembly became mandatory"
    )


def test_corelib_flag_wires_both_halves_the_family_wires():
    # Loader dependency (.asset) and compile-time reference (.asmdef) are
    # separate; --corelib used to set only the first, so the mod loaded CoreLib
    # and could not compile against it.
    for repo, pascal in MODS:
        if "modName: CoreLib" not in _asset(repo, pascal):
            continue
        refs = _runtime_refs(repo, pascal)
        assert refs and "CoreLib" in refs, (
            f"{repo.name} declares the CoreLib loader dependency without the "
            "assembly reference. If that is deliberate, pairing the two is no "
            "longer universal and this guard needs rethinking"
        )
    plan = _plan(corelib=True)
    assert "- modName: CoreLib" in plan[f"unity/{PROBE_PASCAL}.asset"], (
        "--corelib no longer writes the CoreLib loader dependency into the .asset"
    )
    asmdef = json.loads(plan[f"unity/{PROBE_PASCAL}/{PROBE_PASCAL}.asmdef"])
    assert "CoreLib" in asmdef["references"], (
        "--corelib writes the loader dependency but not the assembly reference — "
        "the scaffolded mod would fail with CS0246 on its first `using CoreLib;`"
    )


# --- the formatting gate ----------------------------------------------------


def test_csharpierrc_matches_the_repos_verbatim():
    contents = {_read(repo, ".csharpierrc") for repo, _ in MODS}
    if len(contents) != 1:
        pytest.skip(
            "the mod repos' .csharpierrc files differ, so there is no universal "
            "version to hold the generator to"
        )
    assert nm.build_csharpierrc() == contents.pop()


def test_csharpierignore_patterns_match_the_repos():
    def patterns(text):
        return [
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]

    generated = patterns(nm.build_csharpierignore())
    for repo, _ in MODS:
        text = _read(repo, ".csharpierignore")
        assert text is not None, f"{repo.name} has no .csharpierignore"
        assert patterns(text) == generated, (
            f"{repo.name} ignores {patterns(text)}, the generated file ignores "
            f"{generated} — comments may differ, the patterns may not"
        )


def test_precommit_config_contains_the_shared_csharpier_block():
    # A mod may append its own hooks (complete-tiny-font guards its font
    # artifacts), so the shared block has to be contained, not equal.
    generated = nm.build_precommit_config()
    for repo, _ in MODS:
        text = _read(repo, ".pre-commit-config.yaml")
        assert text and generated in text, (
            f"{repo.name}'s .pre-commit-config.yaml no longer contains the block "
            "new_mod.py generates — the gate's shared shape changed"
        )


def test_csharpier_pin_matches_every_repo():
    pins = set()
    for repo, _ in MODS:
        text = _read(repo, ".config/dotnet-tools.json")
        if text:
            pins.add(json.loads(text)["tools"]["csharpier"]["version"])
    if len(pins) != 1:
        pytest.skip(f"the mod repos pin different CSharpier versions: {sorted(pins)}")
    generated = json.loads(nm.build_dotnet_tools_json())["tools"]["csharpier"][
        "version"
    ]
    assert generated == pins.pop(), (
        "every mod repo pins a different CSharpier version than the scaffold "
        "would — a version bump did not reach new_mod.py"
    )
