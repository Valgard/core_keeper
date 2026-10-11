# Let the game decide where a rail may go, by extending its permission rather than testing tiles

## Context and Problem Statement

Core Keeper lays a bridge automatically when a wall is built across a pit: the
player carries bridges, builds the wall, and the bridge appears underneath. The
same does not happen for rails, so crossing a pit with a rail means placing the
bridge by hand, tile by tile, and the asymmetry is pure friction.

Making the rail behave like the wall needs the game to consider a rail
*placeable* on a pit at all, and that is a permission question rather than a
behaviour question.

## Decision Drivers

- Which tiles a bridge may be built on is not derivable by reading the
  decompiled code: it is data in the baked object database, and one tile's
  permission does not imply another's.
- A game update that adds a bridge type or a new bridgeable tile should be
  inherited rather than chased.
- The player must not be able to lay a rail they cannot pay for, and must not
  be charged twice.

## Considered Options

1. Enumerate the bridgeable tiles in the mod and test for them
2. Borrow the bridge's own permission and let the vanilla check decide

## Decision Outcome

**Option 2.** The mod never tests for a pit, water or lava. It makes the rail
carry the same placement permission a bridge carries, and the game's own check
then answers where a rail may go. Wherever a bridge may be built, a rail may be
too — including on tiles and bridge types a later update adds.

Bridges come from the player's inventory only, never from a chest, and the gate
is a carried bridge: no bridge, no placement. Tearing a rail up leaves the
bridge behind, because the two are independent tiles and a rollback would
destroy something the player may want.

### Consequences

- Good: the question nobody could answer from the code — whether bridges are
  allowed over water or lava — never has to be answered. It is data, and the
  data is consulted by the game.
- Good: new bridgeable tiles and new bridge types are free.
- Bad: **the mechanism this decision was designed around does not exist, and
  the first implementation was dead code.** The design assumed a bridge carries
  boolean placement flags that could be copied onto the held rail. Measured
  in-game, those flags read false on a real wooden bridge, both on the database
  prefab and while it is equipped. The permission actually lives in an
  allow-list of object ids on the prefab, which the game consults through a
  second, independent branch of its placement check. The hook built on the
  flags therefore never fired — and because its guard gated the two hooks after
  it, those were unreachable as well, while the build was green and the loader
  log clean.
- Bad: the correction moves the intervention to bake time. Permission has to
  exist *before* placement runs, because the placement path returns early when
  permission is false, so no hook can justify a placement after the fact. What
  ships is a prefix on the database post-conversion that adds the two tile ids
  to the rail's own allow-list, which means the mod now edits baked data rather
  than reacting to an event.
- Neutral: the decision survived its mechanism. "Borrow the permission, do not
  enumerate tiles" is still exactly what the shipped mod does; only the place
  where the borrowing happens changed.

## Pros and Cons of the Options

### Enumerate the bridgeable tiles

- Good: no dependency on how the game expresses permission, and trivially
  debuggable — the list is right there.
- Bad: the list cannot be derived from the code, so it would have to be
  measured and then maintained against every update.
- Bad: it answers a question the game already answers, and answers it worse.

### Borrow the permission

- Good: one source of truth, inherited updates, and no tile list to keep.
- Bad: it depends on finding *where* permission lives — and the first answer
  was wrong in a way that produced silent dead code rather than a failure.

## More Information

The raw design spec this distils is in the commit that deleted it:

~~~
git show "$(git rev-list -1 HEAD -- docs/specs/2026-08-08-auto-rail-bridges-design.md)^:docs/specs/2026-08-08-auto-rail-bridges-design.md"
~~~

It carries its own superseding note at the top, written after implementation,
and the three-hook design the flags assumption produced. Read the hooks, the
double-debit protection and the tile ordering as shipping; read the permission
mechanism as refuted. Its pointer to a plan workspace is dead — that directory
was scratch and is gone.

How placement permission really works — the two crossed property hashes, the
allow list and its measured contents — is [`docs/ck/world-and-mechanics.md`](../ck/world-and-mechanics.md);
the bake-time patch, which tick it takes effect on, and what has not been
measured about it are in `auto-rail-bridges/CLAUDE.md`.
