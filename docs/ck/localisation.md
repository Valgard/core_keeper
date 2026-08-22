# Localisation

Core Keeper resolves mod text through two localisation sources, and the one your
AssetBundle feeds is the *second* of them. The first is a single, game-wide
table on disk that every installed mod writes into once, and it shadows the
bundle indefinitely. Read this chapter before you ship translated text, and
again the moment you *change* a string and the game keeps showing the old one.

## Where mod text actually comes from

At load time the game exports **every** mod's localisation terms into the
game-wide I2 Localization source:

```text
<Steam>/steamapps/common/Core Keeper/localization/Localization.csv
```

I2 holds two sources and takes the first one that knows the term.
`LocalizationManager.Sources[0]` is loaded from that CSV; `Sources[1]` holds the
game's own terms plus every mod's `TextDataBlock`s out of the bundles. So a CSV
row **shadows** whatever your bundle says, while a term the CSV has never seen
resolves from the bundle-derived source — and is copied into the table on that
same launch. Either way the two layers are decoupled: your bundle can be
perfectly fresh while the CSV row it was supposed to populate is stale.

The CSV is tab-separated, with a header row naming the columns and one row per
term after it:

```text
Key	Type	Desc	English	German	Japanese	Korean	Spanish	Chinese (Simplified)	Thai
```

| Column | Content | Example |
|---|---|---|
| `Key` | Term key, `<Namespace>/<Leaf>` | `FasterTalents-Config/_hint` |
| `Type` | Term type | `Text` |
| `Desc` | The term's description — CK appends ` [new]` to it for every term it auto-adds | ` [new]` |
| 4… | One column per language, English first | `Talent + XP tuning`, `Talent- + XP-Feineinstellung` |

The whole file is a regenerable accumulator — no shipped base block lives in it.
A typical installation holds roughly 7,500 terms, essentially all of them
carrying ` [new]`. The auto-add pass appends that suffix unconditionally — a
term that already carries its own description still ends up as `"<description>
[new]"` — so the handful of rows without it never went through that pass at all:
their `Desc` came from a CSV imported through [the escape hatch below](#the-escape-hatch-ship-your-own-localizationcsv), not from
the auto-add. A value may contain newlines, so a term can span several lines of
the file — a line count is not a term count. That matters, because it makes
deleting the entire file a safe repair: nothing renders *from* it that the
bundle-derived source does not also hold, and when the game does rewrite the
file it writes the whole table again — base game *and* every installed mod —
from the current TextDataBlocks.

**Two conditions gate that rewrite, and a full delete trips the second one.**
The import and the rewrite are one block of startup code, skipped whole under
`-safemode` — a flag you may never have typed, because the game restarts itself
with it after an init failure with mods loaded. And the rewrite happens only
when the import left at least one term in the CSV-backed source: `PostInit`
returns `false` on an empty source, and the file is written only when it returns
`true`. With the file deleted there is nothing to import, so unless some mod
seeds terms through [the CSV route below](#the-escape-hatch-ship-your-own-localizationcsv), the file simply stays gone. **An absent
`Localization.csv` is a healthy state, not a failed repair** — every term
renders from the bundle-derived source either way.

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
| Added a new term | The new text, on the same launch, for everyone — no repair needed |
| Changed an existing term's value | The **old** text, indefinitely |
| Removed a term | The old row stays; the string keeps rendering |

**Trap:** this is the single most confusing symptom in the whole area, because
the two halves of a translation pass behave differently. Add five strings and
edit one, and the five appear while the one silently does not. Nothing in the
build or the log is wrong — the bundle contains exactly what you authored, and
verifying the bundle (below) will confirm it and tell you nothing about the
problem.

The merge runs on every launch and knows nothing about versions. It walks the
game's own term list and skips any term the table already holds —
`if (customLanguageSource.ContainsTerm(...)) continue;` — so a term is frozen at
the first value that ever reached the CSV, on your machine and on every player's
alike. **Republishing the bundle does not unfreeze it.** The dev loop is merely
where you *notice* it, because you change strings often: rebuild, cold start,
cold start again — the old text survives all of it.

**Repair, in order of preference:**

1. **Delete the whole CSV**, then cold-start. The blunt but robust fix, and what
   a development install should do automatically every time it deploys a
   loc-shipping mod. Whether the file comes back depends on the two conditions
   above; the repair works either way, because the bundle-derived source is what
   renders once the stale rows are gone.
2. **Delete just the affected rows.** The game re-adds missing terms from the
   bundle on the next launch — but between deletion and re-export the term falls
   back to its raw key, which is a poor state for anything user-facing like a
   settings row.
3. **Edit the stale rows in place.** Back the file up first (it is around 2.9 MB)
   and assert the old string is unique before any byte-level replace.

All three are repairs you carry out on one machine. To reach a player who
already has the frozen row, you need the one route the game itself re-reads
every launch.

## The escape hatch: ship your own `Localization.csv`

The accumulator is not the only file the game reads at startup. For every mod it
has loaded, the loader also looks for a `Localization` directory in that mod's
**installed** directory — a sibling of `Scripts/` and `Bundles/` — and imports
the `Localization.csv` inside it. That import runs in I2's **Merge** mode, and
Merge is the mode that *overwrites*: `AddNewTerms` is the only one that skips a
term the source already holds. A value shipped this way is therefore re-applied
on every launch, on every player's machine, and first-write-wins never touches
it.

The startup order is what makes that work:

1. the CSV-backed source is cleared and the game-wide `Localization.csv` is
   imported into it;
2. each loaded mod's `Localization/Localization.csv` is merged in **on top** —
   overwriting whatever the accumulator had for those terms;
3. the skip-if-present pass adds every term still missing, from the game's own
   terms plus the bundles' `TextDataBlock`s;
4. the whole source is written back out over the game-wide CSV.

Step 4 is why this breaks the freeze rather than working around it: the merged
value lands in the accumulator as well. It is also why a mod shipping a CSV is
what re-creates the accumulator after you delete it — with no such mod
installed, `PostInit` returns at its entry on an empty source, so step 3 never
runs and step 4 never happens.

Two consequences follow from the same mechanism. A term that exists *only* in
this file still renders — the CSV-backed source is a lookup source in its own
right, so text shipped this way needs no `TextDataBlock` behind it at all. And
Merge does not distinguish your terms from the game's, so a row keyed on a
base-game term overwrites the game's own string.

**Getting the file into the build:** put it at `Localization/Localization.csv`
inside your mod's folder in the Unity project. `ModBuilder` copies every `.csv`
under that `Localization` directory into the built mod directory verbatim and
lists it in the generated manifest's `files[]`. The loader imports only the
file named exactly `Localization.csv`; any other `.csv` ships and is never
read.

**Trap: a locally-placed build can silently carry no `Localization/` at all.**
The loader looks for that directory inside whatever directory it resolves for
the installed mod — the same directory `Scripts/` and `Bundles/` live in. If
that directory does not carry a `Localization/` subfolder, the merge step
never sees a file to import — no error, no log line, and the escape hatch just
looks broken. This is a property of the loader, not of any particular install
step: whatever places a local build has to carry `Localization/` across, and a
packaging step that copies only the manifest, `Scripts/` and `Bundles/` drops
it without a word.

**The format is the accumulator's own** — tab-separated, a header row whose first
cell reads `Key`, then `Type` and `Desc`, then one column per language *matched
by name*. A language name the game does not know is not rejected; it is appended
to the source as a new language. The accumulator's own column set is not fixed
by the game either: `PostInit` only ever adds terms, never languages, and
`Sources[0]` starts out with none at all — so whichever CSV reaches it first is
what seeds its language columns. Published mods use that latitude: one ships
the game's own language set exactly, another a 13-language superset.

**Trap: a malformed file imports nothing and says nothing.** The importer bails
out with a `"Bad Spreadsheet Format"` return value when the header row does not
split into more than one cell, or when its first cell does not contain `Key`,
and CK discards that return either way — only a thrown exception reaches the
log. The likelier trigger is the first half of that check: CK's reader splits
only on tabs, so a comma-separated file collapses the whole header row into a
single cell. That cell's text still contains `Key`, but the row never clears
the more-than-one-cell half of the guard, so the import bails anyway — exactly
the mistake a comma-separated file makes. The `Loading extra localization from
<path>` line proves the file was found, not that one term came out of it.
Confirm by looking for the terms in the rewritten accumulator after the
launch.

**What it costs:** a second term source beside the generated `TextDataBlock`
assets, in a format nothing validates, and the two can disagree silently. The
generated-asset route keeps one source of truth, which is why it stays the
default — this file is the answer to the one problem that route cannot solve. The
mechanism above is read off the loader, the importer and the SDK's `ModBuilder`,
and published mods do ship such a file; no build described in this chapter
produces one.

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

This shipped to real subscribers: a release went out missing four terms — three
leaves of one namespace plus a `ControlMapper` keybind term — because the
generated assets on disk were frozen at a state from a different working tree.
The source files had all of them. The mod rendered raw keys for the four, which
reads to a user as "the mod is half-translated". Note that the loss spanned two
namespaces: checking one namespace's term count is not a check.

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
bundles are LZMA-compressed, so plain `strings` or `grep -a` produce
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
guessing.

## Generating the term assets

Mod text reaches the bundle as generated `TextDataBlock` assets. The obvious way
to produce them — enumerate the game's own localisation data blocks through the
SDK's editor API and write terms through it — cannot work.

**Trap:** `LanguageDataBlock` does not exist at build time. Both
`ScriptableDataEditorUtility.GetCachedDataBlocks<LanguageDataBlock>()` and
`AssetDatabase.FindAssets("t:LanguageDataBlock")` return **zero** results — not
only in `-batchmode`, but in a fully loaded interactive Editor as well (checked
across 600 `Update` ticks). These assets are loaded by the game's own
ScriptableData layer at runtime, not by the AssetDatabase.

The consequence for any generator: it cannot go through the real CK-SDK
localisation API and has to **template raw `.asset` YAML** instead. The one
piece of runtime knowledge it needs — the map from language address to ISO code
— must be captured once from a runtime dump and carried in the generator (13
runtime languages, `en` primary).

**CoreLib's `LocalizationModule`** covers the same ground and is the obvious
shortcut past all of this. Weigh it before you take the dependency: its source
carries a `//TODO Remove Localization Module?` comment. That is the CoreLib
author's stated intention, not evidence of removal — but it is why the route
described in this chapter (your own term source, generated into `TextDataBlock`
assets, read back through `API.Localization.GetLocalizedTerm(term) ?? term`) is
the established one here.

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

**Write leaf keys unquoted** in the term source. The leaf is taken verbatim
while only *values* are unquoted, so `"10":` bakes the quote characters into the
term key and the string renders on screen as a raw key. Numeric-looking leaves
are where this bites, because quoting them is the natural YAML instinct. Leaves
are otherwise unrestricted; a leading underscore such as `_hint` is fine.

## Feeding CK's own tooltip with a mod term

Item tooltips localise themselves, which makes it look as though handing CK a
term key is enough. It is not, and the reason is in the mechanism: the
`UIelement` hover virtuals return **raw CK loc keys** — `Items/AncientCoin` —
and CK's own localiser resolves those.

**Trap:** that localiser does not see mod-authored terms. Return your own term
key from a hover virtual and the tooltip renders the key verbatim on screen.

Resolve the term yourself first, with `API.Localization.GetLocalizedTerm`, and
pass the **already-resolved** string with `dontLocalize` set so CK's localiser
leaves it alone. Which hover virtuals exist and how they are overridden belongs
to the [UI framework](ui-framework.md).

## Reacting to a language change

`I2.Loc.LocalizationManager.OnLocalizeEvent` is the hook for rebuilding derived
state — cached strings, composed labels — when the player switches language.

**Trap:** the event is the last thing `DoLocalizeAll` does, after every
`Localize` component in the scene has already been re-localized — you are called
from inside that pass, not after it. Doing the real work synchronously in the
handler throws a `NullReferenceException` out of
`PlayerController.GetObjectName` — once per language switched.

The shape that works:

1. In the handler, set a pending flag and return. Nothing else.
2. Do the work on the next `IMod.Update` tick. Deferring also coalesces rapid
   switches, so clicking through the language list costs one rebuild rather than
   one per click.
3. Guard that work on `Manager.main.player != null` — a language switch on the
   main menu has no ECS world.
4. **Consume the flag even when the guard skips the work.** A flag left set
   survives into a later tick and fires a rebuild against unrelated state.
