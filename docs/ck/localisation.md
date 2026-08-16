# Localisation

Core Keeper does not render mod text from your mod's AssetBundle. It renders it
from a single, game-wide table that every installed mod writes into once, and
the merge is first-write-wins. Read this chapter before you ship translated
text, and again the moment you *change* a string and the game keeps showing the
old one.

## Where mod text actually comes from

At load time the game exports **every** mod's localisation terms into the
game-wide I2 Localization source:

```text
<Steam>/steamapps/common/Core Keeper/localization/Localization.csv
```

At runtime the game renders from **that CSV**, not from the bundle. The two
layers are decoupled: your bundle can be perfectly fresh while the CSV row it
was supposed to populate is stale, or absent.

The CSV is tab-separated, one row per term:

| Column | Content | Example |
|---|---|---|
| 1 | Term key, `<Namespace>/<Leaf>` | `FasterTalents-Config/_hint` |
| 2 | Term type | `Text` |
| 3 | Flag | ` [new]` |
| 4… | One column per language, English first | `Talent + XP tuning`, `Talent- + XP-Feineinstellung` |

The whole file is a regenerable accumulator — no shipped base block lives in it.
A typical installation has roughly 8,000 rows, essentially all of them carrying
` [new]`; the handful without it are split artifacts of multi-line values, not
a hand-authored core. That matters, because it makes deleting the entire file a
safe repair: the game rebuilds it in full on the next launch — base game *and*
every installed mod — from the current TextDataBlocks.

Lookup happens through `API.Localization.GetLocalizedTerm(term)`. It returns
null for a term the table does not know, and the conventional mod-side helper
falls back to the raw term. So **missing localisation is not blank text — it is
the raw key rendered on screen**, e.g. `ItemChecklist-General/Shown` where the
UI should read `128 shown`. Every failure mode below surfaces either as a raw
key or as the wrong-but-plausible previous string.

## First-write-wins: new terms appear, changed terms do not

The export is additive. A term the CSV already contains is **not** refreshed
when your bundle changes its value.

| Change you made | What the player sees |
|---|---|
| Added a new term | The new text, on the next launch, for everyone — no repair needed |
| Changed an existing term's value | The **old** text, indefinitely |
| Removed a term | The old row stays; the string keeps rendering |

**Trap:** this is the single most confusing symptom in the whole area, because
the two halves of a translation pass behave differently. Add five strings and
edit one, and the five appear while the one silently does not. Nothing in the
build or the log is wrong — the bundle contains exactly what you authored, and
verifying the bundle (below) will confirm it and tell you nothing about the
problem.

The per-mod export is re-triggered by the game seeing a new modfile version. A
locally installed development build pinned to a fixed modfile version never
provides one, which is why the dev loop is where this bites hardest: rebuild,
cold start, cold start again — the old text survives all of it.

**Repair, in order of preference:**

1. **Delete the whole CSV**, then cold-start. The file is fully regenerable (see
   above), so this is the blunt but robust fix, and it is what a development
   install should do automatically every time it deploys a loc-shipping mod.
2. **Delete just the affected rows.** The game re-adds missing terms from the
   bundle on the next launch — but between deletion and re-export the term falls
   back to its raw key, which is a poor state for anything user-facing like a
   settings row.
3. **Edit the stale rows in place.** Back the file up first (it is around 2.9 MB)
   and assert the old string is unique before any byte-level replace.

## The four ways localisation has shipped broken

All four are the same defect in different clothing: some path touches one of the
two layers and not the other. Guard each one explicitly — none of them announces
itself.

### 1. The stale development loop

You edit a value, rebuild, cold-start, and the old text renders. The bundle is
correct; the CSV row is stale. This is first-write-wins, above. The fix belongs
in the install step, not in your fingers: clearing the CSV must be part of
deploying any mod that ships localisation.

### 2. A publish path that does not regenerate the table

The generated localisation assets are produced by a generation step, and the
bundle packs whatever those assets happen to be on disk. If your **build** path
runs that step but your **publish** path does not, publishing packs whatever the
last build left behind — from whichever tree that build ran in.

This shipped to real subscribers: a release went out with three of ten terms
missing from the bundle entirely, because the generated assets on disk were
frozen at a state from a different working tree. The source files had all ten.
The mod rendered raw keys for the three, which reads to a user as "the mod is
half-translated".

**Rule:** every path that packs a bundle regenerates localisation first. A
generation step wired only into the build path is a latent shipped bug, not a
minor asymmetry.

### 3. A build with the inputs pointed at the wrong tree — zero localisation

The mirror image of #2, and it needs no stale files at all. If the generator
writes its output into one tree while the bundle is packed from another — the
classic cause is a secondary working tree that inherits its configuration from
the parent directory, so output paths resolve to the main tree while the build
correctly packs the secondary one — the shipped bundle contains **no**
localisation assets whatsoever. Not stale ones. None. Every string in the mod
renders as its raw term key.

**Why it stays invisible:** the configuration is not *missing*, so a
"localisation not configured — skipping" log line never fires. It is a perfectly
valid path to the wrong tree, and no ordinary build step compares the generator's
output directory against the tree being packed.

**The guard that catches it:** after the asset refresh, assert that the first
term's asset exists **and is fresh** under the tree Unity actually packs —
`Application.dataPath/<ModName>/Localization/Generated/`, which follows the
symlink at the OS level and therefore makes no assumption about the working
directory. Existence alone is not enough: an earlier correct build leaves a
complete asset set behind in the symlinked tree, so a mere existence probe stays
silent on exactly this failure. Take the freshness stamp a few seconds *before*
generating, so clock and filesystem skew can only widen the "fresh" window —
erring in the other direction fails good builds.

### 4. An uninstall that leaves dead rows behind

Removing a development build without clearing the CSV leaves that build's terms
in the shared table. The bite comes in the exact transition where it hurts most:
uninstalling the dev build and subscribing to the published one. Any term whose
value changed in between keeps rendering the dev-era text, because first-write-wins
sees the row already there. New terms are unaffected, as always.

**The transferable lesson:** when you write a teardown, count the *write*
operations in the setup, don't read its summary comment. The one write the setup
did not document is precisely the one the teardown will forget.

## Verify per build that localisation is in the bundle

This takes fifteen seconds and catches #2 and #3 before anything leaves your
machine.

`ModManifest.json`'s `files[]` lists the bundle **file**, not its contents. The
sibling `*.assetbundle.manifest` lists the bundle's **contents**, in plaintext
JSON. Count the generated localisation entries in it:

```bash
grep -c Localization/Generated "<install-path>/<Mod>/Bundles/<Mod>_Windows.assetbundle.manifest"
```

A real pair of numbers from the failure in #3 and its fix:

| Build | Assets in bundle | Of those, localisation |
|---|---|---|
| Broken (wrong tree) | 11 | **0** |
| Fixed | 99 | 88 |

Zero is the unambiguous signal. A plausible-but-low count means you are looking
at a bundle that predates your change — check its real modification time with
`os.path.getmtime` rather than parsing `ls`/`stat` output, whose field layout
shifts under a non-English locale.

To confirm a specific *string* rather than a count, you have to decompress: the
bundles are LZ4-compressed, so plain `strings` or `grep -a` produce
false negatives. Load and byte-grep instead:

```python
import UnityPy

env = UnityPy.load(path)
blob = b"".join(bytes(o.get_raw_data()) for o in env.objects)
assert b"Talent + XP tuning" in blob
```

Two false-proof traps are worth naming, because both have wasted time here: a
`git show <tag>:<file> | grep` pipeline returned a false negative where the same
grep standalone found the string, and grepping an installed bundle that turned
out to be older than the build. Re-run any negative result as a bare command
against a file whose mtime you have checked.

Finally, keep the full build log. The generation step names its target directory
outright, and that single line is what distinguishes "wrote to the wrong tree"
from every other explanation — a build run without a captured log leaves you
guessing. See [the build workflow](../../README.md) for how builds and installs
are driven.

## Empty, contentless, missing — three inputs, three different outcomes

The generator produces "no terms" for three completely different reasons, and
collapsing them into one behaviour is how localisation ships silently broken.
Treat them separately:

| Input state | Correct behaviour | Why |
|---|---|---|
| Term table is **empty** | Skip generation **and** delete whatever a previous run wrote | Skipping alone would keep shipping the last generated assets, so emptying a table would have no effect on the built bundle |
| Table **has content but yields no term** | Fail the build | A term is a leaf; namespace headers alone define nothing. The mod builds, ships, and renders raw keys |
| Input file is **missing** | Fail the build | A mod configured for localisation pointing at nothing is a contradiction; a silent skip ships text that quietly fell back to raw keys |

The first row is the one people get wrong. "Nothing to do" is not the same as
"do nothing" — an earlier run's output sits in the tree Unity packs, so a bare
skip is indistinguishable from a successful build of stale content. The cleanup
is the whole point of the rule.

The second row is why "no terms produced" cannot simply be a warning. A file
full of structure and no leaves looks authored and produces exactly the same
on-screen result as an empty bundle: raw keys everywhere.

There is a pleasant consequence once these three are separated properly: because
a wired-but-empty table is a legal, silent state, a mod can carry its
localisation wiring from its very first commit, with a fully commented-out
template as its term source. The first localisation step then is *writing a
term*, not wiring anything up — and nothing about that empty state can ship
stale assets.

## Term-key conventions

A term key is `<Namespace>/<Leaf>`, and that concatenation is the CSV row key.
Because the table is **game-wide and shared by every installed mod**, keys
collide across mods unless you prefix them. Two conventions follow:

| Namespace kind | Shape | Example |
|---|---|---|
| Mod-owned | `<ModName>-<Category>` | `ItemChecklist-General/Shown`, `FasterTalents-Config/_hint` |
| Shared with the game | `<SharedNamespace>` with a mod-prefixed leaf | `ControlMapper/ItemChecklist-CancelTrackingPC` |

`ControlMapper` is the shared namespace for rebindable controls, so a keybind's
terms must carry the mod name in the **leaf**, not the namespace. Registering
the binding itself — categories, descriptions, and how the options menu presents
them — belongs to the [UI framework](ui-framework.md).

**Write leaf keys unquoted** in the term source — the settings-menu framework's
consumer contract requires it. Leaves are not restricted to identifier-shaped
names; a leading underscore such as `_hint` is fine.
