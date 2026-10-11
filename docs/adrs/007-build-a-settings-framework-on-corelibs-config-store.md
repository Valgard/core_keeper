# Build a settings framework on CoreLib's config store rather than adopt the existing menu

## Context and Problem Statement

Mods here hardcoded their tunables. The load-time sandbox forbids `System.IO`,
so a config value lived as a literal in a `ModConfig` singleton and changing one
meant a rebuild. Neither the SDK nor CoreLib offers an in-game settings screen,
and the player-facing consequence is that nothing a mod does is adjustable.

Something already existed. "General Mod Config Menu" reads CoreLib config files
and mounts an entry in the game's settings, with 53,000 subscribers — so the
question was not whether to write a settings UI, but whether to write *another*
one.

## Decision Drivers

- A consumer mod must declare only what it needs. If using the framework costs
  more than hardcoding a literal, nobody uses it.
- Nothing may require `skipSafetyChecks`: that flag turns off the sandbox
  wholesale and changes the mod's published access type.
- A value must survive a restart and be readable live, with no apply step.
- Labels must be localisable through the pattern the other mods already use.

## Considered Options

1. Adopt the existing menu as our settings UI and feed it
2. Let each mod build its own menu, which is what the ecosystem actually does
3. Build a framework mod with our own UI on CoreLib's config store

## Decision Outcome

**Option 3.** `mod-settings-menu` is a published framework mod. A consumer
declares its settings in one declarative chain in `IMod.Init()` and gets typed
handles back; the framework owns the menu entry, the layout, the widget prefabs
and the persistence. Labels and hints come from terms derived from the setting
key, so the builder takes no label argument, and they resolve through the same
YAML-to-`TextDataBlock` pipeline every other mod here uses — not through
CoreLib's own localisation module, which is deprecated in its own source.

The existing menu is adopted as a **technical reference** rather than as the UI.
Its menu-mount technique is the one worth copying: a prefix on the menu
manager's initialisation clones the options entry on the *prefab*, which is
cleaner than patching the instance. So are its own-prefab screen, the engine's
linear-layout component for vertical stacking — which removed the hand-rolled
box stacking that was this design's largest UI risk — and its
template-instantiate-and-bind rendering. Its RPC layer for server-to-client
config sync, the bulk of its source, is skipped: these are client settings.

### Consequences

- Good: a consumer mod's settings cost one chain in `Init()` and read live
  through a handle, with no file API anywhere in its own sources, so the
  sandbox stays on.
- Good: because the backend is the shared CoreLib config store, a consumer is
  configurable in *both* menus at once, on the shared foundation rather than in
  competition.
- Bad: that shared foundation is also a shared failure. The other menu turns
  the config store's save-on-set off across every registered config, including
  from the main menu, so with both installed a change made here is lost
  silently. The design recorded the dual visibility as a bonus and did not
  foresee that the same coupling runs the other way; the workaround is to
  disable the other menu, and a real fix is on this mod's roadmap.
- Bad: consumers take a hard dependency on two mods rather than none, and a
  framework's API is a promise — the declarative chain cannot change shape
  without breaking every consumer.
- Neutral: the ecosystem's mainstream remains "each mod its own menu". Of 26
  installed mods measured at the time, exactly one fed the existing menu, and
  one polished popular mod deliberately built its own instead.

## Pros and Cons of the Options

### Adopt the existing menu

- Good: no UI to build, no prefabs, no mount patch, and an audience already
  has it installed.
- Bad: its UX is the wrong shape for this — a mod list that pages into a screen
  per mod, raw path-and-file keys as labels, unpolished rendering.
- Bad: no source repository and no screenshots, so adopting it as the UI means
  depending on something that can only be read by decompiling an installed
  copy.
- Bad: it would make every consumer's settings screen somebody else's design
  decision.

### Each mod builds its own menu

- Good: no dependency, and it is demonstrably what most of the ecosystem does.
- Bad: the mount patch, the prefabs and the persistence get written once per
  mod, and each copy is a place for the same UI bug to live.

### Build a framework on the shared config store

- Good: the declarative API keeps a consumer's cost at one chain, and the
  shared backend gives dual visibility for free.
- Bad: a framework is a standing obligation to its consumers, and it inherits
  whatever the shared backend does — including what another mod does to it.

## More Information

The raw design spec this distils is in the commit that deleted it:

~~~
git show "$(git rev-list -1 HEAD -- docs/specs/2026-06-29-mod-settings-menu-design.md)^:docs/specs/2026-06-29-mod-settings-menu-design.md"
~~~

It carries the landscape evaluation, the component table, the term convention
and the per-mod pilot tunables, and it predates the save-on-set collision above.

Why CoreLib's localisation module is avoided is [`docs/ck/localisation.md`](../ck/localisation.md); what
the config store costs and how a setting can silently fail to persist is [`docs/ck/persistence.md`](../ck/persistence.md).
The framework's own architecture, the consumer API and its gotchas are the mod's
`mod-settings-menu/CLAUDE.md`, with a tutorial beside it.
