# Storing configuration and state

`System.IO` is denied to a mod's own sources — the whole namespace, down to
purely in-memory types such as `MemoryStream` (see [the sandbox](sandbox.md)).
That does not leave a mod without storage. The verification inspects references
in *your* code, so a call into an already-trusted assembly costs nothing, and
the loader ships a file API of its own for exactly this purpose.

What follows is the three routes that gives you, what the rest of the mod
catalogue actually does, and how to write state without corrupting the game's
save.

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

Paths are relative to the API's root — the `mods/` directory — so your own files
carry your mod's name as their first segment:

```text
…/LocalLow/Pugstorm/Core Keeper/<platform>/<user-id>/mods/<ModName>/
```

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
  out `.pugbackup` and `.pugtmp` siblings, so the backups described
  [below](#the-pugbackup-sibling--a-free-beforeafter-diff) are invisible to it.
  `Read` still opens them by name.
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
sandbox-legal, and CoreLib uses exactly that pair.

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

Three things to know before writing against that registry:

- **Enums survive the serialized round trip.** TOML writes an enum as its
  *name*, so `GetSerializedValue` / `SetSerializedValue` carry enum tokens
  losslessly without a per-type code path.
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

### 3. `skipSafetyChecks: true` — last resort

Setting `skipSafetyChecks: true` in the ModBuilderSettings `.asset` disables
the verification entirely and gives you raw `System.IO`. It is for what the
first two routes genuinely cannot express.

Two costs: you lose the guarantee that your mod is inspectable-by-construction,
and the flag **feeds a derived mod.io tag** — the `Access Type` tag on your
published listing is computed from it, so flipping the flag re-tags the mod on
the next publish. See [publishing](publishing.md).

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
`SaveManager` is on no deny list, and it is a perfectly patchable class — calls
through `Manager.saves` are merely *observed* to fail verification, which a
Harmony patch attribute never goes through in the first place (see [the load-time sandbox](sandbox.md#what-is-banned)).

The symmetric load point is `CharacterData.OnAfterDeserialize`.

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
