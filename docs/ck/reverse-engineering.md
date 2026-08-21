# Finding things out

Core Keeper has no published API reference. Every non-trivial question — what a
system does before it writes a component, which field a prefab actually carries,
whether the behaviour you are looking at is the game's or your own patch's —
gets answered from the shipped build itself: a decompile of the game
assemblies, an extraction of the asset file, and a test in a running game. This
chapter covers how to produce those three, how deep to dig before calling an
answer settled, and which external sources are worth a look once the local
material is exhausted.

## Decompiling the game assemblies

The game code lives in the installation's `Managed` directory:

| Installation | Path relative to the install root |
|---|---|
| Client | `CoreKeeper_Data/Managed/` |
| Dedicated server | `CoreKeeperServer_Data/Managed/` |

These are the **game's** assemblies, not the SDK's. The SDK ships reference
copies for the Editor to compile against; the `Managed` ones are what actually
runs and what a mod binds to at load time.

**Do not go looking in `Assembly-CSharp`.** In most Unity games that is where
the game code is; in Core Keeper it is effectively empty (~11 KB). All game code
sits in named assemblies — the whole `Pug.*` family plus one assembly per ECS
feature, split by role (`<Feature>.Components`, `.Authoring`, `.Converters`,
`.Systems`).

### The flat checkout

Decompile with **`ilspycmd`** (the ILSpy .NET global tool) into a single flat
directory outside the repo — one `<Assembly>.decompiled.cs` per DLL, no
per-assembly subdirectories. Assembly-derived filenames never collide, and a
flat tree means one `grep` pass covers the entire game.

```bash
export PATH="$HOME/.dotnet/tools:$PATH"
GAME="<install>/CoreKeeper_Data/Managed"
CHECKOUT="<a directory outside the repo>"

ilspycmd "$GAME/<Name>.dll" -o "$CHECKOUT"          # whole assembly → <Name>.decompiled.cs
ilspycmd -l c "$GAME/<Name>.dll"                    # list types (c=class, e=enum, …)
ilspycmd -r "$GAME" -t <FullTypeName> "$GAME/<Name>.dll"   # one type, to stdout
```

Two flags earn their keep on large or framework assemblies: `-r "$GAME"`
supplies the reference path and silences resolver noise, and `-t <FullTypeName>`
emits a **single type** to stdout instead of the whole assembly — the right move
for a quick look that does not deserve a multi-megabyte file in the checkout.

**What to decompile.** The useful default is the game-authored core: every
`Pug.*` assembly, all the ECS gameplay assemblies, `PugMod.*`, `ScriptableData`,
`ObjectLookup`, `WorldGen`, `ZipSaveFolder` — the surface a mod binds against.
Beyond that, a handful of third-party libraries matter for modding and are worth
having locally:

| Assembly | Why you want it |
|---|---|
| `0Harmony` | The patching API itself |
| `RoslynCSharp`, `RoslynCSharp.Compiler` | The load-time compile pipeline |
| `Trivial.CodeSecurity` | The verifier that walks your mod's IL and rejects banned surface — the enforcement side of the [sandbox](sandbox-and-config.md) |
| `modio.UI`, `modio.UnityPlugin` | The mod.io plugin the SDK wraps |
| `I2` | The `I2.Loc` engine behind [localisation](localisation.md) |
| `Unity.Entities` | DOTS internals — `SystemBaseRegistry`, `WorldUnmanagedImpl.UpdateSystem` and the managed-vs-Burst dispatch chain that explains a misbehaving ECS patch |

Pure third-party libraries (PlayFab, Sentry, MessagePack, Rewired, Steamworks,
…) and the rest of the Unity/.NET framework are normally left out — but that is
**grep hygiene, not a barrier**. Anything excluded can be decompiled on demand
with the same command.

**Grep, do not read.** The big files are big: `Pug.Other` is ~16 MB / ~441k
lines, `Pug.ECS.Components` ~4 MB (the `*CD` component-data structs),
`Pug.Objects` ~1 MB, and `Pug.Base` holds the `ObjectInfo` class plus the
`ObjectType`, `Rarity` and `ObjectCategoryTag` enums.

**The ECS naming triple makes those greps precise.** An authored
`<X>Authoring` MonoBehaviour bakes through an `<X>Converter` into the runtime
`<X>CD` component data. Whichever end of a mechanism you happen to hold, the
convention gives you the other two by name — and it makes a negative finding
legible: the decompile has `DiggableAuthoring` and `DiggableCD`, and no
`DiggingSpotCD`.

### Record the build the checkout came from

An answer found in a decompile is true **for that build only**. Note the exact
version string (e.g. `1.2.1.5-8be0`) with the checkout and re-decompile after a
game update if a type you rely on may have moved.

Between patch releases the drift can be nil. Across the `1.2.1.4` → `1.2.1.5`
update, 119 of the 121 assemblies compared were byte-identical; only `Pug.Other` (42 lines)
and `PugMod.Loader` (4 lines) differed at all — and that difference was locally
applied host patches disappearing, not the game changing. That is **one**
measured update, and only at the fourth version component; nothing here says
anything about a minor or major one. The point of the version stamp is not that
drift is large; it is that you cannot tell without it.

**Trap: decompile from stock DLLs.** If the installation carries locally applied
IL patches — on macOS/CrossOver hosts it does, see [platforms and hosts](platforms.md)
— the decompile bakes those patches in and presents them as the game's own code.
A checkout made this way silently misrepresents `PugMod.Loader` and `Pug.Other`.
Verify the install through Steam to restore stock DLLs first, decompile, then
re-apply the patches to play.

**A `.prepatch-backup` is not stock by definition — it is stock by history.** It
holds whatever some earlier patch run found in place. The patcher used here
refuses to make that worse: it writes or refreshes a backup only when the live
DLL was fully unpatched, and against a part-patched one it leaves the backup
alone and tells you to Steam-verify instead. What no such guard can repair is a
backup that predates it, or one written against an older game version and never
refreshed because the patcher was not re-run while the DLL was stock. This is
why the same file can be untrustworthy at one point in time and a perfectly good
source at another, and why the question can only be settled per file and per
moment.

Settling it is cheap: decompile the backup and diff it against a checkout known
to be stock. A zero-line diff proves it. A backup verified that way is a
legitimate source and saves the Steam re-verify round trip.

**Trap: an anchor test proves nothing about a file it did not test.** Client and
dedicated server are separate installs, each carrying its own `Pug.Other`,
`PugMod.Loader` and `modio.UnityPlugin` backup, and every one of those files has
its own history. Verifying one and then decompiling from a *different* one leaves
exactly the gap the test was meant to close.

What the trap demands is a proof per file, not an anchor test per file. Two
others settle it after the fact, on the checkout you already have:

- **Diff the finished file against a known-stock counterpart.** A zero-line diff
  settles it outright, whatever backup it came from — that is how the server's
  `modio.UnityPlugin` is settled without ever anchor-testing its backup.
- **Read the patched region in the output.** Each patch has a recognisable shape,
  so its absence is the answer. Stock `StandaloneFilesystem.DeleteDirectory`
  (`Pug.Other:435027`) reads `Directory.Delete(Rel2Abs(path), recursive: true)`
  and stock `SystemIOWrapper.DeleteDirectory` (`modio.UnityPlugin:39200`) reads
  `Directory.Delete(path, recursive: true)` — neither is the iterate-and-delete
  rewrite the host patches install in their place.

**Trap: decompile from `Managed/`, never from AssetRipper's re-emitted
`GameAssemblies/`.** The extractor's re-emit changes synthetic variable names
and reorders members, turning a build-to-build diff into thousands of spurious
lines.

**The dedicated server needs its own checkout only in part.** 117 of 122
assemblies decompile identically for client and server. Only `Pug.Other`,
`WorldGen`, `Pug.Objects`, `Pug.Dev` and `PugMod.Loader` genuinely differ — for
everything else the client checkout already *is* the server's code.

**Trap: in a partial server checkout, a failed grep means "identical", not
"absent".** Because only the differing assemblies are kept, searching the server
directory for anything else returns nothing — which reads exactly like the type
does not exist on the server. For everything outside those five assemblies, the
client checkout is the authority. Do not search both trees.

**Trap: a differing MD5 or file size proves nothing.** Two separate Unity builds
stamp different MVIDs and timestamps, so a hash difference means nothing on its
own — 190 of the 356 shared DLLs differ by hash while being functionally
identical. The converse also happens: an assembly can be *smaller* on one side
and still decompile identically, because PE sections pad to a fixed boundary.
The test only runs one way — an **identical** hash does settle identity, and
that alone clears the other 166 for free. For everything that differs, only a
decompile diff answers the question.

**Maintenance:** regenerate a partial server checkout after every game update.
Otherwise the retained files are compared against a parent directory that has
moved on, and plain version drift reads as a client/server difference.

### Open-source dependencies: read the source, not a decompile

CoreLib is open source, which makes a decompile the wrong artifact — it goes
stale against the version actually loaded and reads worse than the original.
Determine the running version from `Player.log` (`Loading Core Library version
X`), then read the matching tag from `github.com/CoreKeeperMods/CoreLib`.
CoreLib also ships that identical source inside its own mod.io download, under
`Scripts/` in its cache directory — that copy is version-precise ground truth
for exactly the build the game loaded.

### Every installed mod is readable source

That property is not special to CoreLib. Source mods ship their `Scripts/*.cs`
and are compiled at load time, so **every mod you have installed is a readable
C# reference** sitting in its mod.io cache directory. When you want to know how
someone solved a problem — or why their mod conflicts with yours — read their
code rather than inferring from behaviour. Two locations hold the same sources:

| Location | What it is |
|---|---|
| `…/mod.io/5289/mods/<modId>_<modfileId>/Scripts/` | The downloaded mod file as published — the `<modfileId>` pins the exact release |
| `ModLoader/<ModName>/Scripts/` | What the loader extracted from it to compile — **client only**. A dedicated server extracts to `ModLoader/DedicatedServer/<GUID>/` instead, with a fresh GUID minted per mod load: the path differs on every start, and its name does not say which mod it holds |

The exception is a mod that ships a **precompiled assembly** rather than
sources — an asset-only mod, or one declaring a `.dll` under
`accessesExtraAssemblies`. For those you are back to a decompile.

The catalogue is enumerable beyond what you happen to have installed: the
mod.io REST API lists and downloads every published mod for game `5289`, which
turns "which mod touches this namespace" into a byte scan over the downloaded
set instead of a guess. **Exclude the bundled `CoreLib*.dll` files from such a
scan** — they carry the very strings you are searching for and report every
CoreLib-dependent mod as a hit.

**Trap: a reference mod's own helper types are not game API.** This is the
failure mode that makes the technique backfire. Reading a mod for a pattern is
sound; copying an identifier out of it is not, because you cannot tell from the
call site whether a type belongs to the game or to that mod.

The worked example is `ClientWorldStateSystem.HasRunAtLeastOnce`, which reads
exactly like a Core Keeper world-state API and is an ItemBrowser-internal
`ISystem` in `ItemBrowser.Common.Api` — unreachable from your mod. The
CK-native equivalent is waiting on `Manager.main.player`. The pattern is
persistent enough that a mod carried the wrong description in its
own notes long after its shipped code had stopped doing it.

Before adopting an identifier found in another mod, confirm it resolves in the
decompiled *game* assemblies. If it only appears in that mod's `Scripts/`, it is
that mod's, and you need the native mechanism underneath it.

**Trap: a shipped mod's source records the build it was written against.** Run
that same check even on identifiers that are unmistakably the game's, because a
mod's `Scripts/` say what Core Keeper exposed when its author last touched them,
not what it exposes now. PermaBreak ships a patch on
`PlayerController.ReduceDurabilityOfEquipment` — a method `PlayerController` no
longer has. The name itself is still in the build, which is what makes the
mistake easy to miss: it now lives as a private job method inside
`PlayerEquipment.ChangeDurabilitySystem`, whose `OnUpdate` is where the
durability reduction actually runs. A patch target lifted from another mod can
be plausible, confidently documented, greppable — and still bind against
nothing.

## Unpacking the game's resources

Prefabs, sprites, textures and every authored MonoBehaviour live in
`resources.assets` (~143 MB, plus a ~227 MB `.resS` stream): 130,172 objects, of
which 55,493 are MonoBehaviours, 7,918 Sprites and 6,954 Texture2Ds.

**Trap: the obvious Python route does not work.** UnityPy alone cannot read
Core Keeper MonoBehaviours, because the shipped build has **stripped type
trees** — only the ~44 base bytes survive, and `read_typetree` fails with
`Expected to read N bytes, but only read 44`. The `m_Script` PPtr still resolves
cleanly to `Namespace.Class.Assembly`, so UnityPy remains useful for identity
questions, but never for field values. UnityPy's `TypeTreeGenerator` plus
`TypeTreeGeneratorAPI` was evaluated as a way around this and rejected:
non-deterministic native `SIGSEGV` (uncatchable, the same class crashing only
intermittently), incomplete reads for inherited classes (`SpriteAsset` read
248 of 296 bytes), and `NullReferenceException` on many types.

**AssetRipper is the working tool** (verified with 1.3.14). It loads the real
`Managed/` assemblies through Cecil and therefore resolves every MonoBehaviour
to *named* fields — `HealthAuthoring → maxHealth: 300` — with no type tree
needed. On macOS clear the download quarantine (`xattr -dr`) before first run.
Drive it headless rather than through the GUI:

```bash
AssetRipper.GUI.Free --headless --port 5577
# then, against localhost (the service documents itself at /openapi.json):
#   POST /LoadFolder        {path}
#   POST /Export/UnityProject {path}      # ~40 s
```

**Scope trick — isolate `resources.assets` but keep Mono resolution.** Pointing
AssetRipper at the single `.assets` file yields `Unknown scripting backend` and
no field names. Instead build a throwaway `CoreKeeper_Data/` directory of
**symlinks** — `resources.assets`, its `.resS`, `globalgamemanagers*` and
`Managed/` — and `LoadFolder` that. AssetRipper recognises the `*_Data`
structure, loads the assemblies under the Mono backend, and exports only that
one content layer. Symlinks avoid duplicating 143 MB.

### What the export gives you

All 55,493 MonoBehaviours come through, **most of them embedded inside
`.prefab` files rather than standing alone**. 78.9 % carry named fields; the
remaining 21.1 % are fieldless ECS tag components (`IndestructibleAuthoring`
and its kind) — that is correct output, not a failure.

**Where a vanilla UI widget lives — check both places.** A menu is ordinarily
its own file. The export carries 4,607 `.prefab` files, 4,172 of them standalone
in `Resources/Assets/GameObject/`, and that is where `SettingsMenu.prefab`,
`Pause Menu.prefab`, `UISettings.prefab`, `ControlMappingMenu.prefab` and
`CreateWorldMenu.prefab` sit — 17 of the standalone prefabs have "Menu" in the
name — the kind of input a scripted importer takes.

In-world HUD widgets are the other case: some have no prefab file at all and
exist only as subtrees inside one giant `Resources/Assets/Resources/Global
Objects (Main Manager).prefab` — 6.5 MB, 2,626 GameObjects. `CoordinatesUI` is
one of those; nothing in the export matches `*Coordinates*`, and it lives in
that file from around line 7813 as five GameObjects.

So look for a standalone prefab first, and fall back to `grep -n "m_Name:
<Widget>"` in the Main Manager prefab. Lifting a subtree out of it means
carrying its dependencies by hand — [prefabs and rendering](prefabs-and-rendering.md) covers what has to
travel with it.

The export is a nominally openable Unity project, but next to a decompile
checkout most of it is redundant: `GameAssemblies/`, `Assets/Plugins/`,
`Packages/`, `ProjectSettings/` and `Assets/Scripts/` all duplicate what the
`.cs` files already say, and the data YAML is self-contained without them.
Deleting them trims the export to a lean data dump at the cost of it no longer
opening as a project.

**Script identity in the export.** The hybrid script export means
`m_Script.guid` is the **assembly** GUID and `fileID` identifies the class
within that assembly — not the per-script GUID a Unity author expects. Two
lookup tables reconstruct the mapping: assembly-GUID → assembly name, and
`(guid, fileID)` → full class name. The `fileID` is a portable hash over
namespace and class name, so it is identical in every install; the derivation is
in [database and baking](database-and-baking.md).

Because the GUIDs are AssetRipper's and not the SDK's, an extracted vanilla
prefab dropped into a mod loads with "Missing Script". The fix is a 1:1
assembly-GUID remap plus copying the transitive asset hull — the fileIDs need no
change at all. [Prefabs and rendering](prefabs-and-rendering.md) covers it; It is worth scripting; the [example repository](https://github.com/Valgard/core_keeper)
has one.

### What you may do with the export

Everything above extracts Pugstorm's assets. They stay Pugstorm's: Core Keeper
modding runs under a personal-use, non-commercial EULA, and an extraction is a
**reference and research artifact, not raw material to ship**.

In practice that means two habits. Keep the export out of version control with
an explicit ignore rule — it is large, it is not yours, and it is trivially
re-generated from the game you already own. And never let extracted art or audio
travel inside a published AssetBundle; a mod ships what you authored, plus
references to what the game already has.

Reading the export to learn how something is built, measuring a sprite to match
its conventions, or querying the data YAML to answer a question are exactly what
it is for.

## Answering a question about a prefab

Query the YAML. Do not reason about it.

Unity prefab YAML is multi-document with a per-file `%TAG !u!
tag:unity3d.com,2011:` directive and `--- !u!<classID> &<fileID>` document
headers. **Standard YAML parsers (PyYAML, `yq`) trip over the `!u!` tag handle
on documents 2..N**, because the `%TAG` directive only applies to the first
document — so the naive parse fails, and hand-tracing `fileID` references with
`grep`/`sed` is brittle enough to produce wrong answers quietly.
A purpose-built query tool sidesteps both — split on the `--- ` marker, parse
the `!u!<classID> &<fileID>` header itself, and hands only the standard-YAML
body to PyYAML, yielding `fileID -> (classID, body)`.

| Command | Answers |
|---|---|
| `<query> <prefab> names` | Every named GameObject → its fileID |
| `<query> <prefab> tree [Name]` | GameObject hierarchy with component types and active flags |
| `<query> <prefab> dump-go <Name>` | One GameObject's components, children and sprites |
| `<query> <prefab> sprite <fileID>` | The `m_Sprite` behind a SpriteRenderer |
| `<query> <prefab> verify` | Orphans, broken `m_Script`, dangling refs (exit 1 if any) |

The [example repository](https://github.com/Valgard/core_keeper) has one such tool if you would rather read than write it.

### Trap: prefab architecture constraints are usually asserted, not checked

Claims of the shape **"this needs N separate prefabs"** or **"these cannot share
one template"** are the ones that turn out to be false, and they are expensive
because a design gets built around them. Two corrections worth internalising:

- **Derived MonoBehaviour types do not each need their own prefab.**
  `AddComponent<T>()` at runtime lets several types share one prefab. The real
  cost of that route is different and smaller: you lose Editor-time wiring for
  that type's own serialised fields.
- **Differently-typed row templates can and do live in one prefab file.** In
  this repo's own settings-menu prefab, `SettingTemplate`, `ListTemplate` and
  `SectionTemplate` are siblings in the *same* `.prefab`, each with its own
  baked-in, Editor-wired component set. A single
  `grep -n "m_Name: .*[Tt]emplate"` settles the question.

The rule: grep the authored `.prefab` YAML first, state the constraint second.

## How deep to dig before calling a mechanism generic

There is a large difference between "the base class does it this way" and
"Core Keeper always does it this way", and only the second justifies building
on it. Before describing behaviour as vanilla, universal, or "CK's own", run
all four checks:

| Check | How | What it buys |
|---|---|---|
| No subclass overrides it | `grep ": ClassName"` across the whole decompile | Zero hits means nothing currently specialises the behaviour |
| The method is not `virtual`/`abstract` | Read the declaration | Closes the door *structurally* — a much stronger claim than "nothing overrides it today" |
| Count every call site | `grep -c` the method name; declaration + calls | A single call site proves there is no alternate path that could behave differently |
| No Harmony patch on it | Your own patch classes, and any sibling mod loaded beside yours | A private method can still be patched by name — otherwise you may be observing **your own patch** and calling it vanilla |

The last one is the trap that catches people who own the mod they are
investigating. A behaviour you introduced three sessions ago looks exactly like
game behaviour from the inside.

### A reference mod is precedent only if it does the same thing

"Another mod does it this way, so the approach works" is evidence only when that
mod met your problem. Tool Resizer was weighed as proof that a standalone ECS
system escapes Harmony ordering conflicts, and does not support the claim: it
adjusts numeric values and places nothing, so it never faces the ordering
problem it was being cited for. Check what the reference mod *does* before
letting it settle a design question — not merely which mechanism it uses.

### A negative finding needs the whole type body

"Type X does not have member Y" is the easiest claim in this codebase to be
confidently wrong about, and it is the premise of nearly every "therefore this
is impossible, we need a workaround" argument.

**`grep -n "struct X" -A 90 | grep Y` reports absence when the member merely
sits past line 90.** The decompiled ECS types are large enough for that to
happen routinely — `LookupEquipmentUpdateData` is around 190 lines, and
`EquipmentUpdateAspect`'s constructor signature alone is a single 33-parameter
line. A real case: a design concluded that neither available hook could reach
the inventory, because a 90-line window showed only `InventoryChangeBuffer`. The
field it needed, `containedObjectsBufferLookup`, sits ~135 lines into the same
struct, and `EquipmentUpdateSystem.UpdateJob.Execute` already reads it — which
was precisely the call the design wanted. A whole risk item and a
UX-degrading fallback were built on the false negative before it was caught.

Before asserting a member is missing:

- Print the **full** type body — find the next type declaration and slice to it
  — or grep the member name file-wide and check whether any hit falls inside the
  type's line range.
- **Cross-check against vanilla.** Grep for how the game solves the same need.
  If any vanilla code reads the thing you "cannot" reach, your negative is
  wrong, full stop.

## Observation beats derivation

A reproducible in-game observation outranks any conclusion drawn from reading
the decompile. When the two disagree, the decompile reading is missing
something — not the other way round. In this game specifically there are at
least four ways a correct reading of the source still describes something other
than what runs:

- The managed method you read is **Burst-compiled** at runtime, so your patch on
  it never executes ([Harmony and ECS](harmony-and-ecs.md)).
- The path that actually runs is **generated** ECS code, not the authored method.
- **Another mod** loaded beside yours patched the same target.
- Your checkout is from a **different build** than the game you are testing.

So when a symptom contradicts the model, do not re-derive the model. Look for
the assumption underneath it that was never actually verified, and then run one
test that isolates a single variable. Explaining the same observation away
twice is the signal to stop and go looking for that assumption.

**Design the test so the code can actually run.** An idle dedicated server sits
at `timescale = 0` and never simulates, so a patch that "never fires" there may
simply never have been reached — see [multiplayer and server](multiplayer-and-server.md).
A test that cannot distinguish "broken" from "not executed" proves nothing.

**Test every case a change unlocks, separately.** Where one edit enables
several variants — a bake-time change that permits building on both `Pit` and
`Water` tiles, say — the shared code path is a reason to *expect* they behave
alike, never evidence that they do. Exercise each variant in every verification
round and record it as tested; "follows from the common path" is a derivation,
not a result.

## When the local material runs out

Third-party Core Keeper documentation exists, but it is **generic and shallow
compared to what a decompile answers**. The loader's real behaviour, the Roslyn
sandbox's actual ban list, Burst interaction with Harmony, publishing mechanics
— none of it is written down outside this repo. Treat these as gap-fillers,
consulted after the repo and the decompile, and ahead of a general web search.

| Source | URL | Use for |
|---|---|---|
| Official Pugstorm modding site | `https://modding.corekeepergame.com/` | The vendor's own framing of the SDK |
| Modding wiki (community, GitBook) | `https://core-keeper-modding.gitbook.io/modding-wiki` | Orientation; `creating-mods/getting-started-modding` and `playing-with-mods/discovering-mods` |
| mod.io guide: SDK introduction | `/g/corekeeper/r/core-keeper-mod-sdk-introduction` | Editor-side workflow |
| mod.io guide: ECS component compendium | `/g/corekeeper/r/ecs-component-compendium` | The most useful of the guides for game-logic work — a catalogue of components, and the one that also settles negatives |
| mod.io guide: missing scripts | `/g/corekeeper/r/how-to-fix-missing-scripts` | The "Missing Script" symptom on prefabs |
| mod.io guide: dnSpy | `/g/corekeeper/r/how-to-use-dnspy` | IL inspection, interactive |
| mod.io guide: user guidelines | `/g/corekeeper/r/user-guidelines` | Publishing rules — see also [../publishing.md](publishing.md) |

**Cross-check the compendium, absences included.** ILSpy stays the authority,
but the compendium is a cheap second opinion on a decompile finding — and the
only external source that says anything about components which are *not* there.
It lists `DiggableAuthoring → DiggableCD` and no `DiggingSpotCD`, matching the
decompile exactly, so a name missing from both is far more likely genuinely
absent than mis-grepped. It also documents the `Authoring`/`Converter`/`CD`
convention itself, which is what makes the search grep-able in the first place.

**On IL tools:** the community guides point at **dnSpy**, which is a good
interactive browser when you want to click through call hierarchies. It is not
what the flat checkout is built with — `ilspycmd` exposes the same information
as text you can `grep` across every assembly at once, which is the operation you
actually perform ninety percent of the time.

**Fetching note:** GitBook serves JS-rendered HTML, so a plain fetch often
returns an empty shell; a reader proxy resolves it.

### Patch notes and version history

The Steam store news page (app ID `1621690`) also renders client-side, so
`curl` sees nothing. The full text of every announcement comes out of the Steam
API in one request, as BBCode:

```bash
curl -s "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid=1621690&count=40&maxlength=0"
```

This is the fastest answer to "what changed in the game" — the whole 1.x patch
history is in there. Two traps: the API's `gid` is **not** the `view/<id>` in
the store URL (correlate by title instead), and hyperlink targets embedded in
body text are lost in the API export — only explicit `[url=…]` BBCode survives.
