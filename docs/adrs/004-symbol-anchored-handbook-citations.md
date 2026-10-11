# Anchor handbook citations on a named element, not on an absolute decompile line

## Context and Problem Statement

The handbook in `docs/ck/` argues from the decompiled game source and cites it
by line: `` `Pug.Other:NNNNNN` ``. A game update renumbers those lines, so every
citation below an edit points somewhere new. `utils/relocate_citations.py` finds
each one again by the text recorded in `utils/ck-citation-snapshot.json`, which
makes the form affordable — but the repair is the cost. One 1.3.0.6 hotfix
rewrote some 320 lines across nine chapters, and `harmony-and-ecs` lost its
verification tick to a diff of 31 changed lines of which 31 were citation
numbers and none was prose.

So the defect was not fragility. It was that the most densely cited chapters —
the best-worked ones — are the ones an update disturbs most, and that
maintaining the numbers is itself a source of error: one commit shifted four
citations by two lines while editing something else, and only the final review
caught it.

## Decision Drivers

- A citation must survive the changes an update actually makes, which are
  overwhelmingly outside the element the sentence is about.
- Every claim checkable today stays checkable: the recorded-text comparison is
  kept rather than traded for a tidier notation.
- No gate may turn red on correct documentation. The citation checks run over
  the whole repository whenever any `.md` is staged, so a blocking cosmetic
  finding would stop commits nowhere near `docs/ck/`.
- "Nothing is known about this file" must stay distinguishable from "this file
  declares nothing", or an open boundary becomes a silent verdict.

## Considered Options

1. Keep the absolute line and invest in the relocation tooling
2. A symbol name alone, with no line
3. A symbol plus a line counted from it, in three tiers
4. Class-relative line counting for every citation

## Decision Outcome

**Option 3**, following sibling project `salesbuddy`'s ADR 0042: what a citation
*names* is separate from where it *points*. Five forms and no others —
`` `Assembly:Class:member:N` ``, the same with an `N-M` range, the element or the
type alone, and `` `Assembly:N` `` as an escape hatch. The member is spelled as
the decompile spells it, shortened to the shortest form unique within its type,
with `…` marking an elided parameter.

A line anchors to the innermost thing that names it: the member, else the type,
else nothing. The type tier carries the weakness that kills option 4 —
`PlayerController` is some 7,600 lines — which is why it is a fallback for the
citations with no member to name and not the scheme. The escape hatch is
permitted only where no type encloses the line, which the checker decides by
reading the file: six citations in the handbook, five at namespace level in
`Unity.Entities` and one `.prefab` that is not C# at all.

What the elements are comes from `utils/decompile_structure.py`, a tree-sitter
index over the decompile, cached outside the repository under a key of the
file's own identity. `describe` is the single judge of "shortest unique" — the
style checker calls it rather than re-deciding, because ADR 0042 records what
two implementations judging one claim cost there. `locate` is its permissive
inverse, so a verbose but valid citation still resolves.

### Consequences

- Good: an anchored citation survives every change outside its element. Of the
  159 citations the motivating hotfix renumbered, every one was anchorable and
  none needed the escape hatch.
- Good: a third drift outcome exists that absolute lines cannot produce. A
  renamed or removed member stops resolving and says so, where a line number
  went on pointing at whatever moved into its place.
- Good: the notation makes a wrong citation visible. A citation that reads
  "line 17 of this member" on a sentence about the member's declaration can be
  doubted without opening the file, where a bare number said nothing checkable
  — two such mismatches surfaced in `docs/roadmap.md` the day its citations
  were anchored, one of them sixteen lines out.
- Bad: `tree-sitter` and `tree-sitter-c-sharp` become ordinary pinned
  dependencies, because one consumer is a pre-commit hook and an extra would
  make that gate's behaviour depend on how the environment was installed. An
  exact pin, since a grammar release that re-shaped one node would move every
  citation inside it silently.
- Bad: an anchored citation runs some 40 characters longer, which forced two
  tools to change. `utils/check_docs_wrapping.py` had to learn that a citation
  is one unbreakable token — 41 of 809 carry a space, and breaking one makes it
  invisible to every pattern at once — and `utils/verify_status.py` had to
  compare normalised *words* instead of lines, because the rewrap the extra
  length forces reads as 429 added and 299 deleted lines where no word moved.
- Neutral: the migration runs chapter by chapter inside each chapter's
  verification pass, so the handbook carries both notations meanwhile. Four
  files and 253 citations are anchored; ten chapters and 624 occurrences are
  not. `relocate_citations.py` keeps serving those and names how many it
  skipped, so its workload is not read as a progress counter.
- Neutral: the convention reaches further than the tooling. Seven mod
  repositories carry decompile citations with no gate at all, where the notation
  is the only thing that survives an update.

## Pros and Cons of the Options

### Keep the absolute line and invest in the relocation tooling

- Good: no new vocabulary, and the tool already finds 722 of 722 recorded
  snippets after an update.
- Bad: misses the goal. The numbers keep churning, the ticks keep falling, and
  the repair keeps producing fresh errors of its own.
- Bad: a rename is invisible to it. Recorded text cannot catch a method that was
  renamed, and the game code renames itself between versions.

### A symbol name alone

- Good: survives any renumbering, and reads well in prose.
- Bad: imprecise, measured over this corpus with the real parser — a median
  search space of 36 lines, and a quarter of all citations located only to
  within more than 100. `salesbuddy` measured 49 and 25 % and reached the same
  conclusion.

### Class-relative line counting for every citation

- Good: one rule, no tiers, nothing to decide per citation.
- Bad: the search space explodes exactly where it is already large.
  `PlayerController.CanConsumeEntityInSlot` would be line 3,687 of 7,598.

### Finer forms that were weighed and dropped

- Arity (`member/2`) separates none of the three real overload groups here;
  their collisions are `(3, 3)`, `(2, 4, 4)` and `(1, 1)`, differing in types.
- An ordinal (`member#2`) is opaque to a reader, who would have to count
  occurrences in a 460,000-line file, and it moves when an overload is added
  above it.
- The first parameter type alone reads as a complete one-parameter list, which
  is misleading rather than merely short.
- The full parameter list, never truncated, has a longest instance of 337
  characters — which the repository's own wrapping gate would reject as
  uncommittable.
- A committed element index means 57,399 members for `Pug.Other` alone, and a
  stale index anchors citations wrongly in silence: the most expensive failure
  available.
- Roslyn as the index generator adds a second source of truth to keep in step,
  plus `dotnet` and MSBuild on every documentation commit.

## More Information

The raw design spec this distils, with the measurement behind every rejection
above, is in the commit that deleted it:

~~~
git show "$(git rev-list -1 HEAD -- docs/specs/2026-10-10-symbol-anchored-citations-design.md)^:docs/specs/2026-10-10-symbol-anchored-citations-design.md"
~~~

The rule as a handbook reader meets it is [`docs/ck/reverse-engineering.md`](../ck/reverse-engineering.md),
section "Line citations carry their assembly"; how a verification pass anchors
its chapter is the `ck-verify-chapter` skill. The prior art is `salesbuddy`'s
`docs/adr/0042-separate-what-a-citation-names-from-where-it-points.md`.
