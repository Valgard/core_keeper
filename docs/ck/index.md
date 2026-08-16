# Core Keeper modding handbook — index

**The handbook starts at [README.md](README.md).**

It is called that so it renders automatically when this directory is opened on
GitHub or Forgejo; this file exists because `index.md` is what you look for when
you are reading the files directly.

[README.md](README.md) is the wayfinder: it routes by **symptom** ("my patch
never fires"), by **task** ("add an options-menu entry"), and by **starting from
nothing** if you have never built a mod for this game.

## The chapters

| File | Covers |
|---|---|
| [mod-anatomy.md](mod-anatomy.md) | `IMod` lifecycle, assembly definitions, the ModBuilderSettings `.asset` vs. the generated manifest, GUIDs, dependencies, chat commands, `requiredOn` |
| [sandbox-and-config.md](sandbox-and-config.md) | What load-time verification rejects and what it does not; the three ways a sandboxed mod stores settings |
| [harmony-and-ecs.md](harmony-and-ecs.md) | Burst-compiled systems and `BurstDisabler`, patch binding, instrumenting generated DOTS code, reading the live ECS world |
| [database-and-baking.md](database-and-baking.md) | Editing baked object data, `objectsByType`, variations and paint, item level and sell value, adding a craftable item, fileIDs |
| [ui-framework.md](ui-framework.md) | Sprite UI instead of uGUI, mounting windows, options entries, keybinds, the hint bar, text input, scrolling, disabled options |
| [prefabs-and-rendering.md](prefabs-and-rendering.md) | Prefab editing, nested prefabs and variants, sprite import, masking, Z-sorting, PugText and fonts, HUD vs. world space |
| [world-and-mechanics.md](world-and-mechanics.md) | World geometry and the origin, tile layers and placement, map markers, entity radii, ore boulders, livestock and pets, food |
| [multiplayer-and-server.md](multiplayer-and-server.md) | Ghost protocol and what changes its hashes, the mod set as a second compatibility layer, how the dedicated server differs |
| [localisation.md](localisation.md) | The game-wide table, first-write-wins, the ways localisation ships broken, term conventions |
| [savegame-formats.md](savegame-formats.md) | World, map and character files — what is readable, what is not, and why |
| [troubleshooting.md](troubleshooting.md) | Symptom-first index for mods that fail after building successfully |
| [reverse-engineering.md](reverse-engineering.md) | Decompiling, unpacking assets, querying prefab YAML, how much evidence a claim needs |

## Not in the handbook

Building and installing a mod, publishing to mod.io, running a local dedicated
server and host-specific setup live one directory up, in
[`../`](../) and in the [repository README](../../README.md). This handbook
covers the game and the SDK; that side covers the workflow around them.
