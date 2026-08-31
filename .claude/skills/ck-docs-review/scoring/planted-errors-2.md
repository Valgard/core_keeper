# Answer Key — Planted Errors 2 (SCORING ONLY)

⚠️ **This document is for scoring only.** It must never be given to a lane during a baseline or verification run. A lane that is handed the answers is not measuring anything. Destroy this file or withhold it from every agent that reviews the fixture.

Fixture: `../fixtures/flawed-diff-2.md`. Same instrument as `planted-errors.md`,
against a fixture whose subject matter and planted sentences do not overlap
with it — the lanes have the first fixture's four errors and verdicts
memorised, so this fixture cannot reuse any of them and still measure
detection.

---

## The four errors

Three were found by reading the decompile directly (not by extracting a claim
list first — see `ckdocs-wording-attacker`'s "extraction is where these
errors survive" note) and confirmed by hand against
`~/Projects/checkouts/CoreKeeperDecompile/`, then deliberately planted into
the fixture. The fourth was not planted: it was written into the fixture
believing it true, and both review lanes independently refuted the
corresponding sentence during verification. It stays in this table rather
than being quietly corrected away, because it is the strongest evidence in
this file that the gate works — it caught something this document itself got
wrong.

| Sentence | Class | Evidence |
|---|---|---|
| "`World.All` hands you every loaded world with no extra bookkeeping on your side, and it can be treated like any other `IEnumerable<T>` — for example `World.All.Where(w => w.Flags == WorldFlags.GameServer).ToList()` — and it behaves the same way a plain `foreach` over it already does." | Overreach | `Unity.Entities.decompiled.cs:66101` — `World.All` returns `NoAllocReadOnlyCollection<World>`. The struct (`:66044-66071`) exposes a public `GetEnumerator()` (`:66052`) that satisfies a plain `foreach` by duck typing, but its explicit `IEnumerable<T>.GetEnumerator()` (`:66062-66065`) and `IEnumerable.GetEnumerator()` (`:66067-66070`) both `throw new NotSupportedException("To avoid boxing, do not cast NoAllocReadOnlyCollection to IEnumerable<T>.")`. `.Where()` is an `IEnumerable<T>` extension method, so the compiler resolves it through the explicit implementation — `World.All.Where(...)` throws at runtime instead of behaving like the `foreach` above it |
| "None of this is specific to `ISystem`. The same `SystemTypesToDisableBurstFor` bookkeeping and the same `AddWorld` arming described above cover `SystemBase` systems too, so a mod with a mix of managed and unmanaged systems can register and arm both kinds the same way." | Wrong scope | `PugMod.SDK.Runtime.decompiled.cs:798-820` — `DisableBurstForSystemInternal` checks `TypeManager.IsSystemManaged(systemType)` (`:810`); for a managed system (`SystemBase`) it calls `PatchManagedSystem` (`:818`) and returns immediately (`:819-820`), never reaching `SystemTypesToDisableBurstFor.Add(systemType)` (`:833`) or the `AddWorld`/`SystemHandlesToDisableBurstFor` machinery, both in the unmanaged-only branch below the early return. `SystemBase` systems are instead patched directly on their own lifecycle methods (`PatchManagedSystem`, `:872-907`) and never touch that bookkeeping at all |
| "Because every call routes through the same internal patching routine, switching a system from `DisableBurstForSystemAndJobs<T>()` back to the plain `DisableBurstForSystem<T>()` keeps the SDK's bookkeeping in sync with whatever is actually patched — call either overload as often as you like without worrying about what an earlier call installed." | Understatement | `PugMod.SDK.Runtime.decompiled.cs:862-870` — `PatchSystem` builds a fresh `List<MethodInfo>` on every call and unconditionally overwrites `_patchedMethods[systemType] = list;` (`:869`); it never merges with or unpatches what an earlier call for the same type left behind. A system first armed with `DisableBurstForSystemAndJobs<T>()` gets a live Harmony postfix on `OnUpdate` (`CreateCompleteDependencyPatch`, `:925-936`); calling the plain `DisableBurstForSystem<T>()` afterward for the same type overwrites the dictionary entry with a new *empty* list without ever calling `harmony.Unpatch` on the old postfix, which stays installed and keeps running every frame. `UnpatchSystem` (`:909-922`) only removes what `_patchedMethods` currently records, so a later `burstEnabled: true` call finds the empty list, logs "Unpatched all methods for `<X>`", and leaves the orphaned postfix in place — the opposite of "keeps the SDK's bookkeeping in sync" |
| "Call either one again later with `burstEnabled: true` and the SDK unpatches whatever it installed, handing Burst back to the system — useful for a debug toggle that restores a system's normal compiled form without a full reload." | Overreach | `PugMod.SDK.Runtime.decompiled.cs:822-830` — on the unmanaged (`ISystem`) path, `burstEnabled: true` calls `UnpatchSystem` and removes the type from `SystemTypesToDisableBurstFor`, but touches neither of those the same way it touches `SystemHandlesToDisableBurstFor` — a different set. That set is what the Harmony prefix patched onto `WorldUnmanagedImpl.UpdateSystem` actually reads (`:966`, `if (BurstDisabler.SystemHandlesToDisableBurstFor.Contains(sh))`) to decide whether to disable Burst for a given `SystemHandle`. A handle only leaves that set via `ResetWorlds` (`:841-844`, `SystemHandlesToDisableBurstFor.Clear()`), whose sole caller is `ECSManager.UnloadWorldsInternal` (`Pug.Other.decompiled.cs:2938`), reached on a full world unload — not on this call. So a system already armed by `AddWorld` keeps running un-Bursted after `burstEnabled: true` reports it fixed, the opposite of "handing Burst back to the system." Not planted deliberately — this sentence was written into the fixture believing it true, and both `ckdocs-source-verifier` and `ckdocs-wording-attacker` independently flagged it during verification |

## Uncovered class

**Runtime claim as code fact — not covered.** No instance was found in this
area that could be grounded honestly: every claim strong enough to plant
here (`World.All`'s enumeration contract, the managed/unmanaged split in
`DisableBurstForSystemInternal`, `PatchSystem`'s overwrite-not-merge
behaviour) is fully decidable by reading the decompile, which makes each of
them Overreach, Wrong scope, or Understatement rather than a claim that only
runtime observation could settle. Fabricating one to fill the row would
leave this fixture's one deliberately-unverifiable-by-source claim as the
only thing in it not actually grounded — exactly the failure mode the
fixture exists to catch. Left open rather than faked.

## What must stay true in the fixture

Everything else added by `flawed-diff-2.md` is accurate and should draw
`NO OBJECTION`:

- `World.All` returning every loaded world and being usable in a plain
  `foreach` (`Unity.Entities.decompiled.cs:66052`, `:66101`), including the
  code sample's `foreach (var world in World.All) BurstDisabler.AddWorld(world);`.
- `WorldFlags.GameServer` existing as a real flag value
  (`Unity.Entities.decompiled.cs:66021-66035`) — only the claim that `.Where()`
  works on `World.All` is planted, not the flag name itself.
