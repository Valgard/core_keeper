# Replace the tiny font passively, and keep the mod that does it dependency-free

## Context and Problem Statement

Core Keeper's smallest face carries 114 codepoints: no German umlauts, no
accents, no Cyrillic. A missing character does not fail — the font lookup falls
back to the CJK face, which renders it in CJK metric, deformed, with no warning
anywhere. Any mod whose UI uses that face inherits the problem.

One mod had worked around it by injecting its own glyphs at run time from its
own sheet. Then the hand-drawn master became a *complete* face — all 331
codepoints, reviewed defect-free — at which point a complete font was no longer
one mod's implementation detail.

## Decision Drivers

- Every mod with chrome in that face should benefit, not just the one that drew
  the glyphs.
- A font sits underneath other UI: whatever ships it may end up as the bottom
  layer of a dependency chain.
- The style must stay coherent. Mixing hand-drawn and vanilla glyphs of the
  same face is visible — a six-pixel `A` beside a five-pixel `Ä`.

## Considered Options

1. Keep the glyph injection inside the consuming mod
2. A font mod with a registration API that consumers call
3. A font mod that replaces the face passively, with no API and no dependencies

## Decision Outcome

**Option 3.** The mod replaces the face on load and exposes nothing. The
replacement is a side effect on a global singleton, so a consumer does not call
anything — it simply gets correct glyphs. Full replacement of all 331
codepoints is fixed rather than configurable.

The mechanism is a swap rather than an append: the complete build *is* a font
resource with its own atlas geometry, not a patch set, so swapping the texture
and glyph data and letting the game run its own codepoint initialisation
applies the game's sprite conventions instead of the mod reproducing them.

### Consequences

- Good: no API means no customer to support and nothing to version. A
  registration framework would have had no caller anyway — the other two faces
  in use are already complete, so exactly one face is deficient.
- Good: **the mod takes no dependencies at all**, which is the point of fixing
  the replacement rather than offering a toggle. A toggle needs a settings
  framework, and a font is potentially the bottom layer other UI mods depend
  on; taking the settings mod as a dependency here would foreclose that mod
  ever depending on the font.
- Good: a fixed full replacement cannot produce the mixed-metric style break
  that "only the missing glyphs" would.
- Bad: a consumer that needs the complete face has to declare a hard
  dependency to get a guaranteed load order, which means a user who installs
  the consumer alone gets a refusal rather than a degraded face.
- Neutral: the mod is named for its effect rather than for the engine's name
  for the face, which is the family convention; the precise face and atlas
  names go in the first line of the description, where full-text search finds
  them.

## Pros and Cons of the Options

### Keep the injection in the consuming mod

- Good: no new mod, no new dependency, and it already worked.
- Bad: every other mod using that face keeps the deformed fallback, and a
  second mod wanting correct glyphs would inject its own copy.

### A font mod with a registration API

- Good: explicit, and a consumer could ask for a subset.
- Bad: no caller. One face is deficient and the others are complete, so the
  API would exist to be called by nobody.
- Bad: an API is a promise that outlives the problem it was built for.

### Passive replacement, no API, no dependencies

- Good: consumers need no code at all, and the mod can sit at the bottom of
  any dependency chain.
- Bad: a side effect on a global singleton is invisible — nothing in a
  consumer's source says where its glyphs come from.

## More Information

The raw design spec this distils is in the commit that deleted it:

~~~
git show "$(git rev-list -1 HEAD -- docs/specs/2026-08-11-complete-tiny-font-design.md)^:docs/specs/2026-08-11-complete-tiny-font-design.md"
~~~

It carries the five numbered decisions with their rationales, the verified
metrics behind the swap, and the consuming mod's own change.

The faces, their atlases, their codepoint counts and which charset each uses are [`docs/ck/prefabs-and-rendering.md`](../ck/prefabs-and-rendering.md);
how a missing character crashes or deforms is [`docs/ck/ui-framework.md`](../ck/ui-framework.md). Where
the swap is applied, why the first call site was the wrong one, and the guard
that refuses a mismatched atlas are in `complete-tiny-font/CLAUDE.md`.
