---
status: accepted
date: 2026-08-25
---

# A dedicated review gate for pull requests into Pugstorm's modding docs

## Context and Problem Statement

Pull requests into `Pugstorm/CoreKeeperModDocs` are documentation, and their
readers are the people who wrote the code being described. The risk they carry
is a wrong statement about game behaviour that a maintainer can disprove from
their own source in seconds.

`pr-review-toolkit`, the gate for every other repository here, dispatches six
agents that examine properties of *code*: error handling, type design, test
coverage, simplification. A prose change into a foreign repository has none of
those. Running it is not wrong, it is empty — and an empty review reports "no
issues found", which reads like assurance.

## Decision Drivers

* The failure mode is a claim that cannot be supported, not a code defect.
* An unguided review of exactly this kind of change was measured and found
  1 of 12 planted errors — while positively certifying four of the misses as
  verified-correct, each with an accurate line citation.
* A gate that is routinely passed by exception stops being a gate.

## Considered Options

* Keep `pr-review-toolkit` for this repository too.
* A purpose-built lane set, enforced by the existing hook pair.
* A skill with no enforcement, relying on the documented bypass each time.

## Decision Outcome

Chosen: **a purpose-built lane set, hook-enforced per repository.** Three
agents read the same raw diff independently and attack it from different
directions — assertions against the decompiled game and SDK, prose against its
own claims, and the change against the target repository's conventions. The
guard requires all three for this repository and the toolkit agent everywhere
else.

Two properties are load-bearing and were reached by measurement rather than
design instinct:

* **No lane ever receives an extracted claim list.** The errors this gate
  exists to catch survive extraction: a scope error normalises into a true
  statement on the way from the text to a summary of it. Every lane reads the
  diff.
* **Findings are not filtered by corroboration.** The lanes are deliberately
  non-overlapping, so a finding raised by one and not the others is the normal
  case, not a weak signal. Verification against the source is the filter.

### Consequences

* Good: measured on a fixture the lanes had never seen, they found 3 of 3
  planted errors, both source-reading lanes independently. They also refuted a
  claim the fixture's own author had recorded as true — the strongest available
  evidence that the gate catches what a careful human misses.
* Good: the lanes hold read-only tools, so a review cannot modify what it
  reviews.
* Bad: a review marker records that a lane ran, not what it reviewed. A run
  against a fixture therefore satisfies the gate for an unrelated pull request.
  This is inherited from the existing gate rather than introduced here, and the
  guard's own header already calls itself a friction threshold rather than
  proof.
* Bad: the lane definitions must carry measured examples to work, and the first
  measured examples came from the first pull request they reviewed. The
  dispatch template therefore keeps every lane out of the skill's own fixtures;
  the overlap fades as later changes cover other subjects.

## More Information

The raw design document this was distilled from, including the rejected
alternatives in their original form:

~~~
git show "$(git rev-list -1 HEAD -- docs/specs/2026-08-24-ck-docs-review-gate-design.md)^:docs/specs/2026-08-24-ck-docs-review-gate-design.md"
~~~

The gate's own workings — the three lanes, the dispatch contract, the
orchestrator's discipline — live in `~/.claude/skills/ck-docs-review/SKILL.md`
and the three `~/.claude/agents/ckdocs-*.md` definitions. Enforcement is
`~/.claude/hooks/pr-create-review-guard.sh` and `pr-review-marker.sh`, with
tests beside them.
