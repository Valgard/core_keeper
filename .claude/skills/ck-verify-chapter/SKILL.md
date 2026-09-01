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
