# Multiplayer and the dedicated server

Everything a mod does in singleplayer it does alone. The moment a second machine
is involved, two independent gates decide whether the two sides may talk at all:
Unity NetCode's own protocol validation, and Core Keeper's mod check on top of
it. Neither knows about the other, and both fail in ways that name neither your
mod nor the real cause. This chapter covers what those gates check, what a
mismatch looks like from the player's seat, and what is different about a mod
running inside a dedicated server process.

## The netcode stack

Three layers, all of them off-the-shelf:

| Layer | Assembly | Role |
|---|---|---|
| Transport | `Unity.Networking.Transport.dll` | packet delivery |
| Replication | `Unity.NetCode.dll` (+ `.Physics`, `.Hybrid`, `.Authoring.Hybrid`) | NetCode for Entities — ghosts, snapshots, RPCs |
| Relay | `Facepunch.Steamworks.Win64.dll` | Steam Datagram Relay (SDR) |

The replication layer is stock **NetCode for Entities / DOTS Netcode**. The
server assemblies carry its symbols verbatim — `GhostCollectionSystem`,
`GhostCollectionPrefabSerializer`, `GhostCollectionHash`,
`GhostCollectionCustomSerializers`, `NetworkProtocolVersion` — and the SDK
matches them with `ProjectSettings/NetCode{Client,Server,ClientAndServer}Settings.asset`.

SDR does **not** come from Unity. It is Facepunch's Steamworks binding
(`SteamNetworkingSockets`, `SteamNetworkingIdentity`, `SteamDatagramHostedAddress`,
`SteamNetworkingFakeUDPPort`), and it sits underneath as a swappable transport
interface, not as protocol semantics. A server started with a port set takes
direct UDP connections; with no port it is reachable only through the relay. The
protocol above is identical either way.

### What changes the ghost hashes — and what does not

On connect the two sides exchange `NetworkProtocolVersion` — NetCode version,
game version, RPC collection, component collection — plus the ghost collection
hash. NetCode generates its ghost serializers at **build time** from the ECS
component types, so those hashes are a fingerprint of the component landscape,
not of anything the loader can negotiate at runtime.

For a mod this splits cleanly:

| Kind of change | Hashes |
|---|---|
| Harmony patches on managed systems | unchanged |
| Bake-time property edits, changed values, recipe/database tweaks | unchanged |
| **New ECS components, or new ghost prefabs** | **changed** |

The first two are the overwhelming majority of mods, and they pass NetCode's
check untouched — their compatibility problem is entirely the mod-set layer
below. Registering a new replicated component is the case to think twice about:
it alters the component/ghost collection, so the NetCode check fires **on top of**
whatever `requiredOn` says, and `requiredOn` cannot excuse it.

### Why there is no third-party server

The obvious-looking blocker — SDR — is not the blocker. The blocker is the
build-time-generated ghost serialization: a reimplementation would have to
reproduce the whole component landscape bit-exactly, which is the whole game,
including the world generation that needs OpenGL/Mesa on the server side. The
pragmatic path for anything server-authoritative is always the official server
binary plus a server-side mod.

**There is no macOS build at all** — not of the server, not of the game. The
Steam store API reports `platforms.mac = False` for app 1621690, and server
depots exist for Windows and Linux only. On Apple Silicon that leaves Wine/
CrossOver or a Linux container; the `escapingnetwork` server image has an ARM
variant via Box64. Running it locally in the CrossOver bottle is described in
[../dedicated-server.md](../dedicated-server.md).

## The second layer: the mod set

Core Keeper runs its own mod comparison at connect time, in
`ModInfoRpcSystem` and `NetworkClientStartSystem`, entirely independent of
NetCode's hash validation. What it compares is driven by each mod's
`requiredOn` flag — see [mod anatomy](mod-anatomy.md) for the enum itself and
how to choose a value. What matters here is the network consequence.

**The checks are crossed.** This is the part that gets set wrong:

| Flag on your mod | Effect |
|---|---|
| `Server` (2) | `NetworkClientStartSystem` (Pug.Other ~124928): `localMod.required = (requiredOn & ModExistsOn.Server) != 0` — the **client** demands the mod **on the server** |
| `Client` (1) | `ModInfoRpcSystem` (~125929): `required = (requiredOn & ModExistsOn.Client) != 0` — the **server** demands it **on the client** |
| flag absent | the mod is removed from the check list entirely (`localMods.RemoveAt`) and never interferes in that direction |

So a client-only HUD mod that carries `Server` does not "declare itself
client-side" — it declares that every server you join must also run it.

### What the server actually sends

Once the connection is up the client sends an empty `ModInfoRequestRPC`, and the
server answers with one `ModInfoRPC` per loaded mod
(`Pug.ECS.Components:3682`):

| Field | Type |
|---|---|
| `modId` | `long` |
| `modGuid` | `Hash128` |
| `modName` | `FixedString32Bytes` |
| `required` | `bool` |
| `lastMod` | `bool` |

Identity is matched on `modId` **or** `modGuid` (`Pug.Other:124570`) — the name
is never compared. `modName` travels only so the missing-mod dialogue has
something to print; it ends up in `ModCheck.modName`.

**Trap: that name is truncated to 14 characters.** The server fills the field
with `name.Substring(0, min(UTF8MaxLengthInBytes / 2, len))`
(`Pug.Other:125924`), and `FixedString32Bytes` holds 29 UTF-8 bytes — so 14
characters are all that survive. A 26-character internal name such as
`SimpleCraftingPoolExtender` reaches the player as `SimpleCrafting`. Matching is
unaffected, so this is not a bug to hunt; but the first 14 characters of
`metadata.name` are the whole of what a player sees when your mod is the one
blocking their join.

**If you patch this layer:** `ModInfoRpcSystem.OnCreate` builds its mod list
exactly **once**, not per request, and — unlike `OnUpdate` and `OnDestroy` in the
same struct — carries **no `[BurstCompile]` attribute**. On the client,
`NetworkClientStartSystem.OnUpdate` (`Pug.Other:124905`) is a plain
`protected override void OnUpdate()` and already holds the client's copy of the
list; the job that receives the RPCs is an `IJobChunk` and may be Burst-compiled.
Whether a Harmony patch on `OnCreate` binds early enough on a **dedicated
server** — where `IMod.Init()` runs after the worlds are built, see below — is
untested.

### What a mismatch looks like to the player

It is a hard block, not a warning (~124940-124978). Joining a server that lacks a
`Server`-flagged mod raises `Menu/ModMissingServerDialogue`, and the dialogue
offers exactly two ways out:

- **disable the mod** — `ModIOUnity.DisableMod` plus a restart of the game, or
- **cancel the connection** — `cancel = true` → `Disconnect`.

There is no "join anyway". And with a **development build carrying a fake mod ID**
(`modId <= 0`) it is worse: the disable branch is not offered at all, because
there is no mod.io subscription to disable, so the dialogue reduces to
`cancelDialogue` — the player cannot get onto that server by any route the game
provides.

This is why an over-broad `requiredOn` costs real usability: it turns "my HUD
mod does nothing on unmodded servers" into "my HUD mod cannot be installed by
anyone who plays on public servers".

## Writing patches that behave in multiplayer

### `PlayerController` methods fire for every player

A patch on a `PlayerController` method runs for **every connected player**, not
just for the one at the keyboard. Singleplayer has exactly one player, so a
missing check is invisible in the very place mods get tested; in a session with
several players the same hook does the work — or mutates the same client-side
state — once per player. Gate every client-side `PlayerController` patch on the
instance:

```csharp
if (!__instance.isLocal)
    return;
```

### Check `[GhostField]` before assuming a write replicates

Whether an ECS write reaches the other side is decided by the component's
declaration, not by which world you wrote it in. Read the attribute before
assuming either way:

| Component | Replicated |
|---|---|
| `HealthCD` | yes — declared `[GhostField]`, so a server-side change travels to the client |
| `PlacementCD` flags | no — not `[GhostField]`s (`Pug.ECS.Components:4297-4314`), so they are world-local state |

What the client then *does* with a replicated value is a separate question: for
`HealthCD` it is unverified whether a damage-stage sprite or a progress bar
refreshes on its own.

For `PlacementCD` the consequence runs the other way — writing those flags on one
side changes nothing on the other. The surrounding code is present on both:
`EquipmentSystemGroup` (`Pug.Other:418855`) runs in the server **and** the client
simulation world, and `EquipmentUpdateSystem.UpdateJob` is a scheduled job.
Whether a Harmony prefix in that area therefore behaves identically across
singleplayer, a hosted session and a dedicated server is an open question — treat
it as "can run on either side" and verify on the topology you care about.

## The dedicated server

Wiring one up locally — the helper script, the world and mod symlinks, the
bottle — is [../dedicated-server.md](../dedicated-server.md). What follows is
what is true of the *game*, wherever the server runs.

### The client builds no server world

Joining a dedicated server, the client constructs only `ClientWorld0` — there is
no `ServerWorld` in the process. Anything server-authoritative is decided
entirely in the server process, and a client-side patch on a server-authoritative
system will at best win for a few ticks before the next ghost snapshot overwrites
its value.

### A mod-set mismatch reports a version error

The client shows **"wrong game version"**. The actual error is
`Error/BadProtocolVersion`, and it almost never has anything to do with the game
version — a mod-set difference produces exactly this message, because the mod set
is upstream of the hashes NetCode compares. Nothing in the message mentions mods.

Diagnose in `Player.log`: hundreds of `ComponentHash[N]` lines followed by
`Client disconnected because Error/BadProtocolVersion`.

**A missing required dependency is one of the ways the sets drift apart.** If a
mod declares a `required` dependency that is not installed on the server, the
loader's `SortMods` drops the *dependent* mod there and says so only in a log
warning — see [mod anatomy](mod-anatomy.md) for that drop. The two sides then
hold different mod sets, and the client reports the same
`Error/BadProtocolVersion`; nothing in it names a dependency. So when you publish
a mod that depends on another, the server needs **both** installed, not just
yours — and this is the diagnostically expensive case, because the symptom points
at the game version while the cause is one absent dependency on one machine.

### Version filtering is client-side only

Only the client checks a mod's version-compatibility tags. It skips a mod that
does not match the running game version, unless the mod's GUID sits in
`modloader/config.json` → `unsupportedModsToLoad`, which is what the "load
anyway" dialogue writes.

**Trap:** copying that list to the server accomplishes nothing. The server's
directory scan passes `supportsCurrentVersion: true` **hardcoded**
(`PugMod.Loader` ~2172) and loads everything it finds, so the gate the list feeds
— `!supportsCurrentVersion && !contains(guid)` — can never fire there.

The asymmetry therefore runs one way only, and it is a mismatch generator: a mod
the **client rejects** but the server still loads is a set difference. Resolve it
on the side that actually filters — either confirm the mod in the client's
dialogue, or remove it from the server. Note also that the loader **clears
`unsupportedModsToLoad` on every game-version change**, so a mod confirmed once
silently drops out of the client's set after the next game update, and the join
that worked yesterday fails today with no change on either machine.

### Duplicate mods: last one wins

The loader deduplicates by `metadata.name` — the manifest identity, not the
mod.io profile name and not the folder name. When two loaded folders claim the
same `metadata.name`, `SortMods` keeps **the last one in enumeration order**.
Only one of them ever runs, and nothing announces which. Two mods can also share
a `guid` without being the same mod — a fork inherits it along with the manifest
— so a shared guid is not proof of a duplicate, but it does clash for the
data-block loader, which keys on the guid.

### The server needs the same loader patches as the client

On a Wine/CrossOver host the server installation must be patched **separately**
from the game — it is a different install directory with its own
`CoreKeeperServer_Data/Managed`. Skipping it produces a very specific failure:
the mods **load but never compile**, because Roslyn chases a missing satellite
assembly, and the client then rejects the join as `Error/BadProtocolVersion` —
i.e. the mod-set symptom, one step removed from the real cause. Details in
[../macos-crossover-loader.md](../macos-crossover-loader.md).

### An idle server never simulates

This is the single most misleading thing about server-side debugging. After world
start the server settles at `timescale = 0` and stops simulating; its log stops
growing at the same moment. Consequences:

- **An absent log line proves nothing** unless a player was connected at the
  time. "My patch never logged" is not evidence the patch is dead.
- Read the log **after** the session, not during it.
- A mod's `Debug.Log` output does land in the server log — the log file sits
  next to the executable, not in `LocalLow`.

To prove a Harmony patch is live server-side, log from the **static constructor**
of the `[HarmonyPatch]` class. An explicit static constructor suppresses
`beforefieldinit`, so the line fires immediately before the first `Prefix()` call
rather than at some unrelated point of type loading — and then connect a player
so the systems actually run.

The two log formats also differ, which costs time when comparing sides: the
server writes `loaded mod <Name> at <path>`, the client writes
`Loading mod with ID <modId>`. There is no grep pattern that matches both.

### Warning: the lifecycle order is inverted

`IMod.Init()` runs at a different point relative to ECS startup on the two
processes — **before** the worlds are built on the client, **after** them on the
dedicated server. Anything that registers itself during `Init()` and is consumed
by a snapshot taken at ECS startup therefore works in singleplayer and is a
silent no-op on the server, with no error and no log line. `BurstDisabler` is the
case this bites in practice; the mechanism and the fix belong to
[Harmony and ECS](harmony-and-ecs.md). If your mod is server-authoritative and
works alone but not in multiplayer, start there.

## How the server build actually differs

The dedicated server is not a different game. Decompiling both installations of
the same version and diffing them assembly by assembly, **117 of 122 curated
assemblies come out identical**; only five differ at all — `Pug.Other`,
`WorldGen`, `Pug.Objects`, `Pug.Dev` and `PugMod.Loader`. Almost everything you
learn from the client decompile is therefore true of the server as well.

Within `Pug.Other`, only 43 types differ, and most of that volume is not game
logic: a generated type table, the client-only account/session layer, the Steam
platform wrapper and the preferences manager. The modding-relevant residue is
roughly 450 lines across `NetworkingManager`, `NetworkCommandServerSystem`,
`SerializeWorldSystem`, `SaveManager`, `ModManager`, `Manager` and `ECSManager`.

The type inventory is lopsided in the direction you would expect: exactly **one
server-exclusive type**, `NetworkUpdateServerLateSystem` (a `SystemBase` filtered
to `ServerSimulation`, ordered last in the `SimulationSystemGroup` after
`GhostSendSystem` and `RpcSystem`), against **18 client-exclusive** ones — the
account, lobby, authentication and cross-platform session types.

### Why an idle server stops simulating — the actual condition

The `timescale = 0` behaviour described above is not a heuristic. `ECSManager`
pauses when the world has finished loading, **no connection exists**, and no save
is in flight; otherwise it resumes. So the server idles precisely when the last
player disconnects, and resumes the moment one connects.

### The server builds no client world

`CreateClientWorld` is still *defined* in the server build — but it is never
called, and `SaveClientSystem`, though present as a class, is never registered.
Only `SaveSystem` runs, on the server world.

**Trap:** the presence of a class in the decompiled server assembly is not
evidence that it runs. Both of these types survive the build and do nothing.
Check for the call site, not for the definition.

### Mod scripts extract to a fresh directory every start

| Build | Extract path |
|---|---|
| Client | `<temporaryCachePath>/ModLoader/<mod name>` |
| Server | `<temporaryCachePath>/ModLoader/DedicatedServer/<fresh GUID>` |

The server never reuses a directory, so it accumulates one extract directory per
start. It also means a stale-extract problem cannot occur there — and any host
patch that exists to repair a leftover extract directory is inert on the server
side.

### The server renders, so it needs a graphics device

Both builds rasterise the procedural world texture during generation; they only
differ in how they read it back — the client asynchronously through a command
buffer, the server synchronously with a camera render followed by `ReadPixels`.

**This is the reason a dedicated server may run with `-batchmode` but never with
`-nographics`:** world generation genuinely requires a graphics device, and
removing it breaks world creation rather than merely suppressing output.

### The server has no world list

A client holds an array of world slots and indexes into it. A dedicated server
hosts exactly one world and takes its properties from the server configuration
instead — the accessors are rewritten accordingly:

| Accessor | Client | Server |
|---|---|---|
| `GetWorldInfo(int id)` | bounds-checks `id`, returns `worldInfo[id]` | builds a fresh `WorldInfo` from `Manager.prefs.server*`, ignoring `id` |
| `GetWorldMode(int id)` | from the array | returns `Manager.prefs.serverWorldMode` |
| `GetWorldName(int id)` | from the array | returns `Manager.prefs.serverWorldName` |
| `IsWorldModeEnabled(int id, …)` | from the array | tests `Manager.prefs.serverWorldMode` |

In every server case the id parameter is accepted and **never read**. Passing a
slot number therefore does not select anything — you always get the one hosted
world, and a mod that treats a differing id as a differing world will be wrong
in a way that no error reports.

**The array itself is not dead** — be precise here, because the obvious
generalisation is wrong. It is allocated normally, still loaded from disk, and
still read for `activatedCrystals`, `creationDate`, `iconIndex` and
`ActivatedContentBundles`. A mod reading *those* through the save manager gets
real data on a server. Only mode, name, seed and the assembled `WorldInfo`
bypass it.

**Trap: the setters were not rewritten to match the getters.** `SetWorldMode`
and `SetWorldName` are character-identical to their client versions and still
write into `worldInfo[_worldId]`. The write genuinely happens — it just cannot
matter, for two independent reasons:

1. None of the four rewritten getters consults the array, so nothing reads the
   value back.
2. The write-back path is gone. `WriteWorldInfo(int)` is replaced server-side by
   a single `Debug.LogError("Trying to write world info as server")`, and the
   parameterless overload delegates to it — so the value never reaches disk
   either.

Configuration is the only path that reaches a server's world properties.

**Trap: that error line is not your bug.** A mod calling `WriteWorldInfo` on a
server plants `[Error] Trying to write world info as server` in the log. It
reads like a fault in the caller; it is the server's ordinary refusal path.

### Achievements and RGB peripherals are compiled out

Two build defines are absent server-side, which removes every achievement
trigger and every RGB-peripheral event from the compiled code — that difference
alone accounts for the entire `Pug.Objects` and `Pug.Dev` diff. Correspondingly,
the RGB SDK library ships with the client installation and not with the server.

A mod that triggers an achievement or drives peripheral lighting is therefore
calling into something that does not exist on a server. Guard such calls, or
keep them on the client side of your mod.
