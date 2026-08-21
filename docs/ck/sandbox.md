# The load-time sandbox

A Core Keeper mod does not ship a compiled assembly. It ships C# sources
(`Scripts/*.cs`) that the loader compiles with RoslynCSharp at game start, and
then puts through a security verification before it is allowed to run. That
verification is **default-allow with explicit deny lists**: everything is
permitted except seven namespaces, sixteen types, seven assemblies and two
members, and a violation kills the mod at load time — after the Editor build
already reported success.

This chapter is what the sandbox forbids, and why that is narrower than it
looks. The commonest thing it costs you is file access — [storing configuration and state](persistence.md)
is how a mod does that anyway.

## What the verification checks

The check runs over **the mod's own Roslyn-compiled IL** and counts references
to banned namespaces, types and members. It does not care what those references
would have done at runtime; it only cares that the symbol appears in your
assembly. When it trips, `Player.log` shows:

```text
Assembly 'X' has failed code security verification. Illegal Assembly Reference = 'N', Illegal Namespace References = 'N', Illegal Type References = 'N', Illegal Member References = 'N', Illegal PInvoke References = 'N'
mod X load error: CompileFailed
```

It is **one line**, the counts are single-quoted, and there are five of them —
assembly and PInvoke counts come before and after the three you would expect.
Grepping for `Illegal Namespace References = 1` finds nothing; the quotes are
part of the string.

**The ban is on the reference, not on the capability.** Your code may not
mention `System.IO`, but the *ability* to touch files is not withdrawn — it is
relocated. Every call you make into an assembly that is already loaded and
trusted (the game DLLs, `0Harmony.dll`, `Newtonsoft.Json`, CoreLib) costs zero
references in your own IL, no matter what that assembly does internally. This
single fact is what makes the rest of this chapter possible: "no `System.IO`"
never implies "no runtime config".

## An Editor build succeeding is not evidence

The SDK's `-batchmode` build does **not** enforce the sandbox. It compiles
against `precompiledReferences` that include `System.IO.dll` and friends, so
banned code compiles perfectly and fails only when the game loads it.

**Smoke-test it by launching the game to the main menu** and grepping
`Player.log` for `passed code security verification` versus `failed`. No world
load is needed — the loader runs the check at startup.

There are three independent gates, and passing two says nothing about the
third. Grep for all of them:

| Gate | What it is | Log needle |
|---|---|---|
| Editor compile | The SDK build | `error CS` |
| Sandbox verification | RoslynCSharp security check at load | `failed code security verification`, `CompileFailed` |
| Harmony bind | The loader's auto-`PatchAll` | `patching failed` (the loader's own annotation check) or `failed to patch mod <name>, got exception` (anything Harmony throws, e.g. `ArgumentException: Undefined target method`) |

A mod can clear the first two and silently fail the third, in which case none of
its hooks exist and it simply does nothing. The binding rules for that third
gate live in [Harmony and ECS](harmony-and-ecs.md); what a failed load does to *other* mods is in [troubleshooting](troubleshooting.md).

**One change shape is exempt: a deletion-only fix.** The verification fires on
*additions* of banned surface, so a change that only removes calls leaves a
strict subset of a file that already passed — it cannot introduce a new banned
reference, and it will still clear the sandbox gate. That is the one case where
skipping the launch-and-grep cycle is justified rather than optimistic.

## What is banned

**The list is data, not folklore.** The verifier reads
`Resources/Assets/Resources/RoslynCSharpSettings.asset` from the game's own
resources, and every group in it carries `defaultBehaviour: 0` — `Allow`. What
follows is that file, complete as of this version. Nothing has to be discovered
by bisection; if a load fails on something not listed here, the game has
changed and the asset is where to look.

| Group | Denied |
|---|---|
| Namespaces (7) | `System.IO.*`, `System.Diagnostics.*`, `System.Net.*`, `System.Runtime.InteropServices.*`, `System.Reflection.*`, `RoslynCSharp.*`, `Pug.Platform.*` |
| Types (16) | `System.AppDomain`, and fifteen `HarmonyLib.*` types: `AccessTools`, `Code`, `FastAccess`, `FastInvokeHandler`, `Harmony`, `MethodInvoker`, `Patch`, `PatchClassProcessor`, `Patches`, `PatchInfo`, `PatchProcessor`, `ReversePatcher`, `SetterHandler`, `Transpilers`, `Traverse` |
| Assemblies (7) | `UnityEditor.dll`, `Mono.Cecil.dll`, and the five `MonoMod.*` assemblies |
| Members (2) | `UnityEngine.Application.Quit`, `System.Type.InvokeMember` |

Three consequences the list makes obvious and a bisection would not:

- **Whole namespaces, not selected types.** `System.Diagnostics.*` takes
  `Stopwatch`, `StackTrace` and `Debug` with it, not just `Process` — which
  matters to anyone trying to time their own scan. `System.Reflection.*` is why
  an innocent `ex.GetType().Name` fails: `Type.Name` *is* `MemberInfo.Name`.
- **Harmony's attribute surface is untouched.** Fifteen `HarmonyLib` types are
  denied — but `[HarmonyPatch]`, `[HarmonyPrefix]` and friends are attributes,
  not those types. That is why declarative patching works while every
  programmatic entry point is closed.
- **`System.Security.Cryptography` is not on any list**, which is why CoreLib
  can hash with it.

The following were observed to fail and are *not* on the list — the reason lies
in what the expression resolves to, not in a listed symbol:

| Observed failure | What it resolves to |
|---|---|
| `Manager.saves.X()` — property access on `SaveManager` | `SaveManager` is on no deny list. What trips is the *property* path: this repo's ItemChecklist records `Manager.saves.*` property access failing while field access on the same object passes, and the published ItemBrowser mod calls `Manager.saves.HasDiscoveredObject(...)` directly without trouble. Treat it as a property-versus-field distinction, not a banned class. |
| Some game-side ECS component reads | `em.HasComponent<CharacterGuidCD>(entity)` + `GetComponentData<CharacterGuidCD>(entity)` + `Hash128` together produced 1 namespace + 1 type + 1 member illegal ref — something in that expression resolves into `System.Reflection.*` or `System.Runtime.InteropServices.*`. Bisect the expression, not the deny list. |

`System.IO.*` deserves its own note because the namespace ban reaches further
than the name suggests: purely in-memory types go with it — `MemoryStream`,
`BinaryWriter`, `BinaryReader`, `EndOfStreamException`. `BinaryWriter`-style
framing has to be hand-rolled; string-to-`byte[]` does not, since
`System.Text.Encoding` is legal.

**`AccessTools` is denied outright** — it sits on the type list beside
`Traverse`, so the reflection-wrapper route into private fields is closed by
both of its entrances. The legal route below does the same job with no
dependency on either.

**Not banned, contrary to expectation: `System.Security.Cryptography`.** It
looks like exactly the BCL surface the sandbox rejects, and it is not: CoreLib
uses `MD5.Create()` and `ComputeHash` in its own sandboxed source
(`skipSafetyChecks: false`) and passes verification. That does not make it the
right tool for the job that tempts you into it — hashing to skip a redundant
write — but the reason is cost and allocation rather than legality; see [writing in lockstep with the game's save](persistence.md#writing-in-lockstep-with-the-games-save).

**Trap: `Type.Name` is not a string operation.** The most common way to trip
the sandbox by accident is a diagnostic log line. Three ways around it:

- Catch the typed exception and write the type name as a string literal: `catch
  (NullReferenceException ex) { Debug.Log("NullReferenceException: " +
  ex.Message); }`
- Log only `ex.Message` and drop the type entirely.
- For non-exception cases, use the SDK's `GetMembersChecked()` /
  `GetNameChecked()` extension methods (`PugMod.SDK.Runtime`) — the reflection
  happens inside that trusted assembly, so it costs no reference of your own. A
  reflective lookup written as
  `typeof(UIScrollWindow).GetMembersChecked().FirstOrDefault(x =>
  x.GetNameChecked() == "_scrollable")` passes cleanly.

### Reaching a private member: resolving it is only half the job

The lookup above finds a private member. It does not let you *use* it — and
that gap is worth stating plainly, because stopping there makes the sandbox look
far more restrictive than it is, and sends people to `skipSafetyChecks: true`
for something that is perfectly legal.

The other half is the SDK's own reflection surface:

| Call | Extension form | Purpose |
|---|---|---|
| `API.Reflection.Invoke(member, target, params…)` | `member.InvokeChecked(target, …)` | call a private method |
| `API.Reflection.GetValue(member, target)` | `member.GetValueChecked(target)` | read a private field |
| `API.Reflection.SetValue(member, target, value)` | `member.SetValueChecked(target, value)` | write a private field |

Note the type: these take a **`PugMod.MemberInfo`**, not a
`System.Reflection.MemberInfo` — which is exactly what `GetMembersChecked()`
hands you, so the two halves fit together directly.

```csharp
// resolve once, cache in a static — the lookup is not free
static readonly MemberInfo UpdateScrollHeight = typeof(UIScrollWindow)
    .GetMembersChecked()
    .FirstOrDefault(m => m.GetNameChecked() == "UpdateScrollHeight");

// call it
API.Reflection.Invoke(UpdateScrollHeight, scrollWindow);
```

**Both halves are SDK surface, so the whole recipe costs no dependency at all.**
`GetMembersChecked` and `GetNameChecked` are extension methods in
`PugMod.SDK.Runtime` (`:602`, `:642`) alongside `API.Reflection` itself — CoreLib
is not involved anywhere in this.

## What is not banned

Verified by passing live loads:

- **`PugMod.API.ConfigFilesystem`** — the loader's own file API. See below.
- **Harmony attributes that name banned types.** See the next section.
- **`Newtonsoft.Json.*`** — trusted precompiled library; usable from mod code
  even though it uses `System.IO` internally.
- **`System.Text` — `Encoding`, `UTF8Encoding` and `StringBuilder`.** CoreLib
  compiles all three under the sandbox: `Encoding.UTF8.GetBytes` /
  `GetString` wrapping its `API.ConfigFilesystem` calls, and
  `new UTF8Encoding(false)` plus `StringBuilder` in its TOML writer. Its
  manifest carries `skipSafetyChecks: false`, so it goes through exactly the
  check your mod does, and its assembly logs `has passed code security
  verification`.
- **`Convert.ToBase64String` / `Convert.FromBase64String`** — these live in
  `System`, not `System.IO`.
- **`UnityEngine.PlayerPrefs`** — Unity-native persistence, sandbox-safe.
- **Pug's ECS surface and most of `Unity.Entities` / `Unity.Collections`** —
  `Entity.Null`, `World.All`, `World.DefaultGameObjectInjectionWorld`,
  `EntityManager.CreateEntityQuery`, `ToEntityArray`, `ToComponentDataArray`,
  `HasBuffer<T>` / `GetBuffer<T>`. **ECS writes are sandbox-legal too**, not
  just reads. The query patterns and the performance rules that govern them are
  in [Harmony and ECS](harmony-and-ecs.md).

`JsonUtility` is the one serialisation entry point still unverified in either
direction — no load here has exercised it.

## Harmony attributes are exempt — hook bodies are not

`[HarmonyPatch(typeof(SaveManager), nameof(SaveManager.SetObjectAsDiscovered))]`
loads cleanly, even though `SaveManager` is a banned access surface. The patch
attribute is a special-cased compile-time-only reference: the reflection that
resolves it happens inside the precompiled, trusted `0Harmony.dll`, not in your
IL.

**This unlocks a banned class's API — within limits.** Hook the method instead
of calling it; your code sees the arguments and the result, while the member
access itself happens inside trusted code.

The limits are worth knowing before relying on it. `InvokeChecker.CheckType`
accepts a patch target only if its assembly name starts with `Pug`, `Unity`,
`SpriteInstancing`, `I2` or `Rewired`, the type is not marked
`[DisallowPatching]`, and it does not live in `PugMod.Loader` itself. BCL types,
`modio.*`, `Newtonsoft.Json` and CoreLib are all outside those prefixes. And the
rejection is **all-or-nothing**: one disallowed target makes the check return
false for the whole assembly, `PatchAll` never runs, and *none* of the mod's
patches bind. The log says `Trying to patch type X from unknown assembly`.

**But the exemption stops at the attribute.** Calling `Manager.saves.X()` from
*inside* a Harmony postfix is still a banned reference and still fails
verification. Only the attribute is free.

Two patterns follow from this:

**Direct-args.** If the banned method's parameters already carry what you need,
hook it and read them — you only touch `int`/`string`/value types, so nothing
banned appears in your assembly.
`SaveManager.SetObjectAsDiscovered(ObjectDataCD, bool __result)` gives you the
object ID and the new-or-not flag this way.

**State machine.** When the data lives in another method's scope, hook both and
correlate them with a static flag. To capture the active character GUID, for
example: a postfix on `SaveManager.SetCharacterId(int id)` sets a static
"awaiting" flag, and a postfix on `CharacterData.OnAfterDeserialize` reads the
public `__instance.characterGuid` field and clears it. This works because CK's
path is strictly sequential — `SetCharacterId` → file read → JSON overwrite →
`OnAfterDeserialize` on that specific character. No banned API is touched; you
read a public field and a value-type argument.

## Finding the banned identifier

**The log names the offending member. Grep for it and skip the detective work.**

A failed verification writes **two** separate error entries, back to back:

1. the counts summary — `Illegal Namespace/Type/Member References = N`
2. a full occurrence report, one line per usage site, of the form
   `Referenced in method body: '<Type>.<Method>()' at instruction: '<IL_…>'`

The second is not conditional on any setting: `RegisterAssemblyImpl` calls
`GetAllText(reportAllOccurences: true)` with the flag as a hardcoded literal
(`RoslynCSharp:3866`), through the same log gate as the summary. If the counts
line reached your `Player.log`, the naming lines did too.

**Trap: grepping for `Illegal` finds only the summary.** The two entries are
separate `Debug.LogError` calls, so Unity puts a stack trace between them and
the detail block scrolls out of a narrow grep window. Search for **`Referenced
in method body`** instead — that lands on the culprit directly.

Fall back on these only when the log was truncated or the detail entry is
genuinely absent:

1. **Bisect.** Comment out the most recently added external API call, rebuild,
   reload. If verification passes, that call was it. This is how the
   `Manager.saves.GetWorldId()` ban was found, and it is nearly always faster
   than the alternative.
2. **Decompile** the mod's freshly built DLL from `ModLoader/<Mod>/` and match
   its external type references against the reported counts. See
   [reverse engineering](reverse-engineering.md).
