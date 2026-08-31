# Handbook verification programme — design

A programme to check every statement in `docs/ck/` against the decompiled
game, the mods in this workspace, the installed third-party mods, and — where
nothing static can settle it — against a purpose-built probe mod. One chapter
at a time, one session per chapter.

## The problem this solves

The handbook's own preamble states the defect: *"an overreaching claim reads
exactly like a well-supported one, and nothing in the text distinguishes
them."* Every chapter began as a finding about one mod, at one call site, on
one host, and what was written down is the generalisation of that finding.
Where the generalisation is too wide, the sentence must be reworked the moment
a contradicting case turns up.

The goal is therefore **not** to find wrong sentences. It is to bring every
statement onto the scope its evidence actually carries, so that a later finding
*extends* it rather than overturning it. A sentence that says only what its
evidence supports never needs revising — the next case either falls inside it
or widens it.

This reframes the work: it is a rewriting pass, not a correction pass.
Sentences that are perfectly true get touched too, because a sentence that
happens to be right without saying how far it reaches does not meet the goal.

## What comparable works do, and why it settles the form

Two rounds of research, one into reverse-engineering documentation and one into
printed reference works. The two genres answer differently, and the difference
is the reason for the form chosen below.

**Reverse-engineering documentation has no genre-wide convention.** No project
cites another as precedent; markers are locally invented. Three of the most
substantial works — Pan Docs, NESdev, Discord Userdoccers — carry no formal
marker at all. Where marking happens it marks **the doubtful**, not the
established: Minecraft Wiki's `{{Verify|type=…}}` (536 pages in that category)
and its separate `{{Check the code}}`; gb-ctr's `#speculation[]`. The common
case is a blanket disclaimer up front plus prose hedging in the body — which is
what this handbook already does. Its preamble *is* that disclaimer.

The single lived per-statement evidence field is Kaitai Struct's `doc-ref` (381
occurrences at attribute level), and it works because `.ksy` is structured
data. For running prose the research found no case at all.

**Printed works mark comprehensively rather than selectively.** CATZOC (the
survey-reliability class on nautical charts, IHO S-57) assigns a class to
*every* area including the best-surveyed; CODATA gives every value an
uncertainty; the OED cites every sense. This is possible precisely because the
scale is small and mechanically derivable — CATZOC follows from position
accuracy, depth accuracy and seafloor coverage, not from a feeling. Where a
scale requires judgement, marking reverts to selective (`str.`, the negative
apparatus).

**Four printed constructions carry a statement's scope so that a new finding
extends it:**

| Construction | Mechanics | What a new finding does |
|---|---|---|
| CATZOC | the claim holds for an *area* | reclassifies that area, not its neighbour |
| CODATA | uncertainty sits inside the notation | the better value lies *within* the old interval |
| Loseblatt | a date of record per supplement | replaces the single sheet, not the work |
| OED | "the **earliest known** attestation" | moves the date, leaves the definition intact |

The OED construction is the one this programme adopts, because it needs no
apparatus at all: the immunity against later findings is built into the wording.

**And CATZOC separates two states that are easy to conflate: `unsurveyed` and
`unassessed`.** Not surveyed is not the same as not classified. A statement
nobody has examined yet is a different thing from one that was examined and
stayed open. Merging them would be the most expensive mistake this programme
could make, and the register below keeps them apart.

**One negative result worth recording:** for prose documentation the research
found no case of a project auditing its own existing body of statements. Where
that exists it is automated — matching decompilation, where the state of the
work is a measurement (`sm64ds-decomp`: 11,230 of 11,401 functions) rather than
an editorial note. This programme has no precedent to copy; it has an analogy,
and the analogy says to keep the state as a number.

## The form: scope everywhere, evidence class where it would mislead

**Comprehensive: every statement carries its own scope, in the sentence.** No
markup, no sigil — the wording does it, in the OED manner. The handbook already
does this in places without knowing it:

> A DOTS system whose `OnUpdate` is Burst-compiled cannot be intercepted by
> Harmony.

Unbounded. Any case showing an exception makes this sentence false.

> Every system this repo's mods disable Burst for is an `ISystem` struct.

Carries its scope. A mod that un-Bursts a `SystemBase` tomorrow *extends* this
statement; it was never more than it says.

Three patterns already present in the handbook, worth using deliberately:
scope by provenance ("every system this repo's mods disable Burst for"), scope
by extent of measurement ("measured across four built bundles"), scope by
extent of verification ("verified for `PugMod.Loader` and `Pug.Other`").

**Selective: the evidence class, and only where its absence would mislead.**
Being grounded in the decompile is the handbook's normal case and the preamble
already says so; a marker sitting on most sentences carries no information. Two
classes are marked, because a reader would otherwise draw a false conclusion:

- **measured** — observed in the running game, not forced by the code. The
  wording names the setup. This is the `wording-attacker`'s "runtime claim as
  code fact" class, disarmed at the source.
- **unverified** — examined, and neither the decompile nor a measurement could
  settle it. Explicitly *not* a hedge and not a soft REFUTED: it is the correct
  answer whenever tracing finds nothing either way, and the `source-verifier`'s
  contract already forbids rounding it up.

A third state exists and deliberately never appears in the text: **unassessed**
— not yet examined. It lives in the register. Putting it in the chapters would
paint 21 chapters with markers that say nothing about the subject.

## The procedure for one chapter

Three lanes read the chapter independently, then the orchestrator verifies each
finding against the source itself. This is the `ck-docs-review` discipline, and
its red flags carry over unchanged: never change a word because a lane said so,
never treat agreement between two lanes as verification, never sample
citations.

**Two existing lanes are used unmodified.** `ckdocs-source-verifier` and
`ckdocs-wording-attacker` were calibrated against fixtures with planted errors;
any change to their contract voids that calibration silently. They expect a
diff and the full file — and a whole chapter *is* a diff, namely the one
against the empty file: `git diff --no-index /dev/null <chapter>` renders every
line as an addition, which is exactly the shape their contract already accepts.
The full file is the chapter itself. Their contracts stay untouched and their
calibration keeps holding.

**One lane is new: `ckdocs-corpus-checker`.** `ckdocs-repo-fit` checks a
foreign repository's house style and is useless here. In its place, a lane that
reads the corpus this workspace has and the decompile does not:

- **Counter-cases.** The mods here are real code running against the same API.
  Where the handbook says something cannot be done and a mod does it, that is a
  refutation — and it is the "incomplete because the contradicting case never
  came up" failure, which no amount of decompile reading finds.
- **Claims about this workspace's mods.** Where a chapter describes what a mod
  does, that is checkable directly.
- **Precedent presented as rule.** `reverse-engineering.md` warns that "a
  reference mod is precedent only if it does the same thing"; a chapter leaning
  on an installed third-party mod as evidence of a *rule* is making exactly
  that error.

The corpus is the mod repositories in this workspace and the installed
third-party mods, whose sources are readable in the mod.io cache.

**Search caveat, passed to every lane:** the in-session `grep` honours
`.gitignore`, and this directory's `.gitignore` is `/*` — a root-relative
search finds nothing in the mod repositories. An empty result is inconclusive,
never evidence of absence.

## Three kinds of open question

A question the decompile cannot settle falls into one of three kinds, and the
kind decides what happens to it. The grouping that matters is **the game state
a measurement needs**, not the chapter it came from: two questions needing the
same state cost almost nothing together, two needing different states are two
rounds whether or not they share a chapter.

**Blocking** — other statements in the same chapter depend on it. Answered
immediately, with its own small probe, because the alternative is assessing the
dependent statements on a guess. The rare case.

**This session's batch** — every other question the chapter raises, in one
build, grouped by game state. One round per state the chapter needs, not one
round per chapter.

**Left standing** — everything this session does not settle: a question whose
game state does not arise here, a question belonging to another chapter, a
question needing a world state too expensive to arrange for one answer. It is
marked `unverified` in the chapter and stays there, which is both the honest
answer to the reader and the record that the question is open. Every future
measurement round then takes along whatever its state can settle — a server
round for chapter twelve carries the server questions left standing in chapter
four.

**That standing set is the hazard the research identified.** Marking is cheap
and settling is expensive, which is how 536 pages of open doubt accumulate.
What keeps it honest is that it is countable — `grep -rc unverified docs/ck/`
against the history says whether it grows or shrinks — and that the measurement
rounds exist to shrink it. An `unverified` that no round is ever aimed at is a
backlog wearing the clothes of a result.

Two rules make the batch survivable. Each probe point is independent, so
bundling does not violate the one-variable rule — that rule constrains a single
*test*, not a build. And a **smoke check precedes every measurement round**: the
game is started once and the log read for whether the probe loaded and
registered its points, because a probe that fails to compile takes all of its
measurements with it and would otherwise be discovered only after the round was
played.

Measurement hygiene is non-negotiable and is the real cost: a measurement
counts only with the probe and its dependencies loaded, because
`DisableBurstForSystem*` registers a *type* and any other mod un-Bursting the
same system carries the probe silently.

## The cross-chapter obligation

The handbook is deliberately redundant — `harmony-and-ecs.md` and
`multiplayer-and-server.md` both speak about the dedicated server,
`mod-anatomy.md` and `publishing.md` both about `requiredOn`. Correcting a
statement in one chapter and leaving its twin standing in another produces
something **worse than the original**: two chapters that contradict each other,
neither saying which is right.

This is documented experience, not a worry. The `ck-docs-review` skill records
that a wrong-scope multiplayer claim survived two verification rounds inside
the handbook and reached three documents before a later pass caught it.

So every chapter session ends with a reworked-statement sweep: for each
statement changed, find where the same thing is asserted elsewhere and correct
both in the same commit.

**The sweep reaches past `docs/ck/`, and that is where it matters most.**
Handbook claims have migrated into the parent `CLAUDE.md`, into individual mods'
`CLAUDE.md` files and into their `docs/`. The `SystemBase` precedent that never
existed lived in the parent `CLAUDE.md`, not in a chapter — a sweep confined to
the handbook would have left it standing and produced exactly the contradiction
this step exists to prevent. Since a mod repository is a separate repository,
correcting a claim there is its own commit; the handbook edit and the derived
correction cannot share one, and the sweep has to name both rather than assume
a single commit closes it.

## No register file, and no pool file

An earlier draft of this design gave the programme a tracked register and a
tracked pool. Both are dropped, because both restate something that already
exists somewhere better.

**The chapter is the pool.** A question that was examined and stayed open is
marked `unverified` in the text — that is the whole point of the form chosen
above. So `grep -rn unverified docs/ck/` enumerates every open question, and a
separate list would be a second copy that can disagree with the first. This
repository already treats working artefacts as slop (`docs/superpowers/` is
ignored for exactly that reason), and the distillation rule it applies asks for
"result, not route": a list of ticked-off questions is route.

**Git is the register.** Whether a chapter has been examined is answered by its
commit history; which game version it was examined against belongs in the
commit message. That reproduces the CATZOC distinction at no cost —
`unassessed` means no verification commit exists, `examined, open` means one
exists and the text carries `unverified`. The backlog trend is then computable
after the fact rather than maintained by hand: `git log` plus a count of
`unverified` per revision says whether the open statements are growing or
shrinking, and it cannot drift from the chapters, because it is derived from
them.

What this gives up is small and deliberate: the game state an open question
needs is written nowhere. Recording it would put process metadata into the
product, and it is cheap to recover — before a measurement round, read the
`unverified` passages and see which ones that round's state can settle.

## Artefacts and where they live

| Artefact | Location | Tracked |
|---|---|---|
| This spec | `docs/specs/` | yes |
| `ck-docs-review` skill | `.claude/skills/` | yes, in this repo |
| Chapter session skill | `.claude/skills/` | yes, in this repo |
| The three existing lanes | `.claude/agents/` | yes, in this repo |
| The new corpus lane | `.claude/agents/` | yes, in this repo |
| Citation drift snapshot | `utils/` plus its data file | yes |
| Probe mods | a mod repository, throwaway | no |
| Register, pool | — | they do not exist |

**The review machinery moves out of the machine's global config and into this
repository.** The `ck-docs-review` skill and its three lanes are entirely Core
Keeper specific — they check this handbook and pull requests into
`CoreKeeperModDocs`, which is itself a checkout under this directory. They
belong beside the thing they check, versioned with it, so that a change to a
lane and the chapter that motivated it can be read together.

This required one `.gitignore` change: the repository ignores everything by
default (`/*`) and un-ignores named paths, and `.claude/` used a three-line
idiom that re-allowed `skills` alone. `agents` is now re-allowed beside it,
while `settings.json` stays local as before.

**Nothing breaks in the review gate, and that was worth checking before
moving.** `hooks/pr-create-review-guard.sh` and `hooks/pr-review-marker.sh`
identify the lanes purely by **name** — `CKDOCS_REQUIRED="ckdocs-source-verifier
ckdocs-wording-attacker ckdocs-repo-fit"` and the pattern `ckdocs-*` — never by
path. The hooks themselves stay in `~/.claude/hooks/`, because they are wired
into that machine's settings and are not repository content.

One consequence to be aware of: a session started **inside a mod
subdirectory** no longer sees these lanes, where the global location made them
visible everywhere. That is acceptable because both consumers — the handbook
and the `CoreKeeperModDocs` checkout — live at this level, but a session that
needs a lane must be started here rather than in a mod.

## Tools: now versus after the pilot

The procedure must be fixed before the first session, or session twelve differs
from session one and "verified" ends up meaning twenty different things. The
*tools* need not be, and building them now would build them on assumptions
rather than experience.

**Now, because their value does not depend on the untested procedure:**

- **The chapter session skill** — it is this spec made executable, not a guess
  about it. Without it the procedure is not reproducible, which is the whole
  point.
- **The new corpus lane** — likewise part of the procedure.
- **The citation drift checker** — extracts every `Assembly:NNNN` reference in
  the handbook and stores the *text* of the cited line as a snapshot. It answers
  in seconds, after every game update, the question that otherwise costs a
  four-agent sweep: which citations now point at something else. It does not
  check whether a statement is true — no script can — it checks whether the
  ground under it moved. On 2026-08-22 that question cost four parallel
  verifiers across 175 references to find six errors, and the same cost falls
  due at the next update with nobody knowing which references are affected.

**Also now, because it is a move rather than a build:** the `ck-docs-review`
skill and its three lanes come out of the machine's global config into this
repository, per the artefact table above.

**After the pilot chapter, from what actually recurred:** a probe scaffold, a
log evaluator, a concordance for the cross-chapter sweep, and — if counting the
standing `unverified` set by hand turns out to be tedious — a one-line report
over the history. Each depends on facts the first real chapter produces: what a
probe for this handbook looks like, how many questions a chapter raises, whether
grouping by game state is even the right cut.

## Chapter order

No fixed sequence is written down: it would go stale, and the right question
each time is which chapter comes next, not which package to schedule.

**The first is `harmony-and-ecs.md`** (868 lines), as a deliberate pilot. Its
statements have already migrated into the parent `CLAUDE.md`, so an undetected
error there is expensive; two of its core claims were demonstrably wrong before
(a wrong-scope "does nothing in multiplayer", and a `SystemBase` precedent that
never existed); and it is the one chapter that exercises all four evidence
sources, because Burst behaviour on a dedicated server is not statically
decidable. It calibrates the procedure on the chapter where getting it wrong
costs most.

Its session carries an extra obligation: record what recurs and what hurts,
because that record is what the remaining tools are built from.

**Afterwards, by two criteria rather than a list.** Chapters whose claims have
travelled outside the handbook come before ones that have not; chapters that
are structurally checkable come before heavily empirical ones, so the procedure
is settled before it meets the chapters that need the most measurement rounds.
The short chapters (`toolchain.md`, `platforms.md`, `organising-a-mod-project.md`,
`announcing-in-discord.md`, `README.md`) are not worth a session each and are
taken together.

## Open points

- **The exact wording of the two evidence-class markers** is settled during the
  pilot, against real sentences rather than invented ones. `measured` and
  `unverified` are working names; what matters is that they read as prose, not
  as tags.
- **Whether one session really holds one chapter** is unknown for the largest
  ones. `ui-framework.md` at 2126 lines and roughly 100 core assertions may
  need splitting; the pilot gives the first real rate.
- **The marker has to be prose and greppable at once**, and that is a real
  tension rather than a detail. Dropping the pool file only works if the open
  questions can be enumerated from the chapters, which requires the word to
  appear literally — "this remains **unverified**: …" reads as prose and is
  still found by a search, whereas "nothing settles this either way" reads
  better and is invisible to one. The pilot decides the exact phrasing, under
  the constraint that a search must find every instance. If that constraint
  cannot be met without the text turning into tags, the pool file comes back —
  as the fallback, not as the default.
