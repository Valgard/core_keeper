# A review gate for PRs into Pugstorm's modding documentation

Design for `ck-docs-review`: a skill plus three agents that replace
`pr-review-toolkit` as the review gate for pull requests against
`Pugstorm/CoreKeeperModDocs`, and the two hook changes that make that
substitution binding rather than optional.

## Why a separate gate

`pr-review-toolkit` dispatches six agents that examine properties of *code*:
error handling, type design, test coverage, simplification. A documentation PR
into a foreign repository has none of those. Five of the six find no surface at
all, and the sixth reviews prose against conventions written for source files.
Running it is not wrong, it is empty — and an empty review reports "no issues
found", which reads like assurance.

The risk that documentation PR actually carries is different in kind: **a
statement about the game's behaviour that is wrong, and that a reader will act
on.** It is published under the author's name, in a repository maintained by the
people who wrote the code being described, where any claim can be checked
against the source in seconds. Nothing in a code-review toolkit looks for that.

This gate looks for exactly that, and for nothing else.

## The lesson the design is built on

On 2026-08-24, preparing the first such PR, the technical chain was verified
against the decompile and then checked a second time by an independent agent.
Both passes confirmed it. The published wording still contained two errors,
found only by a third pass that was given something the earlier ones were not:
**the verbatim text**, rather than a list of claims extracted from it.

The errors were instructive:

- "the mod ... does nothing in multiplayer" — wrong scope. A hosting client
  creates its own server world inside the same process and is unaffected; only
  the dedicated-server binary is.
- "on the client it arms nothing that the regular startup would not arm anyway"
  — overreach. The set the code walks is a strict superset of the set the claim
  describes.

Neither is visible in a claim list, because extraction had already normalised
them away: "does nothing in multiplayer" had become "the prefix does not fire on
a dedicated server", which is true. **The error lived in the abstraction, not in
the chain.**

That yields the design's one non-negotiable rule, from which most of the rest
follows: no reviewing agent ever receives a claim list. Every lane reads the
diff.

## The three lanes

Each agent receives the same input — the raw diff, the complete changed file,
and the paths to both decompile trees with their search caveats. They differ
only in what they are told to attack.

### `ckdocs-source-verifier`

Every factual assertion about game or SDK behaviour, checked against the
decompiled assemblies for both the client and the dedicated-server build.

Returns, per assertion: a verdict of `CONFIRMED`, `REFUTED`, or
`UNSUPPORTED-BY-SOURCE`, the file and line number, and the actual text of the
line read. The third verdict is load-bearing and not a hedge: a claim that is
only observable at runtime — a startup ordering, an exception that depends on
initialisation timing — must be labelled as such rather than confirmed, because
the decompile cannot settle it and a reviewer who traces the code will find
nothing supporting it.

Citation checking is exhaustive. Every `Assembly:NNNN` reference is confirmed to
land on the line the sentence claims; sampling is forbidden. This is a standing
rule rather than a precaution — every citation error found in this project so
far sat one to five lines off its target, which is precisely the error a sample
misses.

### `ckdocs-wording-attacker`

The added and changed prose, sentence by sentence, with two questions asked of
each: *for which configurations is this literally true?* and *what does this
sentence claim that the code does not support?*

It hunts four named classes, all of which have actually occurred:

| Class | Shape |
|---|---|
| Understatement | the function does more than the sentence credits it with |
| Wrong scope | true of one configuration, written as true of a category |
| Overreach | the claimed set is not the set the code touches |
| Runtime claim as code fact | stated in the indicative, derivable only by observation |

Findings quote the offending sentence. A finding that cannot name a sentence is
not a finding.

### `ckdocs-repo-fit`

The only lane that reads the target repository rather than the decompile.

It covers house style — determined by inspection, not assumption, because the
conventions are unwritten: the repository uses no Markdown tables anywhere,
`{% hint style="..." %}` for callouts, tabs in the C# examples, and a YAML
frontmatter block carrying `description:`. It verifies claims made *about* the
repository's own content, which both verification passes explicitly flagged as
outside what they could check. And it enforces the two standing prohibitions:
no AI or assistant attribution anywhere in the change, and nothing specific to
the author's build environment — no macOS, CrossOver, Wine, or local tooling.

It also checks that the diff does not reach past what the change needs.

## Invariants

These distinguish the skill from a checklist, and each exists because its
absence cost something.

- **No lane receives an extracted claim list.** The raw diff, always.
- **Findings do not carry authority.** Every finding is re-checked against the
  source before it changes a word. In the run this design comes from, both
  verification passes were partly right and partly overreaching; accepting
  either wholesale would have introduced new errors while removing old ones.
- **`UNSUPPORTED-BY-SOURCE` is a real verdict.** Runtime-only claims are marked,
  not promoted to confirmations.
- **Citation checking is exhaustive.**
- **Confirmed findings go back to the handbook.** A defect found in PR text is
  usually a defect in `docs/ck/` too — the scope error above had been sitting
  there through two prior verification rounds. Fixing only the PR leaves the
  source of the next one in place.

## Hook binding

The gate is enforced by the existing hook pair, extended rather than replaced.

`pr-review-marker.sh` today writes a marker line only for agents whose type
begins `pr-review-toolkit:`. It gains a second recognised family, `ckdocs-`.

`pr-create-review-guard.sh` today requires one hardcoded agent
(`pr-review-toolkit:code-reviewer`) for every repository. The required set
becomes a function of the repository path: for `CoreKeeperModDocs`, all three
lanes; for everything else, unchanged. The guard already matches markers
per-repository, so the mechanism for this is present — only the requirement is
currently global.

The existing validity rule applies to each lane separately: every one of the
three needs a marker no older than HEAD's committer date. A new commit or an
`--amend` therefore invalidates the whole review rather than the last lane to
run, which is the intended reading — the lanes examine the diff, and the diff
is what changed.

Requiring all three is deliberately stricter than the toolkit's single-agent
rule. The toolkit designates one agent because most of its six are conditional;
here the set is small, fixed, and every lane always applies, so a partial run
has no legitimate reading.

The documented bypass (`# review-gate-checked`) stays exactly as it is: an
exception for a deliberate case, not a step in the normal path. A gate that is
routinely passed by exception is not a gate — the guard's own comments say so,
and this design does not weaken that.

## Layout

Skill and agents live in `~/.claude/`, alongside the hooks that enforce them,
rather than in a project directory:

```text
~/.claude/skills/ck-docs-review/SKILL.md
~/.claude/agents/ckdocs-source-verifier.md
~/.claude/agents/ckdocs-wording-attacker.md
~/.claude/agents/ckdocs-repo-fit.md
~/.claude/hooks/pr-create-review-guard.sh      (modified)
~/.claude/hooks/pr-review-marker.sh            (modified)
~/.claude/hooks/tests/                         (extended)
```

The alternative — `core_keeper/.claude/` — was rejected on a specific ground:
the fork is its own git repository sitting inside `core_keeper`, so a session
working in it may not resolve the parent project's `.claude/` at all. Global
placement removes the question. Placing anything inside the fork itself was
never an option: it has no `.gitignore`, so tooling committed there would travel
into a pull request.

## Out of scope

- Code quality of any kind. There is no code under review.
- The PR's tone, scope, or whether to open it. Those stay editorial decisions.
- Any other repository. `pr-review-toolkit` remains the gate everywhere else,
  unchanged.

## To verify during implementation

Two assumptions in this design are cheap to check and expensive to get wrong,
and neither has been tested yet:

1. That a globally-defined agent is dispatchable from a session whose working
   directory is the fork.
2. That the guard's repository resolution yields the fork's path — and not
   `core_keeper`'s — when a command is run from inside the nested repository.
   The guard reads `git rev-parse --git-common-dir`, which should give the
   fork's own git directory, but a nested repository is exactly the arrangement
   where that deserves a test rather than an assumption.
