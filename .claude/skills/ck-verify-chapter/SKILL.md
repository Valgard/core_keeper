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

Render the chapter as a diff — a whole chapter *is* the diff against the empty
file, which is the shape the lanes' contracts already accept:

    git diff --no-index /dev/null docs/ck/<chapter>.md

Fill this template and send it unchanged to all three lanes:

    DIFF (REQUIRED): <verbatim output of the command above>
    FULL FILE (REQUIRED): <complete current contents of the chapter>
    DECOMPILE — client: ~/Projects/checkouts/CoreKeeperDecompile/
    DECOMPILE — dedicated server: ~/Projects/checkouts/CoreKeeperDecompile/DedicatedServer/
    CORPUS — mod repositories: enumerate under the core_keeper root with
      find . -maxdepth 2 -name .git -not -path "./.git*" | sed 's|^\./||; s|/\.git$||' | grep -v "^CoreKeeperModSDK$" | sort
    CORPUS — installed third-party mods: …/CrossOver/Bottles/Core Keeper/drive_c/users/Public/mod.io/5289/mods/<id>/Scripts/
    SEARCH CAVEAT: this directory's .gitignore is /*, and the in-session grep
      honours it — a root-relative search across the mod repositories returns
      nothing at all, silently. Use `command grep`. An empty result is
      inconclusive, not evidence of absence.
    OUT OF BOUNDS: do not read any path ending in skills/ck-docs-review/ or
      skills/ck-verify-chapter/. Their fixtures and scoring notes carry worked
      examples with their verdicts — reading them swaps your own source reading
      for a memorised answer.

The lanes are `ckdocs-source-verifier`, `ckdocs-wording-attacker` and
`ckdocs-corpus-checker`. `ckdocs-repo-fit` is not dispatched here: it checks a
foreign repository's house style, which a chapter of this handbook does not
have.

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
`root`", `docs/ck/ui-framework.md:278`), by extent of measurement ("measured
across four built bundles", `docs/ck/steam-workshop.md:216`), by extent of
verification ("this is verified for the equipment/durability case",
`docs/ck/database-and-baking.md:313`).

## Mark the evidence class only where its absence misleads

Being grounded in the decompile is this handbook's normal case, and the
preamble says so. A marker on most sentences carries no information. Two
classes are marked:

- **measured** — observed in the running game, not forced by the code; the
  wording names the setup that produced it.
- **unverified** — examined, and neither the decompile, the corpus, nor a
  measurement settled it.

`unverified` is not a hedge and not a soft refutation. It is the correct answer
whenever the investigation finds nothing either way, and rounding it up to a
flat statement is the failure this whole programme exists to prevent.

**The word appears literally.** "This remains **unverified**: …" reads as prose
and is found by a search; "nothing settles this either way" reads better and is
invisible to one. There is no pool file — `grep -rn unverified docs/ck/` *is*
the list of open questions, and wording that hides from that search silently
loses them.

A third state never appears in the text: **unassessed**, meaning nobody has
examined it. That is the absence of a verification commit, not a mark on a
sentence — writing it into the chapters would paint the whole handbook with
markers that say nothing about their subject.

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

A dated aside (`CLAUDE.md:221`) folded into the paragraph it corrects, naming
the wrong wording and the date it stopped holding. No instance of this shape
exists inside `docs/ck/` itself.

**There is no `> **Correction (…):**` blockquote form.** That has been claimed
as this project's convention before, and it was wrong — the same `grep` that
finds `unverified` finds this claim has no instances to stand on either.

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
  *type* (`CLAUDE.md:222-223`), so any other mod un-Bursting the same system
  carries the probe silently and the result is worthless.
- **Smoke-check before the measurement round.** Start the game once and read
  the log for whether the probe loaded and registered its points. A probe that
  fails to compile takes all its measurements with it, and without this that is
  discovered only after the round has been played.
- **The probe is throwaway.** It lives in a mod repository, is never published,
  and is removed afterwards.
- **A dedicated server needs a connected player.** An idle one sits at
  `timescale = 0` and never simulates (`docs/ck/harmony-and-ecs.md:368`; the
  mechanism — `ECSManager` pausing on no connection rather than a heuristic —
  is `docs/ck/multiplayer-and-server.md:553-554`), so a probe there logs
  nothing.
  To prove a patch is live server-side, log from the `[HarmonyPatch]` class's
  static constructor (`docs/ck/harmony-and-ecs.md:361`,
  `docs/ck/multiplayer-and-server.md:500`) and read the log after a session
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
