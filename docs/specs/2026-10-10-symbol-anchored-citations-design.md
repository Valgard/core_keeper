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

The citations do not silently break. `utils/relocate_citations.py` finds each
recorded snippet again in the regenerated tree and rewrites the number, and on
2026-10-09 it found all 722 of them. What costs is the repair itself:

| Cost of one hotfix (commit `7788522`, 1.3.0.5 → 1.3.0.6) | |
|---|---|
| lines rewritten across ten chapters | ~320 |
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
line relative to it. CK had rejected symbol names for the same reason and kept
absolute lines instead. Both projects independently rejected the other's choice;
the hybrid is what neither had.

Measured here, the imprecision is the same magnitude:

| Search space a symbol name alone leaves open | CK | salesbuddy |
|---|---|---|
| 1–10 lines | 23 % | 13 % |
| 11–30 | 24 % | 19 % |
| 31–50 | 14 % | 21 % |
| 51–100 | 14 % | 22 % |
| over 100 | 26 % | 25 % |
| median | 36 lines | 49 lines |

## Goal

After a hotfix, `git diff` over `docs/ck/` is empty and `verify_status.py`
reports unchanged ticks.

### Success criteria

- A citation survives any decompile change outside the element it names.
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
| **Migration** | per chapter, carried by the verification programme |
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
| `Interface<T>.member` | 9 | explicit interface implementation, spelled as the decompile spells it |

Measured over the ambiguous citations: a one-type prefix suffices for 35, two
types for 7, four types for 1, and 9 are explicit interface implementations
whose parameter lists are identical by language rule. Parameter *names* never
appear; modifiers separate nothing in the current corpus.

The counts in that table sum to 725 of the 727 resolvable citations, because
the ambiguity measurement indexed methods only while the resolution
measurement indexed every member kind. The two-citation residue and the
6-versus-9 figure below have the same cause; neither changes a rule.

The ellipsis is what keeps this short. Without it the full list would be needed,
whose longest instance is 337 characters — `EvaluateConsumeResultJob.Execute`,
an `IJobEntity` whose parameter list *is* its query, with 14 components. With it,
that citation reads `Execute(Entity, …)`:

| Member specification | full list | shortest prefix |
|---|---|---|
| median | 43 characters | **29** |
| longest | **337** | **57** |
| over 60 characters | 13 | **0** |

### The escape hatch

`` `Assembly:7` `` is permitted only where no element exists to name, which the
checker decides by reading the file rather than from a list:

| Case | Citations |
|---|---|
| the line lies in no element (namespace level, `using`, attribute) | 64 |
| the file is not a decompiled assembly (a `.prefab`, CoreLib's own source) | 2 |
| the line lies inside a parser error node | 2 |

The last two reach the escape hatch through the structure layer answering
`None`. No location check runs there — not a lenient one, none.

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

The layer takes a **path**, not an assembly name; resolving assembly to path is
already `check_citation_drift.resolve`'s job. That removes every special case: a
`.prefab` is not C# and yields `None`, CoreLib's `LocalizationModule.cs` is C#
and yields real elements, an unreadable path yields `None`.

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
than the repository, and so that `git clean -fdx` does not cost 7.8 s. The build
identity is recorded but deliberately **not** part of the key: a decompile
regenerated without a version change would otherwise keep serving a stale index,
which is the one failure this approach exists to avoid.

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

It exists because a **stored** number must be rewritten after an update. Under
the new notation nothing stored needs rewriting: the symbol stays valid and the
line is recomputed on every run. The concept of relocation disappears.

It is kept unchanged for the transition, because unmigrated chapters still carry
absolute lines — and its remaining workload after an update *is* the migration
progress, so no separate counter is needed. When it touches no citation, the
migration is complete and the file is deleted.

### `check_citation_style.py`

It learns the new grammar, accepts both forms during the migration, and gains
three findings: a bare number where a name is available, an ambiguous form, and
a form longer than necessary. All three need `describe`, and therefore the
decompile. The checker splits in two:

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
no line, so no tick falls. For an unmigrated one it remains, and the case is
live today. Citation line numbers are therefore normalised before the diff —
explicitly as a transitional measure, with the same planned end of life as
`relocate_citations.py`.

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

`harmony-and-ecs` and `multiplayer-and-server` are migrated first: they are
small (31 and 9 citations), they are the two chapters currently losing ticks to
renumbering, and they are the only ones where an error would show up immediately
against a known-good state.

**Unverified chapters are not migrated ahead of their pass.** The new notation
is more persuasive than the old one, and that is the hazard.
`Pug.Other:370859` looks like a number somebody wrote down;
`Pug.Other:SmallTitleUIBackground:UpdateTextAndBackground:29` looks like a
statement somebody understood — it names a class, a method and a position, which
a reader takes as evidence of knowledge. A mechanically re-spelled citation in an
unverified chapter has no such knowledge behind it: it points exactly where the
old number pointed, and if that was wrong, the new form is wrong *and*
authoritative. A machine migration would upgrade 793 citations of which 40 have
been read by anyone.

## Tests

| Test | Form | Catches |
|---|---|---|
| round trip over the real corpus | `locate(describe(line)) == line` for all 727 | both prototype bugs found while designing this, immediately |
| calibration | the four known citations as fixtures | regressions in name construction |
| **paired property** | every `describe` output passes the structural half of `check_citation_style` | the failure ADR 0042 hit twice |
| migration acceptance | after each chapter migration, the drift checker is green | a citation that moved to a different line |
| `None` versus `()` | a `.prefab` yields `None`, an empty C# file yields `()` | merging "nothing known" with "nothing there" |
| cache invalidation | a changed `mtime` re-parses | the lying index |

The paired property is the most important and the easiest to omit. Without it a
pass could write citations that its own commit hook rejects.

## Limits

| Failure | Caught by |
|---|---|
| the tool anchors wrongly | round trip plus the recorded text |
| `describe` and the gate judge differently | the paired property |
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
of whichever bug dominated. Only calibration against known citations exposed it.

This is the reason the structure layer uses a real parser and the reason the
round-trip property runs over the whole corpus rather than a sample.

## Defined end

When the last chapter is migrated: `relocate_citations.py` is deleted, the
normalisation in `verify_status.py` is reverted, the old grammar is dropped from
`check_citation_style.py`, and the "both forms are valid" paragraph leaves
`reverse-engineering.md`. The transition has an end rather than carrying two
forms indefinitely.

## Rejected alternatives

| Option | Killed by |
|---|---|
| symbol name alone | a quarter of citations would be located to within more than 100 lines; the handbook had already rejected this |
| arity (`member/2`) | separates none of the three sampled overload groups — CK's collisions are `(3, 3)`, `(2, 4, 4)` and `(1, 1)`, differing in types |
| ordinal (`member#2`) | opaque to a reader, who would have to count occurrences in a 460,000-line file; and it moves when an overload is added above it |
| first parameter type only | `Execute(Entity)` reads as a complete one-parameter list — misleading, not merely inconsistent |
| full parameter list, never truncated | longest instance 337 characters, which the repository's own wrapping gate would reject as uncommittable |
| class-relative line counting | the search space explodes exactly where it is already large: `PlayerController.CanConsumeEntityInSlot` would be line 3,687 of 7,598 |
| Roslyn as a .NET index generator | a second source of truth that must be kept in step, plus `dotnet` and MSBuild on every documentation commit |
| committed element index | 57,399 members for `Pug.Other` alone, and a stale index anchors citations wrongly in silence — the most expensive failure mode available |
| additive adoption (ADR 0042's own choice) | misses the goal: 722 citations would keep churning and the ticks would keep falling |

## Open questions

- The count of explicit interface implementations measured as 6 in one pass and
  9 in another, from different grouping of non-method members. The exact figure
  is to be pinned down in implementation; the design does not depend on it.
- Whether `tree-sitter-c-sharp` belongs in the repository's dependencies or in
  a dedicated extra, given that only the structural half of one checker needs
  it.
- Two of the 25 cited "assemblies" are not assemblies —
  `ControlMappingMenu.prefab` and CoreLib's `LocalizationModule.cs`. They work
  under the escape hatch, but the grammar's first field is named for assemblies
  and now also carries file references.

## More information

- `docs/ck/reverse-engineering.md`, section "Line citations carry their
  assembly" — the rule this replaces, and why the short forms were banned.
- `salesbuddy`, `docs/adr/0042-separate-what-a-citation-names-from-where-it-points.md`
  — the prior art, its measured history, and the negative consequences it
  accepted.
- `.claude/skills/ck-verify-chapter/SKILL.md` — the verification programme that
  carries the migration.
