# Core Keeper modding handbook — where to start

## Preamble

**This describes Core Keeper `1.2.1.5`** unless a passage names another version.
Everything here was read off a running game or out of decompiled assemblies
rather than from documentation, so a game update can invalidate any statement in
it without warning, and nothing announces that it has.

Every statement also began somewhere narrower than it now reads. A finding
arrives while building one particular mod, at one call site, on one host; what
gets written down is the generalisation of it — "this is how Core Keeper
behaves" — and that step is a derivation, not the observation it resembles.
Usually it holds, which is why reading the relevant chapter first saves the most
time. Where it does not, the failure takes one of four shapes: the claim is true
only of the situation it was found in; or it is simply wrong; or it is incomplete,
because the case that would have contradicted it never came up; or it is
backwards, cause and effect having been read the wrong way round in the one case
available. The chapters try to say so where the evidence is narrow, but that is
an intention rather than a guarantee — an overreaching claim reads exactly like a
well-supported one, and nothing in the text distinguishes them.

Which makes this a place to start rather than an authority to cite. Take a
chapter as the best available hypothesis plus a record of what has already been
ruled out, and check it against the decompile or the running game before
building something expensive on it — and before repeating it outside your own
work. Where the game disagrees with a chapter, the game is right: correct the
chapter there, visibly, so a reader who remembers the old claim learns that it
changed. [Reverse engineering](reverse-engineering.md) has the checks that make a generalisation safe, and
the four ways a correct reading of the source still describes something other
than what runs.

It covers the game and the SDK — nothing about any individual mod, and no
script, path or command belonging to a particular workspace. How you build,
publish or run a server is yours to arrange; what the chapters describe is the
machinery those arrangements sit on.

## The chapters

| Chapter | Covers |
|---|---|
| [Toolchain requirements](toolchain.md) | What the SDK demands of any setup — the exact Unity version, the build modules, the wizard steps and why a game update repeats one, the project lock, duplicate package GUIDs, the macOS Inspector that drops edits, and where the macOS meta-file fix is written up |
| [Organising a mod project](organising-a-mod-project.md) | Why the Editor writes outside your repository and what closes that gap, separating machine paths from mod identity, a formatting gate that cannot silently pass, pinning what produces shipped bytes |
| [Platforms and hosts](platforms.md) | Where the game runs and keeps its files, what a Wine-based host breaks and how those failures look, reading logs on a translated host |
| [Mod anatomy](mod-anatomy.md) | The `IMod` lifecycle, assembly definitions, the ModBuilderSettings `.asset` versus the generated manifest, the two kinds of GUID, dependencies, chat commands, and `requiredOn` with its crossed checks |
| [The load-time sandbox](sandbox.md) | What the verification rejects and what it does not, why an Editor build proves nothing, why Harmony attributes are exempt, and how to find the identifier that failed |
| [Storing configuration and state](persistence.md) | The three routes a sandboxed mod has to a file, what the rest of the catalogue actually uses, and writing state in lockstep with the game's own save |
| [Harmony and ECS](harmony-and-ecs.md) | Why Burst-compiled systems swallow patches, `BurstDisabler` and its silent failure on 1.2 dedicated servers, why a mod's own code is not Bursted, patch binding, instrumenting generated DOTS code, live ECS access |
| [Database and baking](database-and-baking.md) | Editing baked object data through the converter hook and when the conversions run, the `(objectID, variation)` key, variations and paint, item level and sell value, adding a craftable item and pinning its `ObjectID`, station windows and their titles, data-block addresses and their order, fileIDs |
| [UI framework](ui-framework.md) | Sprite UI instead of uGUI, mounting windows, options-menu entries, rebindable keybinds, the hint bar, text input, redirecting menu input, scrolling, and disabled-but-visible options |
| [Prefabs and rendering](prefabs-and-rendering.md) | When a prefab may be edited by script, nested prefabs and variants, editing a vanilla object's graphical prefab at bake time, sprite import, masking, Z-sorting, PugText and the font system, HUD versus world space |
| [World and mechanics](world-and-mechanics.md) | World geometry and the origin, tile layers and the `AddTile` queue, the placement permission model, map markers, entity radii, ore boulders, livestock and pets, cooked food |
| [Multiplayer and server](multiplayer-and-server.md) | The NetCode/ghost protocol and what changes its hashes, declaring an RPC and what it costs, admin level and guest mode, the mod set as a second compatibility layer, how the dedicated server build differs |
| [Localisation](localisation.md) | The game-wide table, first-write-wins and its consequences, the ways localisation has shipped broken, term-key conventions |
| [Publishing to mod.io](publishing.md) | Profile versus modfile and why a changelog cannot be edited, which manifest field becomes which tag, the silent tag drop, dependencies existing twice |
| [Publishing to the Steam Workshop](steam-workshop.md) | One item instead of a profile and a modfile, tags grouped by the platform, the 1 MB preview cap, what the SDK tab does behind its fields, and the native library macOS needs |
| [Announcing a mod in the community Discord](announcing-in-discord.md) | The `#available-mods` forum's rules and what they demand of a post, and why an inactive thread is archived rather than gone |
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

1. **[Mod anatomy](mod-anatomy.md)** — what a mod consists of, what the loader reads, and how it
   is configured. Without this the rest has no frame.
2. **[The load-time sandbox](sandbox.md)** — what your code may reference at all. This is the
   chapter that prevents the classic first experience: a mod that builds
   perfectly and dies at load.
3. **[Harmony and ECS](harmony-and-ecs.md)** — how to hook into the game. Read at least the first
   section; a patch that binds but never fires is the single most common early
   confusion.

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
| Works in single-player and when you host, does nothing on a dedicated server | [Harmony and ECS](harmony-and-ecs.md) — the dedicated-server trap (measured through 1.2; gone on a fresh 1.3.0.5 server) |
| `Undefined target method for patch method …` | [Harmony and ECS](harmony-and-ecs.md) — `in`/`ref` parameter binding; [mod anatomy](mod-anatomy.md#harmony-patches-are-auto-discovered) — a target the type only inherits |
| Every source mod fails to compile, on a non-English machine | [Platforms and hosts](platforms.md) — the Roslyn satellite lookup |
| A mod that loaded yesterday does not load today | [Troubleshooting](troubleshooting.md) — a stale game-version tag, the commonest cause; [Multiplayer and server](multiplayer-and-server.md) if it is a join that broke; [Platforms and hosts](platforms.md) on a Wine host |
| A recipe added to a vanilla workbench never shows up, or `Not enough SimpleCraftingUIs` in the log | [Database and baking](database-and-baking.md#how-a-station-window-lays-out-the-list-six-slots-three-windows) — the station window has three six-slot windows |
| A modded item turns into another item on a dedicated server, or a craft there takes the materials and gives them back | [Database and baking](database-and-baking.md#where-a-modded-items-objectid-comes-from) — client and server numbered the item differently; [pinning the ID](database-and-baking.md#pinning-a-modded-items-objectid-seed-the-lookup-first) |
| Item Browser (or another reader of the managed recipes) throws in `ObjectUtility.GetValue` when its Items tab opens | [Database and baking](database-and-baking.md#seeding-an-item-hides-its-recipe-from-the-managed-catalogue) — a pre-seeded item's ingredients resolved to `None` |
| `Missing title for crafting UI window` floods the log | [Database and baking](database-and-baking.md#how-a-station-window-lays-out-the-list-six-slots-three-windows) — an added window needs a title; patch the getter on a copy |
| A workbench shows an empty extra window | [Database and baking](database-and-baking.md#how-a-station-window-lays-out-the-list-six-slots-three-windows) — observed with trailing `None` padding, cause open |
| A setting changed in a menu is back to its old value after a restart | [Storing configuration and state](persistence.md#2-corelibs-configfile--typed-entries-at-a-price) — another mod turned `SaveOnConfigSet` off |
| An edit made from `Init` misses another mod's entries, depending on load order | [Database and baking](database-and-baking.md#trap-a-config-value-the-bake-reads-must-be-bound-in-earlyinit) — every `Init` runs before any `Update` |
| The Unity Editor crashes when you open any prefab | [Toolchain requirements](toolchain.md#after-a-game-update-update-the-sdk-then-update-game-files-again) — stale SDK Editor assemblies after a game update |
| Inspector edits revert on macOS | [Toolchain requirements](toolchain.md#on-macos-the-inspector-loses-edits-on-components-that-reference-a-data-block) — the data-block drawer throws; use the Debug Inspector |
| Every prefab shows a missing script after adding a package's source while the package was still installed | [Toolchain requirements](toolchain.md#two-copies-of-one-package-break-its-guids) — two copies, new GUIDs |
| A tag you set on mod.io simply is not there | [Publishing to mod.io](publishing.md) — unknown values are dropped silently |
| The Steam Workshop tab's "Initialize Steam" does nothing | [Troubleshooting](troubleshooting.md) — a native library the SDK does not ship on macOS |
| A Workshop upload fails, or its preview is rejected | [Publishing to the Steam Workshop](steam-workshop.md) — the 1 MB preview cap and what else the tab does silently |
| Your Discord announcement is no longer in the channel list | [Announcing a mod in the community Discord](announcing-in-discord.md) — inactivity archives a thread, it does not delete it |
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
| Masked content vanishes entirely once you add a second mask | [UI framework](ui-framework.md) — masks combine as OR, and a range whose lower bound sits on the target drops it out of both |
| A second mask widens the clip instead of narrowing it | [UI framework](ui-framework.md) — same cause, seen from the other side |
| Your HUD lands on top of another mod's | [Prefabs and rendering](prefabs-and-rendering.md) — sharing a corner, measured rather than referenced |
| Text vanishes in every menu after a mod's screen was opened a few times | [UI framework](ui-framework.md#destroying-a-text-that-still-holds-glyphs-drains-the-shared-pool) — destroyed texts drain the shared glyph pool |
| Typing inserts at the wrong position in a text field | [UI framework](ui-framework.md#glyph-positions-are-not-string-positions) — glyph positions are not string positions |
| A held key repeats for the game and fires once for your patch | [UI framework](ui-framework.md#the-typing-path-repeats-keys-on-a-timer-of-its-own) — the typing path has a repeat timer of its own |
| Players are blocked from joining your server | [Multiplayer and server](multiplayer-and-server.md), [Mod anatomy](mod-anatomy.md) — `requiredOn` |
| "Game version mismatch" between client and server | [Multiplayer and server](multiplayer-and-server.md) — a mod-set mismatch, or a hash moved by a new ghost prefab or `IRpcCommand`; neither names a mod |
| Dedicated server fails to generate a world | [Multiplayer and server](multiplayer-and-server.md) — the server renders, so `-nographics` breaks it |
| A call works in single-player but not on a server | [Multiplayer and server](multiplayer-and-server.md) — some subsystems are compiled out server-side |
| `Failed to resolve MapMarkerIconDataBlock` repeats in the log, and a map marker shows a blue diamond or another marker's icon | [World and mechanics](world-and-mechanics.md#since-13-a-user-markers-icon-is-a-data-block) — the marker's icon block is not loaded |
| Minimap marker icons of a mod jitter while the player moves | [World and mechanics](world-and-mechanics.md#marker-sprites-are-fixed-even-boxes-and-an-odd-size-jitters) — odd-sized sprites put the pivot on half a pixel |
| The big map stutters badly with a mod's markers in view | [World and mechanics](world-and-mechanics.md#since-13-a-user-markers-icon-is-a-data-block) — an unresolved icon logs a stack trace per marker per frame |
| An object turns invisible (edge-on) or cannot be used after you gave it an interactable | [Prefabs and rendering](prefabs-and-rendering.md#interactable-must-be-set-and-on-a-directional-object-it-must-be-a-child) — `interactable` is null, or points at the root |
| ECS initialisation fails after you added interaction components at bake time (on a Wine host, the game then hangs on exit) | [Prefabs and rendering](prefabs-and-rendering.md#interaction-triggers-need-an-interactableobject-first) — the post converter found no `InteractableObject` |
| An RPC about an object the player just placed has no effect | [Multiplayer and server](multiplayer-and-server.md#a-just-placed-object-cannot-be-named-in-an-rpc-yet) — the object is still a predicted ghost with no id |
| The sign or chest window shows a stale visibility state | [UI framework](ui-framework.md#the-sign-window-reads-the-visibility-state-once) — it reads the state only when it opens |

## Start from the task

| What you want to do | Go to |
|---|---|
| Understand what a mod is made of and what the loader reads | [Mod anatomy](mod-anatomy.md) |
| Give your mod a config file | [Storing configuration and state](persistence.md) |
| Persist mod state across sessions, without corrupting a save | [Storing configuration and state](persistence.md) |
| Know what you may reference at compile time | [The load-time sandbox](sandbox.md) |
| Patch a DOTS system, or read the live ECS world | [Harmony and ECS](harmony-and-ecs.md) |
| Change a recipe, an item stat, or any baked object data | [Database and baking](database-and-baking.md) |
| Give a modded item an `ObjectID` that client and server agree on | [Database and baking](database-and-baking.md#pinning-a-modded-items-objectid-seed-the-lookup-first) |
| Know when your code runs relative to the database conversions | [Database and baking](database-and-baking.md#trap-a-config-value-the-bake-reads-must-be-bound-in-earlyinit), [Mod anatomy](mod-anatomy.md#the-imod-lifecycle) |
| Add an item to a vanilla workbench, or to a vanilla loot table | [Database and baking](database-and-baking.md#how-a-station-window-lays-out-the-list-six-slots-three-windows), [loot tables](database-and-baking.md#adding-an-item-to-a-vanilla-loot-table) |
| Add an options-menu entry or a rebindable keybind | [UI framework](ui-framework.md) |
| Make directional input mean something else for a while (a "mode") | [UI framework](ui-framework.md) |
| Build a HUD element or a menu window | [UI framework](ui-framework.md), [Prefabs and rendering](prefabs-and-rendering.md) |
| Work with prefabs, sprites or fonts | [Prefabs and rendering](prefabs-and-rendering.md) |
| Place tiles, or understand where things may be built | [World and mechanics](world-and-mechanics.md) |
| Notice the local player's own placements | [World and mechanics](world-and-mechanics.md#the-moment-of-placement-is-recorded-on-the-player-not-the-object) |
| Give a vanilla object an interaction or a label | [Prefabs and rendering](prefabs-and-rendering.md#editing-a-vanilla-graphical-prefab-at-bake-time), then [Database and baking](database-and-baking.md#trap-objectdatacdamount-is-not-a-stack-size-everywhere) for the drop count |
| Read or place map markers | [World and mechanics](world-and-mechanics.md) — at runtime; [Savegame formats](savegame-formats.md) — out of a world file |
| Add map-marker icons | [World and mechanics](world-and-mechanics.md#since-13-a-user-markers-icon-is-a-data-block), then [Database and baking](database-and-baking.md#scriptabledata-blocks-addresses-and-order) for the address |
| Ship a mod that works in multiplayer | [Multiplayer and server](multiplayer-and-server.md) |
| Send something to the server, or gate on admin rights | [Multiplayer and server](multiplayer-and-server.md) |
| Translate your mod's text | [Localisation](localisation.md) |
| Read data out of a save | [Savegame formats](savegame-formats.md) |
| Publish a mod, or fix what its listing says | [Publishing to mod.io](publishing.md), [Publishing to the Steam Workshop](steam-workshop.md) |
| Tell players a mod exists, or that a new version shipped | [Announcing a mod in the community Discord](announcing-in-discord.md) |
| Find where the game keeps mods, saves or logs | [Platforms and hosts](platforms.md) |
| Answer a question nothing here answers | [Reverse engineering](reverse-engineering.md) |
| Get a build running in the first place | [Toolchain requirements](toolchain.md) |
| Lay out a mod so it stays in version control | [Organising a mod project](organising-a-mod-project.md) |

## Licence note

Core Keeper modding under Pugstorm's EULA is personal-use and non-commercial.
