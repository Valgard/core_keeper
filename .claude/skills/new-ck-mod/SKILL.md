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
utils/new_mod.py <kebab-name> \
  --summary "<one-line mod.io summary>" \
  --required-on {1|2|3} \
  --modio-type "<Type|Type>"
```

- **`<kebab-name>`** is the single identity source → `MOD_NAME` (Pascal) and
  `displayName` (Title) are derived. Override with `--name` / `--display-name`
  only for acronyms the casing gets wrong (e.g. `HUD`, `CoreLib`).
- **`--summary` is required** and lands in the mod.io listing. Confirm the real
  one-liner with the user first — do not invent one silently.
- **`--required-on` is required**, with no default on purpose: `1` = Client,
  `2` = Server, `3` = both. Ask **does the SERVER need this mod for the feature
  to work?** — `1` for a read-only HUD/UI mod (a blanket `3` hard-blocks joining
  unmodded servers), `3` for new items, recipe/database changes or
  server-authoritative logic. Full semantics in the parent `CLAUDE.md`.
- **`--modio-type` is required**: pipe-separated mod.io "Type" tags, e.g.
  `"Visual|Quality of Life"` (pipes because the values contain spaces). Known
  values: Visual, Audio, Item, NPC, Quality of Life, Overhaul, Language, World,
  Library, Other. Without it the *publish* aborts, not the build — pick the tags
  with the user, since they drive discoverability.
- **`--corelib`** wires CoreLib both ways — the loader dependency in the `.asset`
  and the assembly reference in the runtime `.asmdef` (a mod needs both: the
  first to have CoreLib loaded, the second to compile against it). Use for UI
  mods or anything depending on CoreLib; plain Harmony-patch mods take no flag.
- **`--dry-run`** prints the plan + derived names and writes nothing. Good for a
  pre-flight check.

It writes the full tree (ModBuilderSettings `.asset`, runtime/Editor `.asmdef`s
with live-scanned game DLLs, all `.meta` with fresh GUIDs, `_modio.asset` with
modId 0, the IMod bootstrap, `.envrc`/`.envrc.example`/`.gitignore`/`CHANGELOG`,
the CSharpier gate, a commented-out `localization/localization.yaml`, a
placeholder `logo.png`), then `git init` + `link.sh`. It deliberately omits
the Harmony patch class, `ModConfig.cs`, `CLAUDE.md` (→ `/init`), and the prose
docs `README.md` / `modio-description.md` — you author the docs next (see
below), and write the patch + config during the actual modding.

`utils/tests/test_new_mod_parity.py` holds the generator to whatever *every* mod
repo has. If it is red, fix `new_mod.py` before scaffolding — the red is telling
you the scaffold is already missing something the family requires.

## Before running
- The Unity **Editor must be closed** — any file write or build collides with
  the Editor's own saves/reserialization.

## After running

**1. Author the two prose docs.** The generator omits these on purpose — a
static template would be dead prose, but you (the LLM) write them well from the
mod's actual purpose. Create both in the mod root, in English, matching a
sibling's style (e.g. `../faster-pet-talents/README.md` and
`../faster-pet-talents/modio-description.md`):

- **`README.md`** — developer-facing. `# <displayName>` title, one bold
  one-liner, then a short what-and-how paragraph (name the patch target /
  `ModConfig.cs` knob where relevant), a `## Compatibility` section (EULA +
  client/server + dependencies), and a `## Build & install` section pointing at
  the shared `../utils/build.sh` / `../utils/upload.sh`.
- **`modio-description.md`** — player-facing mod.io listing, in the unified
  house format: a `# <displayName>` H1, a bold one-line tagline, a short intro
  paragraph, then either `## What it does` / `## Good to know` / `##
  Requirements` sections (feature-rich mod) or a few prose paragraphs (a simple
  mod may skip the sections), a `---` rule, and the shared italic footer
  **verbatim**: `*Built with the official Pugstorm Core Keeper Mod SDK.
  Personal-use, non-commercial (Core Keeper EULA). Not affiliated with or
  endorsed by Pugstorm.*` Requirements always note "install on both client and
  server" for a multiplayer-required mod. (The headings/rules match the Markdown
  subset `CLIPublishHelper` converts to HTML for the mod.io profile.)

Draft from what the user told you the mod does; confirm specifics you're unsure
of rather than inventing mechanics.

**2. Only for a mod with in-game text — write the terms.** Nothing to wire: the
scaffold ships `LOC_YAML`/`LOC_OUT` in the `.envrc`, an all-comment
`localization/localization.yaml`, and the `.gitignore` entries for the generated
output. A table with no terms is skipped, so uncomment the example and edit it:

```yaml
<ModName>-Config:
  enabled:
    hint: "Master on/off toggle label."
    en: "Enabled"
    de: "Aktiviert"
```

`Namespace:` at indent 0 → term at indent 2 → `hint`/`en`/`de` at indent 4, leaf
keys unquoted. Two ways to break it: a namespace header with **no** term under it
fails the build (content that yields nothing — either a complete term or all
comments), and U+2026 (`…`) / U+2014 (`—`) in values are rejected, because the
game's thin font crashes on the first and misrenders the second. The
`Localization.meta` folder carrier Unity writes on the next import *is* tracked —
commit it.

**3. Build:**
```bash
cd <kebab-name> && source .envrc && ../utils/build.sh
```
If the **first** build yields an empty bundle (`ModBuilder.BuildMod` → `files:[]`
despite correct `.meta`s), clear the SDK's `Library/SourceAssetDB` (plus
`Bee`/`ScriptAssemblies`/`ArtifactDB`/`Artifacts`) and rebuild — a known
first-build-of-a-newly-linked-mod quirk. Do not wipe caches preemptively.

Full design + the GUID rules it enforces:
`docs/specs/2026-06-28-new-mod-scaffold-generator-design.md`.
