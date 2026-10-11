# Scaffold a new mod by constructing its files, not by driving the wizard or copying a sibling

## Context and Problem Statement

A new mod in this workspace is created by the SDK's "Create New Mod" wizard
inside the Unity Editor. That path is slow, needs the Editor open, takes the
shared SDK project's lock — and produces a fraction of what a usable mod here
needs. The wizard emits four things: the ModBuilderSettings `.asset`, the
runtime `.asmdef`, the folder, and the `.meta` GUIDs. Everything
`utils/build.sh` and `utils/upload.sh` depend on — the `Editor/` folder, the
mod.io identity asset, the `IMod` bootstrap, `.envrc`, `CHANGELOG.md` — was
hand-grown beside it.

So a new mod was a checklist, and a checklist that long is a checklist with
silent gaps: a wrong GUID does not fail the build, it crashes the loader at
run time with "Data block loader already added".

## Decision Drivers

- A new mod must be buildable and publishable with no Editor step at all,
  because the Editor is the slowest and most contended resource here.
- Whatever creates the scaffold must stay in step with the conventions every
  existing mod already carries, or it produces a repo that looks finished and
  fails later.
- The GUID rules are the correctness core, not a detail: the failures they
  prevent are silent at build time.

## Considered Options

1. Drive the Editor wizard, headless, and fill the gaps afterwards
2. Copy an existing sibling mod and find-replace its name
3. Construct every artifact from data in a standalone Python script

## Decision Outcome

**Option 3.** `utils/new_mod.py <kebab-name>` is the only path to a new mod
repo. The kebab name is the single source of identity, from which the Pascal
`MOD_NAME` and the Title `displayName` are derived, so the three-level naming
convention cannot drift unless an override is used deliberately. Standard
library only, matching the shell-first tooling beside it.

Two things it computes rather than templates, because a frozen copy would go
stale in silence: the runtime `.asmdef`'s precompiled references come from a
live scan of the SDK's plugin directories, exactly as the wizard scans them, so
a game update's new DLLs are picked up; and every `.meta` GUID is freshly
generated, except the two verbatim SDK MonoScript GUIDs that bind a generated
ScriptableObject to its SDK class and the one internal cross-reference from the
mod.io asset to the settings asset.

### Consequences

- Good: a new mod is one command, and it builds and publishes without the
  Editor being open or the SDK project being locked.
- Good: the identity rules are enforced by construction rather than by review.
- Bad: the generator is now a standing liability — when a convention lands in
  every mod repo it has to land here in the same change, or the next scaffold
  produces a repo that fails later. Three such drifts were found in one day,
  and the generator's own unit suite was green throughout, because it can only
  check the generator against itself. The guard that followed is
  `utils/tests/test_new_mod_parity.py`, which compares the generated tree
  against what every mod repo actually has.
- Bad: content mods are out of scope. The one wizard step with no pure-Python
  equivalent is the compiled-DLL call that registers a `Data/` folder context,
  so a mod needing one still starts in the Editor. Script mods — Harmony
  patches — need no `Data/` folder.
- Neutral: the CLI grew stricter than designed. `--summary` was the only
  required argument; `--required-on` and `--modio-type` became required too,
  with no default, after a scaffold that defaulted `requiredOn` to "client and
  server" produced mods that needlessly blocked players from joining unmodded
  servers. A value this consequential is asked for, not guessed.

## Pros and Cons of the Options

### Drive the Editor wizard headless

- Good: the GUID and asmdef logic is the SDK's own, so it cannot diverge.
- Bad: keeps every property that made the wizard the problem — the Editor
  dependency, the project lock, the minutes per run.
- Bad: still leaves the whole convention layer to be filled in afterwards, so
  the checklist survives and only its first four lines are automated.

### Copy a sibling and find-replace

- Good: trivially produces something that builds, because the sibling does.
- Bad: a copy carries whatever the sibling happened to have, including its
  GUIDs — and a duplicated `metadata.guid` is the loader crash above.
- Bad: it makes every new mod a snapshot of one arbitrary older mod, so
  conventions spread by accident instead of by rule. The same reasoning kept
  the Workshop identity asset's shape in the publish code that reads it rather
  than in a second copy here: two copies of one shape drift, and that drift is
  silent.

### Construct from data

- Good: deterministic, reviewable, and the identity rules are code.
- Bad: it re-implements wizard logic, which is only correct as long as somebody
  keeps it in step — see the parity guard above.

## More Information

The raw design spec this distils is in the commit that deleted it:

~~~
git show "$(git rev-list -1 HEAD -- docs/specs/2026-06-28-new-mod-scaffold-generator-design.md)^:docs/specs/2026-06-28-new-mod-scaffold-generator-design.md"
~~~

It lists the generated file manifest and the GUID table in full, and predates
both the parity guard and the two further required arguments.

What the generator must keep in step, and what is deliberately left out of a
scaffold, is [`CLAUDE.md`](../../CLAUDE.md), section "New mods — keep `utils/new_mod.py` in step";
the invocation is in [`README.md`](../../README.md) and in the `new-ck-mod` skill.
