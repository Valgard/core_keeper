# Mod Screenshots — Retake and Fill the Galleries

- **Date:** 2026-10-22
- **Scope:** twelve published mods of this workspace — content work, no code
- **Status:** **approved** 2026-10-22. Scope, capture method and destinations
  are decided; the motifs are proposals refined at capture time; the open points
  at the end are settled when their mod's turn comes.

## Why

The mod.io gallery and the Steam Workshop gallery are the first thing a player
sees of a mod, and for several mods here they show nothing at all, or show
something a player never sees on their own machine: a macOS window title bar,
the German game UI, or a menu from the 1.2 game builds that no longer looks that
way. One Workshop comment (Complete Tools, 2026-10-22) asked for real pictures
instead of only the AI logo, and the reply promised screenshots within days.

**The rule every picture has to meet:** it shows one real function of the mod,
the way a player sees the game with that mod today — Core Keeper 1.3, English
UI, a full-screen 16:9 frame, nothing around it.

## Goals, non-goals, anti-goals

**Goals**

- Every mod listed under [Work per mod](#work-per-mod) gets pictures that meet the
  rule, on both the mod.io gallery and the Steam Workshop gallery — Auto Rail
  Bridges gets videos instead.
- Each mod's `sources/` carries the new originals, and `CK_DISCORD_MEDIA` names
  them.
- Auto Rail Bridges gets its two clips onto its Workshop page as YouTube videos.

**Non-goals**

- The logos. They stay as they are; the criticism of AI art is not addressed by
  this task.
- Automating gallery uploads. The publish pipeline uploads the logo and nothing
  else (`utils/CLIPublishHelper.cs`, `utils/ck-workshop`), and the galleries
  stay hand-filled.
- Disable Durability, Faster Talents, Faster Pet Talents and Reusable Cattle
  Box. Their galleries were checked and meet the rule.
- Complete Tools' first Discord post (decided). The mod has no
  `#available-mods` thread — `CK_DISCORD_THREAD` is empty, and a search of the
  server on 2026-10-22 found only mentions of the mod. Its first post, through
  the `ck-discord-post` skill, is a task of its own; this one only leaves the
  new pictures in `sources/` and `CK_DISCORD_MEDIA` for it.

**Anti-goals** — a picture that does any of these is a failure even if it is
otherwise good:

- shows window chrome, a shadow or black side bars;
- shows the German UI, or German number formatting (`5,1%`) — except where the
  language is the subject (Complete Tiny Font);
- shows a mod build that is not the published one — above all an unreleased
  development build (Mod Settings Menu's v2 runs as the local dev build);
- shows another mod's UI in a way that reads as part of this mod;
- is enlarged with a smoothing filter (pixel art is enlarged nearest-neighbour or
  not at all).

## Current state (measured 2026-10-22)

Every gallery image on both platforms was downloaded and inspected. Steam and
mod.io carry the same images in the same count for every mod, with one
exception noted below.

| Mod | Gallery today | Problem |
|---|---|---|
| Complete Tools | none | no picture |
| Complete Tiny Font | none | no picture |
| Refill Ore Boulders | none | no picture |
| Sign Labels | none | no picture |
| Auto Rail Bridges | none (two GIFs in the mod.io description) | no Workshop video |
| Caveling Divining Rod | 3 | macOS title bar; rod and arrow art predate 1.1.1 |
| Simple Crafting Pool Extender | 2 | macOS title bar |
| Map Markers Enhanced | 8 | German UI; shows the 1.x icon set, not 2.0.0's seven |
| Rebalance Key Crafting | 4 | German UI |
| Mod Settings Menu | 4 | three show the version label `1.2.1.5`; the set predates 1.3 |
| Item Checklist | 7 | `settings`, `controls` show `1.2.1.5`; `hud` shows `5,1%`; four have black bars |
| Player Coordinates HUD | 1 | predates 1.1.0; on mod.io also uncropped 32:9 |

Seven mods already carry a roadmap point for exactly this, with what is settled
and what is open: `auto-rail-bridges`, `caveling-divining-rod`,
`complete-tiny-font`, `item-checklist` (Iter-49), `player-coordinates-hud` and
`simple-crafting-pool-extender`, each in its own `docs/roadmap.md`. This
document does not replace them; it lists what the umbrella task decides on top
of them.

## How a picture is made (decided)

- **Sven captures in game.** Core Keeper runs in its full-screen mode; the
  capture is ⇧⌘5 → *Capture Entire Screen*. *Capture Selected Window* is what
  produced the title bars and is not used.
- **Crop with `utils/crop-center-169.sh -k`.** On the ultra-wide monitor the
  full-screen capture is 32:9 with the game in the middle; the script cuts the
  centre 16:9 slice at full height and, with `-k`, keeps the original. It cannot
  repair a window capture — it narrows the width and leaves a title bar where it
  is — so a window capture is retaken, not cropped.
- **English game UI**, switched in the game's options for the session and back
  afterwards. Complete Tiny Font is the exception.
- **Integer Scaling off** for the whole round (decided). With it on, every 16:9
  crop carries a uniform black frame (80/45 px at 1980 px height) that the crop
  script cannot remove; off gives frameless 3520×1980 pictures like most of the
  existing ones. Whether Complete Tiny Font's enlarged pixel crops need it on is
  settled with that mod's other open points.
- **Staged in World 0**, as every earlier gallery picture was (decided). This
  is a deliberate exception to the standing rule that World 0 is not used for
  tests; it has the late-game stations the motifs need.
- **Every mod as its last published version, no dev build at all**
  (decided). A dev build wins over the subscribed copy — the loader
  deduplicates by name — so before the round every fake-id dev install is
  removed with `utils/uninstall-macos.sh`, run from each mod's repo, and the
  mods are subscribed on mod.io. The script also clears the game's
  `Localization.csv` for mods that ship localisation; that file is
  first-write-wins, and without the clear the dev builds' wording would stay on
  screen. Check before the first capture: in `Player.log`, every mod's
  `Loading mod with ID <id>` line names its real mod.io id, never a fake one
  (`9999xxx`). This matters most for Mod Settings Menu, whose local dev build is
  the unreleased v2 and which draws every Mod Settings section in these
  pictures, whichever mod it belongs to. After the round the dev installs are
  rebuilt with `utils/build.sh` and the subscriptions ended; the local dedicated
  server's mod links are reconciled by `utils/server.sh relink`.

  For the record: on 2026-10-22, `main` was ahead of the release tag for six
  mods, and none of those differences shows in game — comments, log messages and
  SDK GUID references only. The rule stands regardless.
- **Other mods out of frame where they are not the subject.** Item Checklist's
  counter, Player Coordinates HUD's readout and the divining rod's ring are on
  screen in normal play. Tool Resizer sets tool sizes itself and must be off for
  any picture that shows a tool's area (Complete Tools' compatibility note).

## Where a picture goes

For each mod, in this order:

1. **`sources/`** in the mod repo, tracked. Replacing a picture keeps its file
   name, so `CK_DISCORD_MEDIA` stays valid; a new picture follows the mod's
   existing naming (`core_keeper_<mod>_<subject>.png` for most,
   `<mod>-<subject>.png` for the two rod-and-extender repos).
2. **`CK_DISCORD_MEDIA`** in the mod's `.envrc` lists the new set, in gallery
   order.
3. **mod.io gallery** — by hand on the website, by Sven (decided); old images
   that fail the rule are deleted.
4. **Steam gallery** — by hand on the Workshop page (*Add/edit images &
   videos*), by Sven; same.
5. **Discord** — the new pictures go into the mod's existing `#available-mods`
   thread as a comment (decided). The thread's opening post cannot take new
   images in the web client, so the comment is the only way they get there.
6. **The mod's roadmap point** is closed or reduced to what is left.

## Work per mod

Motifs are proposals unless marked as decided. Two to four pictures per mod; the
first one is the one a gallery shows largest.

### Complete Tools — new (promised on Steam, do first)

1. The Relucite Smithing Table's crafting window with the new Relucite tools,
   the tooltip of the Relucite Pickaxe open.
2. A large hoe in use — the Relucite Hoe's 9×9 area on tilled ground. Tool
   Resizer off.
3. The sledge hammers craftable: a workbench window showing them, with
   *loot-only tools craftable* switched on.
4. The Mod Settings section with that setting. A separate picture, not a
   montage with 3 — the two are on different screens. *(Author's call.)*
5. Optional: all twelve new tools side by side in the inventory.

### Complete Tiny Font — new

Decided in its roadmap: a before/after of an accented or Cyrillic character,
since the slot numbers barely change; the "before" needs the mod unloaded and a
restart; both halves need the mod's log line checked first; enlargement only
nearest-neighbour. Still open there: one composed frame or two images, which UI
surface, German and Russian in one pair or two, crop and scale. This mod is the
one exception to the English-UI rule and to the full-frame rule: an enlarged
crop and a composed before/after are allowed here, enlarged nearest-neighbour
only. Its four open points are settled with Sven when its turn comes, before
the first "before" restart, so no restart cycle is spent on a guessed format.
*(Author's call.)*

### Refill Ore Boulders — new

1. A half-mined ore boulder, with `/refillboulders` typed into the chat.
2. The same boulder back at full, with the command's reply in the chat.

### Sign Labels — new

1. A row of arrow signs along a path, each with its label shown (*Always*) —
   the waypoint use the mod is for.
2. The game's sign window open on an arrow sign, editing its label.
3. Several of the seven sign types labelled side by side.
4. Optional: its Mod Settings section, *Default visibility*.

### Auto Rail Bridges — videos, no stills (decided)

The function is a process and is not shown as a still. mod.io keeps the two GIFs
in its description. For Steam, the two MP4s already in `sources/`
(`ck_auto_rail_bridges_wood.mp4`, `ck_auto_rail_bridges_stone.mp4`) are uploaded
to YouTube by Sven as **unlisted** videos (decided) and linked on the Workshop
item — provided Steam accepts an unlisted video, which is checked first. The
channel is Sven's to choose; titles and descriptions are written at upload. The
same two links also go
into the mod.io gallery, which accepts YouTube videos, so that gallery is not
left empty *(author's call)*. The GIFs stay in the mod.io description and stay
the Discord route.

### Caveling Divining Rod — retake three

Keep the existing division, which its roadmap considers sound: the arrow ring
pointing at dig spots, a find being dug up, the recipe at the Iron Workbench —
now with the 1.1.1 art and the ring centred on the character. Optional fourth:
its Mod Settings section.

### Simple Crafting Pool Extender — retake two

The after-state at two stations rather than a before/after: a "before" looks
like plain vanilla and shows nothing. The Iron Workbench with its fourth window
open (the divining rod's), and a second station with a fifth window (Complete
Tools adds them at the Galaxite and Solarite workbenches).

### Map Markers Enhanced — retake, English UI and 2.0.0

The map with a spread of the mod's markers, then the marker dialog once per new
icon — General, Ores, Flags, Tapestry, Orbs, Numbers, Letters. That is eight
pictures, the same count as today, now showing the 2.0.0 set.

### Rebalance Key Crafting — retake four, English UI

Keep the existing set: the same key recipe at vanilla, quarter and half cost and
at one ingot, each with its tooltip. Optional fifth: its Mod Settings section.

### Mod Settings Menu — retake four, published 1.2.2

The main menu with its mod count, the Settings menu with the *Mod Settings*
entry, and the Mod Settings screen with several mods' sections (two pictures).
Captured with the published 1.2.2, like every other mod in the round.

### Item Checklist — retake all seven

Retake the whole set at one size (decided), which settles its roadmap's Iter-49:
`hud` (English formatting), `settings` and `controls` (1.3 menus), and the four
window captures `filter`, `filter_selected`, `search` and `sort`. Their content
is current, but cropping off their black bars would leave them at 4112×2310
beside 3520×1980. The retake can also fix what Iter-49 noticed in passing: a
character at 3.2 % discovery shows nearly every row as `???`.

### Player Coordinates HUD — retake

Its roadmap records the one picture as stale: it predates the five positions,
the marker and the edge-flush alignment, so it is retaken rather than only
cropped for mod.io (decided). Proposal: the readout bottom-left with
its marker in normal play, the readout below the minimap, and the Mod Settings
section where the position is chosen.

## Order

1. Complete Tools — promised publicly.
2. The other mods with no picture: Sign Labels, Refill Ore Boulders, Complete
   Tiny Font.
3. The title-bar sets: Caveling Divining Rod, Simple Crafting Pool Extender.
4. Stale content: Player Coordinates HUD, Map Markers Enhanced.
5. Language and version: Rebalance Key Crafting, Mod Settings Menu, Item
   Checklist.
6. Auto Rail Bridges' videos — independent of the game, any time.

## Open decisions

- **Complete Tiny Font's four points** (format, surface, languages, crop and
  scale), settled with Sven when that mod's turn comes.
- **The YouTube channel** for Auto Rail Bridges' two clips — Sven's choice.
