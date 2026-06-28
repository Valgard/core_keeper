---
name: new-ck-mod
description: Use when creating or scaffolding a brand-new Core Keeper mod in this repo — a new mod directory under core_keeper/. Applies whether the mod is a Harmony-patch mod or needs CoreLib.
---

# Creating a new Core Keeper mod

Scaffold a new mod with the deterministic generator `utils/new_mod.py`.
**Never** use the Unity Editor "Create New Mod" wizard (it locks the shared SDK,
needs the Editor open, and emits only a fraction of a buildable mod) and
**never** copy a sibling mod (a duplicated `metadata.guid` causes the loader's
"Data block loader already added" crash). One command produces a buildable +
publishable skeleton:

```bash
utils/new_mod.py <kebab-name> --summary "<one-line mod.io summary>"
```

- **`<kebab-name>`** is the single identity source → `MOD_NAME` (Pascal) and
  `displayName` (Title) are derived. Override with `--name` / `--display-name`
  only for acronyms the casing gets wrong (e.g. `HUD`, `CoreLib`).
- **`--summary` is required** and lands in the mod.io listing. Confirm the real
  one-liner with the user first — do not invent one silently.
- **`--corelib`** adds the CoreLib loader dependency — use for UI mods or
  anything depending on CoreLib. Plain Harmony-patch mods take no flag.
- **`--dry-run`** prints the plan + derived names and writes nothing. Good for a
  pre-flight check.

It writes the full tree (ModBuilderSettings `.asset`, runtime/Editor `.asmdef`s
with live-scanned game DLLs, all `.meta` with fresh GUIDs, `_modio.asset` with
modId 0, the IMod bootstrap, `.envrc`/`.envrc.example`/`.gitignore`/`CHANGELOG`,
a placeholder `logo.png`), then `git init` + `link.sh`. It deliberately omits
the Harmony patch class, `ModConfig.cs`, and `CLAUDE.md` (→ `/init`) — write
those next, during the actual modding.

## Before running
- The Unity **Editor must be closed** — any file write or build collides with
  the Editor's own saves/reserialization.

## After running
```bash
cd <kebab-name> && source .envrc && ../utils/build.sh
```
If the **first** build yields an empty bundle (`ModBuilder.BuildMod` → `files:[]`
despite correct `.meta`s), clear the SDK's `Library/SourceAssetDB` (plus
`Bee`/`ScriptAssemblies`/`ArtifactDB`/`Artifacts`) and rebuild — a known
first-build-of-a-newly-linked-mod quirk. Do not wipe caches preemptively.

Full design + the GUID rules it enforces:
`docs/specs/2026-06-28-new-mod-scaffold-generator-design.md`.
