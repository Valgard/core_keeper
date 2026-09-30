# Sign Labels — Design

- **Date:** 2026-09-30
- **Mod:** `sign-labels` (new repo)
- **Status:** implemented; what the running game has and has not confirmed
  is under *What is not yet observed*
- **Citations:** every `Pug.*:N` line number refers to Core Keeper
  `1.3.0.2`, the build this design was written against

## Problem

Core Keeper has three signs that can carry a label: the text sign
(`ObjectID.SignText = 4154`, `Pug.Base:2833`), `SignTextMetropolis` (4155) and
`ExcavationSign` (6858). The placeable arrow and the other decorative signs
cannot. A player who wants a waypoint — "→ Base", "Copper mine" — has to put a
text sign next to the arrow.

Two community mods add labels to other objects, but neither touches signs:
*More Labels* covers mannequins, aquariums, terrariums and pedestals, and
*Gravestone Label* covers the player grave. This mod covers the signs.

## Acceptance criteria

The user's decisions from the design conversation, quoted verbatim (German;
several are the label of the option they picked). Text outside the quotes is
context added here, not part of the decision.

1. The need: *"Aber es gibt keine Mod, der den platzierbaren Pfeilen ein Label
   hinzufügt."*
2. Scope: *"Alle Sign-Objekte"*, and, when the review found the two wooden
   signs, *"Aufnehmen"*. Context: the three text signs already carry a label,
   so the targets are the seven listed under Decisions.
3. Text entry: *"Hover + Interact-Binding"*, chosen as Gravestone Label's
   pattern. Context: the hover-and-interact half stands — it is how the
   game's interaction opens the window. The own-dialog half was replaced by
   the game's sign window once the spike showed it can be reused; the user
   approved that design (criterion 8).
4. Cut: *"Sign-Labels-Mod jetzt + Vereinende Mod später"*.
5. Visibility: *"Einstellbar, Standard wie bei CK (nur beim Hovern)"*.
6. *"Pro Schild wie Truehn, aber Standard-Sichtbarkeit über MSM"*.
7. *"Zusätzlich MSM-Standard"*. Context: asked after learning vanilla has no
   default.
8. The design: *"Passt, Spec schreiben"*.
9. When the default applies: *"Beim Platzieren"*.

Standing rules: from `CLAUDE.md`, *"The question to ask: does the SERVER need
this mod for it to work?"* for `requiredOn`, and *"Personal-use,
non-commercial only (Pugstorm EULA)."* From the family's naming convention,
kept with the `new-ck-mod` skill: repo, namespace and display name match.

## What the game already has

Labelling is a generic mechanism in the game, built around `WorldLabel`
(`Pug.Other:320342`):

- **Text** lives in the entity's `DescriptionBuffer`, written server-side by
  the `SetDescription` RPC (`Pug.Other:414563`).
- **Visibility** lives in `ObjectDataCD.amount` — `0` off, `1` only while the
  object is the interaction target, anything else always (`Pug.Other:320393`,
  `:320397`). It is written by the `SetWorldLabelVisibility` RPC, whose server
  handler sets `amount` on any entity without checking its type
  (`Pug.Other:414464`, `:414467`).
- **The sign window** — text field, visibility toggle, parental-control filter —
  accepts any `WorldLabel` as the player's active label (`Pug.Other:337856`). It
  is the same window the text sign opens.
- **In guest mode** the server drops both RPCs from players without admin
  rights (`Pug.Other:414193`, `:414528`). That is vanilla behaviour and applies
  to the text sign in the same way; the mod inherits it rather than working
  around it.

`SignText` (`Pug.Other:319055`) is a `WorldLabel`. The targets derive from
`EntityMonoBehaviour` directly (`SignArrow`, `Pug.Objects:1048`, and alike).
What they lack sits on two levels:

- **The graphical prefab** has no interaction point and no text object.
- **The entity** has none of the text sign's `DescriptionAuthoring`,
  `LocalInteractableAuthoring` and `AlwaysDropOneAuthoring`, so no
  `DescriptionBuffer`, no interaction triggers and no `AlwaysDropOneCD`.

The design adds both.

## Decisions

| Question | Decision | Why |
|---|---|---|
| Which objects | `SignArrow` (4151), `SignSkull` (4152), `SignBrute` (4153), `SignYellowWarning` (4156), `SignRedWarning` (4157), `WoodenSign1` (5809), `WoodenSign2` (5810) | Every sign without a label. Seven ids on five graphical prefabs: yellow and red warning share one, and so do the two wooden signs. |
| Own dialog or the game's | The game's sign window | Controller support, the filter, the visibility toggle and familiar handling come with it. A Gravestone-Label-style dialog would rebuild all of it, worse. |
| Visibility | Per sign, through the game's toggle | Identical to text signs and chests. |
| Default visibility | A Mod Settings Menu option — Off / Hover / Always, default Hover — applied when the local player places a target sign | Hover is what the game gives every placed object. The option saves one click per waypoint for players who want them always visible. |
| Target list | Data, not type checks | A later mod that unites the label mods reuses the list. For another plain `EntityMonoBehaviour` object that is one entry; see *Not in this iteration* for where it is more. |
| `requiredOn` | `3` | **Server:** the converter adds the description buffer and interaction components to the server-side entity; without the mod there, the text has nowhere to live. **Client:** the flag makes the server announce the mod as required (`Pug.Other:130395`), and a client without it is turned away at its mod check (`:129042`). That is the intended failure: the alternative is letting it in with a different ghost layout for these signs — `DescriptionBuffer` is a ghost component — which nothing here has tested and which the mod check exists to prevent. |

**The default is an extension beyond vanilla, and deliberately so.** Vanilla
has no default: a placed object simply carries `amount = 1`, the same field
that is a stack size elsewhere. With the option set to anything but Hover, a
labelled arrow and a text sign placed side by side start differently. That was
weighed and accepted.

## Architecture

A throwaway spike (`spike-sign-labels`, fake id, 2026-09-29) proved the
approach on `SignArrow` in the running game, observed by the user: the sign
window opens, text and visibility persist across a reload, the label renders in
the right place, and every pooled instance carries the modified prefab. Three
traps surfaced on the way, and each shapes the design below.

### Trap 1: a loaded graphical prefab accepts components, but not children

The graphical prefab `PrefabInfo.GetGraphical()` returns is a loaded asset
(`scene.IsValid() == false`). `AddComponent` and `DestroyImmediate(c, true)`
work on it. `Instantiate(x, assetTransform)` does not: Unity logs *"Cannot
instantiate objects with a parent which is persistent"* and creates the object
unparented in the scene.

So the asset gets only components. Everything that needs its own hierarchy is
built per instance in `Awake`, where the object is a scene object.

### Trap 2: `interactable` is both an ECS reference and a rotated transform

`EntityMonoBehaviour.interactable` serves two purposes:

- Spawning copies it into `InteractableObjectReferenceCD` (`Pug.Other:457863`).
  That is how the interaction system gets back to the component whose
  `onUseActions` it invokes. Left null, the hover appears for a moment and
  interaction does nothing.
- For an entity with `DirectionCD`, `OnSpawn` rotates `interactable.transform`
  to the object's direction (`Pug.Other:283997`). Pointed at the root, it
  turns the whole sign edge-on to the camera: sprite and label vanish, the
  flat shadow stays. Of the targets, arrow and warning signs are directional;
  skull, brute and wooden signs carry no rotation authoring.

So it must be set on every target. It must point at a child on the directional
ones; the others would tolerate the root, but a child everywhere keeps one code
path for all seven. The asset carries the `InteractableObject` on its root,
because baking needs one there (next section). Each instance moves it onto a
child `Interactable` in `Awake`, before `base.Awake()` caches it.

### Trap 3: visibility and drop amount share one field

Mining an object drops `amount` items unless it has `AlwaysDropOneCD`
(`Pug.Other:90158`). A sign set to Always has `amount = 2`, so without that
component it would drop two. The text sign carries it (`AlwaysDropOneAuthoring`
on its entity prefab), and the spec review found it on every other vanilla
label carrier as well. The converter adds it unconditionally, before anything
else can fail.

### Bake time: what the entity needs

`InteractablePostConverter` (`Pug.Other:449262`) builds `InteractableCD` from
the graphical prefab's `InteractableObject`. It runs for any entity that has a
`TriggerUseInteractionBuffer` or a `TriggerExitInteractionBuffer`, and it
indexes the first `InteractableObject` without checking whether one exists
(`Pug.Other:449303`).

That makes the order a correctness condition. If either trigger buffer is added
but the prefab edit failed, the post converter throws, ECS initialisation
fails, and the game hangs on its way out under Wine — the spike's first run did
exactly that. So the converter adds the trigger components **only when the
prefab edit verifiably succeeded**.

The vanilla `LocalInteractableConverter` is not reused. It accepts only an
`InteractableObject` whose events carry persistent calls, and the only way a
mod gets those is by copying them — the spike did, and the copies pointed at
the text sign's component, not at the mod's. The converter adds the same
components itself.

### Units

| Unit | Responsibility |
|---|---|
| `SignLabelTargets` | The target list: `ObjectID` → the vanilla root component type expected on its graphical prefab. |
| `SignLabelConverter : Converter` | Per target entity: `AlwaysDropOneCD`, `DescriptionBuffer`, and — only after a successful prefab edit — `TriggerUseInteractionBuffer`, `LocalUseInteractionTriggerCD` (disabled), `LocalUseInteractionTriggerSubIndexCD { subIndex = 0 }`, `TriggerExitInteractionBuffer`, `LocalExitInteractionTriggerCD` (disabled). |
| `GraphicalPrefabEditor` | Edits one graphical prefab exactly once, **keyed by the prefab, not by `ObjectID`**, because two pairs of targets share one. Swaps the vanilla root component for `LabeledSign`, carrying its serialized fields over with `JsonUtility`. Adds an `InteractableObject` to the root, copied from the text sign's, with fresh event lists and the outline pointed at the sign's own sprite. Leaves `interactable` null on the asset. |
| `LabeledSign : WorldLabel` | Per instance in `Awake`: moves the `InteractableObject` onto a child and sets `interactable`, clones the text sign's `WorldText` child and sets `worldLabel`, subscribes `Interact` / `OnPlayerLeft`. Both mirror `SignText`'s. |
| `PlacementMatcher` | Pure matching logic, no Unity types: a placement (start tick and tile) against a sign spawned on that tile within a short window. |
| `DefaultVisibility` | The Mod Settings Menu option, the placement watch, and the deferred send below. |

The text sign's graphical prefab is reachable at bake time through
`PugDatabase.GetObjectInfo(ObjectID.SignText)` — measured, not assumed.

### Default visibility at placement

The game records every placement as state on the placing player's entity:
`PlaceItem` restarts `PlacementCD.timeSincePlaced` (`Pug.Other:322011`) and
writes the placed tile to `PlacementCD.positionLastPlacedAt` (`:322015`). Both
are `[GhostField]`s (`Pug.ECS.Components:4425`), so the placing client holds
them whether it predicted the placement or received it from the server.

The mod reads that state instead of intercepting the placement. That needs no
Harmony patch and, in particular, not the process-wide Burst change a patch on
`PlaceObjectSlot.UpdateEquipment` would require — `auto-rail-bridges` pays that
price for its own hook. The design:

1. Each frame, the client reads the local player's `PlacementCD`. A
   `timeSincePlaced.startTick` different from the last one seen means a
   placement at `positionLastPlacedAt`; it is recorded with the time.
2. When a `LabeledSign` spawns on that tile within a short window, still at
   `amount = 1`, the sign is matched once and the default is taken as the
   option reads at that moment. The placement record does not name the
   object; the spawn does, and only target signs are `LabeledSign`s. Text
   on the sign does not block the default: a label is not a visibility
   choice.
3. The spawn is a client-predicted ghost (`GhostInstance.ghostId == 0`,
   `PredictedGhostSpawnRequest` present), and an RPC naming it cannot be
   resolved by the server. NetCode later promotes the same entity to the
   server-confirmed ghost, so the client sends `SetWorldLabelVisibility`
   only then — provided the sign still exists and is still at Hover — and
   gives up after 5 s.
4. The game's sign window reads the state only when it opens. If it is open
   on the sign when the send is due, a toggle the player already moved off
   Hover wins and nothing is sent; otherwise the toggle is set to the
   default. For 2 s after the send, the client waits for the new state to
   arrive and then sets the toggle of a window still open on that sign,
   unless the player has moved it off Hover. The toggle is set directly,
   never through the window's own send, which would repeat the RPC.

The vanilla RPC is the only write, so the mod adds no network message. In
multiplayer the placing player's own default applies, which matches how the
toggle works: it too is one client's choice. It inherits the toggle's limit as
well: a guest without admin rights on a guest-mode world has the RPC dropped,
so their signs start at Hover whatever the option says — just as that guest
cannot change the toggle.

The replicated state reaches the client as the design assumed, so the
fallback — a Harmony postfix on `PlaceObjectSlot.UpdateEquipment`
(`Pug.Other:321960`), with the Burst change it brings — was not needed.

### What is not yet observed

Observed since, in singleplayer on macOS/CrossOver (the mod's
`docs/manual-tests.md` has the runs): on 1.3.0.3, all seven signs on all
five graphical prefabs — interaction, text, the three visibility states,
save and reload, the arrow and a warning sign in all four directions, a
pooled instance reused after mining; on 1.3.0.4, the placement watch and
the default — Off and Always applied 0.12–0.18 s after placing, across ten
placements — signs loaded from a save keeping their state, and a sign
window opened right after placing switching to the default on its own,
with or without text typed.

Still unobserved:

- that mining a sign set to Always drops exactly one item — decompile-backed;
- painting the arrow;
- a sign streamed in by walking into its chunk keeping its state;
- a toggle the player changes in the window before the default is sent
  being kept — the gap is too short to click in by hand, so this rests on
  code review;
- **the prefab edit on a dedicated server.** The server's trigger components
  depend on it succeeding there, and every run so far was a hosting client.
  If it failed on the server while clients succeed, the two would disagree on
  those entities' components. Text, visibility and the placing player's
  default reaching a second client are untested with it;
- the combination with More Labels.

## Error handling

- **A prefab edit that fails leaves that sign behaving as vanilla.** It gets no
  trigger components, so there is no interaction and no label. It still
  carries `DescriptionBuffer` and `AlwaysDropOneCD`; neither has a visible
  effect without the rest, and both are added on every side alike, so they
  keep the ghost layout consistent. One log line names the object and the
  step. The game loads.
- **An unexpected root component** — a game update replaced the class the
  target list names — is treated the same way, and the log says so.
- **`AlwaysDropOneCD` is added independently of the edit**, so no combination
  of success and failure can duplicate items.

## Verification

In-game, written into the mod's `docs/manual-tests.md`:

- label, change and clear text on each of the seven signs;
- all three visibility states, and that the label follows them;
- save, quit, reload: text and visibility survive;
- place the arrow and a warning sign in all four directions, then interact;
- mine a sign set to Always: exactly one item drops;
- paint the arrow — the only paintable target: colour and label both survive;
- default visibility: each of Off / Hover / Always on a fresh placement, and
  that a sign loaded from a save is never touched;
- a dedicated server with a second client: labels work there at all (the
  prefab edit ran server-side), and text, visibility and the placing player's
  default reach the other client;
- with More Labels installed alongside: the signs' labels still behave as
  specified (see below).

## Not in this iteration

- **The uniting label mod.** What reuse of this design costs there depends on
  the object:
  - an object whose root is already a `WorldLabel` (More Labels' targets are,
    through `Chest` — directly for the terrarium, via `Table` for the rest)
    needs no component swap, only the text object and the entity data;
  - an object whose root is a plain `EntityMonoBehaviour` is expected to be
    one entry in the target list — shown so far for signs only;
  - anything else — the player grave, whose root is `PlayerGrave` — needs its
    own check that the swap is safe.

  One question has to be answered first: Gravestone Label attaches its own
  label component, so installing it beside a mod that covers the grave yields
  two labels and two interactions there. More Labels fills the vanilla
  `worldLabel` field for its own targets, so an overlap there would be a second
  text object on a field that holds one.
- **More Labels reaches these signs even now.** It patches
  `WorldLabel.UpdateWorldText` and `PlayerController.ManagedUpdate` globally
  (its `ShowOnHoverLogic`), so with it installed its hover option applies to
  every `WorldLabel` — the signs' labels included. Not a conflict to solve here,
  but a combination the tests cover.
- **The holoboards** — small, large and broken (`InfoBoardSmall` 5824,
  `InfoBoardLarge` 5825, `InfoBoardBroken` 5826), which players read as signs
  too. The user deferred them to the uniting mod. This design cannot take them
  as they are: their root classes are not empty (`Pug.Objects:3044-3080`) — all
  three play their break effects in `OnDeath`, and the small one picks its
  sprite variant in code — so swapping the root would lose that behaviour. They
  also draw with Unity `SpriteRenderer`s rather than `SpriteObject`s, which the
  hover outline relies on. A label there needs a component beside the original
  root, not in its place.
- A default for the three vanilla text signs and for chests.

## Identity

- Repo `sign-labels`, namespace `SignLabels`, display name "Sign Labels" —
  the three levels match.
- Dependency: Mod Settings Menu.
- mod.io type: Quality of Life.
- Personal-use, non-commercial (Pugstorm EULA), like every mod here.

## Deliverables beyond the scaffold

- The three traps go into the handbook — trap 1 and 2 into
  `docs/ck/prefabs-and-rendering.md`, trap 3 into
  `docs/ck/database-and-baking.md` — so the next mod does not rediscover them.
- The spike repo is deleted once this mod reproduces its results.
