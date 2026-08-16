# Server Mod Version Check — Design (DRAFT)

- **Date:** 2026-08-13
- **Mod:** working title `server-mod-version-check` (new repo) — name open
- **Status:** **draft**, feasibility researched but nothing built. Deliberately
  **not** part of [`mod-update-notice`](2026-08-12-mod-update-notice-design.md):
  same motive, entirely different mechanism (ECS/RPC versus the mod.io API).

## Problem

When a client and a server run the same mods at different versions, the join
fails as `Error/BadProtocolVersion` — which reads as "wrong game version" and
sends you debugging the wrong thing. Core Keeper cannot tell you more, because
**it never learns the other side's mod versions.** It exchanges mod *identity*
only.

Making both sides state their versions turns a misleading error into a
diagnosis: "ItemChecklist differs — server has an older build."

## Precondition, not a limitation

**Both sides must have this mod installed.** That is the premise of the
mechanism, not a defect in it: the versions travel because this mod puts them
in the packet, so where it is absent there is nothing to compare. A foreign
server without it simply yields no version data.

What follows is that the mod must **detect that case and say so**, rather than
silently showing nothing or, worse, reporting a false match. The detection is
self-referential and exact — see § Detecting a capable server.

## What the wire already carries

Line references are against game **1.2.1.4** as decompiled at
`~/Projects/checkouts/CoreKeeperDecompile/`; expect drift, use them as grep
starting points.

After a connection is established, the client sends an empty
`ModInfoRequestRPC` and the server answers with one `ModInfoRPC` per loaded mod
(`Pug.ECS.Components:3682`):

```csharp
public struct ModInfoRPC : IRpcCommand, IComponentData {
    public long modId;
    public Unity.Entities.Hash128 modGuid;
    public FixedString32Bytes modName;
    public bool required;
    public bool lastMod;
}
```

Three facts make this exploitable without touching the protocol:

1. **`modName` is half empty.** The server fills it as
   `name.Substring(0, math.min(FixedString32Bytes.UTF8MaxLengthInBytes / 2, len))`
   (`Pug.Other:125924`). `FixedString32Bytes` holds **29** UTF-8 bytes
   (`utf8MaxLengthInBytes = 29`, Unity.Collections), and CK cuts at `29 / 2` =
   **14 characters**. Roughly **15 bytes per record are unused**.
2. **`modName` is never compared.** Identity matching runs on `modId` **or**
   `modGuid` (`Pug.Other:124570`); the name is only copied into
   `ModCheck.modName` for the dialogue text.
3. **The struct stays untouched, so the protocol hash does not move.** RPC
   serializers are generated and their type hash feeds the protocol version. A
   *new field* would change it and cause the very `BadProtocolVersion` this mod
   exists to explain. Different *content* in an existing field is invisible at
   that layer. This is the whole reason the approach is viable.

## Where the version comes from

**There is no version to read.** `ModMetadata` (`PugMod.SDK:90`) holds `guid`,
`name`, `displayName`, four booleans, `requiredOn`, `files`, `dependencies` —
and `LoadedMod` adds only `ModId`, `Handlers`, `Assets`, `AssetBundles`. Neither
carries a version. This is the finding that shapes the design: the version has
to be **derived**.

The chosen source is the **mod.io modfile id, read from the install directory
name**. The loader exposes `string GetDirectory(long modId)`
(`PugMod.SDK.Runtime:574`), and installs are laid out as `<modId>_<modfileId>`:

```
3177992_7710097     ← CoreLib, older modfile
3177992_7845185     ← CoreLib, current modfile
```

Properties that make this the right choice:

- **Sandbox-legal.** `GetDirectory` returns a `string`; splitting it needs no
  `System.IO` reference. (`LoadedMod.GetFile` internally uses `FileInfo`, but
  that code lives in a trusted assembly, not in mod source.)
- **Exact.** Every published release mints a new modfile id, so equality means
  "byte-identical release", which is a stronger and more useful statement than a
  matching semantic version string.
- **Cheap.** No network, no mod.io login, no file reads.
- **Short.** 7 digits fits the free space with room to spare.

Its limits, both acceptable: it is **not human-readable** (`7845185`, not
`1.4.0`), and **locally installed dev builds have no modfile id** — those need a
sentinel (e.g. `dev`) and must be reported as "not comparable" rather than as a
mismatch.

Rejected alternative: hashing `ModMetadata.files` GUIDs. It needs no I/O at all,
but asset GUIDs only change when files are added or removed — a release that
merely edits code would hash identically. Silently wrong beats loudly missing.

## Mechanism

**Server side.** A Harmony postfix on `ModInfoRpcSystem.OnCreate` walks the
`modList` it just built and appends `#<modfileId>` to each `modName`, staying
within 29 bytes. `OnCreate` is the right hook for two reasons: the list is built
there exactly once rather than per request, and — unlike `OnUpdate` and
`OnDestroy` in the same struct — **it carries no `[BurstCompile]` attribute**, so
it should be an ordinary managed patch with no `BurstDisabler` involved. *To be
confirmed at runtime, see U1.*

**Client side.** Read the incoming `ModInfoRPC`s, split the suffix off the name,
and compare against the local modfile id for the same `modId`. The receiving
lambda job is an `IJobChunk` and may be Burst-compiled; the safer hook is the
managed `NetworkClientStartSystem.OnUpdate` (`Pug.Other:124905`,
`protected override void OnUpdate()`), which already owns the client's copy of
the list.

**Detecting a capable server.** The client checks whether **its own** modId or
modGuid appears in the received server list. Present → the server runs this mod,
suffixes are expected, absence of one is a real anomaly. Absent → no comparison
is possible, and the UI must say exactly that. The check needs no extra traffic
and cannot produce a false positive, because it uses the same identity fields
CK itself matches on.

## Report surface

Undecided, and less pressing than in the sibling spec because the information
arrives at connect time. Candidates: extend the existing mismatch dialogue;
write a single summary line to the log; a small panel on the connect screen.
What the surface must distinguish is three states, never two:

| State | Meaning |
|---|---|
| match | same modfile on both sides |
| mismatch | different modfile — the actionable case |
| **not comparable** | server lacks this mod, or one side is a dev build |

Collapsing "not comparable" into "match" would make the mod lie in exactly the
situation it was built for.

## `requiredOn: 0` — decided, and it took a tool change

Both non-zero values are wrong here, in symmetric ways:

- **`1` (Client)** makes *your server* demand this mod from every joining
  client — it would block strangers.
- **`2` (Server)** makes *your client* demand it from every server — it would
  block you from joining anyone who lacks it.

A mod whose purpose is to explain blocked joins must not cause one, so the right
value is **`0`** (`ModExistsOn.None`): present on both sides by choice, demanded
of neither. The comparison still works, because it rides on the mod-info
exchange that happens anyway — `requiredOn` governs the *enforcement* dialogue,
not whether `ModInfoRPC` is sent.

That value used to be unavailable: `CLIPublishHelper` derived the mod.io
`Application Type` tag from `requiredOn` and **aborted the publish** on `0`. The
constraint was self-imposed rather than a platform rule — mod.io models
`Application Type` as a checkbox group, where none ticked is valid. The
publisher and `new_mod.py` now accept `0`, publishing with no tag in that group
(and removing one that is present). It logs a warning while doing so, because
`0` is also what an unset field reads as, and nothing but the author can tell
`None` apart from "forgot to fill it in" — for this mod, the warning is expected
and correct.

**The price, accepted knowingly:** with no Application Type tag, the mod does
not appear when someone filters the catalogue by that facet. A discoverability
cost, not a defect — and the right trade here, since the alternative is a tag
that would *lie* about which side the mod runs on. Worth a sentence in
`modio-description.md` stating plainly that it belongs on both.

## Open unknowns

1. **Does the `OnCreate` patch bind in time on a dedicated server?** `OnCreate`
   runs during world setup, and on a dedicated server `IMod.Init()` runs *after*
   `ECSManager.StartEcs`. If patch registration has not happened by then, the
   postfix never fires — no error, no log line, it simply does nothing. This is
   the same ordering trap that made `DisableBurstForSystem` a silent no-op
   server-side, and here it would hit the sending side, which is the one that
   matters. **Settle this first; it can invalidate the whole approach.**
2. **Is the client's receiving job Burst-compiled?** Decides between patching the
   job and patching the managed `OnUpdate`.
3. **Does a `#`-suffixed name break anything downstream?** Vanilla only puts it
   in dialogue text, so the expectation is no — but an unpatched client would
   display `ItemChecklis#7845185` in the missing-mod dialogue. Cosmetically poor,
   arguably more informative than before; note that 14-character truncation
   already mangles long names today (`SimpleCraftingPoolExtender` →
   `SimpleCrafting`).
4. **Do dev-build installs really lack a parsable id,** and what does
   `GetDirectory` return for them?

## Verification

1. Build, then grep `Player.log` for `error CS`, `CompileFailed`,
   `safetyCheck=True`.
2. **Prove the server patch fires at all** before testing behaviour: log from
   the patch class's static constructor and read the *server* log after a
   session with a player connected. An idle dedicated server sits at
   `timescale = 0` and never simulates, so an empty log proves nothing.
3. Three-way matrix, since the third state is the one that regresses silently:
   - client and server on the same modfile → "match"
   - deliberately mismatched (install an older modfile on one side via the
     mod.io cache directory) → "mismatch", naming the right mod
   - server without this mod → "not comparable", **never** "match"
4. An unpatched foreign client must still join normally, with no dialogue it
   would not otherwise have seen.

## Identity

- Repo `server-mod-version-check`, namespace `ServerModVersionCheck`,
  DisplayName "Server Mod Version Check" — all three matching. Note the
  14-character wire truncation affects display only, not the internal name.
- Scaffold with `utils/new_mod.py` (see `new-ck-mod`); `--summary`,
  `--required-on` and `--modio-type` are mandatory. Here: `--required-on 0`.
- Fake mod.io dev ID **9999985** — 9999986 is reserved for `mod-update-notice`,
  9999987…9999999 are in use.
- `requiredOn: 0`, `skipSafetyChecks: 0`. No `accessesExtraAssemblies` needed:
  unlike the sibling mod this one talks to ECS and the loader API, not to mod.io.

## Relationship to `mod-update-notice`

Complementary, not overlapping. The update notice warns **before** drift exists
("mod.io has a newer build than you"); this one diagnoses drift **after** it has
happened ("the server's copy differs from yours"). They share no code: one reads
the mod.io plugin, the other patches an ECS RPC. Keeping them apart also keeps
their profiles apart in ways that would otherwise have to be reconciled: this
one needs `requiredOn: 0` and no mod.io access, the badge needs `1` and
`accessesExtraAssemblies`.
