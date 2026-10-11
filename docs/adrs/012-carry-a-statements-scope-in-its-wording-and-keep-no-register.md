# Carry each handbook statement's scope in its wording, and keep no register beside the text

## Context and Problem Statement

The handbook's own preamble states its defect: an overreaching claim reads
exactly like a well-supported one, and nothing in the text distinguishes them.
Every chapter began as a finding about one mod, at one call site, on one host,
and what got written down was the generalisation of that finding. Where the
generalisation is too wide, the sentence has to be reworked the moment a
contradicting case appears.

So the programme that checks the handbook against the game needs two things
decided before it starts: how a statement says how far it reaches, and how the
programme knows which chapters it has already examined.

## Decision Drivers

- The goal is not to find wrong sentences. It is to bring every statement onto
  the scope its evidence actually carries, so that a later finding *extends* it
  rather than overturning it.
- Whatever marks a statement must carry information. A marker that sits on
  almost every sentence says nothing about any of them.
- "Nobody has examined this yet" and "this was examined and stayed open" must
  not be able to merge. Conflating them is the most expensive mistake available
  here.
- Process metadata must not end up in the product.

## Considered Options

For the form:

1. A per-statement evidence marker on every statement
2. Markers only on the doubtful, as reverse-engineering projects do
3. Scope carried in the wording, with a marker only where its absence misleads

For the bookkeeping:

4. A tracked register of examined chapters and a tracked pool of open questions
5. The chapters and the commit history as the register

## Decision Outcome

**Option 3 and option 5.**

Every statement carries its own scope in the sentence, with no markup and no
sigil — "every system this repo's mods disable Burst for" rather than a bare
universal. Two classes are marked because a reader would otherwise draw a false
conclusion: **measured**, for something observed in the running game rather
than forced by the code, and **unverified**, for something examined where
neither the decompile nor a measurement could settle it. A third state,
*unassessed*, deliberately never appears in the text.

There is no register file and no pool file. The chapter is the pool: a question
that stayed open is marked in the text, so grepping for that marker enumerates
every open question, and a separate list would be a second copy that can
disagree with the first. Git is the register: whether a chapter has been
examined is answered by its commit history, and which game build it was
examined against belongs in the commit message.

### Consequences

- Good: a sentence that says only what its evidence supports never needs
  revising. The next case either falls inside it or widens it.
- Good: the two states stay apart at no cost. No verification commit means
  unassessed; a commit plus the marker in the text means examined and open.
- Good: the backlog trend is computable after the fact — the commit history
  plus a count of the marker per revision — rather than maintained by hand, and
  it cannot drift from the chapters because it is derived from them.
- Bad: this is a rewriting pass, not a correction pass. Sentences that are
  perfectly true get touched too, because a sentence that happens to be right
  without saying how far it reaches does not meet the goal. That makes the
  programme far larger than "fix the errors" would have been.
- Bad: the game state an open question needs is written nowhere. Recording it
  would put process metadata into the product; recovering it costs reading the
  open passages before a measurement round.
- Neutral: the form has no precedent to copy. The research found no project
  auditing its own existing body of prose statements; where that exists it is
  automated against a decompilation, where the state of the work is a number
  rather than an editorial note.

## Pros and Cons of the Options

### A marker on every statement

- Good: comprehensive, and printed reference works do exactly this — survey
  reliability on nautical charts classifies every area, including the
  best-surveyed ones.
- Bad: those scales work because they are mechanically derivable from
  measurements. Where a scale needs judgement, even printed practice reverts to
  marking selectively.
- Bad: being grounded in the decompile is this handbook's normal case and its
  preamble already says so, so the marker would carry no information.

### Markers only on the doubtful

- Good: it is what the comparable genre does. The substantial
  reverse-engineering references carry no formal marker at all, and where
  marking happens it marks the doubtful rather than the established.
- Bad: it leaves the actual defect untouched. An overreaching claim is not
  doubtful-looking; that is the whole problem.

### Scope in the wording

- Good: needs no apparatus. Immunity against later findings is built into the
  sentence, which is the construction a dictionary uses when it writes "the
  earliest known attestation" — a new find moves the date and leaves the
  definition standing.
- Good: the handbook already does this in places without having decided to.
- Bad: it cannot be checked mechanically. Nothing fails when a sentence
  overreaches; only a reader notices.

### A tracked register and pool

- Good: the state of the programme is visible in one place.
- Bad: both restate something that exists somewhere better, and a second copy
  can disagree with the first.
- Bad: a list of ticked-off questions is route, not result — which is what this
  repository's own distillation rule asks for.

## More Information

The raw design spec this distils is in the commit that deleted it:

~~~
git show "$(git rev-list -1 HEAD -- docs/specs/2026-08-30-handbook-verification-programme-design.md)^:docs/specs/2026-08-30-handbook-verification-programme-design.md"
~~~

It carries both rounds of comparable-works research with their counts, the four
printed constructions that make a statement extensible, the per-chapter
procedure, and the chapter order.

The procedure as it is executed, including what a pass owes its commit message,
is the `ck-verify-chapter` skill. What the handbook is and is not — the witness
rather than the judge — is [`CLAUDE.md`](../../CLAUDE.md). The citation form the programme writes
in is [`004-symbol-anchored-handbook-citations.md`](004-symbol-anchored-handbook-citations.md).
