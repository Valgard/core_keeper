---
name: ck-verify-chapter
description: Use when verifying one chapter of the docs/ck/ handbook against the decompile, the mod corpus and the running game — the chapter-by-chapter programme, not a review of a pull request.
---

# ck-verify-chapter

Verify one chapter of `docs/ck/`, statement by statement, and leave every
statement on the scope its evidence carries.

The goal is not to find wrong sentences. A sentence needs reworking when it
claims more than its evidence supports, which is why a true sentence gets
touched too: one that happens to be right without saying how far it reaches
will be overturned by the next finding rather than extended by it.

## Dispatch

Read the chapter yourself before dispatching. The three lanes verify
assertions; whatever is wrong with a chapter that is *not* an assertion has no
other reader — a stray leading space mid-sentence, the shape a deletion
leaves behind, passes both documentation gates and every lane's contract
alike, and only a reading catches it.

Run the gates once before dispatching too, not only at commit time:

    uv run utils/check_docs_links.py .
    uv run utils/check_docs_wrapping.py .
    uv run utils/check_citation_drift.py

Thirty seconds, and what it buys is the chapter's starting state — a gate
failure found later is either something this pass introduced or something
that was already there, and without a baseline there is no way to tell
which.

Work happens in a scratch directory outside any tracked path, made once per
chapter and reused for the rest of this run:

    WORK=$(mktemp -d -t ck-verify-chapter)

Render the chapter as a diff — a whole chapter *is* the diff against the empty
file, which is the shape the lanes' contracts already accept — and write both
it and a copy of the full file into `$WORK` rather than into a message:

    git diff --no-index /dev/null docs/ck/<chapter>.md > "$WORK/diff.txt"
    cp docs/ck/<chapter>.md "$WORK/full.md"

Everything pasted into a dispatch prompt stays in the orchestrator's own
context for the rest of the session, and pasting the same content into three
separate prompts triples that cost regardless of chapter length. A path costs
one line either way, so it is the default here rather than something reached
for only past some length.

Fill this template and send it unchanged to all three lanes:

    THIS IS NOT A PULL REQUEST: two of the three lanes are defined for a pull
      request into Pugstorm's CoreKeeperModDocs — that is their trigger, in
      their own frontmatter. This is a chapter of this handbook, verified
      statement by statement; treat every sentence as newly asserted.
    DIFF (REQUIRED): $WORK/diff.txt
    FULL FILE (REQUIRED): $WORK/full.md
    DECOMPILE — client: ~/Projects/checkouts/CoreKeeperDecompile/
    DECOMPILE — dedicated server: ~/Projects/checkouts/CoreKeeperDecompile/DedicatedServer/
    CORPUS — mod repositories: enumerate under the core_keeper root with
      cd /Users/valgard/Projects/private/core_keeper && find . -maxdepth 2 -name .git -not -path "./.git*" | sed 's|^\./||; s|/\.git$||' | grep -v "^CoreKeeperModSDK$" | sort
      The `cd` is required, not a convenience: without it, a lane starting
      from a worktree or a mod repository gets nothing back, silently.
    CORPUS — installed third-party mods: …/CrossOver/Bottles/Core Keeper/drive_c/users/Public/mod.io/5289/mods/<id>/Scripts/
    SEARCH CAVEAT: this directory's .gitignore is /*, and the in-session grep
      honours it — a root-relative search across the mod repositories returns
      nothing at all, silently. Use `command grep`. The handbook is also
      hard-wrapped, so a multi-word phrase is routinely split across two
      lines and a phrase grep misses text that is present even where the
      search reaches the file — search for a fragment, not the whole phrase.
      Either way, an empty result is inconclusive, not evidence of absence.
    OUT OF BOUNDS: do not read any path ending in skills/ck-docs-review/ or
      skills/ck-verify-chapter/. Their fixtures and scoring notes carry worked
      examples with their verdicts — reading them swaps your own source reading
      for a memorised answer.
    REPORT: write your full report to $WORK/<lane-name>.md and return only a
      compact index — one line per assertion, its label and verdict. The
      orchestrator reads the file for everything else.

The lanes are `ckdocs-source-verifier`, `ckdocs-wording-attacker` and
`ckdocs-corpus-checker`. `ckdocs-repo-fit` is not dispatched here: it checks a
foreign repository's house style, which a chapter of this handbook does not
have.

The REPORT line closes the same gap from the other side. A lane's report can
run long enough that the channel carrying it back truncates it before the
orchestrator sees the rest — a function of how much the chapter raises and how
much a lane's own contract requires per assertion, not of which lane produced
it, so there is no telling in advance which report will land on the wrong side
of the limit. Writing to a file and returning only the index is the default
for exactly that reason: a run only discovers it needed the file after a
message has already lost part of a lane, silently.

## Aggregation

Every lane's findings enter the fix list; the orchestrator verifies each
against the source. None is discarded for lack of corroboration — the lanes
are deliberately non-overlapping, and each of two error classes is closed by
a single lane. A negative or exclusivity claim is closed by
`ckdocs-source-verifier` alone — a matching NO OBJECTION from
`ckdocs-wording-attacker` on the same claim is expected there, not a weak
result. A chapter's counter-case — a claim that something cannot be done,
refuted by a mod in this workspace that does it — is closed by
`ckdocs-corpus-checker` alone; the other two lanes' silence about it is
structural, not corroboration, since neither reads the corpus.

`ckdocs-corpus-checker` names its verdicts `CONFIRMED-BY-CORPUS` /
`REFUTED-BY-CORPUS` / `CORPUS-SILENT`, deliberately distinct from
`ckdocs-source-verifier`'s `CONFIRMED` / `REFUTED` / `UNSUPPORTED-BY-SOURCE`,
so an aggregated report can never blur which lane said what.

An UNSUPPORTED-BY-SOURCE verdict is reworded as an honest observation, never
dropped for lack of confirmation. Corroboration is not the filter.
Verification is.

**The fix list is a checklist, and the pass is not done while any entry on it
has no decision.** "Every lane's findings enter the fix list" says what goes
in; it does not say when the list is exhausted. A pass that fixes every
sourced error and every refutation can still read as complete while most of
a lane's wording objections sit untouched — those are a separate category
with a separate closure condition, and finishing one looks, from the outside,
like finishing the pass. Number every finding across all three lanes and
close the pass only once each number carries one of three outcomes: changed,
augmented, or dismissed with a stated reason.

Checking that off by diffing sentence text against the objection list
undercounts on purpose. For an understatement the correct fix is to leave the
true sentence standing and add beside it, not to rewrite it — so a
closed objection can leave its original wording completely unchanged next to
the addition that closed it, and a text diff reports it as still open. The
list of decisions is what a completion check compares against, not the
sentences themselves.

## Orchestrator discipline

A lane's verdict informs your check; it never substitutes for it.

## Put the scope in the sentence

Every statement says what it covers. Not in a marker beside it — in the
wording, the way a dictionary writes "the earliest **known** attestation"
rather than "the earliest".

> A DOTS system whose `OnUpdate` is Burst-compiled cannot be intercepted by
> Harmony.

Unbounded. Any case showing an exception makes this false.

> Every system this repo's mods disable Burst for is an `ISystem` struct.

Carries its scope. A mod that un-Bursts a `SystemBase` tomorrow *extends* this
statement rather than overturning it — it was never more than it says.

Three patterns already in the handbook, worth using deliberately: scope by
provenance ("every mod in this family points it at a child GameObject named
`root`", `docs/ck/ui-framework.md:278-279`), by extent of measurement ("measured
across four built bundles", `docs/ck/steam-workshop.md:216`), by extent of
verification ("this is verified for the equipment/durability case",
`docs/ck/database-and-baking.md:313`).

## Mark the evidence class only where its absence misleads

Being grounded in the decompile is this handbook's normal case, and the
preamble says so. A marker on most sentences carries no information. Two
classes are marked:

- **measured** — evidence gathered outside the source, not forced by the code;
  the wording names the setup that produced it (the running game, or an
  external endpoint such as the Steam store API or `steamcmd`, with the date
  and what was queried).
- **unverified** — examined, and neither the decompile, the corpus, nor a
  measurement settled it.

`unverified` is not a hedge and not a soft refutation. It is the correct answer
whenever the investigation finds nothing either way, and rounding it up to a
flat statement is the failure this whole programme exists to prevent.

**The marker is the bold form.** "This remains **unverified**: …" reads as
prose and is found by a search for that form; "nothing settles this either
way" reads better and is invisible to one, and so is a bare `unverified` used
as ordinary sandbox vocabulary rather than as the marker. There is no pool
file — `grep -rin '\*\*unverified\*\*' docs/ck/` *is* the list of open
questions, and wording that hides from that search, or a stray unmarked use
of the word, silently loses or pollutes it. Case-insensitive on purpose: a
marker written `**Unverified: whether …**`, capitalised inside a longer bold
block, is real and open, and a case-sensitive search does not find it either.

A third state never appears in the text: **unassessed**, meaning nobody has
examined it. That is the absence of a verification commit, not a mark on a
sentence — writing it into the chapters would paint the whole handbook with
markers that say nothing about their subject.

**A pass ends with a completion check against that search, not against how
confident the writing feels.** Run the case-insensitive `grep` above for the
markers that exist, then a second, wider pass for prose that could be an open
question without ever spelling the word: "is not established", "was not
established", "has not been established", "cannot be attributed", "has never
been mapped", "is an open question", "nobody has", "untested". Every hit from
either search is a decision, not a result — turn it into a proper marker, or
record why it is deliberately not one. The check exists because the prose
form is always the more elegant sentence to write, which is exactly why an
open question drifts out of the register at the moment the writing is going
well.

The same register fails in the other direction when a hit sits inside a
correction. Fixing a refuted sentence by quoting its old wording verbatim
carries the old `**unverified**` along with it, and the search then finds a
question that was *just answered*, indistinguishable from one still open.
Reword the quoted claim into plain prose instead — "left open whether …",
unmarked — rather than repeating its marker. A hit that turns up inside a
correction paragraph is a candidate for the same completion check above, not
an automatic count either way.

## Keep a correction visible

Overwriting a wrong sentence with the right one erases the one thing a reader
who remembers the old claim is looking for: whether it changed. A correction
needs to read as a correction, not merely land as one.

Two shapes for that exist in this project already — neither is a settled
convention yet, so treat either as available and neither as mandatory:

> ### Correction: thinTiny does not render damage numbers

A heading (`docs/ck/prefabs-and-rendering.md:750`) standing where the wrong
statement stood, with the true fact spelled out immediately below it.

> ("Not in multiplayer" is the wrong scope and stood here until 2026-08-24;
> `docs/ck/harmony-and-ecs.md` has the evidence.)

A dated aside (`CLAUDE.md:222-224`) folded into the paragraph it corrects, naming
the wrong wording and the date it stopped holding. No instance of this shape
exists inside `docs/ck/` itself.

**There is no `> **Correction (…):**` blockquote form.** That has been claimed
as this project's convention before, and it was wrong — the same `grep` that
finds `unverified` finds this claim has no instances to stand on either.

**Make one of these shapes visible only when a reader could still expect the
old claim** — because it stood for a while, was published, or is quoted
somewhere else — and never in addition to a same-pass repair already made in
the running text. A `### Correction:` heading built for a sentence this same
pass had already rewritten in place corrects a version that no longer
exists; the section reads as asserting something and immediately retracting
it, and the only honest reader response is to ask why it is there. Match the
scale to the defect too: the heading is for a paragraph that was wrong as a
whole, the dated aside for a precision inside one that mostly held — a
heading over a footnote-sized fix manufactures structure the chapter does
not otherwise have.

## Questions nothing static can settle

Group by **the game state a measurement needs**, never by chapter: two
questions needing the same state cost almost nothing together, two needing
different states are two rounds whether or not they share a chapter.

**Blocking** — other statements in this chapter depend on it. Answer it
immediately with its own small probe; assessing the dependents on a guess
propagates the guess. Rare.

**This session's batch** — every other question the chapter raises, one build,
grouped by state. One round per state, not one per chapter.

**Left standing** — a question whose state does not arise here, one belonging
to another chapter, one needing a world state too expensive to arrange for a
single answer. It is marked `unverified` and stays in the chapter, which is
both the honest answer to the reader and the record that it is open. A later
round in a matching state takes it along.

### Probe rules

- **Bundling is allowed; mixing is not.** The one-variable rule constrains a
  single *test*, not a build. Twenty independent probe points in one mod are
  fine; one probe point changing two things is not.
- **Measurement hygiene is the real cost.** A measurement counts only with the
  probe and its dependencies loaded. `DisableBurstForSystem*` registers a
  *type* (`CLAUDE.md:224-225`), so any other mod un-Bursting the same system
  carries the probe silently and the result is worthless — and that
  registration check is only half of it. Check separately who else **patches
  the exact method** the probe measures: the registration is a type-level
  fact, a patch on the method is a method-level one, and neither check finds
  what the other would.
- **The rule loosens for a binary question.** "Does the path fire at all" is
  insensitive to a foreign mod that only shifts a number, unlike "by how
  much" — a round built to answer the first can run with a full mod set and
  say so; the same round would be invalid for the second.
- **The rule does not apply to a probe that reads a world property.** A check
  like `world.GetExistingSystem(...) != SystemHandle.Null` counts worlds the
  engine creates, not an effect a mod's patch could have produced, so there
  is nothing for a foreign mod to colour and nothing for the hygiene check to
  rule out.
- **Smoke-check before the measurement round.** Start the game once and read
  the log for whether the probe loaded and registered its points. A probe that
  fails to compile takes all its measurements with it, and without this that is
  discovered only after the round has been played.
- **The probe is throwaway.** It lives in a mod repository, is never published,
  and is removed afterwards.
- **A dedicated server needs a connected player.** An idle one sits at
  `timescale = 0` and never simulates (`docs/ck/harmony-and-ecs.md:483`; the
  mechanism — `ECSManager` pausing on no connection rather than a heuristic —
  is `docs/ck/multiplayer-and-server.md:560-561`), so a probe there logs
  nothing.
  To prove a patch is live server-side, log from the `[HarmonyPatch]` class's
  static constructor (`docs/ck/harmony-and-ecs.md:472`,
  `docs/ck/multiplayer-and-server.md:501`) and read the log after a session
  with a player connected.

### Requesting the round

The measurement round is the only step in this procedure that puts the session
on hold for a person — dispatch, aggregation and rewriting all run without one.
Ask for it as a single block at the end of a message, naming: which mods to
disable (the hygiene rule above is exactly why this has to be spelled out
rather than assumed), what to start — the client, or the dedicated server plus
a player who connects — what to do in game to trigger each probe point, and
roughly how long the round takes. Then stop: don't continue into other work
while it is pending. It is a handover, not a note in passing — there is
nothing left in this chapter to verify until the result comes back, and
drifting into other work is how a returned result meets a session that has
moved on.

## Sweep outward before committing

The handbook is deliberately redundant: `harmony-and-ecs.md` and
`multiplayer-and-server.md` both speak about the dedicated server — one pair
among several that do, `persistence.md` and `platforms.md` no less than these
two — and `mod-anatomy.md` and `publishing.md` both about `requiredOn`, itself
asserted well beyond that pair, in `index.md` and `troubleshooting.md` among
others. Correcting one chapter and leaving its siblings standing is **worse
than the original** — chapters that contradict each other, with nothing
saying which one is right.

This is documented experience, not a hypothetical. Both known errors were
corrected in two documents each. `harmony-and-ecs.md` said `BurstDisabler`
"does nothing in multiplayer" until 2026-08-24
(`docs/ck/harmony-and-ecs.md:239-240`), and the same wrong scope sat in
`CLAUDE.md`'s own bullet until the same day (`CLAUDE.md:222-224`); a
`SystemBase` precedent that never existed ran the other way, originating in
`CLAUDE.md` and propagating into the chapter before both were corrected
together (`CLAUDE.md:210-212`). Neither correction reached a third instance
of the multiplayer claim: `docs/ck/index.md`'s own symptom table used the same
wrong scope as its routing key, and kept it until a pass on 2026-09-01 went
looking for it (`docs/ck/index.md:109`).

For every statement changed, find where the same thing is asserted:

1. the other chapters of `docs/ck/`
2. the parent `CLAUDE.md` — the `SystemBase` precedent that never existed lived
   there, not in a chapter
3. each mod's own `CLAUDE.md` and `docs/`
4. this repository's `docs/` outside the handbook

Searching 3 and 4 needs `command grep`: the mod repositories are invisible to a
root-relative search here.

A mod repository is a separate repository, so a correction there is its own
commit. The sweep names both rather than assuming one commit closes it.

**A citation you insert needs to say which tree it is from.** The client and
dedicated-server decompiles the dispatch template names separately can offset
the same method by a different line count, so an unmarked citation is only
safe once the chapter has committed to one meaning for "unmarked" — state
which tree a new citation is from, or confirm the chapter's own convention
before relying on it silently. A verification pass found exactly this mixed
within one paragraph: client offsets cited between server ones, in a chapter
that had used "unmarked = client" throughout without ever saying so.

**A line-number citation is a state reference, not a fact reference, and
sweeping for it is a different search than sweeping for the same claim.** An
insertion anywhere above a cited line shifts it silently — including from a
file the citing document never mentions and asserts nothing about. That is
not the same failure as citing the wrong line to begin with: the citation was
correct when written, and it is the file around it that moved.
`utils/check_citation_drift.py` does not catch it either — it resolves
`docs/ck/` citations against the decompile, so a `.claude/skills/` file citing
`CLAUDE.md` sits outside its scope on both axes. So after changing a file,
also find what cites *into* it by line — open every one and confirm the line
still says what the citing sentence claims, the same way a citation is
checked on first use.

**Rewrap each touched file by name, or with `.`, never with a directory in
between.** `check_docs_wrapping.py --fix` treats whatever directory it is
handed as its own root, so `--fix docs/` silently rewrites the frozen
`docs/specs/` records this sweep has no business touching — nothing in the
tool's own output says so, only `git status` does. A sweep across several
chapters is exactly the situation that invites running the fixer once "to
catch everything" instead of once per file.

## Commit

    docs(ck): verify <chapter> against <game version>

The version is not decoration. There is no register file: whether a chapter
was examined is its commit history, and against which build is this line. A
commit without it makes the chapter's state unreadable a year later.

Write it in the exact-version-string shape the handbook itself already asks
for, and for the same reason — not the bare four-part game version
(`docs/ck/reverse-engineering.md:85-89`, "record the build the checkout came
from"): `1.2.1.5-8be0`, for example, is the current `game_version` in
`utils/ck-citation-snapshot.json`. Read the current value from there, or from
the decompile checkout itself — the example is a shape to match, not a value
to copy forward.

**Any citation inserted during this pass needs that same snapshot updated, in
the same run:**

    uv run utils/check_citation_drift.py --capture --game-version <version>

Skip it after adding new citations and the next chapter's drift check reports
them as "not in the snapshot" — a false positive with no relation to that
later pass. Use the same version string as the commit line above, so the
snapshot and the commit history agree on what was checked against what.

## Red flags

Thoughts that mean stop, in the shape `ck-docs-review` uses:

| Thought | Reality |
|---|---|
| "The citation checks out, so the sentence is right" | Citation accuracy is not sentence accuracy; a correctly-cited line can support the wrong scope |
| "Two lanes agree" | The lanes are non-overlapping by design; agreement is not verification |
| "This sentence is true, so leave it" | A true sentence with no scope is what the next finding overturns |
| "`unverified` feels like giving up" | It is the correct answer when nothing settles the question; rounding it up is the failure being prevented |
| "I'll phrase the open question more elegantly" | If a search cannot find it, it is lost — there is no pool file |
| "Fixed the chapter, done" | The claim may live in `CLAUDE.md` or a mod repo too |
