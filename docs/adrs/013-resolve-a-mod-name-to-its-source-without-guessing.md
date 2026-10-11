# Resolve a mod name to its source path, refuse to guess, and keep the mirror out of the repository

## Context and Problem Statement

Every installed mod on this machine ships readable source, and the path pattern
is documented in the handbook twice. What was missing is the step from a
**name** to the concrete directory, and that gap is the whole distance between
"the pattern is documented" and "an agent can read a dependency's source
without searching for it".

The cost was measured rather than estimated. Of 23 subagent dispatches aimed at
one dependency's source, 19 were not told where it lives; seven fell back to
scanning the filesystem, with run times up to twelve hours and forty-nine
minutes. That fallback is the worst possible one here specifically: several
network shares are mounted alongside a backup volume holding millions of
hard-linked entries, and a scan without an early exit does not stop at the
first hit — so a mod that *is* installed locally costs a full traversal, and a
mod that is not costs the same traversal and finds nothing.

## Decision Drivers

- The output has to be usable in a dispatch unchanged: absolute paths, and no
  identifier the caller had to know beforehand.
- A wrong answer must be impossible to mistake for a right one. An agent that
  reads a different mod's source reports confidently about it, and nothing in
  the report says which mod it read.
- Whatever the tool stores must not turn into repository data by accident.

## Considered Options

1. Query the live service per lookup and take its best match
2. Mirror the service's catalogue locally, and pick the best match offline
3. Mirror the catalogue, search every name space at once, and refuse to pick

## Decision Outcome

**Option 3.** `utils/mod_source.py <name>` searches the installed cache, this
workspace's own repositories and a local mirror of the service catalogue, and
reports what it knows: the source path, all three of the mod's names, its id
and its install state. A mod that is not installed can be fetched in the same
invocation, and its unpacked source is still at the path the output named after
the run finishes.

**On a genuine ambiguity it exits non-zero and prints every candidate** with its
id, names and install state. It does not pick. This follows the position this
repository already takes for Steam dependencies: a display title is not an
identity, more than one item can carry the same one, and a name match can
resolve silently to the wrong thing. Six of 368 keys are genuinely affected, so
the cost of asking is negligible against the cost of being wrong quietly.

The catalogue mirror and anything a download fetches live outside the
repository, under a cache directory. They are derived runtime state from a
foreign service, not data of this project.

### Consequences

- Good: a dispatch can carry the path, so the filesystem scan never happens.
- Good: lookups work offline once the mirror exists, and they can match slug
  and substring — neither of which the live search offers. Measured: the live
  query matches the title alone, so one mod's full title returns it fifth while
  its internal name and its slug return nothing at all.
- Good: an ambiguity is loud. The failure this prevents is the quiet one.
- Bad: a mirror goes stale, so a catalogue-only hit is provisional until a
  download settles it. One real case shows why: two different mods normalise
  onto the same key, one installed under its internal name and one not.
- Bad: the mirror needs the read-only game key out of the SDK's own config
  asset, which makes the SDK clone an input of a tool that otherwise only reads
  caches.
- Neutral: **the mirror must not live in `utils/`.** The repository's
  `.gitignore` excludes everything and re-includes that directory, so a mirror
  placed there would be tracked by default and every refresh would be a
  committable diff that says nothing about the project. The tracked data files
  in `utils/` are the opposite kind — curated, recording a decision somebody
  made. A resolution a human confirmed belongs there; a copy of someone else's
  catalogue does not.

## Pros and Cons of the Options

### Query the live service per lookup

- Good: never stale, and nothing to store or clean up.
- Bad: its search matches the title alone, so two of a mod's three names return
  nothing.
- Bad: every lookup needs the network, and a dispatch that cannot reach it
  falls back to the scan this exists to prevent.

### Mirror, then pick the best match

- Good: offline, fast, and always answers.
- Bad: the answer can be the wrong mod, and the report will not say so. That is
  the expensive failure mode, and it is silent.

### Mirror, search every name space, refuse to pick

- Good: the only option where a wrong answer cannot pass as a right one.
- Bad: it sometimes asks the caller to choose, and it carries a mirror that can
  go stale.

## More Information

The raw design spec this distils is in the commit that deleted it:

~~~
git show "$(git rev-list -1 HEAD -- docs/specs/2026-09-20-mod-source-lookup-design.md)^:docs/specs/2026-09-20-mod-source-lookup-design.md"
~~~

It carries the measurements behind each decision, the five acceptance criteria,
and the two smaller rules that follow from them: which file decides that an
installed folder is the current one, and why an own mod is identified by its
real id rather than by the fake one a dev install uses.

Why a dispatch must carry the path, and what happens when it does not, is [`CLAUDE.md`](../../CLAUDE.md);
that every installed mod is readable source, and where, is [`docs/ck/reverse-engineering.md`](../ck/reverse-engineering.md).
