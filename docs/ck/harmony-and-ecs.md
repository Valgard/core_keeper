# Patching Harmony and ECS

Core Keeper is a DOTS game whose simulation systems are Burst-compiled, and mods
are Harmony patches compiled at load time inside a sandbox. That combination
produces failure modes that look nothing like a normal Harmony problem: a patch
that loads cleanly and never fires, a system whose body is not in the file you
are reading, and a fix that works in single-player and is inert on a dedicated
server. This chapter covers how to make a patch bind, how to make it fire, and
how to read and write the live ECS world once it does.

Line numbers quoted below (`Pug.Other:295735`) are offsets into the decompiled
game assemblies — see [reverse-engineering](reverse-engineering.md) for how to
produce that decompile.

## Three failure modes, three different causes

Before changing anything, classify the symptom. They have nothing in common
except that your code does not run.

| Symptom | Cause | Fix |
|---|---|---|
| `ArgumentException: Undefined target method for patch method …` at load | Harmony cannot resolve the target signature — typically an `in`/`ref` parameter | `argumentVariations` (below) |
| Mod loads, `safetyCheck=True`, patch binds, prefix never fires | The target is Burst-compiled; the managed IL you patched is never executed | `BurstDisabler` (below) |
| Works in single-player, does nothing in multiplayer | `BurstDisabler` registered too late on the dedicated server | manual `AddWorld` pass (below) |
| Mod does not compile at all (`CompileFailed`) | Sandbox rejection, not a patching problem | [sandbox rules](sandbox-and-config.md) |

## Why a Burst-compiled `OnUpdate` cannot be intercepted

Harmony rewrites managed IL. A Burst-compiled system never runs that IL, so
there is nothing for the patch to intercept — and Harmony has no way to tell you
that, because the bind itself succeeded.

The dispatch chain is worth knowing, because the fix only makes sense against
it. `WorldUnmanagedImpl.UpdateSystem` invokes `UnmanagedUpdate` as a
`$BurstDirectCall` (`Unity.Entities:67217`), which takes the Burst path whenever
`BurstCompiler.IsEnabled`. `CallForwardingFunction` then runs *inside* Burst,
where `CheckBurst` is `[BurstDiscard]` and therefore stripped — so its `status`
stays `true` and the system's Burst function is called unconditionally. The
per-system `BurstFunctionEnabledBits` flag is never even read on that path.

## `BurstDisabler` — moving a system off Burst

`BurstDisabler` ships in `PugMod.SDK.Runtime`, which the wizard-generated
runtime asmdef already references. Using it costs no dependency — in particular
not CoreLib.

```csharp
public void Init()
{
    BurstDisabler.DisableBurstForSystem<ChangeDurabilitySystem>();
}
```

Verified for **both** system shapes: `SystemBase` (`OnUpdate()`) and `ISystem`
structs (`OnUpdate(ref SystemState state)`). In the `ISystem` case the prefix
binds against the `ref SystemState` signature with no "Undefined target method".

### The call has two halves, and only one of them is global

| Half | What it does | Scope |
|---|---|---|
| 1 | `SystemBaseRegistry.SetBurstEnabledForSystem(type, false)` → `BurstFunctionEnabledBits = 0` | global per system type, effective immediately |
| 2 | `SystemTypesToDisableBurstFor.Add(type)` | armed **per world**, only by `BurstDisabler.AddWorld(world)` |

Half 2 is the *gate* to half 1. `DisableBurstForSystemPatch.Prefix` — the SDK's
own Harmony patch on `UpdateSystem`, gated on
`SystemHandlesToDisableBurstFor.Contains(sh)` — flips
`EnableBurstCompilation = false`, which makes the managed path run; only then
does half 1 select `ManagedFunctionsUnBursted`, the `OnUpdate` you can patch.
If half 2 never armed for the world your system runs in, half 1 is dead weight.

### Nested jobs need the `AndJobs` variant

`DisableBurstForSystem<T>` is not enough when the system's real work lives in a
nested job. `EquipmentUpdateSystem` (`Pug.Other:419765`) does everything in
`UpdateJob`, which carries its own `[BurstCompile]` (`:419767`) and calls
`PlaceObjectSlot.UpdateEquipment` (`:419898`). With the plain variant, **no**
patch on that path fires; with `BurstDisabler.DisableBurstForSystemAndJobs<T>()`
(`PugMod.SDK.Runtime:783`) all of them do.

A system whose `OnUpdate` you patch directly, with no job in between, gets away
with the plain call.

**Trap:** the log line

```text
BurstDisabler: Patched OnUpdate on <System> for job burst disabling
```

is **not** evidence that your hooks are live. It comes from the `AndJobs`
variant's dependency patch, which is applied regardless of the per-world
snapshot — so it appears even while the bypass is inactive.

### What it costs

Taking a system off Burst means its `OnUpdate` runs as managed code, which
sounds expensive enough to worry about. In practice it has not been:

- A mod that Burst-disables `EquipmentUpdateSystem` showed **no perceptible
  frame cost** in the operation that hammers it — laying rails while bridges are
  auto-placed underneath across pits and water.
- Several mods on the same installation held systems un-Bursted at once without
  the sum becoming noticeable.

Two honest caveats. This is **play-testing, not measurement** — no profiler
numbers back it, so treat it as "do not pre-optimise against this", not as a
guarantee. And attributing a slowdown correctly is harder than it looks: the one
place that did feel slower was a large base, which is also where an unrelated
inventory-scanning mod does its heaviest work. A cost that appears only where two
mods overlap belongs to neither until you have isolated it.

The scaling factor that actually matters is **how often the system runs and how
much it does per tick**, not the Burst switch itself. A per-input-tick system is
cheap to un-Burst; a system that walks large entity sets every frame is where you
should look first if something does get slow.

## The dedicated-server trap

**`DisableBurstForSystem<T>()` in `IMod.Init()` is a silent no-op on a dedicated
server.** No error, no log line; the prefix simply never fires. The mod works in
single-player and does nothing in multiplayer.

The cause is an inverted lifecycle. `BurstDisabler.AddWorld` is called from
exactly one place, `ECSManager.StartEcs` (`Pug.Other:2675` in the client build,
`:2656` in the server build), and it **snapshots** the types registered up to
that moment. Nothing ever back-fills it.

Note what this does *not* mean: the call is present and runs on both builds,
immediately after authoring-data conversion in each. The server does not skip
it. So "`AddWorld` never runs server-side" is the wrong diagnosis — it runs, it
is simply reached before your `Init()` had a chance to register anything.

| Process | Order (measured in the logs) | Result |
|---|---|---|
| Client | `Init()` first, worlds built afterwards | registration precedes the snapshot → works |
| Dedicated server | worlds built first (`adding worlds to the update loop`), `Init()` afterwards | snapshot empty → patch dead |

### The fix

Follow every `DisableBurstForSystem*` call with a manual pass over the existing
worlds:

```csharp
using Unity.Entities;   // World

public void Init()
{
    BurstDisabler.DisableBurstForSystem<ChangeDurabilitySystem>();
    foreach (var world in World.All)
        BurstDisabler.AddWorld(world);
}
```

`World.All` is sandbox-legal (`safetyCheck=True` on both client and server), and
the registry behind `AddWorld` is a `HashSet`, so the pass is a harmless no-op in
the client ordering. Write it unconditionally rather than branching on
client/server.

**`EarlyInit` is not the fix.** Moving the registration there fails on client
*and* server: `TypeManager` is not initialised that early, so
`TypeManager.IsSystemType` throws `NullReferenceException` out of
`DisableBurstForSystemInternal` and the registration never happens at all.

### How the breakage presents itself

The client's own patch still works and suppresses its *prediction* — a
durability system, for instance, sits in `EndPredictedSimulationSystemGroup` —
but the server stays authoritative and its ghost snapshot overwrites the value a
few ticks later. The player sees the effect flicker in and revert.

Mods usually look half-broken rather than broken, because patches on *managed*
methods (`SaveManager`, `PlayerController`, `PetExtensions`, …) are evaluated by
the client itself and keep working. Only the ECS half goes quiet.

Two variants worth recognising, both of which hide the problem further:

- The system runs in every world, but its input component is created only
  `if (isServer)` — so the client patched a system that never had any work to do.
- The system is declared `WorldSystemFilterFlags.ServerSimulation` only — so
  there is no client-side copy at all and the effect is completely dead.

Anything server-authoritative is in the blast radius: XP and skill grants,
durability, pet levelling, world simulation.

### Proving a patch is live on the server

Put a `Debug.Log` in the **static constructor** of the `[HarmonyPatch]` class.
An explicit static ctor suppresses `beforefieldinit`, so it fires immediately
before the first `Prefix()` call — the line appearing in the *server* log is the
proof that the patch is live there.

Two caveats make an absent line meaningless:

- **An idle dedicated server sits at `timescale = 0` and does not simulate.** A
  player must be connected, or no system updates at all.
- The server log stops growing after world start, so read it *after* the
  session, not during.

See [multiplayer-and-server](multiplayer-and-server.md) for version/protocol
issues and [../dedicated-server.md](../dedicated-server.md) for running one
locally.

## Harmony binding mechanics

### Look for a public event before you patch

Not every hook has to be a patch. Some of CK's extension points are plain public
multicast delegates that any assembly can subscribe to. `Mods.OnModManagementEvent`
is one: the game's own `RadicalMainMenuOption_OpenMods.Awake` attaches its handler
to it with `+=` at `Pug.Other:338594`, and a mod can attach to the same delegate
**without any Harmony patch**, so none of the binding mechanics below apply to it.

Whether CK has further events of this kind has not been surveyed — but checking
the decompile for a public event on the type you were about to patch is cheap.

### `in`/`ref` parameters need `argumentVariations`

A patch whose target has an `in` parameter — by-ref, shown as `A&` in the
decompile — fails at load with `ArgumentException: Undefined target method for
patch method …`. The mod itself loads and sandbox-compiles fine
(`safetyCheck=True`); only the bind fails. That distinguishes it cleanly from
the Burst case, which binds and stays silent.

Add the variations array, `ArgumentType.Ref` for each `in`/`ref`/`out` parameter
and `ArgumentType.Normal` for each by-value one:

```csharp
[HarmonyPatch(
    typeof(PlaceObjectSlot),
    "PlaceItem",
    new[] { typeof(EquipmentUpdateAspect), typeof(EquipmentUpdateSharedData), typeof(LookupEquipmentUpdateData) },
    new[] { ArgumentType.Ref, ArgumentType.Normal, ArgumentType.Normal }
)]
```

`ArgumentType` lives in `HarmonyLib`. The usual alternative — a `TargetMethod()`
resolving the signature via `AccessTools.Method(t, "M", new[] { typeof(A).MakeByRefType(), … })`
— is **not available to a sandboxed mod**: `HarmonyLib.AccessTools` is rejected
outright ("Indirect illegal reference via type exclusion"), as is
`System.Reflection` member access. The `[HarmonyPatch(typeof(X), nameof(X.Y))]`
attribute form is fine, because that reflection runs inside trusted
`0Harmony.dll`. Details in [sandbox rules](sandbox-and-config.md).

### Not everything needs `BurstDisabler`

Managed methods bind without it. `PlaceObjectSlot.PlaceItem` is the canonical
example: `PlaceObjectSlot : EquipmentSlot` is in the global namespace, while the
placement aspect and lookup types (`EquipmentUpdateAspect`,
`EquipmentUpdateSharedData`, `LookupEquipmentUpdateData`) live in namespace
`PlayerEquipment`.

**Trap when picking the overload:** `PlaceObjectSlot` (decompile lines
311283–311633) declares exactly *one* `PlaceItem`, the three-argument
`(in EquipmentUpdateAspect, EquipmentUpdateSharedData, LookupEquipmentUpdateData)`
at `:311319`. Identical-looking overloads at `:310177` and `:311118` belong to
**other classes** — patching by shape rather than by owning type binds the wrong
method.

**The audit question is what you patch, not what Burst touches.** `[BurstCompile]`
on the systems that *write* the components you read is irrelevant. `BurstDisabler`
is needed only when the **patch target itself** is executed by Burst. Read-only
access needs it not at all: an `EntityQuery.ToEntityArray` plus `GetComponentData`
out of a managed coroutine or `Update` requires nothing, even though Burst jobs —
`DropSelfJob` (`Pug.Other:88826`), for instance — match the very same components.
`BurstDisabler` is not a precondition for touching ECS from a mod, and a
needless `DisableBurstForSystemAndJobs` is not free.

### A postfix on an input-driven method fires per input tick

`PlaceItem`'s postfix runs after *every* call, including every early return — no
valid placement spot, cooldown, and so on. While the player merely holds a
placeable item, that is roughly one call per input tick.

The reason is that the method protects itself **internally**: the guards are
early returns inside the body, not conditions at the call site. A prefix runs
ahead of all five of them.

| Guard | Location |
|---|---|
| `if (!valueRW.canPlaceObject) return;` | `Pug.Other:311322` |
| `CanPlaceItem` → `tilePlacementTimer` (0.65 s in this build) | call `:311332`, declaration `:311533`, timer logic `:311538-311555` |
| `timeSincePlaced.isRunning && … < 1f && pos == positionLastPlacedAt` | `:311337` |
| `PlayerController.CanConsumeEntityInSlot` | `:311350` |
| Creative / `ObjectType.PlaceablePrefab` check | `:311354` |

`EntityUtility.AddTile` (`:311379`), immediately followed by vanilla's own
`ConsumeEntityAt`, is the **first point past all five**.

Any side effect gated only on item identity therefore over-fires massively. Gate
on a signal that a placement actually **committed**: `AddTile` being reached, the
`PlaceObject` player-state push, or the consume branch actually being taken. The
postfix firing is not that signal.

This generalises to every equipment/input path in CK: assume the method is
polled, and find the commit point.

### Patch the convergence point to survive other mods

A prefix returning `false` in someone else's mod erases your patch target
wholesale. PlacementPlus (mod.io `3400322`) prefixes
`PlaceObjectSlot.UpdateEquipment` and returns `false`, so vanilla's method and
everything it calls — `PlaceItem` included — never runs for its users. It then
drives its own `ObjectPlacementLogic.PlaceItemGrid`, calls
`EntityUtility.AddTile` itself (in its own `ObjectPlacementLogic.cs`, at `:276`
and `:555`) and consumes the item only afterwards (`:283`).

**"Works on its own" is not a definition of "works".** Design against the mod
population your mod actually runs beside, and *measure* the interaction rather
than reasoning about it: with PlacementPlus active, a prefix on
`PlaceObjectSlot.PlaceItem` fired **zero** times while laying rails. To test a
suspected conflict, toggle the foreign mod through the loader's `disabledMods`
list in `state.json` (see
[../macos-crossover-loader.md](../macos-crossover-loader.md)) and count your own
patch's invocations in both states.

Do not plan around an upstream fix either. Checked in August 2026, the
PlacementPlus repository (`limoka/CoreKeeperMods`) had merged no PR since early
2025. Treat that as a dated observation rather than a permanent property — but
"upstream will fix it" is not something you can ship.

Four strategies exist for a patch target another mod replaces, and three of them
lose:

| Strategy | Why it loses |
|---|---|
| Conflict detection — disable yourself when the other mod is present | Prevents the failure reliably, but removes the feature from exactly the users who have the conflict |
| A standalone ECS system that anticipates the action | Duplicates the decision: two systems now judge the same tile independently — it does not resolve the conflict so much as double it |
| Rely on the foreign mod's own exclude config | Hangs on a user configuration your mod cannot guarantee |
| **Patch the convergence point** | The one that survives |

The robust target is the point where all routes converge. Queuing a tile means
writing into the `TileUpdateBuffer`, and `EntityUtility.AddTile` is the one
utility that does it; the foreign mod calls it too. Patching there lets you
change *whether and where* something is placed without reimplementing the act of
placing, and per-tile decisions cover grid/multi-tile placement for free.

`AddTile`'s parameters carry no player or inventory context. Get that from a
prefix on `UpdateEquipment` marked `[HarmonyPriority(Priority.First)]` — it runs
ahead of the foreign prefix, and the matching **postfix still runs even when a
prefix returned `false`** — then do the actual work in the `AddTile` prefix. One
code path then serves both the vanilla and the modded world.

Worth internalising as a general rule: **a patched method cannot be
Burst-replaced.** While a foreign prefix sits on a method, your own prefix on
the same method fires even without `BurstDisabler`; remove the foreign mod and
yours goes quiet again unless you used the `AndJobs` variant. A patch that only
works while another mod is installed is a real and confusing outcome.

The placement *rules* themselves — which tile accepts which object — are in
[world and mechanics](world-and-mechanics.md).

### A half-working mod can be worse than none

A very common CK mod shape is two independent halves: a **bake-time**
entitlement (the database says this object may now go there — bake time being
the only mutable window, see [database and baking](database-and-baking.md)) and
a **runtime** behaviour that makes the placement sensible. Design for the state
in which only one half runs.

A rail-bridge mod is the worked example. Its bake half made rails placeable on
pits; its runtime half never fired under PlacementPlus. Rails were therefore laid
across chasms, found no substrate, and dropped to the floor as pickups — strictly
worse than not installing the mod at all. Wherever the halves can come apart — a
foreign prefix erasing the runtime hook, or the dedicated-server trap above
killing it silently — work out what the surviving half does on its own, and pick
the strategy that keeps the two together.

## Correlating private state across two methods

Sometimes the data you need is neither in the arguments of any hookable method
nor reachable directly, because the API that exposes it is sandbox-blocked and
the value itself lives in a private field written by one method and consumed by
another.

The pattern: **hook both methods and correlate them with a static flag.**

```csharp
[HarmonyPatch(typeof(SaveManager), nameof(SaveManager.SetCharacterId))]
internal static class SaveManagerActiveSelectHook
{
    public static string ActiveGuid { get; internal set; }
    internal static bool AwaitingActiveDeserialize;

    [HarmonyPostfix]
    static void After(int id)
    {
        if (id < 0) { ActiveGuid = null; AwaitingActiveDeserialize = false; return; }
        AwaitingActiveDeserialize = true;
    }
}

[HarmonyPatch(typeof(CharacterData), nameof(CharacterData.OnAfterDeserialize))]
internal static class CharacterDataDiscoverySnapshot
{
    [HarmonyPostfix]
    static void After(CharacterData __instance)
    {
        string guid = __instance.characterGuid;   // public string field, safe

        if (SaveManagerActiveSelectHook.AwaitingActiveDeserialize)
        {
            SaveManagerActiveSelectHook.ActiveGuid = guid;
            SaveManagerActiveSelectHook.AwaitingActiveDeserialize = false;
        }
    }
}
```

That example obtains the active character's GUID, for which every direct route is
closed: `PlayerController.characterGuid` does not exist, `SaveManager` is a
banned class so `Manager.saves.GetCharacterGuid()` is out, `HarmonyLib.Traverse`
is banned as a reflection wrapper, and `EntityManager.HasComponent<CharacterGuidCD>`
plus `GetComponentData` trips the sandbox on namespace, type and member.

Nothing in the hook bodies violates the sandbox: only value-type parameters
(`int id`), a public `string` field on a non-banned class, and the mod's own
statics. The `[HarmonyPatch(typeof(BannedClass), …)]` attribute is legal because
the reflection behind it runs in trusted `0Harmony.dll`.

**Preconditions — verify all three in the decompile before committing to this:**

- The producer and the consumer are called in deterministic order.
- They run on the same thread with no re-entry in between (the mod/main thread
  qualifies).
- The consumer *always* follows the producer. If it is conditional, the flag
  leaks and pollutes the next legitimate producer call.

If any of these is uncertain, the flag will race or leak, and the bug will be
intermittent.

## Scaling a value that flows from a Burst producer into a Burst consumer

A very common shape: a managed-looking producer method computes an amount, an
ECS component carries it, and a Burst system applies it. **Do not patch the
producer** — its callers are themselves Burst-compiled sim code and bypass your
IL patch entirely.

Instead:

1. `BurstDisabler.DisableBurstForSystem<TConsumerSystem>()` in `IMod.Init()`
   (plus the `AddWorld` pass from above).
2. Harmony `Prefix` on the consumer's `OnUpdate(ref SystemState state)`. Via
   `state.GetEntityQuery(ComponentType.ReadWrite<T>())` and
   `state.EntityManager` (`GetComponentData` / `SetComponentData` /
   `GetBuffer`), **rewrite the pending value before returning `true`** so the
   original system applies your inflated number.

This is robust regardless of whether the consumer's inner *job* stays Burst: you
are mutating the shared component memory that job then reads. It also leaves the
system's own guards (max level, caps) intact, so the change becomes a natural
no-op at the cap. Querying and `SetComponentData`/`GetBuffer` from inside the
prefix are sandbox-safe.

### Worked example — XP grants

CK's XP grants have exactly two choke points, and both fit this shape.

| Track | Producer | Component | Burst consumer |
|---|---|---|---|
| Player skill XP | `PlayerController.AddSkill(Entity, SkillID, int amount, EntityCommandBuffer, bool isServer)` — the sole creator of the component, only `if (isServer)` | `AddSkillValueCD : IComponentData` | `AddSkillValueSystem` (`SkillBuffer.Value += amount`, guarded `levelFromSkill < maxSkillLevel`) |
| Pet XP | `PetExtensions.GetExperienceFromDamage(dmg) = clamp(dmg / 20, 1, 250)` — pets level only from dealt damage | `AddPetExperienceBuffer : IBufferElementData` | `PetHandlerSystem` (`pet.objectData.amount += amount`, guarded `!IsAtMaxLevel`) |

Every skill funnels through `AddSkill` — Mining, Melee and Range via the combat
`skillMultiplier`, Fishing, Crafting, Cooking, Gardening, Running, Vitality,
Summoning, Explosives. Its callers include `PlayerAttackAspect` and the inventory
handlers, all Burst-compiled, which is precisely why patching `AddSkill` itself
does not work.

Both component types are declared in `Pug.ECS.Components` but sit in the
**global namespace**; the systems live in `Pug.Other`. Neither needs a `using`
in mod code.

Scale with rounding that cannot silently zero a grant:

```csharp
int boosted = (int)(amount * mult + 0.5f);
if (boosted < 1) boosted = 1;
```

Because the grant is server-authoritative (`AddSkill` runs only `if (isServer)`),
the effect applies in single-player and as host, and the mod needs the server
side in its `requiredOn` — see [mod anatomy](mod-anatomy.md).

## Instrumenting generated DOTS code

**The `OnUpdate` body you are reading in a mod's `.cs` file is not the one that
executes.** For any system using `Entities.ForEach` or `SystemAPI.*`, the DOTS
source generator has moved the body into
`Scripts/Generated/<System>__System_<id>.g.cs` as
`__OnUpdate_<hash>()`, marked `[DOTSCompilerPatchedMethod("OnUpdate_T0")]`, and
the mod loader rewires the method at runtime. Player.log states it per mod:

```text
Replacing method <Ns>.<System>/OnUpdate_T0 with __OnUpdate_<hash>
```

Diagnostic code added to the source file therefore never runs. It has to go into
the `.g.cs`.

That file is also the better place to measure from: it is a `partial class` and
contains the system's **real** queries (`__query_<id>_0`, … with every filter and
`EntityQueryOptions` applied), so a measurement taken through them observes
exactly what the system observes instead of a hand-built replica. Fields and
helper methods can be added freely.

**Two hard limits:**

- **Do not touch the `Entities.ForEach` body or the Burst job.** Any change
  there would need a fresh source-generator run, which is not available without
  Unity — and `Debug.Log` is forbidden inside a Burst job anyway. Diagnostics go
  *beside* the job, never inside it.
- **Do not introduce new `SystemAPI.*` usage**; that also requires generation.
  `EntityManager.CreateEntityQuery(new EntityQueryDesc { … })` plus
  `ToComponentDataArray<T>(Allocator.TempJob)` plus `UnityEngine.Debug.Log` are
  generator-free and sandbox-legal.

**Procedure.** Edit the `.g.cs` inside the mod.io cache
(`…/Public/mod.io/5289/mods/<modId>_<modfileId>/Scripts/Generated/`), delete the
loader's extraction at `…/Temp/Pugstorm/Core Keeper/ModLoader/<ModName>/`, then
restart the game. Leave the ZIP under `…/Temp/Pugstorm/Core Keeper/5289/` alone —
mod.io tracks integrity and downloads through it.

**Syntax-check without Unity.** Copy the file into a scratch directory *without
`.g` in the name* and run `dotnet csharpier check` on it. CSharpier silently
skips `*.g.cs` ("Checked 0 files") but otherwise parses through Roslyn and
reports genuine syntax errors. The care is warranted: a `CompileFailed` can
cascade and desynchronise *other* mods, not only yours — see
[troubleshooting](troubleshooting.md).

**Two traps when instrumenting a third-party mod:**

- **Do not open the in-game Mods menu.** The mod.io sync re-extracts the mod and
  your edit is gone.
- Every mod update replaces the cache folder outright. Keep a backup of the
  original file **outside** the `Scripts/` tree — a `.bak` left inside it would
  be compiled along with everything else.

## Reading the live ECS world from a mod

Live-world access needs no Harmony routing at all: plain mod `Scripts/*.cs` may
query the ECS world directly, and the whole surface below is sandbox-safe
(`safetyCheck=True`).

**Pick the world by measurement, not by name.** Inventories live in the
**ServerWorld**, not the ClientWorld — including in single-player, where the
client is a local host. Iterate `World.All`, run
`CreateEntityQuery(...).CalculateEntityCount()` for a probe component, and take
the world with the most entities. Hardcoding a world name breaks the moment the
topology changes.

**Trap: the world you measure may not be populated yet.** The measurement is only
safe as a one-shot if the ECS entities are certain to be deserialised by then. An
early callback — `OnOccupied`, for example — can fire before that, and the probe
then pins an empty or simply wrong world for the rest of the session. A scanner
that caches its world therefore needs a re-probe path: after a run of consecutive
empty scans, measure again and re-pin. How many empty scans is per-mod tuning,
not a constant.

From there, `em.CreateEntityQuery(ComponentType.ReadOnly<…>())` →
`ToEntityArray(Allocator.TempJob)` → `GetComponentData<T>`, `HasComponent<T>`,
`GetBuffer<…>` all work.

### Identifying an entity as a particular object

**Trap: there is no per-object-type component.** Hunting the decompile for a
`<Thing>CD` that marks one kind of object is the wrong search and will fail after
a long detour. `PugObjectConverter.Convert` (`Pug.ECS.Conversion:5837`) fills
`ObjectTypeCD` and `ObjectDataCD` on *every* object entity, and those two carry
the identity:

```csharp
// Pug.ECS.Components:3890-3893
public struct ObjectTypeCD : IComponentData, IQueryTypeParameter { public ObjectType Value; }
```

A name like `DiggingSpot` exists as an `ObjectType` value, as an `ObjectID` value
and as a MonoBehaviour — but not as a component. Recognise an entity by
`ObjectDataCD.objectID` and `ObjectTypeCD.Value`.

**A DOTS query selects archetypes, not values.** `EntityQueryBuilder` /
`CreateEntityQuery` cannot express "where `ObjectTypeCD.Value == X`". The
component goes into the query to pick the chunks; the `objectID` / `Value`
comparison belongs in the loop body, per entity. That is a general DOTS property,
but it bites harder in CK than elsewhere, because practically every world entity
carries the same component set — so the query is almost never the filter.

**Use an empty tag component as a chunk prefilter, never as an identity test.**
`DiggableCD` is a null-byte tag:

```csharp
// Pug.ECS.Components:4503-4507
[StructLayout(Size = 1)]
[GhostComponent(PrefabType = GhostPrefabType.All)]
public struct DiggableCD : IComponentData, IQueryTypeParameter { }
```

It sits on everything a shovel can turn over — floor tiles, plants, dig spots —
which makes it worthless as an identity test and valuable in the query, where it
excludes non-matching archetypes cheaply. The game disambiguates the same way,
with `objectID ==` checks (`Pug.Other:296438`, `:296842`, `:310904`). The pattern
generalises — tag narrows, `objectID` decides — while `DiggableCD`'s particular
breadth is just one data point.

### The performance rule

**For a recurring scan over many entities, never call `GetComponentData<T>(e)`
per entity.** Each call is a random chunk-plus-index lookup; done synchronously
on the main thread across a large query, it spikes the frame.

Bulk-copy instead: `q.ToComponentDataArray<T>(Allocator.TempJob)` is a
chunk-sequential memcpy, and the resulting arrays are **index-aligned** with the
entity array as long as they are captured back to back with no structural change
in between. Keep per-entity access (`HasComponent`, `GetBuffer`) for the gated
minority that actually needs it.

| Rule | Value |
|---|---|
| Frame budget for a synchronous main-thread scan | < 16.7 ms (60 fps) — above it, a frame drops and the stutter is visible |
| Measured effect of the bulk swap on a ~1300-entity scan | max 21.5 ms → 9.6 ms |

Diagnose before optimising: a throwaway probe splitting phases with
`Time.realtimeSinceStartup` (plus entity and anchor counts) identifies the
dominant phase. In the measured case, spatial hashing, caching the world
resolution and reusing allocation buffers were all unnecessary — only the
per-entity component reads mattered.

### Hooking the save

To persist mod state in lockstep with CK's own save, Harmony-postfix
**`SaveManager.WriteCharacter(int saveId)`** — the real character-file write
(`characterFiles[saveId].Write(EncodeJson(...))`), which fires on autosave *and*
on "Save & Quit". The parameterless `WriteCharacter()` delegates to it. The
symmetric load point is `CharacterData.OnAfterDeserialize`.

`SaveManager` being a sandbox-banned class does not block this: Harmony patches
run in trusted `0Harmony.dll`.

**Trap:** do **not** gate your save on a return-to-menu signal such as
`SetCharacterId(-1)`. A normal "Save & Quit" does not reliably call it, so the
gated save never reaches disk — the file simply stays absent with no error, a
silent data-loss path. Saving in lockstep also avoids a post-crash desync where
CK reverts the character while your file is newer. Keep a `Shutdown()` and a
character-switch save as cheap backstops.

Where that data goes, and the file API to write it with, is
[sandbox and config](sandbox-and-config.md).
