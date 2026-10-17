# Storing configuration and state

`System.IO` is denied to a sandboxed mod's own sources — the whole namespace,
down to purely in-memory types such as `MemoryStream` (see [the sandbox](sandbox.md)).
That does not leave a mod without storage. The verification inspects references
in *your* code, so what a call into an already-trusted assembly does internally
costs nothing — only the types in that call's own signature count — and the
loader ships a file API of its own for exactly this purpose.

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

That is the client's path on the default Steam branch; on the `experimental`
beta branch the client inserts an `experimental/` segment after `Core Keeper/`
(`Pug.Other:SteamPlatform`). On a dedicated server, everything before `mods/` is
the server's own save root instead — see [where the saves live](savegame-formats.md#where-the-saves-live).

Four members are worth their implementation detail, which comes from
`StandaloneFilesystem` — the one implementation `API.ConfigFilesystem` is
constructed from, on the client and on the dedicated server alike:

- **`GetFileTime` is the only timestamp in the API**, and it is
  `File.GetLastWriteTimeUtc` underneath — **UTC**, so compare it against
  `DateTime.UtcNow`. It is what a staleness check between files under `mods/`
  ("has another mod rewritten its file since I last read it?") has to be built
  on; nothing else here reports a time. It cannot date a save file: every path
  is resolved against the `mods/` root and one that leaves it throws
  `InvalidOperationException` (`Rel2Abs`). A missing file does not throw either
  — .NET's `File.GetLastWriteTimeUtc` returns 1601-01-01 for it — so check
  `FileExists` first. It has no passing-load evidence behind it, unlike the
  API's well-trodden `Read`/`Write` pair — smoke-test it like any new surface.
- **`GetFiles` recurses.** It enumerates with `SearchOption.AllDirectories` and
  returns paths relative to the API root with forward slashes — and it filters
  out `.pugbackup` and `.pugtmp` siblings, so the backups described [below](#the-pugbackup-sibling--a-free-beforeafter-diff) are
  invisible to it. `Read` still opens them by name. A directory that does not
  exist is not an empty result: `Directory.EnumerateFiles` throws, uncaught, so
  guard with `DirectoryExists`.
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
Debug.LogError(...) }` with **no rethrow**. Its two inner loops — deleting the
old backup, then `File.Replace` / `File.Move` — retry only a sharing violation,
sleeping one second per attempt on the calling thread, and give up after ten
attempts each with nothing but another `LogError`; any other `IOException` goes
straight to that outer catch. A full disk, a file locked by something else
(after up to twenty seconds of blocking), and the host-side filesystem faults
covered in [platforms and hosts](platforms.md) that surface as an `IOException` are therefore
invisible to your mod: no exception, no return value, nothing to branch on. What
is not an `IOException` still escapes — an `UnauthorizedAccessException`, or the
`InvalidOperationException` for a path outside the root. If the data matters,
**read the file back** before you record the write as done — above all before
caching any "content unchanged, skip the write" hash.

The API is `byte[]` in and `byte[]` out, which means you serialise yourself.
`Encoding.UTF8.GetBytes` / `GetString` is the normal way to get a string across
that boundary, and `Newtonsoft.Json` covers the structured case — both are
sandbox-legal, and CoreLib uses exactly that pair. Newtonsoft needs
`accessesExtraAssemblies` in the manifest, though, which CoreLib sets: without
it the in-game compile has no reference to it ([the load-time sandbox](sandbox.md#what-is-not-banned)).

Hand-packing a line-oriented format (`id:count,…`) through `(byte)char` /
`(char)byte` loops also works and is verified here, but treat it as a choice one
mod made rather than as a requirement: that loop only round-trips characters
below U+0100, and anything above truncates to its low byte without an error.

That this is genuinely sufficient is not theory: CoreLib itself is a sandboxed
source mod (`skipSafetyChecks: false`) with **zero** `System.IO` references,
and it persists `CoreLib.cfg` and its key-binding files (`KeyBindsActions.json`,
`KeyBindsCategories.json`) entirely through this API.

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
UI-update cost of about 7 ms, even on the title screen — its author's
measurement, not one taken here. Two more things follow from the getter. A
missing or unparsable file reads as `default(T)`, not as the default you
registered. And because a failed read also clears the entry's cached copy, the
next assignment to `Value` dereferences nothing — so once a hand-deleted or
corrupted file has been read, the following write is an exception rather than a
repair.

### 2. CoreLib's `ConfigFile` — typed entries, at a price

CoreLib's `ConfigFile` sits on top of the same `API.ConfigFilesystem` and adds
typed entries, defaults, `AcceptableValueRange` constraints and a TOML-ish
`.cfg` on disk. You buy that with a **hard CoreLib dependency**, which your mod
must declare in its ModBuilderSettings `.asset` — see [mod anatomy](mod-anatomy.md).
The mod.io listing keeps a dependency list of its own that does not follow the
`.asset` by itself, so a publisher has to keep the two in step ([publishing](publishing.md#dependencies-exist-twice-and-the-two-do-not-know-each-other)).

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
  **backslash** followed by one of `Unescape`'s escape letters does neither:
  CoreLib's `Escape` emits it unchanged (a single `@"\"`, where upstream
  BepInEx doubles it) while `Unescape` still consumes it, so feeding `a\b` back
  through `SetSerializedValue` stores `a` + U+0008. A backslash before any other
  character survives, and a value shaped like a drive path (`C:\…`) skips
  `Unescape` altogether.
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
  non-null `AcceptableValues`. Telling the subclasses apart needs no denied
  reflection: `System.Type` is allowed ([the sandbox](sandbox.md#what-is-banned)), so
  `AcceptableValues.GetType()` compared against a `typeof(…)` works, and the two
  stock classes also differ in their public `ToDescriptionString()` text. That
  is read from the sources, not compiled here.
- **The owning mod's display name is not part of the public surface, and
  `ConfigFilePath` is not derived from it.** `ConfigFile`'s constructor takes
  the path as a literal argument — CoreLib itself passes
  `"CoreLib/CoreLib.cfg"`, a settings-menu framework built here passes
  `"<ModId>/config.cfg"` — so a third-party mod need not follow either shape,
  and its first segment is only a convention to lean on, not a guarantee. The
  nearest thing to an owner on record is a header line in the file itself —
  `## Settings file was created by plugin <name>`, the owner's internal name,
  written only when the constructor was handed a `LoadedMod`.
- **`BoxedValue` casts must be type-exact.** An `int` range entry is a boxed
  `int`, and `(float)` on it throws. Branch on `SettingType` — never on what
  the value looks like.

**`Scope` carries access semantics, and one of them can crash you.**
`ConfigEntryBase.Scope` is a `ConfigScope` holding an `accessLevel`
(`ConfigAccessLevel.ViewOnly` / `Client` / `Server` / `Admin`), a
`requireReload` flag declaring that the change takes effect only after a restart
— a declaration only, since nothing in CoreLib reads it — and a `Changeable()`
method.

**Trap: `Changeable()` reads `Manager.main.player`.** For a `Server` or `Admin`
entry it then dereferences that player (`player.guestMode`), so calling it while
there is none — on the title screen, for one — is a null-reference risk; a null
`Manager.main` throws at any level. Guard first:

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
`ConfigScope.Empty` is also one `static readonly` instance shared by every
scope-less entry in the process, and its fields are public and mutable — a
consumer that assigns `entry.Scope.accessLevel` on one such entry changes it for
all of them.

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
there.** The server loads mods the same way the client does, so every `Bind` on
a path the server executes — `EarlyInit`, `Init`, anything not behind
client-only UI or a client world — runs there too, and its entry lands in the
server's own config file whenever a save happens — including entries describing
a HUD that does not exist in that process. They are artifacts, not an
authoritative copy: the client's entry of the same name is a separate instance,
and reconciling the two would overwrite something nobody asked about.

**Every automatic save writes the WHOLE file, and the first one happens inside
`ConfigEntryBase`'s constructor — before `Bind` has registered the entry.**
Setting a value goes `ConfigEntry<T>.Value` → `OnSettingChanged` →
`ConfigFile.Save()` — unless the clamped new value equals the old one, which
returns before anything is saved. `Save` asks every entry in that file for
`GetSerializedValue()`, and, while `GenerateSettingDescriptions` is on (the
default), for its description (`WriteDescription`) — which calls
`AcceptableValues.ToDescriptionString()` on each entry that has a constraint. The
constructor ends in `BoxedValue = defaultValue`, which trips that chain for any
default differing from `default(T)`; only afterwards does `Bind` reach
`Entries[definition] = entry`. Three consequences, none of them local to the
entry that causes them:

- **One entry that throws while being saved makes the whole file unwritable.**
  Every other entry in it stops persisting — the in-memory value changes, the
  `.cfg` does not. The exception is not swallowed on the way: it reaches
  whoever assigned the value, and only `SetSerializedValue` — the path a
  `Reload()` takes — catches it, logging it as a value that "could not be
  parsed". A caller that catches around its own writes sees an exception that
  names the other entry, not its own.
- **Every later entry whose default differs from `default(T)` is never
  registered at all.** Its constructor's save hits the broken entry and throws
  before registration, so the entry does not exist: no row, no error of its own,
  and any code that catches around `Bind` sees only the exception, not the
  absence. Whatever enumerates that file is then short by as many entries, with
  nothing to say why. An entry whose default equals `default(T)` skips the
  constructor save, is registered, and then throws from `Bind`'s own save.
- **A failed save leaves the new value in memory.** The assignment precedes
  the save, so a UI that re-reads after writing shows the change as having
  worked. Only the next launch disagrees.

This bites when an `AcceptableValueBase` subclass computes its description
rather than returning a literal — a plausible thing to write, and the failure
surfaces nowhere near it — and equally when a custom type converter registered
with `TomlTypeConverter` throws from its `ConvertToString`.

**Trap: another mod can switch your file's auto-save off.** The automatic saves
above hang on one public flag, `ConfigFile.SaveOnConfigSet`, which defaults to
`true` (`ConfigFile.cs:ConfigFile:SaveOnConfigSet:1`) and gates the save after a
`Bind` (`ConfigFile.cs:ConfigFile:Bind(ConfigDefinition, …):26`) and the save
after a value change (`ConfigFile.cs:ConfigFile:OnSettingChanged:6`) — and with
the latter also the save inside `ConfigEntryBase`'s constructor, which goes
through that same `OnSettingChanged`. Only two saves ignore it: an explicit
`Save()`, and the one `ConfigFile`'s own constructor makes for a file that does
not exist yet when `saveOnInit` is set. The registry hands every file to every
mod, and General Mod Config Menu (mod.io modfile 8270186) sets the flag to
`false` at three places: `ModConfigMenu.Awake`, which in the measurement below
ran when its menu was created at the title screen, and
`ConfigSyncSystem.OnCreate`, once per simulation world — both skip files whose
`ConfigFilePath` starts with `CoreLib` — and `ModConfigMenu.RegisterFile`, with
no such exception. It never sets it back, so every file that already existed
when those passes ran loses its auto-save for the rest of the process: a foreign
settings UI writes the new value into memory and nothing reaches the disk; the
next launch shows the old one. A file created after both passes keeps the flag
as it was. Measured on 1.3.0.6 with Mod Settings Menu before 1.2.2, which relied
on the auto-save: a changed setting did not survive a restart — on the title
screen as well as in a world, which the `Awake` site explains — and disabling
General Mod Config Menu alone made it stick. Call `ConfigFile.Save()` yourself
after a write whose persistence matters; it is not gated by the flag.

**Change notification and reloading are both there, with limits.**
`ConfigFile.SettingChanged` and the per-entry `ConfigEntry<T>.SettingChanged`
fire on a write that changes the value — not on one whose clamped value equals
the old one, and not at all when the save before them throws. The per-entry
event is declared on `ConfigEntry<T>`, not on `ConfigEntryBase`, so code holding
an entry from the registry cannot subscribe to it without knowing `T`; the
file-level event is the one a foreign reader can use. `ConfigFile.Reload()`
re-reads the file from disk, re-applying each value through
`SetSerializedValue` — so every entry it changes fires the events and, with the
flag on, triggers a full save mid-reload — leaves an entry missing from the file
at its in-memory value, and throws when the file itself is missing. Together they
allow a split that is otherwise awkward to build: the file as the user's stored
preference, the in-memory entry as what is in effect right now, and `Reload()`
as the way back when the temporary authority goes away. That split needs
`SaveOnConfigSet` off for the file: with the default on, assigning the temporary
value saves it over the stored preference, and there is nothing left to reload.

#### Intercepting CoreLib's writes: replace `API.ConfigFilesystem`, do not patch

`ConfigFile.Save()` serialises the **whole file from memory** — every bound
entry through `GetSerializedValue()`, plus the lines it read but no entry claims
(`OrphanedEntries`) — and writes it with a single `API.ConfigFilesystem.Write`.
So a save of one entry rewrites every other entry of that file with its
in-memory value, whoever triggered it.

A sandboxed mod that wants to hold back or alter such a write cannot do it with
Harmony. `ConfigFile` lives in CoreLib, outside the five assembly prefixes the
patch gate admits, and a refused target means none of the mod's patches are
applied, not just that one ([the gate](sandbox.md#harmony-attributes-are-exempt--hook-bodies-are-not)).
One level down it is shut as well: `StandaloneFilesystem`, the implementation
behind `API.ConfigFilesystem`, is `[DisallowPatching]`
(`Pug.Other:StandaloneFilesystem`). The gate runs only for a mod whose
`skipSafetyChecks` is false (`PugMod.Loader:HarmonyBootstrap`), so a mod with
honoured elevated access is not bound by either — at the cost route 3 below
describes.

What is open is the field itself. `API.ConfigFilesystem` is a public static
`IConfigFilesystem` that the game assigns once at startup
(`Pug.Other:Manager:EarlyInit:50`), and CoreLib reads it afresh on every call
rather than keeping a copy. The game itself does keep one: `API.Config` is
constructed a few lines later around the original instance
(`Pug.Other:Manager:EarlyInit:65`) and holds it in a private field, so every
`API.Config` write goes around a wrapper installed afterwards. Within that
limit, a mod can assign a wrapper in its own `EarlyInit` that holds the
original, forwards all eleven members, and intercepts `Write(string, byte[])`:
it may skip the write by not forwarding, or rewrite the bytes first. The wrapper
is plain managed code over a PugMod interface, so the sandbox has nothing to
refuse.

Measured on 1.3.0.6-6e73 (2026-10-17): a probe wrapper saw 235 writes from 25
files — CoreLib's own, PlacementPlus, and every settings-menu consumer among
them — and none bypassed it. A write it skipped left the file on disk
untouched, and a line it rewrote in the bytes arrived rewritten. Caveats:

- It sees only writes issued after the mod's `EarlyInit`; earlier ones, in
  practice startup saves, pass unseen.
- Whatever cached the original instance bypasses it — the game's `API.Config`
  above in every process. No mod behind the 25 files did, but nothing guarantees
  it, and mods stacking wrappers wrap each other in load order.
- It sees a path and bytes, not a caller. `System.Diagnostics.StackTrace` is on
  the deny list, so the obvious way to name who saved is closed; a convention of
  your own is the dependable one. `System.Environment.StackTrace`, a plain
  `string` in an allowed namespace, is not on the list by the data, but whether
  it yields a usable stack inside the game remains **unverified**.
- An exception thrown from the wrapper reaches every caller whose write it
  fails on, whichever mod that is — CoreLib's `Save` catches nothing; catch,
  log, and forward unchanged.

### 3. `skipSafetyChecks: true` — last resort

Setting `skipSafetyChecks: true` in the ModBuilderSettings `.asset` disables
the verification entirely — and the Harmony patch-target gate with it — and
gives you raw `System.IO`. It is for what the first two routes genuinely cannot
express.

It is honoured as written only for a side-loaded mod. The mod.io and Steam
loaders force it back to `false` unless the listing carries the tag `Script
(Elevated Access)` ([the tag table](troubleshooting.md)), and nothing in the SDK sets that tag from
the flag — a publisher sets it by hand or with tooling of their own
([publishing](publishing.md)). Two costs follow: you lose the guarantee that your mod is
inspectable-by-construction, and your listing has to carry that tag, which
exists to warn subscribers.

## Reading a file your mod ships

The three routes above are all for state a mod **writes** at runtime — a config,
a ledger, a cache. A file a mod **ships** — the `Conf/*.json` payload [mod anatomy](mod-anatomy.md#what-ships-and-what-the-loader-reads)
lists as one of the five kinds a build produces — is a different question, and
neither of the first two routes reaches it: it never passes through
`API.ConfigFilesystem`, because the loader never wrote it there in the first
place. (Route 3's raw `System.IO` could read the install directory, at route 3's
price.)

`LoadedMod.GetFile(string path)` (`PugMod.SDK.Runtime:LoadedMod:GetFile:1`) is
the answer. It resolves `path` against the mod's own install directory
(`API.ModLoader.GetDirectory(ModId)`) and returns the file's bytes with
`File.ReadAllBytes` — all inside the trusted `PugMod.SDK.Runtime`, so
referencing it costs nothing against [the sandbox](sandbox.md). It returns `null` in two
cases: when the loader knows no directory for the mod, and, with a logged
warning, for a path that escapes that directory. A file that does not exist is
not one of them — `File.ReadAllBytes` throws, uncaught, into your code.

Reach it off your own `LoadedMod`, [resolved the usual way](mod-anatomy.md#reaching-your-own-loadedmod-and-asset-bundle):

```csharp
foreach (var mod in API.ModLoader.LoadedMods)
{
    if (mod.Metadata.name == ModName)
    {
        var bytes = mod.GetFile("Conf/settings.json");   // throws if the file is missing
        if (bytes != null)
        {
            var text = Encoding.UTF8.GetString(bytes);
        }
        break;
    }
}
```

This needs no `dependencies` entry and no `accessesExtraAssemblies` — the
payload already ships inside your own mod directory, and `GetFile` is a plain
method on the trusted `LoadedMod` wrapper, not a shipped `.dll`. The install
directory `GetFile` reads from has a second documented use: [mod anatomy](mod-anatomy.md#there-is-no-mod-version-at-runtime)
derives a build identifier from its name, read with `API.ModLoader.GetDirectory`
rather than with `GetFile`, since no version field exists anywhere in the
loader's view of a mod.

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
(`Pug.Other:ModManager:Init:24-27`) — plus any `-confdir` folder from the
command line, and none at all under `-safemode` — and five loaders in `Pug.Mods`
read `*.json` from fixed subfolders of each (`Pug.Mods:Factions`,
`Pug.Mods:Fishing`, `Pug.Mods:LootTable`, `Pug.Mods:SpawnTable`,
`Pug.Mods:Talents`):

| Subfolder | Depth read |
|---|---|
| `Factions`, `Fishing`, `Loot`, `Loot/Fishing/Biome`, `Loot/Fishing/Water`, `Talents` | top level only |
| `Spawn/Initial`, `Spawn/Respawn` | every level below |

A `.json` the table covers is game data, and the game parses it as such. Any
other file — directly in `Conf/`, in a subfolder the table does not name
(including one below a top-level-only folder, such as `Loot/Fishing` itself), or
not `.json` at all — is left to you.

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
  schema.** One catalogue mod stores its map-marker labels that way; a generic
  UI can list the keys, but nothing generic can give them meaning, validate or
  migrate them.
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

Three things the postfix has to allow for, all in the client tree's
`SaveManager`:

- **It runs more often than once per autosave.** The method is also called when
  a game is started or continued from the character menu, after every world save
  in a process that hosts the world (`SerializeWorldSystem`), from
  `SaveManager.Deinit`, and at startup from `SaveManager.Init` for every
  character file it upgraded.
- **`saveId` is not always the active character** — the startup upgrade writes
  each slot in turn — so key your data on `saveId`, not on the character in
  play.
- **A postfix runs even when nothing was written.** The method returns without
  writing for a character from a newer game version (logging an error) and for
  the active character once it has died, and a postfix still runs after both. On
  a dedicated server the method only logs "Trying to write character as server"
  — characters are the clients' files there.

The symmetric load point is `CharacterData.OnAfterDeserialize` — with two limits
since 1.3. Each existing character file is decoded once when `SaveManager`
initialises at startup, not when the character is chosen; outside the benchmark
scene, the decode that follows the choice is the server world's decode of a
joining player's data, so it happens only in a process that hosts the world. And
the callback runs **before** `CharacterData.UpgradeIfOutdated()`, so it sees the
record as stored, not the upgraded one. [Correlating private state across two methods](harmony-and-ecs.md#correlating-private-state-across-two-methods)
has the call sites.

**Trap: do not gate your save on a return-to-menu signal.** Hooking
`SetCharacterId(-1)` and saving there looks equivalent and is not — nothing in
the game calls it with `-1`. Returning to the menu resets the field directly in
`SaveManager.OnSceneUnload`, right after that method's own `WriteCharacter()`,
so the hook never fires. The file simply never appears, with no error and no log
line: silent data loss. A character-switch save is a cheap backstop; a
`Shutdown()` save is none, because the loader does not call `Shutdown` at game
quit and in 1.3.0.6 never reloads a mod after startup ([the lifecycle table](mod-anatomy.md#the-imod-lifecycle)). Let
`WriteCharacter` be the trigger.

Saving in lockstep rather than ahead of CK also means your file and the
character file are written at the same moments, so a crash cannot leave the
character reverted to an older state while your file already holds a newer one.

### The cost of that hook is paid on the main thread

**Trap: an unbounded persisted store turns every autosave into a frame spike.**
A `WriteCharacter` postfix runs the full serialize-plus-write inline,
synchronously, at every call — autosave and the other occasions listed above.
Measured on 1.2.1.5 in one hosted session, on an 89 KB / 5503-entry ledger:
12–37 ms per call — 8–24 ms to serialize, 4–13 ms to write — about ten times in
a short session. The same session logged `ServerUpdateFrequencyTracker`
warnings for CK's **host simulation** running past its 55 ms budget (the server
tick, a different budget from the client's ~16.7 ms render frame) — 626 of 1109
frames — and players felt continuous rubber-banding rather than the periodic
hitch a heavy scan produces. After a round of changes shrank the store, skipped
unchanged saves and reworked the scan, a later session showed 4 such frames. The
changes went out together and were never measured apart, and the save figures
alone do not account for the overruns — no single save reached 55 ms, and ten of
them cannot make 626 slow frames. So the save is one measured cost in a host
that was over budget for reasons not fully separated, not the isolated cause.

So budget the serialize like any other frame operation, and keep the store small
**at the source**. A radius-bounded self-heal only limits what it visits — it
does not retroactively clear a backlog that is already on disk. The per-frame
budget for scanning work is in [Harmony and ECS](harmony-and-ecs.md).

### Eliding an unchanged write: keep the bytes, or a 64-bit hash

The exact way to skip an unchanged write is to keep the previous serialized
bytes and compare — no collision risk at all, at the cost of holding one copy
of the store in memory. The obvious lighter relief is to hash the serialized
bytes and skip the write when the hash matches the previous one. Note what a
collision costs there: **a skipped save that was needed** — silent data loss.
The width of the hash *is* the safety margin, so if you hash, hand-roll
**FNV-1a/64**.

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
