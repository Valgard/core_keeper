# Make the cattle box reusable by granting one on release, not by suppressing the consume

## Context and Problem Statement

Core Keeper's Cattle Transport Box is single-use: catching an animal eats the
box, and nothing gives it back. A mod that makes it reusable has to intervene
somewhere in that round trip, and the obvious place — the consume — turns out
not to exist in the form the name suggests.

There is no "filled box" item. `CageCattle` destroys the animal entity, spawns
a dropped item that carries the animal itself as an `ObjectType.Creature` item,
and consumes the empty box. What the player then holds is the animal; the box is
already gone. Releasing the animal consumes *that* item and spawns the creature.

## Decision Drivers

- The refund has to land where the player expects the box back, which is the
  release, not the capture.
- The game is modded through a load-time compiled source mod, so every
  intervention costs either a data patch (cheap, declarative) or a Harmony patch
  into Burst-compiled DOTS code (expensive, and silently inert when done wrong).
- Nothing may change the capture flow, the animal's auxiliary data, or the
  crafting recipe.

## Considered Options

1. Grant one empty box additively when the animal is released
2. Suppress the consume at capture, so the box is never eaten
3. Emit the box from the data-driven loot path, with no code patch at all

## Decision Outcome

**Option 1.** A Harmony postfix on `PlaceObjectSlot.PlaceItem` adds one
`ObjectID.CattleCage` to the placing player's inventory buffer when a cattle
release commits. The vanilla consume is left untouched, which is what makes the
change additive: with the mod disabled or absent, the vanilla single-use
behaviour is what runs.

### Consequences

- Good: the mod touches one call site and no vanilla logic, so it cannot corrupt
  a capture or lose an animal's auxiliary data.
- Good: the refund is switchable at runtime, because an additive patch has
  nothing to undo — the postfix returns early and vanilla behaviour resumes.
- Bad: a code patch into Burst-compiled DOTS code was unavoidable, and the
  target sits inside a nested job rather than in a system's `OnUpdate`. That
  needs `DisableBurstForSystemAndJobs`; with the plain variant the postfix binds
  and never fires, and both Harmony and the loader log look perfect.
- Bad: the design named the wrong patch target. It was planned against the
  system that performs the capture; what the release actually runs through is
  `PlaceObjectSlot.PlaceItem`, found by tracing call sites during
  implementation rather than by reading the method that sounded right.

## Pros and Cons of the Options

### Grant one box additively on release

- Good: additive, so the vanilla path stays intact and the feature is a toggle.
- Bad: needs the Burst treatment and a correctly identified nested-job target.

### Suppress the consume at capture

- Bad: there is nothing to suppress at the moment the player would notice. The
  box is consumed at capture and the animal travels as a creature item, so
  suppressing it hands the player a box *and* an animal, which is a different
  feature.

### Emit the box from the data-driven loot path

- Good: a pure CoreLib data patch, no Harmony, no Burst, no code.
- Bad: tested and rejected. `SpawnsItemsOnUseCD` / `OpenItemAndSpawnLoot` is not
  reached when an item is *placed*, so that path cannot dispense anything at
  placement time.

## More Information

The raw design spec this distils is in the commit that deleted it:

~~~
git show "$(git rev-list -1 HEAD -- docs/specs/2026-06-24-reusable-cattle-box-design.md)^:docs/specs/2026-06-24-reusable-cattle-box-design.md"
~~~

Read it as a record of what was planned, not of what holds: it names the patch
target wrongly, and its scaffolding section predates `utils/new_mod.py`.

The measured mechanism — both consume sites with their citations, the detection
rule, and the dead end of the data-only path — is [`docs/ck/world-and-mechanics.md`](../ck/world-and-mechanics.md),
section "The cattle cage is consumed at two points"; the handbook is also where
it is kept current, which is why no line number appears above. How the patch is
built, why it needs the `AndJobs` variant, and how the refund is gated on a
committed placement is the mod's own `reusable-cattle-box/CLAUDE.md`.
