# Reuse the game's sign window for labels, and let a missing mod fail the check rather than diverge

## Context and Problem Statement

Three of Core Keeper's signs can carry a label. The placeable arrow and the
other decorative signs cannot, so a player who wants a waypoint has to stand a
text sign next to the arrow. Two community mods add labels to other objects —
mannequins, aquariums, pedestals, the player grave — and neither touches signs.

Adding a label to an object needs three things: somewhere for the text to live
on the entity, a way for the player to enter it, and a rule for when it is
shown. Each of those has an obvious build-it answer and a less obvious
reuse-it answer.

## Decision Drivers

- The text has to survive a reload and reach other players, which makes it
  entity data rather than client state.
- Whatever enters the text should behave like the rest of the game — controller
  input, the profanity filter, the visibility toggle — because a label window
  that behaves differently from the game's own is worse than no window.
- A later mod is meant to unite the label mods, so nothing here should be
  shaped so that it cannot be reused.

## Considered Options

1. Build an own text-entry dialog, as the grave-label mod does
2. Reuse the game's own sign window
3. Type checks in code to decide which objects get a label, rather than a list

## Decision Outcome

**Option 2, with the target objects as data.** A spike on one sign proved in
the running game that the game's sign window can be opened for an object that
is not a text sign: the window appears, the text and the visibility setting
survive a reload, the label renders in the right place, and every pooled
instance carries the modified prefab.

The seven target ids sit in a list rather than in type checks, so the uniting
mod can take the list. Visibility works exactly as it does for text signs and
chests, through the game's own per-sign toggle.

The mod declares itself required on both sides, and the consequence is chosen
rather than tolerated. **Server:** the bake-time converter adds the description
buffer and the interaction components to the server-side entity, so without
the mod there the text has nowhere to live. **Client:** that flag makes the
server announce the mod as required, and a client without it is turned away at
its mod check. Being turned away is the intended outcome — the alternative is
letting that client in with a different ghost component layout for these
signs, which nothing here has tested and which the mod check exists to prevent.

### Consequences

- Good: controller support, the filter, the visibility toggle and handling the
  player already knows all come for free, and none of it has to be maintained.
- Good: a labelled sign is indistinguishable from a text sign in use, which is
  the whole point.
- Good: the target list is one entry per further plain object, so the uniting
  mod is cheap for anything shaped like these signs.
- Bad: a player joining a server that runs this mod must install it, and a
  player on a server without it gets no labels. That is a hard failure by
  choice, and the reason is that the silent alternative diverges a ghost
  layout.
- Bad: **the default-visibility option is an extension beyond vanilla.**
  Vanilla has no default — a placed object simply carries the field that is a
  stack size elsewhere — so with the option set to anything but the vanilla
  behaviour, a labelled arrow and a text sign placed side by side start
  differently. Weighed and accepted, because it saves a click per waypoint for
  players who want labels always visible.
- Neutral: seven object ids ride on five graphical prefabs, because two pairs
  share one. The list is of ids; the edits are per prefab.

## Pros and Cons of the Options

### An own text-entry dialog

- Good: complete control over layout and behaviour, and no dependency on a
  vanilla window keeping its shape.
- Bad: it rebuilds controller navigation, the filter and the visibility toggle,
  and the rebuild is worse than the original at each of them.
- Bad: the result looks and feels like a mod, where the goal is a sign that
  behaves like a sign.

### Reuse the game's sign window

- Good: everything above comes with it, and the behaviour cannot drift from the
  game's.
- Bad: it depends on a vanilla window being reusable for an object it was not
  written for — which is why a throwaway spike proved it in the running game
  before the design committed to it.

### Type checks instead of a list

- Good: no list to keep, and a new object is covered the moment it matches.
- Bad: a type check is not reusable by the uniting mod, and it decides by
  accident of class rather than by intent.

## More Information

The raw design spec this distils is in the commit that deleted it:

~~~
git show "$(git rev-list -1 HEAD -- docs/specs/2026-09-30-sign-labels-design.md)^:docs/specs/2026-09-30-sign-labels-design.md"
~~~

It quotes the originating decisions verbatim, lists the three traps the spike
surfaced, and records what the running game had and had not confirmed at the
time of writing.

How a vanilla graphical prefab is edited at bake time — including that several
objects can share one — is [`docs/ck/prefabs-and-rendering.md`](../ck/prefabs-and-rendering.md); why a mod-set
mismatch surfaces as a version mismatch at the mod check is [`docs/ck/multiplayer-and-server.md`](../ck/multiplayer-and-server.md).
The mod's own working rules and the mechanics of the default's predicted spawn
are in `sign-labels/CLAUDE.md`.
