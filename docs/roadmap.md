# Core Keeper modding — Roadmap

Work that concerns every mod here rather than one of them. A mod's own roadmap
lives in that mod's `docs/roadmap.md`.

Points that are **deliberately cut to stand alone**, not a shopping list for a
release. Each entry records what is already settled and what still has to be
decided, so picking one up does not mean re-deriving the groundwork.

Each point carries a reference id — `CK-01`, `CK-02`, … — assigned once and
never reused, the same convention the mod roadmaps use. Cite the id, not the
heading.

## CK-01 · A tool that drives the server from outside

A program — not a mod — that connects to a running dedicated server and sends
it RPCs, so a test can put the world into a given state without a human
clicking through menus. The case that prompted it: MSM-10's criteria 11 and 12
need a player's admin rights revoked **while that player sits in front of an
open settings screen**, and the game offers no way to do that to oneself.

**Settled, measured 2026-10-06 against the 1.3.0.4 decompile.**

The server has no control surface other than the game protocol. There is no
stdin handling (`Console.ReadLine`, `Console.In`, `ReadKey` appear nowhere in
the server assembly), no RCON, no HTTP or TCP listener — the WebSocket imports
belong to mod.io and OpenBLive. `Admins.json`, `ServerConfig.json` and
`PlayerBans.json` are read at startup and not re-read, so editing a file
changes nothing in a running session.

The protocol is **Unity NetCode for Entities** over Unity Transport, in a copy
Pugstorm has modified. On connect both sides exchange `NetworkProtocolVersion` —
NetCode version, game version, RPC collection and a component collection value
that the modified copy pins to `0` — and CK's handshake then compares the ghost
collection hash, which NetCode's build-time serializers determine.

Those hashes are **stable against the kind of mod built here**: Harmony patches
and bake-time edits leave them untouched; only a new ghost prefab, a new
replicated component on one, or a new `IRpcCommand` type moves them. A tool
would therefore survive this workspace's own builds and break on a Core Keeper
update or on installing a mod that registers replicated types.

The commands worth sending are public on `NetworkingManager` and are thin — each
creates one entity carrying `NetworkCommandRpc` + `SendRpcCommandRequest`:
`RemoveAdmin(PlayerController, World)`, `AddAdmin(…)`, `SetGuestMode(bool,
World)` (`Pug.Other:294403-294436`). **The server admits them only from a sender
holding admin privileges above zero** — one gate in front of the whole command
switch, with `ChangePvPTeam` answered before it as the sole exception
(`DedicatedServer/Pug.Other:137119`, gate at
`DedicatedServer/Pug.Other:137132`). So the tool needs an identity that the
server's `Admins.json` lists, and a connection holding no rights can send
nothing but a PvP-team change.

An earlier version of this point claimed the opposite — that `SetGuestMode` and
`RemoveAdmin` go unchecked — from having found `AddOrUpdateAdmin`'s own,
additional check and reading it as the only one. Corrected 2026-10-07 after the
running server refused a `SetGuestMode` with `Ignoring admin command from
non-admin player`. The gate is a property of the game, not of this workspace.

A server-side mod is not an alternative: the same operations are `internal`
there (`DedicatedServer/Pug.Other:290929`), and the Roslyn sandbox forbids the
reflection that would reach them.

**Still to decide.**

Whether the protocol hashes can be reproduced at all is the open risk and
belongs in a spike before anything else. They are build-time values and appear
nowhere in plain text; the two candidate routes are computing them from the
shipped assemblies, or capturing them once from a running client and feeding
them to the tool as data.

Whether a bare connection suffices to have an RPC accepted, or whether the tool
must complete a full player join first, is unknown — and the gate above sharpens
that question rather than answering it. `GetAdminPrivileges` is asked about the
RPC's own `SourceConnection`, so the tool needs both a connection the server
recognises and an `Admins.json` entry its identity matches. Whether a connection
that never spawned a character carries an identity that list can match has not
been traced.

Scope is open: admin level and guest mode are what MSM-10 needs, and
`NetworkCommand` carries more.

**Why it was not built when it came up.** MSM-10 needed two checks walked, and a
twenty-line trigger inside that mod's own `TestFixtures` block reached the first
of them the same day. Then it hit the gate above: a self-revocation is the last
command a player can send, so the reversal the second check wanted stayed out of
reach, and that half was parked rather than walked. The case for this point is
therefore sharper than when it was written, not weaker — server state that has
to be driven repeatedly, across mods, without a mod of its own in the way, and
from an identity that keeps its rights while doing it.
