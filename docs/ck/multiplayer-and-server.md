# Multiplayer and the dedicated server

Everything a mod does in singleplayer it does alone. The moment a second machine
is involved, three gates decide whether the two sides may talk at all: Unity
NetCode's own protocol validation, Core Keeper's mod check on top of it, and
Core Keeper's own connect handshake after that. NetCode's gate knows nothing of
the other two; the client holds the handshake back until the mod check is done, so
those two run in a fixed order. The mod check names the mod it is missing; a
hash mismatch at either of the other two fails in a way that names neither your
mod nor the real cause. This chapter covers what those gates check, what a
mismatch looks like from the player's seat, and what is different about a mod
running inside a dedicated server process.

## The netcode stack

Three layers, two of them off-the-shelf:

| Layer | Assembly | Role |
|---|---|---|
| Transport | `Unity.Networking.Transport.dll` | packet delivery |
| Replication | `Unity.NetCode.dll` (+ `.Physics`, `.Physics.Hybrid`, `.Hybrid`, `.Authoring.Hybrid`) | NetCode for Entities — ghosts, snapshots, RPCs |
| Relay | `Facepunch.Steamworks.Win64.dll` | Steam Datagram Relay (SDR) |

The replication layer is **NetCode for Entities / DOTS Netcode**, but not stock:
the SDK carries it as a local package, `com.unity.netcode` 1.2.4, with
Pugstorm's edits in it (`GhostUpdateSystem.cs` names them: "Due to Pugstorm
modifications…"). One of those edits decides much of what follows and is in the
shipped `Unity.NetCode.dll` of both installations too — see the next section.
The server assemblies carry its symbols verbatim — `GhostCollectionSystem`,
`GhostCollectionPrefabSerializer`, `GhostCollectionCustomSerializers`,
`NetworkProtocolVersion` — and the SDK matches them with
`ProjectSettings/NetCode{Client,Server,ClientAndServer}Settings.asset`. The
similarly-named `ghostCollectionHash` further down is not one of these — it is
CK's own field on `PlayerConnectRequestRPC`
(`Pug.ECS.Components:PlayerConnectRequestRPC:ghostCollectionHash:1`), not a
symbol from `Unity.NetCode.dll`.

SDR does **not** come from Unity. It is Facepunch's Steamworks binding
(`SteamNetworkingSockets`, `SteamNetworkingIdentity`, `SteamDatagramHostedAddress`,
`SteamNetworkingFakeUDPPort`), and it sits underneath as a swappable transport
interface, not as protocol semantics. A server started with a port set takes
direct UDP connections; with no port it is reachable only through the relay. The
protocol above is identical either way.

### What changes the ghost hashes — and what does not

On connect the two sides exchange `NetworkProtocolVersion` — NetCode version,
game version, RPC collection, component collection — and, in CK's own handshake
afterwards, the ghost collection hash. Those are two different comparisons, and
they do not see the same things:

- **NetCode's component collection value is always `0`.**
  `GhostCollectionSystem.CalculateComponentCollectionHash` starts with `return
  0; // TODO(Max): Remove when we have solved why this is 0 only on client` in
  the SDK's package source, and the shipped client and server `Unity.NetCode.dll`
  both decompile to a bare `return 0uL;`. So of the four NetCode values only the
  NetCode version, the game version and the RPC collection can ever differ —
  NetCode's own check sees a mod's **RPCs**, and nothing about its components.
- **CK's `ghostCollectionHash` sees the ghost prefabs.** It is the XOR of every
  `GhostCollectionPrefab.Hash`, and NetCode generates the serializers those
  hashes describe at **build time** from the replicated component types — so it
  fingerprints the *replicated* landscape present at connect time, a mod's own
  included, and nothing the loader can negotiate at runtime. A component with no
  ghost serializer, or one on no ghost prefab, does not enter it.

For a mod this splits as follows:

| Kind of change | Hashes |
|---|---|
| Harmony patches on managed systems | unchanged |
| Bake-time property edits, changed values, recipe/database tweaks | unchanged — unless the edit changes which components a ghost prefab carries |
| **New ghost prefabs, or new replicated components on one** | **CK's `ghostCollectionHash` changes**; NetCode's values do not |
| **A new `IRpcCommand` type** | **NetCode's RPC collection changes** — see below |

The workspace mods sit mostly in the first two rows, but not provably all of
them. `caveling-divining-rod` adds an item entity through CoreLib's
`EntityModule`; its prefab carries no `GhostAuthoringComponent`, which points to
the first two rows, and whether the converted item nonetheless enters the ghost
collection is **unverified**. And every mod here that requires CoreLib inherits
CoreLib's two RPCs (below). Among the third-party mods installed here, counted on
2026-10-07, a third (12 of 36) declare an `IRpcCommand` and so sit in the last
row; the first two rows are common, not universal.

Adding a ghost prefab is the case to think twice about, though not for the
reason it looks. The comparison it trips is CK's handshake, which the client
sends only after the mod check (below) — so for a mod flagged `Server` the mod
check names it first and the hash is never compared. Only a difference the mod
check lets through reaches the hash — a mod without that flag, or the same mod
in two versions whose ghost prefabs differ — and fails there as a version error
that names nothing.

### Declaring one RPC moves the protocol hash for everyone

A mod that needs a message type of its own declares an `IRpcCommand` — one that
can say what it needs through a vanilla command (`sign-labels` drives
`SetWorldLabelVisibility`, below) or through CoreLib's shared command RPC
declares none. Declaring one is sandbox-legal — `Unity.NetCode.dll` is in the
load-time compiler's own reference list (`RoslynCSharpSettings.asset`) — and it
costs a fourth protocol value:

```csharp
// Unity.NetCode, RpcCollection.CalculateVersionHash()
ulong num = m_RpcData[0].TypeHash;
for (int k = 0; k < m_RpcData.Length; k++)
    num = TypeHash.CombineFNV1A64(num, m_RpcData[k].TypeHash);
```

Every registered RPC type's `StableTypeHash` is folded into one value, which
becomes `NetworkProtocolVersion.RpcCollectionVersion`. `RpcSystem` compares all
four values — NetCode version, game version, RPC collection, component
collection — and rejects the connection if **any** of them differs; with the
component value fixed at `0`, that is in practice a comparison of the first
three. The rejection itself is a disconnect with reason `InvalidRpc`, which CK
maps to the same `Error/BadProtocolVersion` as a plain protocol mismatch
(`Pug.Other:ClientDisconnectSystem:OnUpdate:22`). RPCs travel as an index into
the agreed list, not as a hash, so a differing set is caught here, at the
version message, which every other RPC has to wait for — NetCode looks an RPC up
by its hash only in the `DynamicAssemblyList` mode below.

**The one escape is not taken by vanilla.** `CalculateVersionHash` returns `0`
instead of the fold when `DynamicAssemblyList` is set, which would make the RPC
set negotiable — and, in the NetCode 1.2.4 package source, the component set
too. No vanilla code sets that flag: it appears nowhere in the 132 curated
assemblies of the 1.3.0.5 decompile. `Unity.NetCode.dll` itself is not among
them; the NetCode code quoted here is read from the package source, and the
points this chapter rests on — the fold above, the `return 0uL` of the component
hash, the index-versus-hash branch — were checked against a decompile of the
shipped client and server copies of 1.3.0.5 as well.

Two consequences worth knowing before declaring an RPC:

- **The rejection names no mod.** It happens in the NetCode layer, *before* the
  mod-set check below, and surfaces as `Error/BadProtocolVersion` — "Game version
  mismatch". The dialogue that names a mod and offers to disable it belongs to
  the layer that never runs.
- **A dependency can have moved the hash already.** CoreLib's Command submodule
  declares two `IRpcCommand` structs and registers them through two generated
  `ISystem`s, one per struct, whose `OnCreate` runs unconditionally — no
  `[WorldSystemFilter]`, no submodule gate. Whether those systems reach the
  worlds is the same open question as any mod system's registration path, so
  whether CoreLib alone moves the hash is **unverified**: one attempt with a
  CoreLib client against an unmodded server settles it. It matters more than it
  looks — `item-checklist`, `player-coordinates-hud` and `refill-ore-boulders`
  in this workspace are `Client`-only and require CoreLib, so any of them is the
  test case. Read the outcome by which gate answered: NetCode's check runs
  before the mod check, so a moved hash shows as `Error/BadProtocolVersion` with
  all three. An unmoved one lets `refill-ore-boulders` join, while the other two
  stop at the mod check instead — they also require `ModSettingsMenu`, which
  carries `requiredOn: 3`.

### Why there is no third-party server

The obvious-looking blocker — SDR — is not the blocker. The blocker is the
build-time-generated ghost serialization: a reimplementation would have to
reproduce the whole component landscape bit-exactly, which is the whole game,
including the world generation, which needs a graphics device on the server side
(Mesa, on a bare Linux host). The pragmatic path for anything
server-authoritative is always the official server binary plus a server-side
mod.

**There is no macOS build** — see [platforms](platforms.md#there-is-no-macos-build).
On Apple Silicon that leaves Wine/CrossOver or a Linux container for running
the server; the `escapingnetwork` server image ships Box64 builds for ARM hosts,
`m1` among them, according to its own README (checked 2026-10-08).
Getting one running is [below](#getting-one-running).

## The second layer: the mod set

Core Keeper runs its own mod comparison at connect time, in `ModInfoRpcSystem`
and `NetworkClientStartSystem`, entirely independent of NetCode's hash
validation. What it compares, why the two checks are crossed, and how to
choose a `requiredOn` value are in [mod anatomy](mod-anatomy.md#requiredon-and-its-crossed-checks).

It also comes **before** Core Keeper's own connect handshake. The client does
not send its `PlayerConnectRequestRPC` — the request carrying the version and
ghost-collection hashes — until every `ModInfoRPC` has arrived and every
missing-mod dialogue has been answered
(`Pug.Other:NetworkClientStartSystem:OnUpdate:30-90`). So a mod difference the
mod check catches is reported by name, and only a difference it lets through can
reach CK's hash comparison below. NetCode's own check is the exception to that
order: it runs before either, so a mod whose RPCs differ is rejected as a
version error before the mod check could have named it.

The consequence for the network layer: a client-only HUD mod that carries
`Server` does not "declare itself client-side" — it declares that every
server you join must also run it.

### What the server actually sends

Once the connection is up the client sends an empty `ModInfoRequestRPC`, and the
server answers with one `ModInfoRPC` per loaded mod
(`Pug.ECS.Components:ModInfoRPC:1`) — or, with no mods loaded, a single one carrying
only `lastMod = true` (`Pug.Other:ModInfoRequestResponseJob:Execute(Entity, …):13`):

| Field | Type |
|---|---|
| `modId` | `long` |
| `modGuid` | `Hash128` |
| `modName` | `FixedString32Bytes` |
| `required` | `bool` |
| `lastMod` | `bool` |

Identity is matched on `modId` **or** `modGuid`
(`Pug.Other:NetworkClientStartSystem_33002849_LambdaJob_0_Job:OriginalLambdaBody:12`)
— the name is never compared. `modName` travels only so the missing-mod dialogue
has something to print; it ends up in `ModCheck.modName`. The id only counts
when it is non-zero and the same on both sides, and against a dedicated server
it almost never is: the server side-loads every mod (below), so its ids are the
negative side-loader ones, while the client's copy normally carries a mod.io or
Workshop id — or, for a fake-ID dev build, a positive one of its own. In that
topology the guid alone decides. The exception is a client that side-loads the
same mod too: both sides then derive the id by the same formula from the
manifest name (`PugMod.Loader:SideLoader:Update:44`).

**Trap: that name is truncated to 14 characters.** The server fills the field
with `name.Substring(0, min(UTF8MaxLengthInBytes / 2, len))`
(`Pug.Other:ModInfoRpcSystem:OnCreate:13`), and `FixedString32Bytes` holds 29
UTF-8 bytes — so 14 characters are all that survive. Matching is unaffected.
What decides the display is the `modId` the **server** reports, not whether the
mod is published: when the server demands a mod the client lacks, the client
resolves a **positive** `modId` through `ModIOUnity.GetMod` and prints the
mod.io profile name instead
(`Pug.Other:NetworkClientStartSystem:UpdateModChecks:23`), or `"Unknown"` if
that lookup fails (`Pug.Other:NetworkClientStartSystem:UpdateModChecks:16`,
`Pug.Other:NetworkClientStartSystem:UpdateModChecks:19`) — `GetMod` is only ever
called for a positive one
(`Pug.Other:NetworkClientStartSystem:UpdateModChecks:11-30`). For a **negative**
one — a mod side-loaded from `StreamingAssets/Mods`, which on a dedicated server
is every mod — `GetMod` is skipped entirely, and the truncated field is exactly
what reaches the player. So against a dedicated server the 14-character name is
the normal case, published mod or not. A mod a host loaded from the Steam
Workshop reports its Steam file id
(`PugMod.Loader:SteamWorkshopLoader:InitAsync:58`), which the client looks up on
mod.io all the same — and the dialogue's "yes" then asks mod.io to subscribe to
that number (`ModIOUnity.SubscribeToMod`,
`Pug.Other:NetworkClientStartSystem:UpdateModChecks:55-72`), whichever mod.io
mod, if any, happens to carry it. In the other direction — your `Server`-flagged
mod missing on the server — the dialogue prints the client's own local
`metadata.name` (`localMod.name = loadedMod.Metadata.name`,
`Pug.Other:NetworkClientStartSystem:OnUpdate:24`), untruncated, and never
touches this field at all.

**If you patch this layer:** `ModInfoRpcSystem.OnCreate` builds its mod list
**once per world it is created in**, not per request — once on a dedicated
server, once per server world a hosting client starts — and the per-request
responder `ModInfoRequestResponseJob` is itself `[BurstCompile]`
(`Pug.Other:ModInfoRequestResponseJob:1`), so the list build is the patchable
side. `OnCreate` — unlike `OnUpdate` and `OnDestroy` in the same struct —
carries **no `[BurstCompile]` attribute** of its own. The struct itself does
(`Pug.Other:ModInfoRpcSystem:1`), so a grep for the attribute on the type still
turns it up — only `OnCreate` is exempt. On the client,
`NetworkClientStartSystem.OnUpdate`
(`Pug.Other:NetworkClientStartSystem:OnUpdate:2`) is a plain `protected override
void OnUpdate()` and already holds the client's copy of the list; the job that
actually receives the RPCs, `NetworkClientStartSystem_33002849_LambdaJob_0_Job`
(`Pug.Other:NetworkClientStartSystem_33002849_LambdaJob_0_Job:1`), carries no
`[BurstCompile]` attribute either, holds a managed `NetworkClientStartSystem
__this` field
(`Pug.Other:NetworkClientStartSystem_33002849_LambdaJob_0_Job:__this:1`), and is
dispatched through `RunWithoutJobsInternal`
(`Pug.Other:NetworkClientStartSystem_33002849_LambdaJob_0_Job:RunWithoutJobSystem:3`)
— it cannot be Bursted, so a Harmony patch on it is viable. Whether a Harmony
patch on `OnCreate` binds early enough on a **dedicated server** — where
`IMod.Init()` runs after the worlds are built, see below — is **unverified**.

### What a mismatch looks like to the player

It is a hard block, not a warning
(`Pug.Other:NetworkClientStartSystem:OnUpdate:37-75`). Joining a server that
lacks a `Server`-flagged mod the client got from mod.io or the Workshop (`modId
> 0`) raises `Menu/ModMissingServerDialogue`, and the dialogue offers exactly
two ways out:

- **disable the mod** — `ModIOUnity.DisableMod` plus a restart of the game, or
- **cancel the connection** — `cancel = true` → `Disconnect`.

Two details of that pair. "Disable" goes through mod.io whatever the mod's
source: for a Workshop copy the call is handed the Steam file id, and what that
does is **unverified**. And the answers are not independent when several mods
are missing — once one dialogue was answered with "disable", a later "cancel" is
routed into the same restart instead of cancelling
(`Pug.Other:NetworkClientStartSystem:OnUpdate:56-63`).

There is no "join anyway". And for **a mod side-loaded from
`StreamingAssets/Mods`** (`modId <= 0`) it is worse: the dialogue key itself
changes, to `Menu/LocalModMissingServerDialogue` ("Required mod {0} is missing
from server."), and the disable branch is not offered at all, because there is
no mod.io subscription to disable — the dialogue reduces to `cancelDialogue`,
so the player cannot get onto that server by any route the game provides.

This is why an over-broad `requiredOn` costs real usability: it turns "my HUD
mod does nothing on unmodded servers" into "my HUD mod has to be switched off,
with a restart, before every join to a server that lacks it" — and, for a
side-loaded copy, into "cannot join that server at all".

## Writing patches that behave in multiplayer

### `PlayerController` methods can fire for every player

A patch on a `PlayerController` method that runs per instance — the update path
every player's object goes through, for one — runs for **every connected
player**, not just for the one at the keyboard. Code that is only ever reached
through `Manager.main.player`, such as input handlers and UI-driven paths, runs
for the local player alone, so it is the method's call path that decides, not
the class. Singleplayer has exactly one player, so a missing check is invisible
in the very place mods get tested; in a session with several players the same
hook does the work — or mutates the same client-side state — once per player.
Gate every client-side `PlayerController` patch on the instance:

```csharp
if (!__instance.isLocal)
    return;
```

### A just-placed object cannot be named in an RPC yet

On the client that places it, an object first spawns as a **client-predicted
ghost**, and its entity carries `GhostInstance.ghostId == 0`. (It also carries a
`PredictedGhostSpawnRequest` in the frame it spawns, but NetCode's
`PredictedGhostSpawnSystem` removes that through a command buffer at the next
simulation step, so the component is no marker to wait on.) An RPC that names an
entity sends its ghost id — CK's player-command serializer writes
`ghostInstance.ghostId` for `entity0` (`Pug.Other:RpcSerializer:Serialize:7`) —
and the receiving side resolves `0` to nothing: it sets `entity0` to
`Entity.Null` and looks the id up only when it is non-zero
(`Pug.Other:RpcSerializer:Deserialize:9-10`). For `SetWorldLabelVisibility` the
handler then reads `ObjectDataCD` from `Entity.Null`
(`Pug.Other:ServerSystem:OnUpdate:317`), which `EntityUtility.GetComponentData`
catches and logs as *"GetComponentData<…> called on invalid entity"*
(`Pug.Other:EntityUtility:GetComponentData:9`), and records a command-buffer
write of the result against `Entity.Null`
(`Pug.Other:ServerSystem:OnUpdate:319`). Whether that log line appears depends
on the read actually throwing, which needs the Entities safety checks compiled
into the shipped build; what playing back the recorded write does to the rest of
that buffer is **unverified**. Observed on 1.3.0.4 with the RPC sent the moment
a placed sign spawned: a second later the sign's state was unchanged. The
server-side log line is derived from the source; that run did not capture the
server's log. The same command is also dropped outright on a guest-mode world
when the sender has no admin rights (`Pug.Other:ServerSystem:OnUpdate:44`, see
below), whatever it names.

When the server's ghost arrives, CK's own `PugSpawnClassificationSystem` looks
for a predicted spawn of the same ghost type, takes the nearest one less than
three tiles away on the XZ plane
(`Pug.Other:ClassificationJob:Execute(DynamicBuffer<GhostSpawnBuffer>, …):19`) —
or, for a ghost without a position in its snapshot, the oldest one by spawn tick
— and hands the incoming ghost that spawn's entity
(`Pug.Other:ClassificationJob:Execute(DynamicBuffer<GhostSpawnBuffer>, …):43`),
so NetCode promotes the **same** entity to the real ghost. An `Entity` or a
`MonoBehaviour` captured at the predicted spawn then stays valid, and no second
spawn was observed. That holds only when a match is found: a predicted spawn
destroyed meanwhile, or a server ghost more than three tiles off, leaves the
ghost to spawn as an object of its own. Measured on 1.3.0.4 in singleplayer, the
promotion took 0.12–0.18 s across ten placements; over a real network it is at
least a round trip, **unverified** in practice.

So an RPC about something the local player just placed waits for the promotion: keep
the entity, check each frame for a non-zero `GhostInstance.ghostId`, send then, and
give up after a timeout. Re-check before sending that the entity still exists and
still is the object you matched — a pooled `MonoBehaviour` can be handed to a
different entity in the meantime.

### Who is allowed to change things: admin level and guest mode

A mod that gates anything on "may this player do that" does not need to invent a
rule — the game ships one, and CoreLib's config scopes already delegate to it.

**`adminPrivileges` is an `int` on the player, and its levels are not
interchangeable.** `PlayerController.adminPrivileges` reads it off the
`PlayerGhost` component and returns `0` when there is none
(`Pug.Other:PlayerController:adminPrivileges:1`):

| Value | Meaning |
|---|---|
| `0` | no admin |
| `1` | granted through the admin list, and revocable |
| `2` | host or first player — `RemoveAdminInternal` only matches entries with `privileges <= 1`, so no command takes this one away; only `EmptyAdminAndBan`, which clears the whole list and is reachable from the developer-settings menu alone, does |
| `int.MaxValue` | **offline or uninitialised networking** — `GetAdminPrivileges` short-circuits on `!impl.isInitialized \|\| OfflineSession` |

The last two rows are what make singleplayer look like it has no permission
model at all: the one player there is either in an offline session, and so at
`int.MaxValue`, or the local player of a session it hosts, and so handed stage 2
by the bootstrap rule below — an admin either way, which of the two a given
singleplayer run takes being a runtime state of the networking layer. Every
admin-gated branch is taken and nothing locks. A permission feature therefore
**cannot be tested in singleplayer** — it needs a live session and a player
holding no rights.

**It does not need a second account, though.** Stage 2 is handed out by a
bootstrap rule keyed on the *list*, not on the person: `OnPlayerConnect` calls
`AddAdminInternal(…, 2, …)` when `adminList.Count == 0 || isLocalPlayer`
(`DedicatedServer/Pug.Other:NetworkingManager:OnPlayerConnect:6`), and a
dedicated server has no local player. Any entry at all therefore ends the
bootstrap, and every later connection that matches no entry lands on stage 0, so
a placeholder entry carrying a foreign `steamId` in `Admins.json` is enough to
join one's own server without rights. That file matches on `steamId` — or on
`crossPlatformId` when both sides carry one (`PlayerAdminEntry.Equals`,
`DedicatedServer/Pug.Other:PlayerAdminEntry:Equals(PlayerAdminEntry):5`) —
rather than on the name: the server rewrites an entry's `name` to the connecting
character's, in the `OnPlayerNameChange` that follows the bootstrap check, so a
stale name there means nothing. Two hand-written entries with the same `steamId`
do not both survive: the list is deduplicated by it on load
(`DedicatedServer/Pug.Other:NetworkingManager:NetImplInit:53`).

**Stages 1 and 2 differ in one way that decides whether such a test is
possible.** `RemoveAdminInternal` only matches entries with `privileges <= 1`,
so no command takes stage 2 away — but one does take stage 1, and nothing stops
a player from removing *themselves*: the `UNASSIGN_ADMIN` list iterates the
admin list without filtering the local player (`ListConnectedPlayers`,
`Pug.Other:ListConnectedPlayers:Update:29`), and the server-side handler has no
self-check either. Writing stage 1 into `Admins.json` rather than 2 therefore
buys a role change **inside one running session**, which the next paragraph
explains the need for.

**`guestMode` is not a world flag alone.** `WorldInfoCD.guestMode` is the
world's setting, but `PlayerController.guestMode`
(`Pug.Other:PlayerController:guestMode:1`) answers the useful question — it
returns true only when the world flag is set **and** `adminPrivileges < 1`. An
admin in a guest-mode world is not a guest.

**And it does not survive a server restart.** The only write to `guestMode` in
the whole server assembly is the RPC handler (`NetworkCommand.SetGuestMode`,
`DedicatedServer/Pug.Other:NetworkCommandServerSystem_59CC188E_LambdaJob_2_Job:OriginalLambdaBody:125`).
No read of it was found in the save serialization assemblies or in the server's
preferences parsing — a negative over a search, not over a located loader, and a
whole-struct `WorldInfoCD` write would escape a field-level search — and the
restart measurement below agrees: it lives in the running server's `WorldInfoCD`
singleton and is gone the moment that process ends. So a check that enables
guest mode as an admin and then restarts the server to come back without rights
loses the very condition it set up, and loses it silently — the role change has
to happen within the one session, which is what the revocable stage 1 above is
for. Measured this way round: the restart produced a run indistinguishable from
one where guest mode had never been touched.

**Both change during a session.** `NetworkCommand` carries `AddOrUpdateAdmin`,
`RemoveAdmin` and `SetGuestMode`, handled by `NetworkCommandServerSystem` behind
an admin check of its own. So a value read once when a screen opens can be stale
by the time the player acts on it — a UI that gates on either has to re-read or
poll. There is no C# change event for either: `adminPrivileges` is a property
over a component and `guestMode` a field in a singleton. What does travel is
networked: an `AddOrUpdateAdmin` or `RemoveAdmin` that goes through makes the
server broadcast a `NetworkCommandResponseRpc`
(`DedicatedServer/Pug.Other:NetworkCommandServerSystem_59CC188E_LambdaJob_2_Job:OriginalLambdaBody:85`),
which every client's `NetworkCommandClientSystem` applies to its own
`adminPlayers` list (`Pug.Other:NetworkCommandClientSystem:OnUpdate:54`), and
`guestMode` is a `[GhostField]` (`Pug.ECS.Components:WorldInfoCD:guestMode:1`)
that reaches clients by ordinary replication. Neither is an event a UI
subscribes to; both are state it has to look at again.

**That check is one gate in front of the whole command switch, which makes a
self-revocation a one-way door.** `NetworkCommandServerSystem` answers
`ChangePvPTeam` first
(`DedicatedServer/Pug.Other:NetworkCommandServerSystem_59CC188E_LambdaJob_2_Job:OriginalLambdaBody:6`),
then refuses every remaining command whose sender does not hold privileges above
zero
(`DedicatedServer/Pug.Other:NetworkCommandServerSystem_59CC188E_LambdaJob_2_Job:OriginalLambdaBody:19`)
— so over a connection the switch below is reachable for an admin and for nobody
else. Removing one's own stage 1 therefore works exactly once, and is the last
command behind the gate that player can send: every later one is answered with
`Ignoring admin command from non-admin player` in the server log and nothing
else, while `ChangePvPTeam`, answered before the gate, still goes through.
Measured 2026-10-07 against a running 1.3.0.5 server — `RemoveAdmin` went
through, the `SetGuestMode` sent after it did not.

The available mistake is to find `AddOrUpdateAdmin`'s own extra check and read
it as the permission one, which costs a walked test — and it is wrong twice
over. That check asks the privileges of the command's **target**
(`DedicatedServer/Pug.Other:NetworkCommandServerSystem_59CC188E_LambdaJob_2_Job:OriginalLambdaBody:78`,
reached through `rpc.entity0`'s own connection), so all it does is decline to
re-add somebody who is an admin already: an idempotence guard, not a permission
one. The check that asks about the *sender* is the gate, about fifty lines above
the branch.

**The per-command bodies are what make that mistake easy, and there is a second
one shaped like it.** `RemoveAdmin`
(`DedicatedServer/Pug.Other:NetworkCommandServerSystem_59CC188E_LambdaJob_2_Job:OriginalLambdaBody:98`)
and `SetGuestMode`
(`DedicatedServer/Pug.Other:NetworkCommandServerSystem_59CC188E_LambdaJob_2_Job:OriginalLambdaBody:122`)
really do look only at their target and at the world singleton, so reading
either one in isolation says "unchecked" quite convincingly. And the gate opens
with `SourceConnection != Entity.Null &&`, so a command entity created directly
in the **server** world, with no connection behind it, skips the check. That
does not make a host different from a dedicated server: the game's own UI issues
these commands from the client world as RPCs on a host too (`SetGuestMode` is
sent with `Manager.ecs.ClientWorld`, `Pug.Other:GuestModeButton:OnActivated:7`,
and every `NetworkingManager` sender attaches `SendRpcCommandRequest`,
`Pug.Other:NetworkingManager:SetGuestMode:4`), so they arrive over the
in-process connection and pass the same gate, which the host clears by holding
stage 2. The unchecked path is open to a mod that creates the command in the
server world itself — vanilla does so only for `RecreateGameId`
(`Pug.Other:NetworkingManager:RecreateGameID:15`).

**So a player cannot put themselves into a guest mode they can feel in one
step.** Sending `SetGuestMode` requires `adminPrivileges >= 1`, and
`PlayerController.guestMode` returns true only below that — the two conditions
are disjoint. One order does satisfy both, and it has now been walked: enable
guest mode while still holding stage 1, then drop to stage 0. The world flag
outlives the privilege change, so the moment the rights go, `guestMode` becomes
true for that player. Measured 2026-10-08 against a 1.3.0.5 dedicated server, in
a single transition —

~~~text
permissions changed under the open screen: player=True guestMode=True adminPrivileges=0
~~~

— and a second `RemoveAdmin` afterwards changed nothing, so the one-way property
is observed rather than inferred. Two conditions make it work and are easy to
miss: the account must be at `privileges: 1`, because `RemoveAdminInternal`
matches `<= 1` and silently ignores stage 2, and `Admins.json` is read only at
server start.

What this order cannot do is show the two values acting **independently**, since
it moves both in the same instant. A check that needs them separated still needs
a second, admin-holding player.

**There are no chat commands for this.** A search for a command dispatcher —
`ChatCommand`, `StartsWith("/")` — comes up empty across client and server
assemblies; admin rights are granted through the UI and travel as the RPC above.

**Once a player has joined, the server can read their rights from the
connection, and needs nothing from the client.** The connection entity then
carries `ConnectionAdminLevelCD { int adminPrivileges; ulong onlineId }`, a
public struct the server adds, through a command buffer, when it handles the
last part of the player's start request
(`DedicatedServer/Pug.Other:StartGameRPCSystem_2FE3D5A9_LambdaJob_3_Job:OriginalLambdaBody:116`).
Before that — through the mod check, the handshake and the character upload —
the connection has none. Adding or removing an admin rewrites it, together with
`PlayerGhost.adminPrivileges`, through `UpdatePlayerAdminFlag`
(`DedicatedServer/Pug.Other:NetworkingManager:UpdatePlayerAdminFlag:16`).
`EmptyAdminAndBan`, which replaces the whole list, does not call it
(`DedicatedServer/Pug.Other:NetworkingManager:EmptyAdminAndBan:3`), so after
that every connection keeps its old value until the next add or remove.

Vanilla reads the component two ways. The map RPCs index it directly
(`DedicatedServer/Pug.Other:ShareMapServerSystem_12B634E6_LambdaJob_0_Job:OriginalLambdaBody:5`),
which assumes it is there; `ServerSystem`'s command gates and the scanner,
variation and outro handlers call the public extension
`PugEcsExtensions.GetAdminLevelOnServer`, which returns 0 when it is missing
(`Pug.Other:PugEcsExtensions:GetAdminLevelOnServer:3-4`). A mod's RPC handler
can call that same extension on a `ComponentLookup<ConnectionAdminLevelCD>` with
`ReceiveRpcCommandRequest.SourceConnection`, and take the world's guest flag
from `WorldInfoCD` — through `PugSimulationSystemBase.WorldInfo` only if the
handler derives from that class, since the property is `protected`
(`Pug.Other:PugSimulationSystemBase:WorldInfo:1`), and otherwise through the
public `WorldInfoSystem.WorldInfo`, which is how `NetworkingManager` reads the
flag itself (`Pug.Other:NetworkingManager:HandleSideChannelMessage:4`). A sender
is a guest when the flag is set and the privileges are below 1. The other method
vanilla uses, `NetworkingManager.GetAdminPrivileges` — behind the admin-command
gate above, at join and in `UpdatePlayerAdminFlag` — is `internal`, so a mod
cannot call it directly; the SDK's checked reflection would reach it ([sandbox](sandbox.md#reaching-a-private-member-resolving-it-is-only-half-the-job)),
but the public extension already answers the question. Never derive the sender
from an `Entity` the client sends: NetCode resolves it to the server's own copy
of that ghost ([above](#a-just-placed-object-cannot-be-named-in-an-rpc-yet)), but the client chose which ghost to name, so it says
nothing about who sent the request.

Measured 2026-10-17 against a 1.3.0.6-6e73 dedicated server, with a probe RPC
logging what the handler resolved, the value equalled the `Admins.json` entry
each time — a hand-written stage-2 entry (the only entry, so the bootstrap rule
could not have fired) gave `2`; stage 1 gave `1`; a list holding only a foreign
placeholder gave `0` — and the `PlayerGhost.adminPrivileges` of the same player
agreed. Every probe request was sent on a manual trigger with the player
already in the game. It also **followed a change inside one session**: after guest
mode was switched on and the account's stage 1 was revoked, the next request
read `privileges=0 … guest=True`, with no reconnect. So the lookup belongs in the
handler, once per request, not in a cache taken at join.

### Check `[GhostField]` before assuming a write replicates

Two things decide whether an ECS write reaches the other side, and you need
both of them.

**The declaration decides whether the value is on the wire at all.** Codegen
emits one `…GhostComponentSerializer` per replicated component, and its
`Snapshot` struct holds exactly that component's `[GhostField]`s and nothing
else — `PlacementCDGhostComponentSerializer`
(`Pug.ECS.Components:PlacementCDGhostComponentSerializer:4`) is the worked
example below.

**The world you wrote it in decides the direction, and there is only one
direction.** Snapshots are produced in the server world — `GhostSendSystem`,
which `NetworkingManager.InitWorld` (`Pug.Other:NetworkingManager:InitWorld:1`,
the class itself at `Pug.Other:NetworkingManager:1`) configures only in the
world that has one, called from `ECSManager.InitWorld`
(`Pug.Other:ECSManager:InitWorld:1`) for both worlds — and applied in the client
world, `GhostUpdateSystem`, which CK fetches from `Manager.ecs.ClientWorld`. So
a `[GhostField]` write in the server world replicates, and the identical write
in the client world reaches nobody and stands only until a snapshot for that
ghost is next applied over it — when that is depends on the ghost's mode and on
what the server sends, and how long such a write survives in practice is
**unverified**. Client → server is a separate mechanism, not ghost fields:
player input (`ClientInputData`, an `IInputComponentData`,
`Pug.ECS.Components:ClientInputData:1`, carried by the generated command
send/receive systems at
`Pug.ECS.Components:ClientInputDataInputBufferDataSendCommandSystem:4` and
`Pug.ECS.Components:ClientInputDataInputBufferDataReceiveCommandSystem:4`) and
RPCs.

Read the attribute before assuming either way — and read it per *field*, not per
component:

| Component | Replicated |
|---|---|
| `HealthCD` | yes — declared `[GhostField]`, so a server-side change travels to the client |
| `PlacementCD`'s placement-permission flags — `canPlaceOnWalkableTiles` through `blockedByObjectsOnWalls` (`Pug.ECS.Components:PlacementCD:51-69`) | no — the tail of the struct carries no `[GhostField]` and none of those fields appears in the generated snapshot, so they are world-local state. The rest of `PlacementCD` *is* replicated, `canPlaceGround` (`Pug.ECS.Components:PlacementCD:canPlaceGround:2`) and `canPlaceRoofHole` (`Pug.ECS.Components:PlacementCD:canPlaceRoofHole:2`) included — this is a per-field answer, not a per-component one |

What the client then *does* with a replicated value is a separate question: for
`HealthCD` it is **unverified** whether a damage-stage sprite or a progress bar
refreshes on its own.

For those flags the consequence runs the other way — writing them on one side
changes nothing on the other. The surrounding code is present on both:
`EquipmentSystemGroup` (`Pug.Other:EquipmentSystemGroup:4`) runs in the server
**and** the client simulation world, and `EquipmentUpdateSystem.UpdateJob` is a
scheduled job. A Harmony patch in that job runs on every side, and **not**
identically: measured for `reusable-cattle-box` on 1.2.1.5 (2026-08-22), its
hook inside that job fired on a host, on a dedicated server and on a client
attached to that server — once per event on the server, twice on the host and on
the client, because NetCode re-predicts the tick from the last confirmed
snapshot and the hook's condition holds on every replay. Treat such a hook as
"runs on either side, and a client's count tracks latency", and verify on the
topology you care about.

## The dedicated server

What follows is true of the *game*, wherever the server runs. How you wire one
up — where it lives, how it is started and stopped, how its world and mods are
kept beside a client's — is a matter of local arrangement.

### Getting one running

The dedicated server is **Steam app `1963720`**, free, and installable without
owning anything: `steamcmd +login anonymous +app_update 1963720 +quit`. Like the
client, it has no native macOS build either — see [platforms](platforms.md#there-is-no-macos-build) for how that is
known — and like the client, this repository runs it under CrossOver rather than
natively.

It is worth having for mod work. Server commands and world-mutating logic run in
singleplayer already, since that process is its own authority (below); what only
a separate server process exercises without a second machine is everything that
needs a remote client against it — a differing mod set and `requiredOn`, the
inverted `Init()` order, and the build differences at the end of this chapter.

Five things about starting it are not obvious:

- **`-batchmode` yes, `-nographics` never.** Part of world generation runs on
  the GPU, so a headless server still needs a graphics device — the server's own
  README says so, and the readback code agrees. How a server without one fails
  is **unverified** — this chapter's sources never started one with `-nographics`. On a bare
  Linux host that is what `xvfb` plus Mesa are for. (The mechanism is [below](#the-server-renders-so-it-needs-a-graphics-device).)
- **`-port` works only as a command-line argument.** Setting it in
  `ServerConfig.json` has no effect. With a port the server takes direct
  connections; without one it is reachable only through the Steam relay, by its
  Game ID.
- **`-allowonlyplatform Steam`** avoids a join refused for a *"missing the
  crossplay privilege"*: it puts client and server on one platform with
  cross-play off, so the handshake's privilege test, which still runs, passes.
  It does nothing on its own — the shipped `ARGUMENTS.txt` says it "has no
  effect unless -port is also set", because the flag is read only inside the
  direct-connection branch that `-port` gates.
- **`-world` selects, `-worldname` does not — and both persist.** The server
  takes a world by its slot alone; `-worldname` only sets the name clients see
  for whichever slot loads. Each valid argument overwrites a field of the server's
  settings, which are saved as `ServerConfig.json` in its data path, and an
  argument left out leaves the stored value in force (`ReloadAllSettings` in the
  dedicated server's `Pug.Other`, which writes the file back at every start,
  not only on shutdown). Without `-world` the server loads the slot last stored;
  0 is its fallback whenever no usable value is stored — a first run, another
  data path, a `ServerConfig.json` deleted for failing to parse, a stored slot
  outside 0–29 — and without `-worldname` it keeps the name last stored. The
  same holds for seed, mode, season, player cap and Game ID, and for the
  password only together with `-port`: `-password` is read inside the
  direct-connection check, so without a port it is ignored and nothing is
  stored. The stored value is not always one that was passed, though.
  `-serverconfig <path>` reads that file instead of `ServerConfig.json` and then
  saves its values there, and the server writes some fields back itself — the
  generated seed of a new world (`SetServerDefaultsSystem.OnStartRunning`), and
  the Game ID and password of its connection — so a second new world started
  without `-worldseed` gets the first one's seed, not a random one.

  Name and mode of the running world come from those settings — the server's
  `GetWorldInfo` and `GetWorldName` build them from the settings for any slot,
  and its `WriteWorldInfo` only logs an error — so for them it never consults a
  `<slot>.worldinfo`, and never creates one. The seed of a world that already
  exists comes from its save instead: a different stored seed only draws a
  "Seed mismatch … Only the world seed will be used" warning from the same
  `OnStartRunning`. (Until 2026-10-15 this bullet had the seed coming from the
  settings as well.) So a launcher that picks a world by name has to read the
  `.worldinfo` files itself and pass the name along with the slot, or the world
  appears under the stored name — which works only for worlds a client created,
  since one the server generated has no such file. Observed on 2026-10-10 with
  this repository's server under CrossOver: after a start with `-worldname`, the
  name was in `ServerConfig.json` and the slot's `.worldinfo` was untouched.
- **A cold start with a full mod set takes minutes**, observed under CrossOver —
  every source mod goes through Roslyn and the world is decompressed on load. A
  server that looks hung shortly after launch usually is not.

The server autosaves every 60 seconds — `AutoSaveInterval` from the platform
configuration, 60 in the PC asset and as the fallback — so even an abrupt end
costs at most a minute of play. `-disableautosave` does more than stop that
timer: it switches the whole `SaveSystem` off in its `OnCreate`
(`DedicatedServer/Pug.Other:SaveSystem:OnCreate:8`); whether that also takes the
save on quit with it is **unverified**.

### Stopping one without losing the world

A dedicated server writes its world in its **quit handlers**, which run whenever
a quit is let through — the server's own `Application.Quit()` calls, and a
Windows close request, which Unity turns into one. Under Wine/CrossOver that
makes the choice of signal decisive, **measured** there on 2026-08-10:
`taskkill` without `/F` sends a close request and the world was rewritten; a
`SIGTERM` made the process simply disappear, leaving only the last autosave. How
a native Linux server treats a POSIX signal is a different path, and
**unverified**. Pugstorm's own launch script stops the server with `taskkill` as
well, without saying why.

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
system can at best hold a replicated value until the next snapshot for that ghost
is applied over it.

**That absence is the topology test.** `Manager.ecs.ServerWorld` is a public
property (`Pug.Other:ECSManager:ServerWorld:1`) assigned a world only where the
process creates a server world (`Pug.Other:ECSManager:CreateServerWorld:3`), and
otherwise null — set so in `ECSManager.Init` before any world exists
(`Pug.Other:ECSManager:Init:6`) and again on teardown
(`Pug.Other:ECSManager:UnloadWorldsInternal:23`); vanilla itself branches on it
in at least eight places (`Pug.Other:BenchmarkRunner:CreateMetrics:26`,
`Pug.Other:ECSManager:Update:7`, `Pug.Other:ECSManager:OnEarlySceneUnload:3`,
…), and the SDK exposes the same object as `API.Server.World`
(`ModAPIServer.World`, `Pug.Other:ModAPIServer:World:1`). So a mod that needs to
know whether it *is* the authority asks one question:

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
`Pug.Other:Manager:networking:1`) answer narrower questions and are not substitutes for the
one above: `isConnected` is a plain settable `bool` property, and
`currentSessionIsDedicatedServer` asks the platform layer
(`impl.ConnectedToDedicatedServer`) and returns `false` whenever there is no
network at all. Neither distinguishes hosting from joining, which is precisely
what `ServerWorld` does.

**On the Steam build there is no separate host option.** Its title screen
offers one way to start a local game, "Start Game", and that starts a networked
session, so singleplayer and hosting are one mode there. Measured 2026-10-17 on
1.3.0.6-6e73 under CrossOver, in three local runs with the network available:
`API.Server.OnWorldCreated` and `API.Client.OnWorldCreated` fired in the same
frame — `InitWorlds` raises them back to back (`Pug.Other:ECSManager:InitWorlds:7`,
`Pug.Other:ECSManager:InitWorlds:12`) — with `ServerWorld` and `ClientWorld`
set and `currentSessionIsDedicatedServer` and `OfflineSession` false;
`isConnected` followed after 15, 29 and 16 frames, and the local player read
stage **2**. That is the stage-2 branch of the table above.

The code shows three ways into the `int.MaxValue` branch, the offline one, and
none of them was reproduced here. `OfflineSession` is set true only by a title
option whose `_forceOffline` field is enabled
(`Pug.Other:RadicalMainMenuOption_Singleplayer:OnActivated:4`) and by a failed
network check when not joining
(`Pug.Other:NetworkingManager:HandleNoNetwork:12`); networking that never
initialised takes the same branch in `StartServer`
(`Pug.Other:NetworkingManager:StartServer:5`) and in `GetAdminPrivileges`. Each
runs the server world "local only": nothing listens, and nobody can join. The
Steam build does ship such an option without showing it — read from its
installed `Title` scene on 2026-10-22, a second button, "Play Single player",
has `_forceOffline` set and is enabled for the Microsoft Store storefront only,
while the Steam build's code fixes the current storefront to Steam
(`Pug.Other:StorefrontFlagsUtility:MatchesCurrentStorefront:4`). So
`OfflineSession` read `False` in every run above, and it is no singleplayer test
either — nor, with uninitialised networking taking the same branch, a reliable
offline test.

### `OnWorldCreated` fires before the connection exists

A client that joins a remote server gets `API.Client.OnWorldCreated`
(`Pug.Other:ECSManager:InitWorlds:12`) as soon as its own world is initialised,
and that is **before** it even starts connecting: the join menu calls
`Manager.networking.Connect` only from `StartEcs`'s completion callback, after
`InitWorlds` has run (`Pug.Other:RadicalJoinGameMenu:Join:19`). Measured
2026-10-17 on 1.3.0.6-6e73 under CrossOver, in six joins to a dedicated server,
the event logged `ServerWorld=False ClientWorld=True connected=False
dedicated=False` with no connection entity. The connection entity appeared 7–28
frames after the event, logged in the same frame as
`currentSessionIsDedicatedServer` turning true, and
`Manager.networking.isConnected` turned true 53–183 frames after it — event,
entity, connected, per join: 21234 → 21262 → 21364, 38155 → 38162 → 38208, 46031
→ 46047 → 46122, 66282 → 66298 → 66465, 76026 → 76041 → 76206, 85047 → 85054 →
85100. These are six single observations, not a bound: `isConnected` also waits
for the mod check and every dialogue it raises ([the mod set](#the-second-layer-the-mod-set)).

`OnWorldDestroyed` (`Pug.Other:ECSManager:UnloadWorldsInternal:13`) fires on
every leave with `isConnected` already false — `UnloadWorldsInternal` stops the
client, which resets it, just before raising the event
(`Pug.Other:ECSManager:UnloadWorldsInternal:12`) — and a rejoin repeats the
whole cycle. It also fires when a load is cancelled during world conversion: the
worlds exist by then, `InitWorlds` never ran, and the cancellation unloads them
(`Pug.Other:ECSManager:StartEcs:30`), so a handler can see a destroy with no
create before it. A dedicated server builds no client world and raises only
`API.Server`'s pair — `OnWorldCreated` from
`DedicatedServer/Pug.Other:ECSManager:InitWorlds:7`, logged at frame 0 in the
same measurement.

So for a client, `OnWorldCreated` and `OnWorldDestroyed` bracket a session, a
cancelled load aside. On a joining client nothing sent from the event itself
arrives: NetCode's `RpcCommandRequest` send job destroys every request and
queues it only when some connection carries a `NetworkId`, warning otherwise
only in a build with collection checks, so in the shipped game the request
vanishes silently. A host opens its local connection right after the events, and
whether a request created in the event is dropped there too is **unverified**.
Wait from a per-frame update instead; among installed mods, GeneralConfigMenu
polls `isConnected` in `Update`, and ConveyorTunnelMod sends from the event and
then re-sends from its client system's `OnUpdate`, at most once a second, until
answered. A request that needs only the connection can go once `isConnected` is
true. A request the server judges by the sender's rights needs more: the client
queues its start request only once `isConnected` is set **and** it is in the
game (`Pug.Other:NetworkClientStartSystem:OnUpdate:113-116`), and only the
server's handling of that request adds `ConnectionAdminLevelCD`, so a
rights-gated request sent on the first `isConnected` frame can reach a
connection without it and be read as stage 0. Whether that window is wide enough
to catch a real request is **unverified** — every probe request above was sent
with the player already in the game, and each found the component.

### A mod-set mismatch reports a version error

The client shows **"Game version mismatch"** — the English text of the
localisation key `Error/BadProtocolVersion` (the German build reads "Falsche
Spielversion"; the wording is whatever the client is localised to, the key is
not). It almost never has anything to do with the game version — a mod set
that differs in mods which **add ghost prefabs or declare RPCs** produces
exactly this message, because those are the mods that move the hashes the two
sides compare, provided the mod check has not named the mod first. Nothing in
the message mentions mods.

**No mod name appears anywhere in the connect handshake**, which is why the
split in the table above decides who can hit this. Of the ways CK's own connect
handshake rejects, two read as this version error
(`Pug.Other:HandleConnectRequestJob:Execute(Entity, …):16`,
`Pug.Other:HandleConnectRequestJob:Execute(Entity, …):32`): `localVersionHash`,
which is `PlayerConnectRequestRPC.GetVersionHash(Manager.version)` — the game
version and nothing else
(`Pug.ECS.Components:PlayerConnectRequestRPC:GetVersionHash:1`) — and
`ghostCollectionHash`, the XOR of every `GhostCollectionPrefab.Hash`. The client
computes its side in the default world
(`ECSManager.TryCalculateGhostCollectionHash`,
`Pug.Other:ECSManager:TryCalculateGhostCollectionHash:1`), the server its own
from its world's buffer
(`Pug.Other:PlayerConnectRequestSystem:OnStartRunning:19`). The others carry
reasons of their own — `HostNotReady`, `Consoles/MissingPrivilegeReason`,
`Error/HostDoesNotAllowCrossplay`
(`Pug.Other:HandleConnectRequestJob:Execute(Entity, …):26-45`). NetCode's own
`NetworkProtocolVersion` check one layer down compares the RPC set, not the
ghost prefabs. A mod set differing only in Harmony-patch or bake-time mods
leaves all of it untouched and the join **succeeds** — which is exactly the gap
`requiredOn` exists to close.

Content mods are therefore not on the hash-moving side as such; what an added
entity does depends on its prefab. CoreLib's `EntityModule` clones a template and
stamps the clone's `GhostAuthoringComponent` with a fresh `prefabId` only for a
**workbench** it generates (`AddWorkbenchDefinition`) — a change to exactly the
set `ghostCollectionHash` fingerprints. An ordinary modded entity is registered
as authored, and enters the ghost collection only if its own prefab carries a
`GhostAuthoringComponent`.

Diagnose in `Player.log` by which layer answered. NetCode's rejection —
differing RPCs — leaves hundreds of `RpcHash[N]` and `ComponentHash[N]` lines
followed by `Client disconnected because Error/BadProtocolVersion`. CK's
handshake rejection — differing ghost prefabs — leaves no such dump, only
`Server rejected connection with reason BadProtocolVersion`
(`Pug.Other:NetworkClientStartSystem_33002849_LambdaJob_1_Job:OriginalLambdaBody:6`).
Both sides log their half of that comparison, though — `send connect with hash …
for N ghosts` on the client (`Pug.Other:NetworkClientStartSystem:OnUpdate:94`),
`server has ghost collection hash … for N ghosts` on the server
(`Pug.Other:PlayerConnectRequestSystem:OnStartRunning:21`) — and two different
ghost counts are the quickest proof that the mod sets differ in ghost prefabs.

**A missing required dependency is one of the ways the sets drift apart.** If a
mod declares a `required` dependency that is not installed on the server, the
loader's `SortMods` drops the *dependent* mod there and says so only in a log
warning — since 1.3 every such mod, and the mods depending on those in turn;
through 1.2.1.5 only one per pass ([mod anatomy](mod-anatomy.md) has both). The two sides then
hold different mod sets. If the dropped mod is one of the hash-moving kind and
the mod check lets the difference through, the client reports the same
`Error/BadProtocolVersion`, and nothing in it names a dependency; a dropped mod
flagged `Server` is instead named by the missing-mod dialogue, which runs first.
So when you publish a mod that depends on another, the server needs **both**
installed, not just yours — and this is the diagnostically expensive case,
because the symptom points at the game version while the cause is one absent
dependency on one machine.

### Version filtering belongs to the subscription loaders

Which loader fetched a mod decides whether its version-compatibility tags get
checked — not which machine is running it. A subscription loader skips a mod
that does not match the running game version, unless the mod's GUID sits in
`modloader/config.json` → `unsupportedModsToLoad`, which is what the "load
anyway" dialogue writes.

**Trap:** copying that list to the server accomplishes nothing — and not because
the server's loader is a different build. `PugMod.Loader` is all but identical
on both sides. The version check belongs to the *subscription* loaders, which
pass `ModVersion.IsCompatible(Application.version, tags)` into
`Integration.AddMod(…, supportsCurrentVersion)`: `ModIOLoader`
(`PugMod.Platform:ModIOLoader:Init:37`) and `SteamWorkshopLoader`
(`PugMod.Loader:SteamWorkshopLoader:InitAsync:37`). The directory scan does not
— `SideLoader` passes `supportsCurrentVersion: true` **hardcoded**
(`PugMod.Loader:SideLoader:Update:47`), so the gate the list feeds —
`!supportsCurrentVersion && !contains(guid)` — can never fire for a side-loaded
mod. And a dedicated server's `Manager` registers **only `SideLoader`** —
neither `ModIOLoader` nor `SteamWorkshopLoader`
(`Pug.Other:Manager:EarlyInit:72-83`, all three, against
`DedicatedServer/Pug.Other:Manager:EarlyInit:73-76`, one), while
`StreamingAssets/Mods` is how a server is normally given its mods. The rule that
predicts both cases is therefore about the *source* of a mod, not about the
build: a mod side-loaded into the **client's** own `StreamingAssets/Mods` skips
the version check just as thoroughly.

**That narrowed in 1.3.** Through 1.2.1.5 the server registered
`SteamWorkshopLoader` as well; in 1.3.0.2 the type does not appear in the
server's `Pug.Other` at all. A dedicated server can therefore be given mods only
through its directory, and a deployment that relied on the Workshop path has
nothing left to fall back to. Found while re-checking citations after the
update, so it is a code reading rather than a tested deployment — worth
confirming against a running server before planning around it.

The asymmetry therefore runs one way only, and it is a mismatch generator: a mod
the **client rejects** but the server still loads is a set difference. Resolve
it on the side that actually filters — either confirm the mod in the client's
dialogue, or remove it from the server. Note also that the loader **clears
`unsupportedModsToLoad` when the first three version components change**, so a
mod confirmed once silently drops out of the client's set after the next game
update that changes them, and the join that worked yesterday fails today with no
change on either machine. The list is also pruned on every load: an entry whose
mod was not among those tried in that run is removed and the config rewritten
(`PugMod.Loader:Loader:Reload:37-54`), so a mod uninstalled or unsubscribed for a single
launch loses its confirmation with no update at all.

### Duplicate mods: last one wins

The loader deduplicates by `metadata.name` — the manifest identity, not the
mod.io profile name and not the folder name. When two loaded folders claim the
same `metadata.name`, `SortMods` keeps **the last one in enumeration order**.
Only one of them ever runs, and no warning says so; what tells the survivor is
the `Loading mod with ID <modId>` line `ModManager.Init()` writes for it
(`Pug.Other:ModManager:Init:23`), since the two copies' ids differ by source.
Two mods can also share a `guid` without being the same mod — a fork inherits it
along with the manifest — so a shared guid is not proof of a duplicate, but it
does clash for the data-block loader, which keys on the guid.

### The server needs the same loader patches as the client

On a Wine/CrossOver host the server installation must be patched **separately**
from the game — it is a different install directory with its own
`CoreKeeperServer_Data/Managed`. Skipping it produced a very specific failure on
a CrossOver host: the mods **load but never compile**, because Roslyn chases a
missing satellite assembly, and the client then rejects the join as
`Error/BadProtocolVersion` — i.e. the mod-set symptom, one step removed from the
real cause. Details in [platforms and hosts](platforms.md).

### An idle server never simulates

This is the single most misleading thing about server-side debugging. After world
start the server settles at `timescale = 0` and stops simulating; its log stops
growing at the same moment. Consequences:

- **An absent log line proves nothing** unless a player was connected at the
  time. "My patch never logged" is not evidence the patch is dead.
- Read the log **after** the session, not during it.
- A mod's `Debug.Log` output does land in the server log. Started through
  Pugstorm's launch script, that file sits next to the executable rather than in
  `LocalLow`, because the script passes `-logfile CoreKeeperServerLog.txt`; a
  server started without that argument writes Unity's usual `Player.log`.

To prove a Harmony patch is live server-side, log from the **static constructor**
of the `[HarmonyPatch]` class. An explicit static constructor suppresses
`beforefieldinit`, so the line fires on the first touch of the class's statics —
for a patch class that declares no `Prepare`, `TargetMethod(s)` or `Cleanup`,
that is the first `Prefix()` call, rather than some unrelated point of type
loading. Harmony calls those three while it processes the class, so with any of
them the line proves the class was processed, not that the patch fired. Then
connect a player so the systems actually run.

The two mod log formats come from different loader *stages*, not from different
builds — both processes write both. `loaded mod <Name> …` is written once per
mod by whichever loader found it: `… at <path>` for the `StreamingAssets/Mods`
directory scan (what a dedicated server uses,
`PugMod.Loader:SideLoader:Update:52`), `… from mod.io (<Profile>)` for a mod.io
subscription (`PugMod.Platform:ModIOLoader:Init:64`, what the client usually
uses), `… from steam workshop (<Title>)` for the third. Afterwards both
processes log `Loading mod with ID <modId>` once per loaded mod, from
`ModManager.Init()`, regardless of source. So `grep "loaded mod "` is the one
pattern that works on both sides — it is not the only one that names a mod,
though: `not loading incompatible mod <name>` (`PugMod.Loader:Loader:AddMod:5`),
`skipping mod <name> because of missing dependency`
(`PugMod.Loader:DependencySorter:SortMods:23`) and `failed to load mod <name> …`
(`PugMod.Loader:SideLoader:Update:49`) each name one too, for their own failure
case.

### Warning: the lifecycle order was inverted through 1.2

On 1.2 `IMod.Init()` ran at a different point relative to ECS startup on the
two processes — **before** the worlds are built on the client, **after** them on
the dedicated server. That ordering is **measured** in the logs of both builds;
no derivation replaces it, and one that was tried turned out wrong ([Harmony and ECS](harmony-and-ecs.md) carries
the evidence and the failed derivation). Anything that registered itself during
`Init()` and was consumed by a snapshot taken at ECS startup therefore worked
**whenever a player hosts** — singleplayer and host-based multiplayer alike,
since that process builds its own ServerWorld after `Init()` — and was a silent
no-op on a dedicated server, with no error and no log line. `BurstDisabler` is
the case this bites in practice; the mechanism and the fix belong to [Harmony and ECS](harmony-and-ecs.md).

**A freshly started 1.3.0.5 server no longer inverts it.** Its own log, read
2026-10-08, shows `Init()` after the ServerWorld exists and before the
conversion that arms the worlds, because 1.3's `StartEcs` calls the loader's
`Update` itself (`DedicatedServer/Pug.Other:ECSManager:StartEcs:38`). One server
start is the evidence, and the SDK promises no ordering, so a mod still tagged
for 1.2 keeps the fix.

If your mod is server-authoritative and works when you host but not against a
dedicated server, start there. "Works for me in multiplayer" from someone
hosting neither reproduces nor refutes it.

## How the server build actually differs

The dedicated server is not a different game. Decompiling both installations of
the same version and diffing them assembly by assembly, **127 of 132 curated
assemblies come out identical** on 1.3.0.5 (117 of 122 on 1.2.1.5); the same five
differ in both — `Pug.Other`, `WorldGen`, `Pug.Objects`, `Pug.Dev` and
`PugMod.Loader`. Almost everything you learn from the client decompile is
therefore true of the server as well.

The finer breakdown is from the 1.2.1.5 analysis and has not been recounted for
1.3, whose `Pug.Other` diff runs to 13,369 changed lines. On 1.2.1.5, 43 types
differed within `Pug.Other`, and most of that volume was not game logic: a
generated type table, the client-only account/session layer, the Steam platform
wrapper and the preferences manager. The modding-relevant residue was roughly
450 lines across `NetworkingManager`, `NetworkCommandServerSystem`,
`SerializeWorldSystem`, `SaveManager`, `ModManager`, `Manager`, `ECSManager`
and others — the source list this is drawn from does not end there.

The type inventory, recounted on 1.3.0.5, is lopsided in the direction you would
expect: exactly **one server-exclusive type**, `NetworkUpdateServerLateSystem` (a
`SystemBase` filtered to `ServerSimulation`, ordered last in the
`SimulationSystemGroup` after `GhostSendSystem` and `RpcSystem`), against **18
client-exclusive** ones — the account, lobby, authentication and cross-platform
session types, plus four of the Discord integration.

### Why an idle server stops simulating — the actual condition

The `timescale = 0` behaviour described above is not a heuristic. `ECSManager`
pauses when the world has finished loading, **no connection exists**, and no save
is in flight; otherwise it resumes. So the server idles after world load until
the first player connects and again once the last one has left, and resumes
whenever a player connects or a save is pending.

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
`-nographics`:** world generation reads back a texture the server renders itself,
so it needs a graphics device to render it with — how its absence makes world
creation fail is the open question [above](#getting-one-running).

### The server has no world list

A client holds an array of world slots and indexes into it. A dedicated server
hosts exactly one world and takes its properties from the server configuration
instead — the accessors are rewritten accordingly:

| Accessor | Client | Server |
|---|---|---|
| `GetWorldInfo(int id)` | bounds-checks `id`, returns `worldInfo[id]` | builds a fresh `WorldInfo` from `Manager.prefs.server*`, ignoring `id` — with `worldGenerationType` hard-coded to `FullRelease`, so on a creative server it disagrees with `GetWorldGenerationType()` |
| `GetWorldMode(int id)` | from the array | returns `Manager.prefs.serverWorldMode` |
| `GetWorldName(int id)` | from the array | returns `Manager.prefs.serverWorldName` |
| `IsWorldModeEnabled(int id, …)` | from the array | tests `Manager.prefs.serverWorldMode` |
| `GetWorldGenerationType()` (no id) | returns `worldInfo[_worldId].worldGenerationType` | derives it from the configured mode: `Creative` if `GetWorldMode()` is creative, else `FullRelease` |

In each of these rewritten accessors that still takes an id, the parameter is
accepted and **never read** — the accessors that were left alone, such as
`WorldExists(int id)`, still index by it. Passing a slot number therefore does
not select anything — you always get the one hosted world, and a mod that treats
a differing id as a differing world will be wrong in a way that no error
reports.

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

### Achievement and RGB calls are compiled out of the game code

Two build defines, `PUG_ACHIEVEMENTS` and `PUG_RGB_ENABLED`, are absent
server-side. That drops the `[Conditional]` achievement triggers and the
RGB-peripheral events from the server's compiled game code — the difference
alone accounts for the entire `Pug.Objects` and `Pug.Dev` diff. It does not
remove the machinery: `AchievementsManager` and `RGBManager` still exist on the
server (`DedicatedServer/Pug.Other:AchievementsManager:1`,
`DedicatedServer/Pug.Other:RGBManager:1`), `TriggerAchievement` is there with an
empty body
(`DedicatedServer/Pug.Other:AchievementsManager:TriggerAchievement(AchievementID):2`),
and the server still awards achievements to connected players through an
`AchievementRpc` (`TriggerAchievementForEveryone`,
`DedicatedServer/Pug.Other:AchievementSystem:TriggerAchievementForEveryone:1`).
The RGB SDK library ships with the client installation and not with the server.

A mod that triggers an achievement or drives peripheral lighting therefore calls
something that exists on a server — the direct `TriggerAchievement` with an
empty body there, so nothing happens — and a call to a `[Conditional]` overload
is dropped from the mod's own compile unless the loader defines the symbol for
it. Guard such calls, or keep them on the client side of your mod.
