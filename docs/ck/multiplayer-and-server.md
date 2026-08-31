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
`GhostCollectionPrefabSerializer`, `GhostCollectionCustomSerializers`,
`NetworkProtocolVersion` — and the SDK matches them with
`ProjectSettings/NetCode{Client,Server,ClientAndServer}Settings.asset`. The
similarly-named `ghostCollectionHash` further down is not one of these — it is
CK's own field on `PlayerConnectRequestRPC` (`Pug.ECS.Components:3628`), not a
symbol from `Unity.NetCode.dll`.

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
| **A new `IRpcCommand` type** | **changed** — see below |

The first two are the overwhelming majority of mods, and they pass NetCode's
check untouched — their compatibility problem is entirely the mod-set layer
below. Registering a new replicated component is the case to think twice about:
it alters the component/ghost collection, so the NetCode check fires **on top of**
whatever `requiredOn` says, and `requiredOn` cannot excuse it.

### Declaring one RPC moves the protocol hash for everyone

A mod that wants to talk to the server declares an `IRpcCommand`. That is
sandbox-legal — `Unity.NetCode.dll` is in the load-time compiler's own reference
list (`RoslynCSharpSettings.asset`) — and it costs a fourth protocol value:

```csharp
// Unity.NetCode, RpcCollection.CalculateVersionHash()
ulong num = m_RpcData[0].TypeHash;
for (int k = 0; k < m_RpcData.Length; k++)
    num = TypeHash.CombineFNV1A64(num, m_RpcData[k].TypeHash);
```

Every registered RPC type's `StableTypeHash` is folded into one value, which
becomes `NetworkProtocolVersion.RpcCollectionVersion`. `RpcSystem` compares all
four values — NetCode version, game version, RPC collection, component
collection — and rejects the connection if **any** of them differs.

**The one escape is not taken.** `CalculateVersionHash` returns `0` instead of
the fold when `DynamicAssemblyList` is set, which would make the RPC set
negotiable. That flag is set **nowhere** in the 122 decompiled assemblies, so
the fold always applies.

Two consequences worth knowing before declaring an RPC:

- **The rejection names no mod.** It happens in the NetCode layer, *before* the
  mod-set check below, and surfaces as `Error/BadProtocolVersion` — "Game version
  mismatch". The dialogue that names a mod and offers to disable it belongs to
  the layer that never runs.
- **A dependency can have moved the hash already.** CoreLib's Command submodule
  declares two `IRpcCommand` structs and registers them through a generated
  `ISystem` whose `OnCreate` runs unconditionally — no `[WorldSystemFilter]`, no
  submodule gate. Whether those systems reach the worlds is the same open
  question as any mod system's registration path, so treat this as **plausible,
  not established**: one attempt with a CoreLib client against an unmodded
  server settles it.

### Why there is no third-party server

The obvious-looking blocker — SDR — is not the blocker. The blocker is the
build-time-generated ghost serialization: a reimplementation would have to
reproduce the whole component landscape bit-exactly, which is the whole game,
including the world generation that needs OpenGL/Mesa on the server side. The
pragmatic path for anything server-authoritative is always the official server
binary plus a server-side mod.

**There is no macOS build** — see [platforms](platforms.md#there-is-no-macos-build).
On Apple Silicon that leaves Wine/CrossOver or a Linux container for running
the server; the `escapingnetwork` server image has an ARM variant via Box64.
Getting one running is [below](#getting-one-running).

## The second layer: the mod set

Core Keeper runs its own mod comparison at connect time, in `ModInfoRpcSystem`
and `NetworkClientStartSystem`, entirely independent of NetCode's hash
validation. What it compares, why the two checks are crossed, and how to
choose a `requiredOn` value are in [mod anatomy](mod-anatomy.md#requiredon-and-its-crossed-checks).

The consequence for the network layer: a client-only HUD mod that carries
`Server` does not "declare itself client-side" — it declares that every
server you join must also run it.

### What the server actually sends

Once the connection is up the client sends an empty `ModInfoRequestRPC`, and the
server answers with one `ModInfoRPC` per loaded mod
(`Pug.ECS.Components:3681`):

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
(`Pug.Other:125928`), and `FixedString32Bytes` holds 29 UTF-8 bytes — so 14
characters are all that survive. Matching is unaffected, and for a **published**
mod neither is the display: when the server demands a mod the client lacks, the
client resolves `modId` through `ModIOUnity.GetMod` and prints the mod.io
profile name instead (`:125076`), or `"Unknown"` if that lookup fails
(`:125066`, `:125072`) — `GetMod` is only ever called for a **positive**
`modId` (`Pug.Other:125064-125083`). For a **negative** one — a mod
side-loaded from `StreamingAssets/Mods` — `GetMod` is skipped entirely, and
the truncated field is exactly what reaches the player. In the other
direction — your `Server`-flagged mod missing on the server — the dialogue
prints the client's own local `metadata.name` (`localMod.name =
loadedMod.Metadata.name`, `Pug.Other:124927`), untruncated, and never touches
this field at all.

**If you patch this layer:** `ModInfoRpcSystem.OnCreate` builds its mod list
exactly **once**, not per request, and — unlike `OnUpdate` and `OnDestroy` in the
same struct — carries **no `[BurstCompile]` attribute** of its own. The struct
itself does (`Pug.Other:125498`), so a grep for the attribute on the type still
turns it up — only `OnCreate` is exempt. On the client,
`NetworkClientStartSystem.OnUpdate` (`Pug.Other:124905`) is a plain
`protected override void OnUpdate()` and already holds the client's copy of the
list; the job that actually receives the RPCs,
`NetworkClientStartSystem_33002849_LambdaJob_0_Job` (`Pug.Other:124547`),
carries no `[BurstCompile]` attribute either, holds a managed
`NetworkClientStartSystem __this` field (`:124549`), and is dispatched through
`RunWithoutJobsInternal` (`:124642`) — it cannot be Bursted, so a Harmony patch
on it is viable. Whether a Harmony patch on `OnCreate` binds early enough on a
**dedicated server** — where `IMod.Init()` runs after the worlds are built, see
below — is untested.

### What a mismatch looks like to the player

It is a hard block, not a warning (~124940-124978). Joining a server that lacks a
`Server`-flagged mod raises `Menu/ModMissingServerDialogue`, and the dialogue
offers exactly two ways out:

- **disable the mod** — `ModIOUnity.DisableMod` plus a restart of the game, or
- **cancel the connection** — `cancel = true` → `Disconnect`.

There is no "join anyway". And for **a mod side-loaded from
`StreamingAssets/Mods`** (`modId <= 0`) it is worse: the dialogue key itself
changes, to `Menu/LocalModMissingServerDialogue` ("Required mod {0} is missing
from server."), and the disable branch is not offered at all, because there is
no mod.io subscription to disable — the dialogue reduces to `cancelDialogue`,
so the player cannot get onto that server by any route the game provides.

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

### Who is allowed to change things: admin level and guest mode

A mod that gates anything on "may this player do that" does not need to invent a
rule — the game ships one, and CoreLib's config scopes already delegate to it.

**`adminPrivileges` is an `int` on the player, and its levels are not
interchangeable.** `PlayerController.adminPrivileges` reads it off the
`PlayerGhost` component and returns `0` when there is none (`Pug.Other:298371`):

| Value | Meaning |
|---|---|
| `0` | no admin |
| `1` | granted through the admin list, and revocable |
| `2` | host or first player — `RemoveAdminInternal` only matches entries with `privileges <= 1`, so this one cannot be taken away |
| `int.MaxValue` | **offline or uninitialised networking** — `GetAdminPrivileges` short-circuits on `!impl.isInitialized \|\| OfflineSession` |

That last row is what makes singleplayer look like it has no permission model at
all: everyone is a full admin there, so every admin-gated branch is taken and
nothing ever locks. A permission feature therefore **cannot be tested in
singleplayer** — it needs a second player who is not the host.

**`guestMode` is not a world flag alone.** `WorldInfoCD.guestMode` is the world's
setting, but `PlayerController.guestMode` (`:298432`) answers the useful
question — it returns true only when the world flag is set **and**
`adminPrivileges < 1`. An admin in a guest-mode world is not a guest.

**Both change during a session.** `NetworkCommand` carries `AddOrUpdateAdmin`,
`RemoveAdmin` and `SetGuestMode`, handled by `NetworkCommandServerSystem` behind
an admin check of its own. So a value read once when a screen opens can be stale
by the time the player acts on it — a UI that gates on either has to re-read or
poll. There is no change event for either: `adminPrivileges` is a property over a
component and `guestMode` a field in a singleton, and nothing announces a write
to them.

**There are no chat commands for this.** A search for a command dispatcher —
`ChatCommand`, `StartsWith("/")` — comes up empty across client and server
assemblies; admin rights are granted through the UI and travel as the RPC above.

### Check `[GhostField]` before assuming a write replicates

Two things decide whether an ECS write reaches the other side, and you need
both of them.

**The declaration decides whether the value is on the wire at all.** Codegen
emits one `…GhostComponentSerializer` per replicated component, and its
`Snapshot` struct holds exactly that component's `[GhostField]`s and nothing
else — `PlacementCDGhostComponentSerializer` (`Pug.ECS.Components:42160`) is the
worked example below.

**The world you wrote it in decides the direction, and there is only one
direction.** Snapshots are produced in the server world — `GhostSendSystem`,
which `NetworkingManager.InitWorld` (`Pug.Other:285322`, the class itself at
`:284453`) configures only in the world that has one, called from
`ECSManager.InitWorld` (`:2996`) for both worlds — and applied in the client
world, `GhostUpdateSystem`, which CK fetches from `Manager.ecs.ClientWorld`. So
a `[GhostField]` write in the server world replicates, and the identical write
in the client world reaches nobody and is overwritten by the next snapshot.
Client → server is a separate mechanism, not ghost fields: player input
(`ClientInputData`, an `IInputComponentData`, `Pug.ECS.Components:3444`, carried
by the generated command send/receive systems at `:15462` and `:15612`) and
RPCs.

Read the attribute before assuming either way — and read it per *field*, not per
component:

| Component | Replicated |
|---|---|
| `HealthCD` | yes — declared `[GhostField]`, so a server-side change travels to the client |
| `PlacementCD`'s placement-permission flags — `canPlaceOnWalkableTiles` through `blockedByObjectsOnWalls` (`Pug.ECS.Components:4298-4316`) | no — the tail of the struct carries no `[GhostField]` and none of those fields appears in the generated snapshot, so they are world-local state. The rest of `PlacementCD` *is* replicated, `canPlaceGround` (`:4287`) and `canPlaceRoofHole` (`:4290`) included — this is a per-field answer, not a per-component one |

What the client then *does* with a replicated value is a separate question: for
`HealthCD` it is unverified whether a damage-stage sprite or a progress bar
refreshes on its own.

For those flags the consequence runs the other way — writing them on one side
changes nothing on the other. The surrounding code is present on both:
`EquipmentSystemGroup` (`Pug.Other:418856`) runs in the server **and** the client
simulation world, and `EquipmentUpdateSystem.UpdateJob` is a scheduled job.
Whether a Harmony prefix in that area therefore behaves identically across
singleplayer, a hosted session and a dedicated server is an open question — treat
it as "can run on either side" and verify on the topology you care about.

## The dedicated server

What follows is true of the *game*, wherever the server runs. How you wire one
up — where it lives, how it is started and stopped, how its world and mods are
kept beside a client's — is a matter of local arrangement.

### Getting one running

The dedicated server is **Steam app `1963720`**, free, and installable without
owning anything: `steamcmd +login anonymous +app_update 1963720 +quit`. Like the
game itself it ships for **Windows and Linux only** — see [platforms](platforms.md)
for what that means on a Mac.

It is worth having for mod work. It is the only way to exercise the
server-authoritative half of a mod — `requiredOn` behaviour, server commands,
world-mutating logic — without a second machine.

Four things about starting it are not obvious:

- **`-batchmode` yes, `-nographics` never.** Part of world generation runs on
  the GPU, so a headless server still needs a graphics device; without one it
  exits during generation. On a bare Linux host that is what `xvfb` plus Mesa
  are for. (The mechanism is [below](#the-server-renders-so-it-needs-a-graphics-device).)
- **`-port` works only as a command-line argument.** Setting it in
  `ServerConfig.json` has no effect. With a port the server takes direct
  connections; without one it is reachable only through the Steam relay, by its
  Game ID.
- **`-allowonlyplatform Steam`** avoids a join refused for a *"missing the
  crossplay privilege"*: it puts client and server on one platform, and the
  check is skipped. It does nothing on its own — the shipped `ARGUMENTS.txt`
  says it "has no effect unless -port is also set", because the flag is read
  only inside the direct-connection branch that `-port` gates.
- **A cold start with a full mod set takes minutes** — every source mod goes
  through Roslyn and the world is decompressed on load. A server that looks hung
  shortly after launch usually is not.

The server autosaves every 60 seconds (`AutoSaveInterval`, switchable off with
`-disableautosave`), so even an abrupt end costs at most a minute of play.

### Stopping one without losing the world

A dedicated server writes its world in its **quit handlers**, and those only run
on a Windows close request — what Unity turns into a quit. `taskkill` without
`/F` sends one; a POSIX signal does not. Kill it with `SIGTERM` and the process
simply disappears, leaving only the last autosave. Pugstorm's own launch script
uses `taskkill` for this reason.

The log distinguishes the two paths outright:

```
Got quit request
Exit blocked by ECSManager     <- the manager holding the world defers the quit
Quit blocked
Got quit request
Running quit handlers          <- Deinit() on every manager
```

`Running quit handlers` appears only on the graceful path.

**`PID.txt` is never written.** `IsPreviousServerRunning()` — the function that
would write it — has no call site in either build, so the installed server
directory holds none. The function that reads one, `CheckPIDFile`, reports "a
server is already running" only when `Process.GetProcessById(pid)` resolves to
a live process whose `MainModule.FileName` matches — but with nothing ever
writing the file, that check has nothing to find.

### The client builds no server world

Joining a dedicated server, the client constructs only `ClientWorld0` — there is
no `ServerWorld` in the process. Anything server-authoritative is decided
entirely in the server process, and a client-side patch on a server-authoritative
system will at best win for a few ticks before the next ghost snapshot overwrites
its value.

**That absence is the topology test.** `Manager.ecs.ServerWorld` is a public
property (`Pug.Other:2381`) assigned only where the process creates a server
world (`:2837`) and nulled on teardown (`:2936`); vanilla itself branches on it
in at least eight places (`:2152`, `:2487`, `:2517`, …), and the SDK exposes the
same object as `API.Server.World` (`ModAPIServer.World`, `:392317`). So a mod
that needs to know whether it *is* the authority asks one question:

```csharp
bool iAmTheAuthority = Manager.ecs.ServerWorld != null;
```

| Situation | `ServerWorld` | `ClientWorld` |
|---|---|---|
| Singleplayer | ✓ | ✓ |
| Hosting a session | ✓ | ✓ |
| Joined a host, or a dedicated server | ✗ | ✓ |
| Dedicated server process | ✓ | ✗ |

**Singleplayer and hosting are the same case, not two.** Both own the server
world, so both *are* the authority — a mod that asks the server for permission
has nobody to ask in either, and a round trip there is a round trip to itself.
The distinction that matters is not "am I in multiplayer" but "does someone else
decide".

Two neighbouring signals on `Manager.networking` (a `NetworkingManager`,
`Pug.Other:263198`) answer narrower questions and are not substitutes for the
one above: `isConnected` is a plain settable `bool` property, and
`currentSessionIsDedicatedServer` asks the platform layer
(`impl.ConnectedToDedicatedServer`) and returns `false` whenever there is no
network at all. Neither distinguishes hosting from joining, which is precisely
what `ServerWorld` does.

### A mod-set mismatch reports a version error

The client shows **"Game version mismatch"** — the English text of the
localisation key `Error/BadProtocolVersion` (the German build reads "Falsche
Spielversion"; the wording is whatever the client is localised to, the key is
not). It almost never has anything to do with the game version — a mod set
that differs in mods which **register ECS components or ghost prefabs**
produces exactly this message, because those are the mods that move the
hashes the two sides compare. Nothing in the message mentions mods.

**No mod name appears anywhere in the connect handshake**, which is why the
split in the table above decides who can hit this. CK's own connect handshake rejects on two
values (`Pug.Other:126187`, `:126203`): `localVersionHash`, which is
`PlayerConnectRequestRPC.GetVersionHash(Manager.version)` — the game version and
nothing else (`:126655`) — and `ghostCollectionHash`, the XOR of every
`GhostCollectionPrefab.Hash` in the default world
(`ECSManager.TryCalculateGhostCollectionHash`, `:2450`). NetCode's own
`NetworkProtocolVersion` check compares the same kind of thing one layer down.
A mod set differing only in Harmony-patch or bake-time mods leaves all of it
untouched and the join **succeeds** — which is exactly the gap `requiredOn`
exists to close. In practice that puts content mods on the hash-moving side:
adding an entity through CoreLib's `EntityModule` clones a prefab and stamps the
clone's `GhostAuthoringComponent` with a fresh `prefabId` — a change to exactly
the set `ghostCollectionHash` fingerprints.

Diagnose in `Player.log`: hundreds of `ComponentHash[N]` lines followed by
`Client disconnected because Error/BadProtocolVersion`.

**A missing required dependency is one of the ways the sets drift apart.** If a
mod declares a `required` dependency that is not installed on the server, the
loader's `SortMods` drops the *dependent* mod there and says so only in a log
warning — and does that for at most one such mod per pass; see [mod anatomy](mod-anatomy.md) for
that limit. The two sides then hold different mod sets, and if the dropped mod
is one of the hash-moving kind the client reports the same
`Error/BadProtocolVersion`; nothing in it names a dependency. So when you
publish a mod that depends on another, the server needs **both** installed, not
just yours — and this is the diagnostically expensive case, because the symptom
points at the game version while the cause is one absent dependency on one
machine.

### Version filtering belongs to the subscription loaders

Which loader fetched a mod decides whether its version-compatibility tags get
checked — not which machine is running it. A subscription loader skips a mod
that does not match the running game version, unless the mod's GUID sits in
`modloader/config.json` → `unsupportedModsToLoad`, which is what the "load
anyway" dialogue writes.

**Trap:** copying that list to the server accomplishes nothing — and not because
the server's loader is a different build. `PugMod.Loader` is all but identical on
both sides. The version check belongs to the *subscription* loaders, which pass
`ModVersion.IsCompatible(Application.version, tags)` into
`Integration.AddMod(…, supportsCurrentVersion)`: `ModIOLoader`
(`PugMod.Platform:70`) and `SteamWorkshopLoader` (`PugMod.Loader:156`). The
directory scan does not — `SideLoader` passes `supportsCurrentVersion: true`
**hardcoded** (`PugMod.Loader:2173`), so the gate the list feeds —
`!supportsCurrentVersion && !contains(guid)` — can never fire for a side-loaded
mod. And a dedicated server's `Manager` registers only `SideLoader` and
`SteamWorkshopLoader`, never `ModIOLoader` (`Pug.Other:263316-263325` against
`DedicatedServer:263259-263262`), while `StreamingAssets/Mods` is how a server is
normally given its mods. The rule that predicts both cases is therefore about the
*source* of a mod, not about the build: a mod side-loaded into the **client's**
own `StreamingAssets/Mods` skips the version check just as thoroughly.

The asymmetry therefore runs one way only, and it is a mismatch generator: a mod
the **client rejects** but the server still loads is a set difference. Resolve
it on the side that actually filters — either confirm the mod in the client's
dialogue, or remove it from the server. Note also that the loader **clears
`unsupportedModsToLoad` when the first three version components change**, so a
mod confirmed once silently drops out of the client's set after the next game
update, and the join that worked yesterday fails today with no change on either
machine.

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
i.e. the mod-set symptom, one step removed from the real cause. Details in [platforms and hosts](platforms.md).

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

The two mod log formats come from different loader *stages*, not from different
builds — both processes write both. `loaded mod <Name> …` is written once per mod
by whichever loader found it: `… at <path>` for the `StreamingAssets/Mods`
directory scan (what a dedicated server uses, `PugMod.Loader:2178`), `… from
mod.io (<Profile>)` for a mod.io subscription (`PugMod.Platform:97`, what the
client usually uses), `… from steam workshop (<Title>)` for the third.
Afterwards both processes log `Loading mod with ID <modId>` once per loaded mod,
from `ModManager.Init()`, regardless of source. So `grep "loaded mod "` is the
one pattern that works on both sides — it is not the only one that names a mod,
though: `not loading incompatible mod <name>` (`PugMod.Loader:1175`), `skipping
mod <name> because of missing dependency` (`:990`) and `failed to load mod
<name> …` (`:2175`) each name one too, for their own failure case.

### Warning: the lifecycle order is inverted

`IMod.Init()` runs at a different point relative to ECS startup on the two
processes — **before** the worlds are built on the client, **after** them on the
dedicated server. Anything that registers itself during `Init()` and is consumed
by a snapshot taken at ECS startup therefore works in singleplayer and is a
silent no-op on the server, with no error and no log line. `BurstDisabler` is
the case this bites in practice; the mechanism and the fix belong to [Harmony and ECS](harmony-and-ecs.md).
If your mod is server-authoritative and works alone but not in multiplayer,
start there.

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
`SerializeWorldSystem`, `SaveManager`, `ModManager`, `Manager`, `ECSManager`
and others — the source list this is drawn from does not end there.

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

The server never reuses a directory, so it accumulates one extract directory per mod per
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
| `GetWorldGenerationType()` (no id) | returns `worldInfo[_worldId].worldGenerationType` | derives it from the configured mode: `Creative` if `GetWorldMode()` is creative, else `FullRelease` |

Wherever a server accessor still takes an id, the parameter is accepted and
**never read**. Passing a slot number therefore does not select anything — you
always get the one hosted world, and a mod that treats a differing id as a
differing world will be wrong in a way that no error reports.

**The array itself is not dead** — be precise here, because the obvious
generalisation is wrong. It is allocated normally, still loaded from disk, and
still read for `activatedCrystals`, `creationDate`, `iconIndex` and
`ActivatedContentBundles`. A mod reading *those* through the save manager gets
real data on a server. Only mode, name, seed, world-generation type and the
assembled `WorldInfo` bypass it.

**Trap: the setters were not rewritten to match the getters.** `SetWorldMode`,
`SetWorldName` and `SetWorldGenerationType` are character-identical to their
client versions and still write into `worldInfo[_worldId]`. The write genuinely
happens — it just cannot matter, for two independent reasons:

1. None of the five rewritten getters consults the array, so nothing reads the
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
