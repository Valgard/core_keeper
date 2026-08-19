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

> **→ [index.md](index.md) is where you start reading.** It routes by
> **symptom** ("my patch never fires"), by **task** ("add an options-menu
> entry"), and by **starting from nothing** if you have never built a mod for
> this game. The list below is the shelf; the index is the librarian.

## The chapters

| Chapter | Covers |
|---|---|
| [Toolchain](toolchain.md) | What the SDK requires of any setup — the exact Unity version, the build modules, the one-time wizard steps, the project lock, the macOS meta-file fix — then one worked example of a build arrangement |
| [Mod anatomy](mod-anatomy.md) | The `IMod` lifecycle, assembly definitions, the ModBuilderSettings `.asset` versus the generated manifest, the two kinds of GUID, dependencies, chat commands, and `requiredOn` with its crossed checks |
| [Sandbox and configuration](sandbox-and-config.md) | What the load-time verification rejects and what it does not, why an Editor build proves nothing, and the three ways a sandboxed mod stores settings |
| [Harmony and ECS](harmony-and-ecs.md) | Why Burst-compiled systems swallow patches, `BurstDisabler` and its silent failure on dedicated servers, patch binding, instrumenting generated DOTS code, live ECS access |
| [Database and baking](database-and-baking.md) | Editing baked object data through the converter hook, the `(objectID, variation)` key, variations and paint, item level and sell value, adding a craftable item, fileIDs |
| [UI framework](ui-framework.md) | Sprite UI instead of uGUI, mounting windows, options-menu entries, rebindable keybinds, the hint bar, text input, scrolling, and disabled-but-visible options |
| [Prefabs and rendering](prefabs-and-rendering.md) | When a prefab may be edited by script, nested prefabs and variants, sprite import, masking, Z-sorting, PugText and the font system, HUD versus world space |
| [World and mechanics](world-and-mechanics.md) | World geometry and the origin, tile layers and the `AddTile` queue, the placement permission model, map markers, entity radii, ore boulders, livestock and pets, cooked food |
| [Multiplayer and server](multiplayer-and-server.md) | The NetCode/ghost protocol and what changes its hashes, the mod set as a second compatibility layer, how the dedicated server build differs |
| [Localisation](localisation.md) | The game-wide table, first-write-wins and its consequences, the ways localisation has shipped broken, term-key conventions |
| [Savegame formats](savegame-formats.md) | World, map and character files — what is readable, what is not, and why the map is a fog-of-war snapshot |
| [Troubleshooting](troubleshooting.md) | Symptom-first index for mods that will not load, will not compile, or take something else down with them |
| [Reverse engineering](reverse-engineering.md) | Decompiling the assemblies, unpacking assets, querying prefab YAML, and how much evidence a claim needs |

## What is not here

This handbook covers the game and the SDK. The surrounding workflow lives
elsewhere in this repository:

| Topic | Document |
|---|---|
| This repository's own scripts, variables and commands — the concrete form of [Toolchain](toolchain.md) | [`../../README.md`](../../README.md) |
| Publishing to mod.io | [`../publishing.md`](../publishing.md) |
| Running a dedicated server locally | [`../dedicated-server.md`](../dedicated-server.md) |
| macOS/CrossOver loader specifics and the game-DLL patches | [`../macos-crossover-loader.md`](../macos-crossover-loader.md) |
| One pixel-art authoring workflow — the one used in this repo, not a requirement | [`../pixaki-format.md`](../pixaki-format.md) |

Individual mods document their own architecture, iteration history and
mod-specific traps in their own repositories. Nothing about a particular mod
belongs here — this handbook only records what holds for the game itself.

## Licence note

Core Keeper modding under Pugstorm's EULA is personal-use and non-commercial.
