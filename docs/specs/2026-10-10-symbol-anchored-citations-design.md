# Symbol-anchored citations for `docs/ck/`

Replace the handbook's absolute decompile line numbers with citations anchored
on a named element and a line relative to it, so that a game update stops
rewriting the chapters.

## Context

A handbook citation is `` `Assembly:line` `` today — an absolute line in
`<Assembly>.decompiled.cs`. `utils/ck-citation-snapshot.json` records what each
cited line *says*, which is what makes the form affordable: after an update the
question "which citations now point at something else" is answered by comparing
text rather than by re-reading every claim. The rule and its reasoning are
`docs/ck/reverse-engineering.md`, section "Line citations carry their assembly".

Most of them do not break silently. `utils/relocate_citations.py` finds each
recorded snippet again in the regenerated tree and rewrites the number, and on
2026-10-09 it found all 722 of them. The exception is a rename, which recorded
text cannot catch — the drift checker section below returns to it. What costs is
the repair itself:

| Cost of one hotfix (commit `7788522`, 1.3.0.5 → 1.3.0.6) | |
|---|---|
| lines rewritten across nine chapters | ~320 |
| lines rewritten in the snapshot | 326 |
| verification ticks lost | 1 (`harmony-and-ecs`) |

`harmony-and-ecs` lost its tick to a diff of 31 changed lines of which **31 were
citation numbers and none were prose**. `utils/verify_status.py` counts them as
text written after the pass, which contradicts the `ck-verify-chapter` skill's
own sentence that relocating citations "moves the numbers, not the verdict".

So the defect is not fragility. It is that the handbook's most densely cited
chapters — the best-worked ones — are the ones a hotfix disturbs most, and that
maintaining the anchors is itself a source of error: commit `38a6394` shifted
four citations in the skill file by two lines while editing something else, and
only the final review caught it.

### Prior art

Sibling project `salesbuddy` settled the same problem in ADR 0042,
*Separate What a Code Citation Names from Where It Points* (2026-09-07, SB-709).
Its history is directly applicable: SB-649 had abolished absolute line numbers
after measuring that 29 anchors slipped at once on a rebase, that the checker
stayed silent on five of five wrong references because all fell inside the file,
and that the correction commit produced two fresh wrong anchors while fixing the
others. Its decisive argument was not that anchors drift — it was that
*maintaining them creates new errors as long as the form stays the same*.

Symbol names alone proved imprecise there (median 49 lines of search space, a
quarter over 100), which is why ADR 0042 is a hybrid: a named element plus a
line relative to it.

The handbook had never weighed symbol names at all. What its rule rejects is two
*abbreviations of the line form* — an assembly inherited from an earlier
sentence, and a tilde-marked approximate offset — and its own advice points the
same way this design does: "Cite a declaration, not a line inside a body" is a
symbol anchor stated in prose, with no notation to carry it. An earlier draft of
this document claimed the two projects had independently rejected each other's
choice. That symmetry is invented; only salesbuddy ever made the comparison.

Measured here with the tree-sitter index described below — not with the
prototypes, whose aggregates are unusable for the reason under "Known hazard in
the prototypes" — the imprecision is the same magnitude:

| Search space a symbol name alone leaves open | CK | salesbuddy |
|---|---|---|
| 1–10 lines | 23 % | 13 % |
| 11–30 | 24 % | 19 % |
| 31–50 | 14 % | 21 % |
| 51–100 | 14 % | 22 % |
| over 100 | 26 % | 25 % |
| median | 36 lines | 49 lines |

## Goal

After a hotfix, no anchored citation is rewritten and `verify_status.py` reports
unchanged ticks. 716 of the 722 citations can be anchored; the six that cannot
are enumerated under "Three tiers of anchor" and keep an absolute line, so
"`git diff` is empty" is the wrong way to say it.

### Success criteria

- A citation survives any decompile change outside the element it names. One
  measured exception exists and is handled rather than denied: the shortest
  unique member form is a property of the whole enclosing type, so an added or
  removed overload changes what the minimal spelling would be. The gate
  therefore *reports* a non-minimal form and does not block on it — see
  `check_citation_style.py`.
- Every claim that is checkable today stays checkable: the recorded-text
  comparison is kept, not traded for convenience.
- `None` ("nothing is known about this file") stays distinct from an empty
  element list ("this file contains no elements"), so that an open boundary
  never becomes a silent verdict.

### Non-goals

- Making citations *correct*. This makes them durable. A citation nobody read
  is no better anchored for being re-spelled — see "Limits".
- Drift checking in the mod repositories (see "Reach").

## Decisions

| | |
|---|---|
| **Migration** | per chapter: mechanical where a verification pass has already run, inside the pass otherwise |
| **Notation** | ADR 0042's separation: anchor in the prose, location in the parenthesis |
| **Reach** | the convention everywhere; the tooling for `docs/ck/` only, apart from the syntactic half of the style check |
| **Structure knowledge** | derived from the decompile via tree-sitter, cached locally |

Reach is worth a sentence. Seven mod repositories carry 73 decompile citations,
52 of them in `complete-tools`, and no citation gate runs in any of them — the
style checker exits 0 when a checkout has no `docs/ck` chapters. Those citations
are therefore unverifiable in principle: nothing ever recorded what they pointed
at. In the handbook, tooling compensates for a fragile notation; in a mod repo
there is no tooling, so the notation is all there is. A symbol anchor survives an
update by itself, which is why the convention reaches further than the tools.

## The notation

The anchor states what is meant and stays in the prose; the parenthesis states
where it stands. The first field is the assembly, prefixed `DedicatedServer/`
for the server build.

```
`Assembly:Class:member:7`       7th line of the element, 1-based
`Assembly:Class:member:7-12`    a range inside the element
`Assembly:Class:member`         the element as a whole
`Assembly:Class`                the type as a whole
`Assembly:7`                    escape hatch
```

The separation carries weight rather than being cosmetic: an anchor may name
something the file does not define at all. The handbook cites log strings
(`` logs `Not enough SimpleCraftingUIs…` ``) and fields at their point of use
(`` `accumulatedDropChance`, precomputed ``); neither can double as a counting
point. Ranges become relative, which also makes them sturdier — an absolute
range can move at one end while the other holds, a relative one travels with
its element.

### Naming the member — shortest unique form

The checker enforces the shortest form that is unique, and reports a longer one
as a finding so the notation does not grow verbose out of caution.

| Form | Citations | Rule |
|---|---|---|
| `member` | 673 (93 %) | the name is unique within its type |
| `member(T1, …)` | 43 (6 %) | shortest unique **prefix** of the parameter type list; `…` marks every omission |
| `member(T1, T2, T3)` | — | no ellipsis when the prefix is the whole list |
| `member(ref T1, …)` | 0 today | modifiers only where they are needed to disambiguate |
| `Interface<T>.member` | 0 today | explicit interface implementation, spelled as the decompile spells it |

Measured over the ambiguous citations: a one-type prefix suffices for 35, two
types for 7, and four types for 1. Parameter *names* never appear; modifiers
separate nothing in the current corpus.

**No citation lands in an explicit interface implementation today.** The rule is
carried regardless, because the hazard sits in the file rather than in the
corpus: the structure layer has to read the qualifier or it merges two real
members, as `RpcSerializer` below shows. An earlier draft of this table claimed
nine such citations. That figure counted ambiguity *groups* the qualifier
separates, not citations pointing into one.

**Citation counts here are per unique `assembly:line`, of which there are 722.**
Occurrence counts are higher — 800 at the time of writing — and mixing the two
is how an earlier draft reported 793 occurrences as "resolvable citations" and
then had to explain why its tables would not add up.

The ellipsis is what keeps this short. Without it the full list would be needed,
whose longest instance is 337 characters — `EvaluateConsumeResultJob.Execute`,
an `IJobEntity` whose parameter list *is* its query, with 14 components. With it,
that citation reads `Execute(Entity, …)`:

| Member specification | full list | shortest prefix |
|---|---|---|
| median | 43 characters | **29** |
| longest | **337** | **57** |
| over 60 characters | 13 | **0** |

### Three tiers of anchor

A line is anchored to the innermost thing that names it, and which tier it lands
in decides what the citation is exposed to. Measured over the 722 citations in
`docs/ck/`:

| Tier | Form | Citations | Exposed to |
|---|---|---|---|
| member | `Assembly:Class:member:N` | 660 | changes inside that member |
| type | `Assembly:Class:N` | 56 | changes inside that type |
| absolute | `Assembly:N` | 5 | any change above it in the file |
| unchecked | `Assembly:N` | 1 | nothing is checked |

The type tier carries exactly the weakness that kills "class-relative line
counting" under "Rejected alternatives": `PlayerController` is 7,598 lines, so a
type-anchored line is exposed to a great deal. As a fallback for 56 citations
that is worth having, because their only alternative is an absolute line. As a
scheme for all 722 it is not, which is why it is a tier and not the design.

The absolute tier is the escape hatch, permitted only where no type encloses the
line — which the checker decides by reading the file rather than from a list.
All five sit at namespace level in `Unity.Entities`: `Unity.Entities:10166`,
`:11024`, `:58169`, `:67217` and `:67551`. A Core Keeper hotfix cannot move
them, because it ships no new Unity; a Unity upgrade can, and the recorded text
still reports it when it does.

One citation is unchecked, and inherently so: `ControlMappingMenu.prefab:2459`
is not C#, the structure layer answers `None` for it, and no location check runs
there — not a lenient one, none.

CoreLib's `LocalizationModule.cs:132` is **not** in that group, which took two
measurements to establish. `check_citation_drift.resolve` already finds it by
globbing the CoreLib clone, so it is C#, it yields real elements, and it sits in
the member tier like any other citation. A first measurement put it here only
because it was taken through `relocate_citations.source_for`, which is the one
resolver that lacks that branch.

**Measured against the real hotfix, the tiers hold.** Of the 161 citations
commit `7788522` renumbered, 161 were anchorable and none was in the escape
hatch. That is one hotfix and not a law, but it is the case this design was
written for.

## The structure layer

```python
@dataclass(frozen=True)
class Element:
    type_name: str | None  # enclosing type; None at namespace level
    member: str | None  # spelled as the decompile spells it
    params: tuple[str, ...] | None  # parameter types; None for non-methods
    start: int  # 1-based
    end: int


@dataclass(frozen=True)
class Structure:
    elements: tuple[Element, ...]
    error_ranges: tuple[tuple[int, int], ...]


def structure_of(path: Path) -> Structure | None: ...
```

`member` carries an `Interface<T>.` qualifier where the decompile writes one
(see below). `params` is `None` for fields, properties and types rather than an
empty tuple, which a nullary method needs.

`None` means nothing is known about this file. `Structure(elements=())` means it
was parsed and contains no elements. The two must not be able to merge, which is
why the return type carries `| None` rather than an empty value.

The layer takes a **path**, not an assembly name. Nothing resolves an assembly
name to a path today, which an earlier draft of this document got wrong:
`check_citation_drift.resolve` returns the cited *lines*, and the function that
does return a path, `relocate_citations.source_for`, has no branch for CoreLib's
own source. Lifting a path resolver into the shared module is therefore part of
this work rather than something to build on. With a path in hand the special
cases disappear: a `.prefab` is not C# and yields `None`, CoreLib's
`LocalizationModule.cs` is C# and yields real elements, an unreadable path
yields `None`.

Error ranges are reported rather than swallowed, because a caller can only say
"I am not checking the location here" if it is told.

**The member name is read as the decompile writes it.** `RpcSerializer` carries
both `public void Serialize(…)` and
`void IRpcCommandSerializer<Rpc>.Serialize(…)` with identical parameter types,
which C# permits because the second name is interface-qualified. tree-sitter's
`name` field returns `Serialize` for both; the qualifier hangs off a separate
`explicit_interface_specifier` node. A layer that read only the name field would
merge two different members into one, and a citation to either would then be
measured against the other.

### Two directions, one canonical form

```python
def locate(s: Structure, c: Citation) -> int | None: ...  # citation -> line


def describe(s: Structure, line: int) -> Citation | None: ...  # line -> citation
```

`describe` is the only place that decides what "shortest unique" means. The
checker uses it for its messages, the migration uses it to write, and `locate`
is its inverse. ADR 0042 records the cost of letting two implementations judge
the same claim: *"both had to be taught to judge alike — they did not, twice,
before this was closed."* Here the consequence would be worse than there — a
verification pass would write citations that its own commit hook rejects, and
the natural response to a red gate over freshly anchored citations is to weaken
the gate.

### The cache

| | |
|---|---|
| Key | `(path, size, mtime_ns)` |
| Location | `~/.cache/ck-decompile-structure/`, overridable from `.envrc` |
| Contents | one serialized `Structure` per assembly, plus the build identity for diagnostics |

Measured cost without a cache: 7.8 s for the 25 cited assemblies (44.6 MB), of
which 5.6 s are the two 16 MB `Pug.Other` files. `Pug.Other` alone is 461,866
lines and parses in 2.7 s, yielding 57,399 members in a further 0.1 s.

The cache sits outside the repository because it describes the decompile rather
than the repository, and so that `git clean -fdx` does not cost 7.8 s. The key
is the **file's** identity and not the build's: a decompile regenerated without
a version change must not keep serving a stale index, and that is the one
failure this approach exists to avoid. The build identity is recorded beside
each entry for diagnostics, where it cannot weaken the key.

## The four tools

The governing change: today the absolute line is stored in the prose and the
recorded text is the check; afterwards the symbol is stored and the line is
derived.

### `check_citation_drift.py`

| | today | afterwards |
|---|---|---|
| snapshot key | `Assembly:line` | the citation, e.g. `Assembly:Class:member:7` |
| value | that line's text | the **resolved** line's text |
| check | compare text | resolve the symbol, then compare text |

This yields a third outcome that does not exist today:

| Result | Meaning |
|---|---|
| resolves, text identical | undisturbed |
| resolves, text differs | the cited code changed — re-check the claim |
| **does not resolve** | the class or member was renamed or removed |

The third is a genuine improvement. When a method is renamed today, the absolute
line still points somewhere: at best the checker reports a text change that
looks like a code edit, at worst the text still matches by coincidence and
nothing is reported. The handbook cites game code that renames itself between
versions, which is exactly where the present form is quietest.

Both key shapes coexist in the snapshot during the migration.

### `relocate_citations.py`

It exists because a **stored** number must be rewritten after an update. For an
anchored citation nothing stored needs rewriting: the symbol stays valid and the
line is recomputed on every run.

It is kept unchanged for the transition, because unmigrated chapters still carry
absolute lines. It does not then go away. Six citations keep an absolute line
permanently, so the tool's floor is six rather than zero and "it touched
nothing" never arrives — which also means its workload is not a
migration-progress counter, and progress has to be read off the chapter list
instead.

### `check_citation_style.py`

It learns the new grammar, accepts both forms during the migration, and gains
three findings: a bare number where a name is available, an ambiguous form, and
a form longer than necessary. All three need `describe`, and therefore the
decompile.

**The three structural findings report; they do not block.** The checker runs
over the whole repository whenever any `.md` is staged (`pass_filenames: false`),
so a blocking version would let one overload added by a hotfix stop every
documentation commit in the repository — including commits nowhere near
`docs/ck/` — until somebody rewrote a citation that still resolves to the right
line. That is the failure ADR 0042 names, and a cosmetic finding is not worth
it. The syntactic findings keep blocking, because a malformed citation is
checkable by nobody.

The checker splits in two:

| Half | Needs | Runs |
|---|---|---|
| syntactic (assembly present, form well-formed) | nothing | everywhere, mod repositories included |
| structural (unique, minimal, a name was available) | the decompile | wherever the decompile is reachable |

With no decompile the structural half is skipped **with its reason stated**, not
silently. Same rule as `None` in the structure layer, and the same reason ADR
0042 gives: a pre-commit hook that turns red on correct documentation teaches
people to "fix" correct citations or to bypass it.

Per the reach decision, the syntactic half is additionally wired into the mod
repositories, where no citation gate runs today.

### `verify_status.py`

For a migrated chapter the defect disappears by construction: a hotfix rewrites
no anchored citation, so no tick falls. For an unmigrated one it remains, and
the case is live today. Two things have to be built for the normalisation to
work at all, and neither is a flag.

`verify_status.py` judges a chapter by `git diff --numstat` alone. That counts
changed lines and cannot tell a citation from a sentence, so normalising means
rendering both revisions through a normaliser and diffing the results here,
rather than asking git to ignore something.

And the normaliser has to canonicalise **both** notations onto one key, because
the migration commit rewrites `Pug.Other:370859` into
`Pug.Other:SmallTitleUIBackground:UpdateTextAndBackground:29`. One that merely
blanked digits would read that as prose and fell the tick of every chapter it
migrates — the exact failure this design exists to remove, reintroduced by the
step meant to carry it. Both measures are transitional, with the same planned
end of life as `relocate_citations.py`.

### Documentation that must move with it

| File | What changes |
|---|---|
| `docs/ck/reverse-engineering.md` | section "Line citations carry their assembly" — the canonical rule |
| `.claude/skills/ck-verify-chapter/SKILL.md` | the capture command, the relocation paragraph, the commit rule |
| `CLAUDE.md`, section Formatting gate | the new structural checker and its decompile dependency |
| `check_citation_style.py` docstring | the rationale that currently defends the old form |

## Migration

| Chapter state | Procedure | Tick |
|---|---|---|
| **verified** | mechanical: `describe` proposes, `locate` proves the round trip lands on the same line | **kept** |
| **unverified** | only inside the verification pass | earned there |

Keeping the tick in the first case rests on a sentence the skill already
carries: relocating citations to a later build moves the numbers, not the
verdict. A claim was weighed against a line; the new citation provably resolves
to that same line; the verdict therefore stands. The proof is the round-trip
property, not trust in the tool.

`harmony-and-ecs` and `multiplayer-and-server` were picked to go first on a
figure that was wrong. 31 and 9 are the lines one hotfix rewrote in them, not
the citations they hold: they hold **150 and 96** unique citations, ranks two and
four of the corpus and a third of it between them. Nor are both losing a tick —
one is, and `multiplayer-and-server` was already partial before the hotfix for
reasons renumbering did not cause.

What survives of the argument is the part that matters: they are the two
chapters a verification pass has actually worked, so they are the only ones
where a migration error would show up immediately against a known-good state.
Which of the two goes first, and whether a third, smaller worked chapter should
go ahead of both, is an open question below.

**Unverified chapters are not migrated ahead of their pass.** The new notation
is more persuasive than the old one, and that is the hazard.
`Pug.Other:370859` looks like a number somebody wrote down;
`Pug.Other:SmallTitleUIBackground:UpdateTextAndBackground:29` looks like a
statement somebody understood — it names a class, a method and a position, which
a reader takes as evidence of knowledge. A mechanically re-spelled citation in an
unverified chapter has no such knowledge behind it: it points exactly where the
old number pointed, and if that was wrong, the new form is wrong *and*
authoritative. A machine migration would upgrade all 722 citations, of which the
246 in the two chapters a pass has worked are the only ones anybody has read.
(An earlier draft put that figure at 40, which was 31 + 9 — the same two hotfix
line counts mistaken for citation counts, carried one step further.)

## Tests

| Test | Form | Catches |
|---|---|---|
| round trip over the real corpus | `locate(describe(line)) == line` for all 722 | both prototype bugs found while designing this, immediately |
| calibration | the four known citations as fixtures | regressions in name construction |
| **gate acceptance** | the style checker accepts every citation `describe` writes, end to end through the hook | a pass writing citations its own commit hook rejects |
| tier assignment | a line in a member, in a type only, and in neither get the three different forms | the escape hatch swallowing an anchorable line |
| migration acceptance | after each chapter migration, the drift checker is green | a citation that moved to a different line |
| `None` versus `()` | a `.prefab` yields `None`, an empty C# file yields `()` | merging "nothing known" with "nothing there" |
| cache invalidation | a changed `mtime` re-parses | the lying index |

The gate acceptance test is the most important and the easiest to omit. It is
deliberately **not** a cross-check between two judges: the structural half calls
`describe` rather than re-deciding minimality, because two implementations
judging one claim is what ADR 0042 paid for twice. What it tests is the wiring —
that the value `describe` returns survives being written into a chapter and
parsed back out by the checker.

## Limits

| Failure | Caught by |
|---|---|
| the tool anchors wrongly | round trip plus the recorded text |
| `describe` and the gate judge differently | ruled out by construction — the gate calls `describe`; the acceptance test covers the wiring |
| the decompile is absent | the structural half is skipped, with its reason |
| a member was renamed | the new third drift outcome |
| **the citation was already wrong** | **nothing** — mitigated only by migrating unverified chapters inside their pass |

The last row is the boundary of this design rather than a gap in it: the change
makes citations more durable, not more correct.

### Known hazard in the prototypes

Two throwaway recognisers were written while designing this, both regex-based,
and both failed **silently and in opposite directions** — one read
namespace-indented type declarations as members of the enclosing type and
produced decoy elements up to 3,816 lines long; the other read `for` loops at
member depth as declarations and lost 51 citations. The median search space
moved by a factor of three between them, so the aggregate figure was an artifact
of whichever bug dominated. Calibration against known citations is what exposed
it at the time; the round-trip property below would have caught both at once,
and that is why it is a test rather than a one-off check.

This is the reason the structure layer uses a real parser and the reason the
round-trip property runs over the whole corpus rather than a sample.

## Defined end

When the last chapter is migrated: the normalisation in `verify_status.py` is
reverted, and the paragraph saying a chapter may still carry the old form leaves
`reverse-engineering.md`.

Two things an earlier draft promised here do not happen, both for the same
reason — the escape hatch is spelled in the old grammar. The bare `Assembly:N`
form stays legal; what the style checker stops accepting is a bare form where a
type encloses the line. And `relocate_citations.py` is not deleted, because
those six citations still need their text re-found after an update. The
transition ends; the tooling outlives it, much smaller.

## Rejected alternatives

| Option | Killed by |
|---|---|
| symbol name alone | a quarter of citations would be located to within more than 100 lines only |
| arity (`member/2`) | separates none of the three sampled overload groups — CK's collisions are `(3, 3)`, `(2, 4, 4)` and `(1, 1)`, differing in types |
| ordinal (`member#2`) | opaque to a reader, who would have to count occurrences in a 460,000-line file; and it moves when an overload is added above it |
| first parameter type only | `Execute(Entity)` reads as a complete one-parameter list — misleading, not merely inconsistent |
| full parameter list, never truncated | longest instance 337 characters, which the repository's own wrapping gate would reject as uncommittable |
| class-relative line counting **as the scheme** | the search space explodes exactly where it is already large: `PlayerController.CanConsumeEntityInSlot` would be line 3,687 of 7,598. Kept as a *tier* for the 56 citations with no member to name, where the alternative is worse |
| Roslyn as a .NET index generator | a second source of truth that must be kept in step, plus `dotnet` and MSBuild on every documentation commit |
| committed element index | 57,399 members for `Pug.Other` alone, and a stale index anchors citations wrongly in silence — the most expensive failure mode available |
| additive adoption (ADR 0042's own choice) | misses the goal: 722 citations would keep churning and the ticks would keep falling |

## Open questions

- Which chapter is migrated first, now that the two candidates turn out to hold
  a third of the corpus between them.
- Whether `tree-sitter-c-sharp` belongs in the repository's dependencies or in a
  dedicated extra. This is not the narrow question an earlier draft made it: the
  drift checker resolves a symbol through `locate` on every run, so the
  pre-commit gate depends on it, not merely the structural half of the style
  check.
- The citation grammar's first field is named for assemblies and carries two
  file references — `ControlMappingMenu.prefab` and CoreLib's
  `LocalizationModule.cs`. 27 distinct names cover 25 assemblies plus those two.

## More information

- `docs/ck/reverse-engineering.md`, section "Line citations carry their
  assembly" — the rule this replaces, and why the short forms were banned.
- `salesbuddy`, `docs/adr/0042-separate-what-a-citation-names-from-where-it-points.md`
  — the prior art, its measured history, and the negative consequences it
  accepted.
- `.claude/skills/ck-verify-chapter/SKILL.md` — the verification programme that
  carries the migration.
