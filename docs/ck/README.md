# Core Keeper modding handbook

How Core Keeper works from a mod's point of view, and how to hook into it
without falling into the traps that make correct-looking code do nothing.

This is a reference work, not a tutorial. It is distilled from building and
shipping mods against Pugstorm's `CoreKeeperModSDK` — so it is **empirical**:
it records what the game was observed to do and what the decompiled assemblies
show, not what any specification promises. Where something was verified only
for a specific case, the text says so rather than generalising.

Knowledge is against Core Keeper **1.2.1.5** unless a passage names a different
version. Facts read out of a decompile are true for the build they were read
from; game updates can and do invalidate them.

*Looking for a plain list of the chapters instead of a wayfinder?
[index.md](index.md).*

## Start from nothing

If you have not built a Core Keeper mod before, read three chapters in this
order. They are the ones whose absence causes the most wasted time, and together
they cover what every mod does regardless of what it is for.

1. **[Mod anatomy](mod-anatomy.md)** — what a mod consists of, what the loader
   reads, and how it is configured. Without this the rest has no frame.
2. **[Sandbox and configuration](sandbox-and-config.md)** — what your code may
   reference at all. This is the chapter that prevents the classic first
   experience: a mod that builds perfectly and dies at load.
3. **[Harmony and ECS](harmony-and-ecs.md)** — how to hook into the game. Read
   at least the first section; a patch that binds but never fires is the single
   most common early confusion.

Then branch by what you actually want to build:

| Your first mod is… | Read next |
|---|---|
| a tweak to recipes, item stats, drop rates | [Database and baking](database-and-baking.md) |
| a HUD element or a window | [UI framework](ui-framework.md) and [Prefabs and rendering](prefabs-and-rendering.md) |
| a change to placement, tiles, creatures, world rules | [World and mechanics](world-and-mechanics.md) |
| anything others will play together | [Multiplayer and server](multiplayer-and-server.md) — before publishing, not after |

**Setting up the toolchain is a separate matter** and is not covered here: the
SDK, the exact Unity version, building and installing live in
[`../../README.md`](../../README.md). This handbook starts where that leaves
off — you can build and install *something*, and now you need to know how the
game behaves.

One habit worth adopting from the start: when something does not work, come back
to the symptom table below rather than reading a chapter end to end. Nearly
every entry in it exists because it cost somebody hours.

## Start from the symptom

Most visits here begin with something not working. The fastest route is the
symptom, not the topic.

| What you are seeing | Go to |
|---|---|
| Patch loads cleanly, prefix never fires | [Harmony and ECS](harmony-and-ecs.md) — the target is Burst-compiled |
| Works in single-player, does nothing in multiplayer | [Harmony and ECS](harmony-and-ecs.md) — the dedicated-server trap |
| `Undefined target method for patch method …` | [Harmony and ECS](harmony-and-ecs.md) — `in`/`ref` parameter binding |
| Mod fails to compile (`CompileFailed`) | [Sandbox and configuration](sandbox-and-config.md), then [Troubleshooting](troubleshooting.md) |
| Scripts are not compiled at all, and the log says nothing | [Troubleshooting](troubleshooting.md) — the mod.io type tag |
| An unrelated, previously working mod stopped patching | [Troubleshooting](troubleshooting.md) — the CompileFailed cascade |
| Game closes at the loading screen | [Troubleshooting](troubleshooting.md) — Steam Cloud conflict, not your mod |
| You changed a string, the game still shows the old one | [Localisation](localisation.md) — first-write-wins |
| The UI shows a raw term key like `MyMod-General/Label` | [Localisation](localisation.md) |
| `LoadAsset<Sprite>` returns null | [Prefabs and rendering](prefabs-and-rendering.md) — sprite import settings |
| A sprite renders grey or dimmed for no reason | [Prefabs and rendering](prefabs-and-rendering.md) — the uiCamera Z tie |
| Your text element is invisible until the string changes | [Prefabs and rendering](prefabs-and-rendering.md) — PugText self-deactivation |
| Your HUD element exists, is active, and does not show | [Prefabs and rendering](prefabs-and-rendering.md) — wrong layer, wrong Z, or scaled to nothing |
| Players are blocked from joining your server | [Multiplayer and server](multiplayer-and-server.md), [Mod anatomy](mod-anatomy.md) — `requiredOn` |
| "Wrong game version" between client and server | [Multiplayer and server](multiplayer-and-server.md) — it is a mod-set mismatch |
| Dedicated server fails to generate a world | [Multiplayer and server](multiplayer-and-server.md) — the server renders, so `-nographics` breaks it |
| A call works in single-player but not on a server | [Multiplayer and server](multiplayer-and-server.md) — some subsystems are compiled out server-side |

## Start from the task

| What you want to do | Go to |
|---|---|
| Understand what a mod is made of and what the loader reads | [Mod anatomy](mod-anatomy.md) |
| Give your mod a config file | [Sandbox and configuration](sandbox-and-config.md) |
| Know what you may reference at compile time | [Sandbox and configuration](sandbox-and-config.md) |
| Patch a DOTS system, or read the live ECS world | [Harmony and ECS](harmony-and-ecs.md) |
| Change a recipe, an item stat, or any baked object data | [Database and baking](database-and-baking.md) |
| Add an options-menu entry or a rebindable keybind | [UI framework](ui-framework.md) |
| Build a HUD element or a menu window | [UI framework](ui-framework.md), [Prefabs and rendering](prefabs-and-rendering.md) |
| Work with prefabs, sprites or fonts | [Prefabs and rendering](prefabs-and-rendering.md) |
| Place tiles, or understand where things may be built | [World and mechanics](world-and-mechanics.md) |
| Ship a mod that works in multiplayer | [Multiplayer and server](multiplayer-and-server.md) |
| Translate your mod's text | [Localisation](localisation.md) |
| Read data out of a save | [Savegame formats](savegame-formats.md) |
| Answer a question nothing here answers | [Reverse engineering](reverse-engineering.md) |

## The chapters

| Chapter | Covers |
|---|---|
| [Mod anatomy](mod-anatomy.md) | The `IMod` lifecycle, assembly definitions, the ModBuilderSettings `.asset` versus the generated manifest, the two kinds of GUID, dependencies, and `requiredOn` with its crossed checks |
| [Sandbox and configuration](sandbox-and-config.md) | What the load-time verification rejects and what it does not, why an Editor build proves nothing, and the three ways a sandboxed mod stores settings |
| [Harmony and ECS](harmony-and-ecs.md) | Why Burst-compiled systems swallow patches, `BurstDisabler` and its silent failure on dedicated servers, patch binding, instrumenting generated DOTS code, live ECS access |
| [Database and baking](database-and-baking.md) | Editing baked object data through the converter hook, the `(objectID, variation)` key, variations and paint, item level and sell value, script fileIDs |
| [UI framework](ui-framework.md) | Sprite UI instead of uGUI, mounting windows, options-menu entries, rebindable keybinds, the hint bar, scrolling, and disabled-but-visible options |
| [Prefabs and rendering](prefabs-and-rendering.md) | When a prefab may be edited by script, nested prefabs and variants, sprite import, on-grid distortion, Z-sorting, PugText and the font system, HUD versus world space |
| [World and mechanics](world-and-mechanics.md) | The XZ plane, tile layers and the `AddTile` queue, the placement permission model, entity radii, ore boulders, livestock and pets, cooked food |
| [Multiplayer and server](multiplayer-and-server.md) | The NetCode/ghost protocol and what changes its hashes, the mod set as a second compatibility layer, dedicated-server behaviour |
| [Localisation](localisation.md) | The game-wide table, first-write-wins and its consequences, the ways localisation has shipped broken, term-key conventions |
| [Savegame formats](savegame-formats.md) | World, map and character files — what is readable, what is not, and why the map is a fog-of-war snapshot |
| [Troubleshooting](troubleshooting.md) | Symptom-first index for mods that will not load, will not compile, or take something else down with them |
| [Reverse engineering](reverse-engineering.md) | Decompiling the assemblies, unpacking assets, querying prefab YAML, and how much evidence a claim needs |

## What is not here

This handbook covers the game and the SDK. The surrounding workflow lives
elsewhere in this repository:

| Topic | Document |
|---|---|
| Building and installing a mod, the formatting gate | [`../../README.md`](../../README.md) |
| Publishing to mod.io | [`../publishing.md`](../publishing.md) |
| Running a dedicated server locally | [`../dedicated-server.md`](../dedicated-server.md) |
| macOS/CrossOver loader specifics and the game-DLL patches | [`../macos-crossover-loader.md`](../macos-crossover-loader.md) |
| One pixel-art authoring workflow — the one used in this repo, not a requirement | [`../pixaki-format.md`](../pixaki-format.md) |

Individual mods document their own architecture, iteration history and
mod-specific traps in their own repositories. Nothing about a particular mod
belongs here — this handbook only records what holds for the game itself.

## Licence note

Core Keeper modding under Pugstorm's EULA is personal-use and non-commercial.
