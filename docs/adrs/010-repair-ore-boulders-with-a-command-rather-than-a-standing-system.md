# Repair worn ore boulders with a command, leaving permanent protection to the mod that has it

## Context and Problem Statement

An ore boulder has no separate "remaining ore" counter — its remaining yield
*is* its health, and every pickaxe swing and drill tick takes from it. At zero
the boulder is destroyed and gone.

A third-party mod normally prevents that, but it moved to a new mod.io id and
stopped loading for a while. With a drill-speed mod active, several boulders
were worn close to zero in that window — and the third-party mod would not have
recovered them anyway: it heals only below a tenth of maximum, so a boulder
sitting at a third stays damaged until further mining pushes it under the
threshold.

So what was missing is not protection. It is a way to top up boulders that are
already damaged, once, on demand.

## Decision Drivers

- Whatever is built must not duplicate the third-party mod that is coming back,
  because two mods holding the same value is a conflict waiting for a tick
  order.
- The selection must be the ore boulders and nothing else, without a list of
  object ids to maintain against every update.
- A repair tool must never be a reason a player cannot join a server.

## Considered Options

1. A standing system that holds every boulder at full health
2. A chat command that tops up what is loaded, once per invocation

## Decision Outcome

**Option 2.** `/refillboulders` sets every loaded boulder's health to its
maximum, skipping the ones already full and the ones at zero, which are
mid-destruction. Everything currently loaded is in scope; the sender's position
is not used, so there is no radius to explain or tune.

Boulders are selected by the component the game itself uses to mark a
drill-requiring destructible, not by an object-id list. Exactly one converter
hands that component out, which makes the component the definition rather than
a proxy for one — verified against the unpacked prefabs rather than assumed.

The mod declares itself required on neither side, so it can never be the reason
a connection is refused.

### Consequences

- Good: no overlap with the third-party mod. This one repairs; that one
  protects, and when it loads again nothing has to be turned off here.
- Good: the selection inherits new boulder types for free and needs no
  maintenance when object ids change.
- Bad: the command does not stop consumption. Boulders keep being worn down —
  at eleven times vanilla speed with the drill mod active — so during an outage
  of the protecting mod this is a repeated manual action, not a fix.
- Neutral: a one-off command has no state, so there is nothing to persist, no
  tick cost, and nothing to reconcile between client and server.

## Pros and Cons of the Options

### A standing system holding boulders full

- Good: subsumes both repair and protection, so one mod would do everything.
- Bad: it duplicates the third-party mod exactly, and two systems writing the
  same health value fight over tick order.
- Bad: it would need to run on the server and therefore gate connections,
  where a command needs nothing of the sort.

### A chat command

- Good: stateless, cheap, and scoped to the problem that actually existed.
- Bad: manual and repeatable rather than automatic — the player has to know to
  run it.

## More Information

The raw design spec this distils is in the commit that deleted it:

~~~
git show "$(git rev-list -1 HEAD -- docs/specs/2026-08-08-refill-ore-boulders-design.md)^:docs/specs/2026-08-08-refill-ore-boulders-design.md"
~~~

Why the drill-requiring component is exactly the ore boulders, with the single
converter that hands it out, is [`docs/ck/world-and-mechanics.md`](../ck/world-and-mechanics.md); the query and
the command registration are in `refill-ore-boulders/CLAUDE.md`.
