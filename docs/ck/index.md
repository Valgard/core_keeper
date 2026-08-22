# Core Keeper modding handbook — where to start

## Preamble

**This describes Core Keeper `1.2.1.5`** unless a passage names another version.
Everything here was read off a running game or out of decompiled assemblies
rather than from documentation, so a game update can invalidate any statement in
it without warning, and nothing announces that it has.

It covers the game and the SDK — nothing about any individual mod, and no
script, path or command belonging to a particular workspace. How you build,
publish or run a server is yours to arrange; what the chapters describe is the
machinery those arrangements sit on.

## The chapters

| Chapter | Covers |
|---|---|
| [Toolchain requirements](toolchain.md) | What the SDK demands of any setup — the exact Unity version, the build modules, the one-time wizard steps, the project lock, and where the macOS meta-file fix is written up |
| [Organising a mod project](organising-a-mod-project.md) | Why the Editor writes outside your repository and what closes that gap, separating machine paths from mod identity, a formatting gate that cannot silently pass, pinning what produces shipped bytes |
| [Platforms and hosts](platforms.md) | Where the game runs and keeps its files, what a Wine-based host breaks and how those failures look, reading logs on a translated host |
| [Mod anatomy](mod-anatomy.md) | The `IMod` lifecycle, assembly definitions, the ModBuilderSettings `.asset` versus the generated manifest, the two kinds of GUID, dependencies, chat commands, and `requiredOn` with its crossed checks |
| [The load-time sandbox](sandbox.md) | What the verification rejects and what it does not, why an Editor build proves nothing, why Harmony attributes are exempt, and how to find the identifier that failed |
| [Storing configuration and state](persistence.md) | The three routes a sandboxed mod has to a file, what the rest of the catalogue actually uses, and writing state in lockstep with the game's own save |
| [Harmony and ECS](harmony-and-ecs.md) | Why Burst-compiled systems swallow patches, `BurstDisabler` and its silent failure on dedicated servers, patch binding, instrumenting generated DOTS code, live ECS access |
| [Database and baking](database-and-baking.md) | Editing baked object data through the converter hook, the `(objectID, variation)` key, variations and paint, item level and sell value, adding a craftable item, fileIDs |
| [UI framework](ui-framework.md) | Sprite UI instead of uGUI, mounting windows, options-menu entries, rebindable keybinds, the hint bar, text input, scrolling, and disabled-but-visible options |
| [Prefabs and rendering](prefabs-and-rendering.md) | When a prefab may be edited by script, nested prefabs and variants, sprite import, masking, Z-sorting, PugText and the font system, HUD versus world space |
| [World and mechanics](world-and-mechanics.md) | World geometry and the origin, tile layers and the `AddTile` queue, the placement permission model, map markers, entity radii, ore boulders, livestock and pets, cooked food |
| [Multiplayer and server](multiplayer-and-server.md) | The NetCode/ghost protocol and what changes its hashes, the mod set as a second compatibility layer, how the dedicated server build differs |
| [Localisation](localisation.md) | The game-wide table, first-write-wins and its consequences, the ways localisation has shipped broken, term-key conventions |
| [Publishing to mod.io](publishing.md) | Profile versus modfile and why a changelog cannot be edited, which manifest field becomes which tag, the silent tag drop, dependencies existing twice |
| [Savegame formats](savegame-formats.md) | World, map and character files — what is readable, what is not, and why the map is a fog-of-war snapshot |
| [Troubleshooting](troubleshooting.md) | Symptom-first index for mods that will not load, will not compile, or take something else down with them — and for the Editor and build failures that have nothing to do with any mod |
| [Reverse engineering](reverse-engineering.md) | Decompiling the assemblies, unpacking assets, querying prefab YAML, and how much evidence a claim needs |

Three ways lead into them, depending on why you are here — from nothing, from a
symptom, or from a task.

## Start from nothing

**If nothing builds yet, start with [toolchain requirements](toolchain.md)** — the exact Unity
version, the build modules, the one-time wizard steps and where the macOS meta-file
fix is written up.

If you have not built a Core Keeper mod before, read three chapters in this
order. They are the ones whose absence causes the most wasted time, and together
they cover what every mod does regardless of what it is for.

1. **[Mod anatomy](mod-anatomy.md)** — what a mod consists of, what the loader
   reads, and how it is configured. Without this the rest has no frame.
2. **[The load-time sandbox](sandbox.md)** — what your code may
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

[Organising a mod project](organising-a-mod-project.md) then walks through one way to lay the project out.
The rest of this handbook assumes you can already build and install *something*
and now need to know how the game behaves.

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
| Every source mod fails to compile, on a non-English machine | [Platforms and hosts](platforms.md) — the Roslyn satellite lookup |
| A mod that loaded yesterday does not load today | [Troubleshooting](troubleshooting.md) — a stale game-version tag, the commonest cause; [Multiplayer and server](multiplayer-and-server.md) if it is a join that broke; [Platforms and hosts](platforms.md) on a Wine host |
| A tag you set on mod.io simply is not there | [Publishing to mod.io](publishing.md) — unknown values are dropped silently |
| Mod fails to compile (`CompileFailed`) | [The load-time sandbox](sandbox.md), then [Troubleshooting](troubleshooting.md) |
| Scripts are not compiled at all, and the log says nothing | [Troubleshooting](troubleshooting.md) — the mod.io `Access Type` tag |
| An unrelated, previously working mod stopped patching | [Troubleshooting](troubleshooting.md) — the CompileFailed cascade |
| Game closes at the loading screen | [Troubleshooting](troubleshooting.md) — Steam Cloud conflict, not your mod |
| You changed a string, the game still shows the old one | [Localisation](localisation.md) — first-write-wins |
| The UI shows a raw term key like `MyMod-General/Label` | [Localisation](localisation.md) |
| `LoadAsset<Sprite>` returns null | [Prefabs and rendering](prefabs-and-rendering.md) — sprite import settings |
| A sprite renders grey or dimmed for no reason | [Prefabs and rendering](prefabs-and-rendering.md) — the uiCamera Z tie |
| Your text element is invisible until the string changes | [Prefabs and rendering](prefabs-and-rendering.md) — PugText self-deactivation |
| Your HUD element exists, is active, and does not show | [Prefabs and rendering](prefabs-and-rendering.md) — wrong layer, wrong Z, or scaled to nothing |
| Players are blocked from joining your server | [Multiplayer and server](multiplayer-and-server.md), [Mod anatomy](mod-anatomy.md) — `requiredOn` |
| "Game version mismatch" between client and server | [Multiplayer and server](multiplayer-and-server.md) — it is a mod-set mismatch |
| Dedicated server fails to generate a world | [Multiplayer and server](multiplayer-and-server.md) — the server renders, so `-nographics` breaks it |
| A call works in single-player but not on a server | [Multiplayer and server](multiplayer-and-server.md) — some subsystems are compiled out server-side |

## Start from the task

| What you want to do | Go to |
|---|---|
| Understand what a mod is made of and what the loader reads | [Mod anatomy](mod-anatomy.md) |
| Give your mod a config file | [Storing configuration and state](persistence.md) |
| Persist mod state across sessions, without corrupting a save | [Storing configuration and state](persistence.md) |
| Know what you may reference at compile time | [The load-time sandbox](sandbox.md) |
| Patch a DOTS system, or read the live ECS world | [Harmony and ECS](harmony-and-ecs.md) |
| Change a recipe, an item stat, or any baked object data | [Database and baking](database-and-baking.md) |
| Add an options-menu entry or a rebindable keybind | [UI framework](ui-framework.md) |
| Build a HUD element or a menu window | [UI framework](ui-framework.md), [Prefabs and rendering](prefabs-and-rendering.md) |
| Work with prefabs, sprites or fonts | [Prefabs and rendering](prefabs-and-rendering.md) |
| Place tiles, or understand where things may be built | [World and mechanics](world-and-mechanics.md) |
| Read or place map markers | [World and mechanics](world-and-mechanics.md) — at runtime; [Savegame formats](savegame-formats.md) — out of a world file |
| Ship a mod that works in multiplayer | [Multiplayer and server](multiplayer-and-server.md) |
| Translate your mod's text | [Localisation](localisation.md) |
| Read data out of a save | [Savegame formats](savegame-formats.md) |
| Publish a mod, or fix what its listing says | [Publishing to mod.io](publishing.md) |
| Find where the game keeps mods, saves or logs | [Platforms and hosts](platforms.md) |
| Answer a question nothing here answers | [Reverse engineering](reverse-engineering.md) |
| Get a build running in the first place | [Toolchain requirements](toolchain.md) |
| Lay out a mod so it stays in version control | [Organising a mod project](organising-a-mod-project.md) |

## Licence note

Core Keeper modding under Pugstorm's EULA is personal-use and non-commercial.
