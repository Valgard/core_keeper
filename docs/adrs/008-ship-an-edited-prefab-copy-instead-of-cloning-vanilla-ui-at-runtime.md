# Ship an edited prefab copy of a vanilla widget rather than clone it at runtime

## Context and Problem Statement

Core Keeper shows world coordinates in one place: the map view, where the
numbers follow the mouse cursor rather than the player, and reading your own
position means opening the map, moving the cursor onto your own marker, reading
it and closing again. A permanent HUD readout removes all four steps, and the
game already contains a widget that renders exactly that pair of numbers.

So the question was how to get that widget into the HUD: instantiate the live
one at run time, or copy its subtree into the mod as an own prefab and edit it
in the Editor.

## Decision Drivers

- The readout must be positioned, sized, faded and layered to sit in the HUD
  without colliding with what is already there, and those are values nobody
  gets right on the first attempt.
- Whatever the mod ships must not carry vanilla *assets*; a subtree of
  components and text objects is not an asset, a sprite or a font would be.
- A HUD element that can be hidden has to be able to come back, which is a
  structural property of the prefab rather than a runtime decision.

## Considered Options

1. `Instantiate` the live widget at run time and fix it up in code
2. Copy its subtree into the mod as an own prefab and edit it in the Editor

## Decision Outcome

**Option 2.** The mod ships its own prefab, copied from the vanilla
coordinates widget's subtree and edited once in the Editor. The inherited
component that writes the *cursor* position is removed there, the layer, depth
and alignment are set there, and the objects the HUD does not need are deleted
there — rather than being undone in code on every game start.

### Consequences

- Good: the calibration loop collapses. Anchor, alpha, sorting order and
  alignment are trial-and-error values; in the Editor each round is seconds,
  and in code each round is a build plus a game launch. This workspace has
  repeatedly lost time to exactly that loop.
- Good: every fix-up the runtime path would need on each start — finding the
  source in the vanilla hierarchy, disabling the inherited component before its
  own update writes the cursor position into the same texts, setting the layer
  recursively, setting depth, clearing and destroying two objects, flipping the
  alignment, positioning — is baked in instead of re-run.
- Good: the runtime-resolve risk disappears with the clone. There is no
  hierarchy to find and no component to race.
- Bad: the prefab is a snapshot. If the vanilla widget changes shape in an
  update, the copy keeps the old shape and nothing says so — where a runtime
  clone would have inherited the change, for better or worse.
- Neutral: the one argument that favoured cloning — shipping no vanilla content
  — does not apply, because the copied subtree carries no assets.

## Pros and Cons of the Options

### Clone the live widget at run time

- Good: nothing vanilla is shipped, and the widget cannot go stale against the
  game.
- Bad: every property that makes it fit the HUD has to be re-applied on each
  start, in code, in the right order, including suppressing the inherited
  behaviour that would otherwise overwrite the display.
- Bad: each calibration round costs a build and a launch.

### Copy the subtree into an own prefab

- Good: the shape is fixed once, visibly, in the tool built for it.
- Bad: a snapshot that can drift from the original in silence.

## More Information

The raw design spec this distils is in the commit that deleted it:

~~~
git show "$(git rev-list -1 HEAD -- docs/specs/2026-08-05-player-coordinates-hud-design.md)^:docs/specs/2026-08-05-player-coordinates-hud-design.md"
~~~

It lists the values read off the original, the Editor edits to make on the copy,
and two features deferred rather than dropped: a rebindable show/hide key and
the corner as a setting.

Why the component that decides visibility must sit on an always-active object,
with the `root` → `hudRoot` → contents shape that follows, is [`docs/ck/prefabs-and-rendering.md`](../ck/prefabs-and-rendering.md);
the mod's own wiring and the constants read off the vanilla prefab are in
`player-coordinates-hud/CLAUDE.md`.
