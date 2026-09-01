---
name: ck-docs-review
description: Use when a documentation change is bound for Pugstorm/CoreKeeperModDocs, when editing or verifying a chapter of this repository's own docs/ck/ handbook, or when any claim about Core Keeper internals is about to be published outside this machine.
---

# ck-docs-review

A review gate for a Core Keeper documentation change. Independent lanes read
the diff, the orchestrator verifies each finding against the source, and fixes
what's confirmed. Which lanes depends on where the change is going.

## Which lanes, for which audience

| Target | Lanes |
|---|---|
| A pull request into `Pugstorm/CoreKeeperModDocs` | `ckdocs-source-verifier`, `ckdocs-wording-attacker`, `ckdocs-repo-fit` |
| A chapter of this repository's own `docs/ck/` handbook | `ckdocs-source-verifier`, `ckdocs-wording-attacker`, `ckdocs-corpus-checker` |

`ckdocs-repo-fit` checks a *foreign* repository's house style — attribution,
scope, build-environment neutrality against `CoreKeeperModDocs` itself — and
has nothing to say about a chapter of this handbook, which is not that
repository. `ckdocs-corpus-checker` reads the mod corpus in this workspace as
its evidence, which a PR into a foreign repo has no counterpart for.
`ckdocs-source-verifier` and `ckdocs-wording-attacker` read the diff and the
decompile the same way regardless of target, so both sets keep them.

The review gate (`~/.claude/hooks/pr-create-review-guard.sh`) requires the
first set by name before a PR into `CoreKeeperModDocs` can be created; nothing
here changes that.

## Dispatch

Fill this template and send it unchanged to all three lanes:

```
DIFF (REQUIRED): <verbatim output of `git diff <base>...HEAD`, unedited>
FULL FILE (REQUIRED): <complete current contents of every changed file>
DECOMPILE — client: ~/Projects/checkouts/CoreKeeperDecompile/
DECOMPILE — dedicated server: ~/Projects/checkouts/CoreKeeperDecompile/DedicatedServer/
SEARCH CAVEAT: `grep` here honours `.gitignore` and can silently return far
  too little from a root-relative search. Run inside the target directory
  or use `command grep`; an empty or too-small result is inconclusive, not
  evidence of absence.
OUT OF BOUNDS: do not read this skill's own directory — any path ending in
  `skills/ck-docs-review/`, wherever it is checked out, and in particular its
  `fixtures/` and `scoring/`. They carry worked examples of this subject with
  their verdicts, so reading them swaps your own source reading for a
  memorised answer. Stated by shape rather than by absolute path because the
  skill has moved once already and a stale path forbids nothing.
```

## Aggregation

Every lane's findings enter the fix list; the orchestrator verifies each
against the source. None is discarded for lack of corroboration — the lanes
are deliberately non-overlapping, and one error class (a negative or
exclusivity claim) is closed by `ckdocs-source-verifier` alone, where a
matching NO OBJECTION from `ckdocs-wording-attacker` is expected, not weak.
The same holds for a handbook chapter's counter-case — a claim that something
cannot be done, refuted by a mod in this workspace that does it — which is
closed by `ckdocs-corpus-checker` alone; the other two lanes' silence about it
is structural, not corroboration, since neither reads the corpus.

`ckdocs-corpus-checker` names its verdicts `CONFIRMED-BY-CORPUS` /
`REFUTED-BY-CORPUS` / `CORPUS-SILENT`, deliberately distinct from
`ckdocs-source-verifier`'s `CONFIRMED` / `REFUTED` / `UNSUPPORTED-BY-SOURCE`,
so an aggregated report can never blur which lane said what.

An UNSUPPORTED-BY-SOURCE verdict is reworded as an honest observation, never
dropped for lack of confirmation. Corroboration is not the filter.
Verification is.

## Orchestrator discipline

A lane's verdict informs your check; it never substitutes for it.

### Red Flags — STOP

- About to change a word because a lane said so, without opening the source yourself
- "Two lanes agree, so it must be right"
- Checking a sample of citations instead of all of them
- Fixing the PR text and leaving `docs/ck/` alone

Every one of these means: open the decompile and check it yourself first.

### Rationalizations that have actually happened here

| Thought | Why it's wrong |
|---|---|
| "The citation checks out, so the sentence is right" | A correctly-cited line can still support the wrong scope — citation accuracy is not sentence accuracy |
| "The wording lane found no objection" | NO OBJECTION means the sentence survived the wording questions, not that its citations were independently re-read |
| "Both lanes are silent on this claim" | Some error classes are closed by one lane; a second lane's silence there is expected, not corroboration |
| "This reads as obviously fine" | Both baseline passes confirmed wording that was wrong, across understatement, wrong scope, and overreach. Applying a finding without checking introduces new errors while removing old ones |

## Handbook return

A confirmed finding is fixed in both places: the PR text and the
`docs/ck/` chapter it came from or contradicts. Do this as a normal
step — a wrong-scope multiplayer claim once survived two verification
rounds inside the handbook and reached three documents before a later
pass caught it. Fixing only the PR leaves that source for the next PR.
