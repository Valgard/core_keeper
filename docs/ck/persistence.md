# Storing configuration and state

`System.IO` is denied to a mod's own sources — the whole namespace, down to
purely in-memory types such as `MemoryStream` (see [the sandbox](sandbox.md)).
That does not leave a mod without storage. The verification inspects references
in *your* code, so a call into an already-trusted assembly costs nothing, and
the loader ships a file API of its own for exactly this purpose.

What follows is the three routes that gives you for state a mod writes at
runtime, a fourth route for reading back a file a mod ships, what the rest of
the mod catalogue actually does, and how to write state without corrupting the
game's save.

## Storing configuration: three routes

In order of preference.

### 1. `API.ConfigFilesystem` — the default answer

`PugMod.API.ConfigFilesystem` is the loader's own file API. `PugMod.SDK.Runtime.dll`
holds only its interface, `IConfigFilesystem`; the real I/O lives in
`StandaloneFilesystem`, in the equally trusted `Pug.Other`. Either way, a call
to it is sandbox-free. It is the right answer for anything a `config.json`
would hold, it needs no dependency, and it is **initialised before any mod's
`EarlyInit`** — so you can read your settings at the earliest point of the [IMod lifecycle](mod-anatomy.md).

`IConfigFilesystem` (`PugMod.SDK.Runtime`) has eleven members — all of them:

| Member | Signature |
|---|---|
| `Read` | `byte[] Read(string path)` |
| `Write` | `void Write(string path, byte[] data)` |
| `FileExists` | `bool FileExists(string path)` |
| `DirectoryExists` | `bool DirectoryExists(string path)` |
| `CreateDirectory` | `void CreateDirectory(string path)` |
| `Delete` | `void Delete(string path)` |
| `DeleteDirectory` | `void DeleteDirectory(string path)` |
| `CopyDirectory` | `void CopyDirectory(string from, string to)` |
| `GetFiles` | `IEnumerable<string> GetFiles(string path)` |
| `GetAllFiles` | `IEnumerable<string> GetAllFiles()` |
| `GetFileTime` | `DateTime GetFileTime(string path)` |

Paths are relative to the API's root — the `mods/` directory every mod shares —
so by convention your own files carry your mod's name as their first segment;
nothing enforces it, and installed third-party mods deviate from it —
ConveyorTunnelMod writes `ConveyorTunnelMod_world_<key>_links.json` straight
into `mods/`:

```text
…/LocalLow/Pugstorm/Core Keeper/<platform>/<user-id>/mods/<ModName>/
```

That is the client's path. On a dedicated server, everything before `mods/` is
the server's own save root instead — see [where the saves live](savegame-formats.md#where-the-saves-live).

Four members are worth their implementation detail, which comes from
`StandaloneFilesystem` — the one implementation `API.ConfigFilesystem` is
constructed from, on the client and on the dedicated server alike:

- **`GetFileTime` is the only timestamp in the API**, and it is
  `File.GetLastWriteTimeUtc` underneath — **UTC**, so compare it against
  `DateTime.UtcNow`. It is what a staleness check or a migration ("is my file
  older than the save it belongs to?") has to be built on; nothing else here
  reports a time. It has no passing-load evidence behind it, unlike the API's
  well-trodden `Read`/`Write` pair — smoke-test it like any new surface.
- **`GetFiles` recurses.** It enumerates with `SearchOption.AllDirectories` and
  returns paths relative to the API root with forward slashes — and it filters
  out `.pugbackup` and `.pugtmp` siblings, so the backups described [below](#the-pugbackup-sibling--a-free-beforeafter-diff) are
  invisible to it. `Read` still opens them by name.
- **`GetAllFiles()` is `GetFiles("")`** — everything under the root, and that
  root is shared, so the result spans every mod that has ever written there. To
  see only your own, pass your mod's directory to `GetFiles`.
- **`DeleteDirectory` really deletes** (`Directory.Delete(path, recursive: true)`),
  and `CopyDirectory` copies recursively but with `overwrite: false`, so an
  existing destination file throws. Neither shares `Delete`'s behaviour of
  renaming the file onto its `.pugbackup` sibling.

**Trap: `Write` does not create missing directories — and fails silently when
they are absent.** There is no `mkdir -p` behaviour. A first-run `Write` into a
mod directory that does not exist yet raises `DirectoryNotFoundException`
internally, but `StandaloneFilesystem.Write` wraps its whole body in
`catch (IOException)` and only logs `Write failed: Could not find a part of the
path …`. Nothing propagates, so a `try/catch` around your call never fires and
the write silently does not happen. Call `CreateDirectory("<ModName>")` before
the first write.

**Trap: a `Write` that did not throw is not a `Write` that landed.** The
`StandaloneFilesystem.Write` path underneath ends in `catch (IOException) {
Debug.LogError(...) }` with **no rethrow**, and its inner `File.Replace` /
`File.Move` retry loop gives up after ten attempts with nothing but another
`LogError`. A full disk, a file locked by something else, and the host-side
filesystem faults covered in [platforms and hosts](platforms.md) are therefore
all invisible to your mod: no exception, no return value, nothing to branch on.
If the data matters, **read the file back** before you record the write as done
— above all before caching any "content unchanged, skip the write" hash.

The API is `byte[]` in and `byte[]` out, which means you serialise yourself.
`Encoding.UTF8.GetBytes` / `GetString` is the normal way to get a string across
that boundary, and `Newtonsoft.Json` covers the structured case — both are
sandbox-legal, and CoreLib uses exactly that pair. Newtonsoft needs
`accessesExtraAssemblies` in the manifest, though, which CoreLib sets: without
it the in-game compile has no reference to it ([the load-time sandbox](sandbox.md#what-is-not-banned)).

Hand-packing a line-oriented format (`id:count;`) through `(byte)char` /
`(char)byte` loops also works and is verified here, but treat it as a choice one
mod made rather than as a requirement: that loop only round-trips characters
below U+0100, and anything above truncates to its low byte without an error.

That this is genuinely sufficient is not theory: CoreLib itself is a sandboxed
source mod (`skipSafetyChecks: false`) with **zero** `System.IO` references,
and it persists `CoreLib.cfg` and `KeyBindsActions.json` entirely through this
API.

There is also **`API.Config`**, a typed store keyed by a `(mod, section, key)`
triple — `Get<T>` / `TryGet<T>` / `Set<T>` / `Register<T>`, the last with a
mandatory `description` — for simple scalar settings such as a tunable radius,
when you do not want to own a file format at all.

**Trap: an `API.Config` value is a file read, not a field.** Every entry of
`ModAPIConfig` (`Pug.Other:ModAPIConfig`) is a JSON file of its own at
`<mod>/<section>-<key>.json` (`Pug.Other:ModAPIConfig:GetPath`), and the `Value`
getter of the entry `Register` hands back reads and parses that file on every
access — it keeps the last read, but never answers from it. There is no change
event. Read it once and keep the result: the published mod Rail Network
(mod.io `6434348`) records in its source that two reads a frame were its whole
7 ms UI-update cost, even on the title screen. Two more things follow from the
getter. A missing or unparsable file reads as `default(T)`, not as the default
you registered. And because a failed read also clears the entry's cached copy,
the next assignment to `Value` dereferences nothing — so a hand-deleted or
corrupted file turns the following write into an exception rather than a repair.

### 2. CoreLib's `ConfigFile` — typed entries, at a price

CoreLib's `ConfigFile` sits on top of the same `API.ConfigFilesystem` and adds
typed entries, defaults, `AcceptableValueRange` constraints and a TOML-ish
`.cfg` on disk. You buy that with a **hard CoreLib dependency**, which your mod
must declare in its ModBuilderSettings `.asset` and which propagates to your
mod.io listing — see [mod anatomy](mod-anatomy.md) and [publishing](publishing.md).

Take this route when the typed-entry ergonomics are worth the dependency, not
because you assume route 1 cannot do it.

**Every `ConfigFile` in the process is readable — and writable — by every other
mod.** `ConfigFile.AllConfigFilesReadOnly` is a public static registry of every
`ConfigFile` any mod has created, and the entries behind it expose a full
non-generic read/write path. This is deliberate on CoreLib's side: the source
comment on `ConfigEntryBase.Scope` reads "Used by GeneralConfigMenu". It cuts
both ways — a settings-menu mod can enumerate and edit foreign settings with no
cooperation from their authors, and your own entries are exposed on the same
terms.

| Member | What it gives you |
|---|---|
| `ConfigFile.AllConfigFilesReadOnly` | every `ConfigFile` in the process |
| `cf.Entries` | `Dictionary<ConfigDefinition, ConfigEntryBase>` |
| `cf.ConfigFilePath` | the path passed to `ConfigFile`'s constructor — a mod's own choice, not a derived value |
| `ConfigEntryBase.SettingType` | the entry's declared type |
| `ConfigEntryBase.BoxedValue` | non-generic read/write path |
| `ConfigEntryBase.DefaultValue` | the declared default |
| `ConfigEntryBase.Description.AcceptableValues` | the range or allowed set |
| `ConfigEntryBase.GetSerializedValue` / `SetSerializedValue` | the on-disk string form |

Five things to know before writing against that registry:

- **Enums survive the serialized round trip.** TOML writes an enum as its
  *name*, so `GetSerializedValue` / `SetSerializedValue` carry enum tokens
  losslessly without a per-type code path.
- **A string does not, and the asymmetry runs the opposite way to the obvious
  one.** The same pair puts a `string` through `Escape` / `Unescape`, so what
  `GetSerializedValue` returns is the on-disk form. A quote or a control
  character is visibly altered on the way out (`"` → `\"`, a newline → `\n`)
  and restored exactly on the way back — those round trip losslessly. A
  **backslash** does neither: CoreLib's `Escape` emits it unchanged (a single
  `@"\"`, where upstream BepInEx doubles it) while `Unescape` still consumes
  it, so feeding `a\b` back through `SetSerializedValue` stores `a` + U+0008.
  Silent corruption, not a re-read, and nothing throws. For display or
  comparison use `BoxedValue`, which is unescaped; for a write it is not simply
  "the raw one" — its setter clamps against `AcceptableValues`, fires
  `SettingChanged` and, by default, saves the file. The reason any of this
  bites is that both types reach the same code: a routine written and verified
  against enum entries looks correct until a string entry arrives.
- **`AcceptableValueList<T>` cannot hold an enum — which does not mean an enum
  entry is unconstrained.** Its constraint is `where T : IEquatable<T>`, which
  no enum satisfies: `AcceptableValueList<SomeEnum>` fails to compile with
  CS0315 (verified, with `<int>` and `<string>` as controls). So a *member
  subset* cannot be declared this way. But `AcceptableValueRange<T>` constrains
  to `IComparable`, which enums do satisfy, and `AcceptableValueRange<SomeEnum>`
  compiles and constructs (verified) — an ordinal interval over the declared
  values, clamping silently rather than rejecting. `AcceptableValueBase` is
  public and abstract, so a third party's own subclass is a second route. Code
  reading a *foreign* constrained entry therefore has to expect an enum with a
  non-null `AcceptableValues`, and cannot tell which subclass it is without the
  reflection the sandbox denies.
- **The owning mod's display name is not part of the public surface, and
  `ConfigFilePath` is not derived from it.** `ConfigFile`'s constructor takes
  the path as a literal argument — CoreLib itself passes
  `"CoreLib/CoreLib.cfg"`, a settings-menu framework built here passes
  `"<ModId>/config.cfg"` — so a third-party mod need not follow either shape,
  and its first segment is only a convention to lean on, not a guarantee.
- **`BoxedValue` casts must be type-exact.** An `int` range entry is a boxed
  `int`, and `(float)` on it throws. Branch on `SettingType` — never on what
  the value looks like.

**`Scope` carries access semantics, and one of them can crash you.**
`ConfigEntryBase.Scope` is a `ConfigScope` holding an `accessLevel`
(`ConfigAccessLevel.ViewOnly` / `Client` / `Server` / `Admin`), a
`requireReload` flag meaning the change takes effect only after a restart, and a
`Changeable()` method.

**Trap: `Changeable()` reads `Manager.main.player`.** On the title screen there
is no player, so calling it there is a null-reference risk. Guard first:

```csharp
if (Manager.main == null || Manager.main.player == null)
    return; // no player yet — do not ask whether the entry is changeable
```

**Trap: the two ways to set a scope have opposite defaults.** Both of these
compile, and they do not mean the same thing:

```csharp
file.Bind(section, key, def, new ConfigDescription(key));                    // -> Server
file.Bind(section, key, def, "desc", ConfigAccessLevel.Client);              // -> Client
```

The first passes no scope at all, so `ConfigEntryBase` falls back to
`ConfigScope.Empty`, which is `new()` — and the `ConfigScope` constructor
defaults to `ConfigAccessLevel.Server`. The overload that takes the level
directly defaults to `Client`. **Omitting the scope is therefore not neutral: it
declares a server-authoritative setting.** For a purely client-side mod that is
the wrong claim, and it stays invisible until something actually reads the level.

**`ShouldSync` is `accessLevel > 0`**, so `ViewOnly` (`-1`) and `Client` (`0`)
are excluded and `Server`/`Admin` included. A consumer of the scopes uses it to
decide what crosses a process boundary at all.

**The vocabulary exists for a consumer, and nothing enforces it.** The doc
comment above `ConfigScope` reads *"Necessary information to ensure the normal
operation of the General Config Menu"* — CoreLib supplies the levels and
`Changeable()`, and leaves every consequence to whoever reads them. An entry's
scope is a declaration, not a lock: nothing in CoreLib prevents a write to a
`ViewOnly` entry.

**A dedicated server binds client-scoped entries too, and they mean nothing
there.** The server loads mods the same way the client does, so every `Bind` runs
and every entry lands in the server's own config file — including the ones
describing a HUD that does not exist in that process. They are artifacts, not an
authoritative copy: the client's entry of the same name is a separate instance,
and reconciling the two would overwrite something nobody asked about.

**Every write saves the WHOLE file, and the first one happens inside
`ConfigEntryBase`'s constructor — before `Bind` has registered the entry.**
Setting a value goes `ConfigEntry<T>.Value` → `OnSettingChanged` →
`ConfigFile.Save()`, and `Save` walks every entry in that file asking each for
`ToDescriptionString()` (`WriteDescription`). The constructor ends in
`BoxedValue = defaultValue`, which trips that chain for any default differing
from `default(T)`; only afterwards does `Bind` reach `Entries[definition] =
entry`. Three consequences, none of them local to the entry that causes them:

- **One entry that throws when described makes the whole file unwritable.**
  Every other entry in it silently stops persisting — the in-memory value
  changes, the `.cfg` does not.
- **A second such entry is never registered at all.** Its constructor's save
  hits the first one and throws before registration, so the entry does not
  exist: no row, no error of its own, and any code that catches around `Bind`
  sees only the exception, not the absence. Whatever enumerates that file is
  then one entry short with nothing to say why.
- **A failed save leaves the new value in memory.** The assignment precedes
  the save, so a UI that re-reads after writing shows the change as having
  worked. Only the next launch disagrees.

This bites specifically when a `AcceptableValueBase` subclass computes its
description rather than returning a literal — a plausible thing to write, and
the failure surfaces nowhere near it.

**Trap: another mod can switch your file's auto-save off.** The automatic saves
above hang on one public flag, `ConfigFile.SaveOnConfigSet`, which defaults to
`true` (`ConfigFile.cs:ConfigFile:SaveOnConfigSet:1`) and gates the save after a
`Bind` (`ConfigFile.cs:ConfigFile:Bind(ConfigDefinition, …):26`) and the save
after a value change (`ConfigFile.cs:ConfigFile:OnSettingChanged:6`) — not the
constructor's own save or an explicit `Save()`. The registry hands every file to
every mod, and General Mod Config Menu (mod.io modfile 8270186) sets the flag to
`false` at three places: `ModConfigMenu.Awake`, which runs when its menu is
created at the title screen, and `ConfigSyncSystem.OnCreate`, once per
simulation world — both skip files whose `ConfigFilePath` starts with `CoreLib`
— and `ModConfigMenu.RegisterFile`, with no such exception. It never sets it
back, so in a process with that mod loaded a foreign settings UI writes the new
value into memory and nothing reaches the disk; the next launch shows the old
one. Measured on 1.3.0.6 with Mod Settings Menu v1, which relied on the
auto-save: a changed setting did not survive a restart — on the title screen as
well as in a world, which the `Awake` site explains — and disabling General Mod
Config Menu alone made it stick. Call `ConfigFile.Save()` yourself after a write
whose persistence matters; it is not gated by the flag.

**Change notification and reloading are both there.** `ConfigFile.SettingChanged`
and the per-entry `ConfigEntryBase.SettingChanged` fire on every write, and
`ConfigFile.Reload()` re-reads the file from disk. Together they allow a split
that is otherwise awkward to build: the file as the user's stored preference,
the in-memory entry as what is in effect right now, and `Reload()` as the way
back when the temporary authority goes away.

#### Intercepting CoreLib's writes: replace `API.ConfigFilesystem`, do not patch

`ConfigFile.Save()` serialises the **whole file from memory** — every bound
entry through `GetSerializedValue()`, plus the lines it read but no entry claims
(`OrphanedEntries`) — and writes it with a single `API.ConfigFilesystem.Write`.
So a save of one entry rewrites every other entry of that file with its
in-memory value, whoever triggered it.

A mod that wants to hold back or alter such a write cannot do it with Harmony.
`ConfigFile` lives in CoreLib, outside the five assembly prefixes the patch gate
admits, and a refused target unbinds *all* of the mod's patches, not just that
one ([the gate](sandbox.md#harmony-attributes-are-exempt--hook-bodies-are-not)).
One level down it is shut as well: `StandaloneFilesystem`, the implementation
behind `API.ConfigFilesystem`, is `[DisallowPatching]`
(`Pug.Other:StandaloneFilesystem`).

What is open is the field itself. `API.ConfigFilesystem` is a public static
`IConfigFilesystem` that the game assigns once at startup
(`Pug.Other:Manager:EarlyInit:49`), and CoreLib reads it afresh on every call
rather than keeping a copy. A mod can therefore assign a wrapper in its own
`EarlyInit` that holds the original, forwards all eleven members, and
intercepts `Write(string, byte[])`: it may skip the write by not forwarding,
or rewrite the bytes first. The wrapper is plain managed code over a PugMod
interface, so the sandbox has nothing to refuse.

Measured on 1.3.0.6-6e73 (2026-10-17): a probe wrapper saw 235 writes from 25
files — CoreLib's own, PlacementPlus, and every settings-menu consumer among
them — and none bypassed it. A write it skipped left the file on disk
untouched, and a line it rewrote in the bytes arrived rewritten. Caveats:

- It sees only writes issued after the mod's `EarlyInit`; earlier ones, in
  practice startup saves, pass unseen.
- A mod that cached the original instance bypasses it. None did in the 25 files
  above, but nothing guarantees it, and mods stacking wrappers wrap each other
  in load order.
- It sees a path and bytes, not a caller. Naming who saved needs a convention
  of your own, because `System.Diagnostics.StackTrace` is on the deny list.
- An exception thrown from the wrapper breaks every mod's config writes, not
  just yours; catch, log, and forward unchanged.

### 3. `skipSafetyChecks: true` — last resort

Setting `skipSafetyChecks: true` in the ModBuilderSettings `.asset` disables
the verification entirely and gives you raw `System.IO`. It is for what the
first two routes genuinely cannot express.

Two costs: you lose the guarantee that your mod is inspectable-by-construction,
and the flag **feeds a derived mod.io tag** — the `Access Type` tag on your
published listing is computed from it, so flipping the flag re-tags the mod on
the next publish. See [publishing](publishing.md).

## Reading a file your mod ships

The three routes above are all for state a mod **writes** at runtime — a config,
a ledger, a cache. A file a mod **ships** — the `Conf/*.json` payload [mod anatomy](mod-anatomy.md#what-ships-and-what-the-loader-reads)
lists as one of the five kinds a build produces — is a different question, and
none of the three routes reach it: it never passes through
`API.ConfigFilesystem`, because the loader never wrote it there in the first
place.

`LoadedMod.GetFile(string path)` (`PugMod.SDK.Runtime:LoadedMod:GetFile:1`) is
the answer. It resolves `path` against the mod's own install directory
(`API.ModLoader.GetDirectory(ModId)`), rejects a path that escapes that
directory, and returns the file's bytes with `File.ReadAllBytes` — all inside
the trusted loader assembly, so referencing it costs nothing against [the sandbox](sandbox.md).

Reach it off your own `LoadedMod`, [resolved the usual way](mod-anatomy.md#reaching-your-own-loadedmod-and-asset-bundle):

```csharp
foreach (var mod in API.ModLoader.LoadedMods)
{
    if (mod.Metadata.name == ModName)
    {
        var bytes = mod.GetFile("Conf/settings.json");
        var text = Encoding.UTF8.GetString(bytes);
        break;
    }
}
```

This needs no `dependencies` entry and no `accessesExtraAssemblies` — the
payload already ships inside your own mod directory, and `GetFile` is a plain
method on the trusted `LoadedMod` wrapper, not a shipped `.dll`. See [mod anatomy](mod-anatomy.md#there-is-no-mod-version-at-runtime)
for `GetFile`'s other documented use — deriving a build identifier from the
install directory's name, since no version field exists anywhere in the loader's
view of a mod.

**It works on any loaded mod, not only your own.** Nothing in `GetFile`
(`PugMod.SDK.Runtime:LoadedMod:GetFile`) ties it to the caller: it returns null
when the loader knows no directory for that mod, and otherwise refuses only a
path that leaves the directory of the mod it is called on. So the `LoadedMod` of
another mod reads that mod's shipped files the same way, and a payload one mod
ships for another to find needs no dependency in either direction. That
containment test compares string prefixes with no trailing separator, so a
sibling directory whose name merely starts with the same characters passes it.
This is read from the source, not yet exercised across mods.

**`Conf/` is shared with the game's own data loaders.** At startup the game adds
every loaded mod's `Conf/` folder that exists to `Config.ConfFolders`
(`Pug.Other:ModManager:Init:24-27`), and five loaders in `Pug.Mods` read `*.json`
from fixed subfolders of each (`Pug.Mods:Factions`, `Pug.Mods:Fishing`,
`Pug.Mods:LootTable`, `Pug.Mods:SpawnTable`, `Pug.Mods:Talents`):

| Subfolder | Depth read |
|---|---|
| `Factions`, `Fishing`, `Loot`, `Loot/Fishing/Biome`, `Loot/Fishing/Water`, `Talents` | top level only |
| `Spawn/Initial`, `Spawn/Respawn` | every level below |

A `.json` the table covers is game data, and the game parses it as such. Any
other file — directly in `Conf/`, in a subfolder of another name, one level
deeper than a top-level-only folder, or not `.json` at all — is left to you.

## What the rest of the catalogue does

Useful if you are writing something that has to read foreign configuration, or
just want to know which conventions a user will already recognise. A survey of
the public Core Keeper catalogue on mod.io (game 5289) on **22 July 2026**:

| Measured | Count |
|---|---|
| Public mods | 254 |
| Declaring a CoreLib dependency | 68 |
| Actually referencing `CoreLib.Data.Configuration` | 23 |
| Of those, exposing real parameters | 21 |
| Parameters found, across the 17 cleanly extractable mods | ~90 |

Those are a snapshot of that date, not constants. The shape of the result is
the durable part.

Parameter types, most to least common: `bool` — dominant by a wide margin —
then `int`, `float`, enum, and `string` used as a comma-separated list.

The prevailing idiom is **one section per feature, containing an `IsEnabled`
toggle plus that feature's tuning keys**. Following it is what makes your
settings legible to a generic settings UI or a config migration.

Two shapes to avoid:

- **A section whose keys are generated per user object is not a settings
  schema.** One catalogue mod stores its map-marker labels that way; nothing
  generic can render, validate or migrate it.
- **Importing `CoreLib.Data.Configuration` without ever calling `.Bind(...)`**
  buys the dependency and configures nothing. Two mods in the survey do exactly
  this.

## Writing in lockstep with the game's save

For per-character mod data, do not invent your own save moment. Harmony-postfix
**`SaveManager.WriteCharacter(int saveId)`** — CK's real character-file write
(`characterFiles[saveId].Write(EncodeJson(...))`). It fires on autosave *and* on
"Save & Quit"; the no-argument `WriteCharacter()` overload delegates to it.
`SaveManager` is on no deny list, and it is a perfectly patchable class — it
lives in `Pug.Other`, inside the patch-target prefixes (see [the load-time sandbox](sandbox.md#harmony-attributes-are-exempt--hook-bodies-are-not)).

The symmetric load point is `CharacterData.OnAfterDeserialize` — with two limits
since 1.3. Each existing character file is decoded once when `SaveManager`
initialises at startup, not when the character is chosen; outside the benchmark
scene, the decode that follows the choice is the server world's decode of a
joining player's data, so it happens only in a process that hosts the world. And
the callback runs **before** `CharacterData.UpgradeIfOutdated()`, so it sees the
record as stored, not the upgraded one. [Correlating private state across two methods](harmony-and-ecs.md#correlating-private-state-across-two-methods)
has the call sites.

**Trap: do not gate your save on a return-to-menu signal.** Hooking
`SetCharacterId(-1)` and saving there looks equivalent and is not — a normal
"Save & Quit" does not reliably call it. The file simply never appears, with no
error and no log line: silent data loss. Keep a `Shutdown()` save and a
character-switch save as cheap backstops, but let `WriteCharacter` be the
trigger.

Saving in lockstep rather than ahead of CK also avoids a post-crash desync
where the game reverts the character to an older state while your file is
newer.

### The cost of that hook is paid on the main thread

**Trap: an unbounded persisted store turns every autosave into a frame spike.**
A `WriteCharacter` postfix runs the full serialize-plus-write inline,
synchronously, at every autosave. Measured on an 89 KB / 5503-entry ledger:
12–37 ms per autosave — 8–24 ms to serialize, 4–13 ms to write. That was enough
to push CK's **host simulation past its 55 ms budget** (the server tick, a
different budget from the client's ~16.7 ms render frame)
(`ServerUpdateFrequencyTracker` warnings; 626 of 1109 frames over budget in one
session), which players experience as continuous rubber-banding rather than as
the periodic hitch a heavy scan produces.

So budget the serialize like any other frame operation, and keep the store small
**at the source**. A radius-bounded self-heal only limits what it visits — it
does not retroactively clear a backlog that is already on disk. The per-frame
budget for scanning work is in [Harmony and ECS](harmony-and-ecs.md).

### Eliding an unchanged write needs a 64-bit hash

The obvious relief is to hash the serialized bytes and skip the write when the
hash matches the previous one. Note what a collision costs here: **a skipped
save that was needed** — silent data loss. The width of the hash *is* the
safety margin, so hand-roll **FNV-1a/64**.

- **Not `string.GetHashCode`.** 32 bits is not a negligible risk over a long
  session, and the value is not stable across runtimes.
- **Not SHA or MD5.** Cryptographic strength buys nothing against accidental
  collisions, it costs more per byte on a main-thread path, and it allocates a
  `byte[]`. Note that this is a cost argument, not a legality one:
  `System.Security.Cryptography` passes the sandbox — CoreLib hashes with it —
  so nothing stops you, it is simply the wrong tool here.

Record the hash only after a write you have **verified** by reading the file
back (see the `IOException` trap above), and let the first save of a session
always land.

## The `.pugbackup` sibling — a free before/after diff

Every `ConfigFilesystem.Write` **over an existing file** leaves a
`<file>.pugbackup` next to the live file holding the **previous** version. This
is observed for every file under `mods/<Mod>/` — configs, ledgers, throwaway
`.bin` files alike — and the backup's mtime always trails the live file's by
exactly one write.

**A first write leaves no backup — and deletes the old one.** `Write` removes
any existing `.pugbackup` before it starts, then replaces the live file only if
one is there; otherwise it moves the temporary file into place with nothing kept
behind. So the write that creates a file destroys the previous generation's
backup without producing a new one.

**This is the first thing to look at for any "my persisted state lost
entries" report.** It needs no new build, no diagnostic flag and no
reproduction: parse the live file and the `.pugbackup`, diff them, and the set
of vanished entries usually names the culprit outright. In one real case a
ledger had lost 21 object IDs covering 2677 units across 5 tiles while zero
tiles had been removed — every lost ID satisfied exactly one predicate, which
identified the offending code path with no guessing, and the same diff then
served as the fix's verification (`REMOVED=0 ADDED=0 CHANGED=0`).

**Caveat: it holds exactly one generation.** The next write overwrites it. If
the pre-damage state matters, copy the `.pugbackup` out before letting the game
write again.
