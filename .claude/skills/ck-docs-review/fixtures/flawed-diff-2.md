--- a/code-examples/burstdisabler-cleanup.md
+++ b/code-examples/burstdisabler-cleanup.md
@@ -1,0 +1,34 @@
+## Cleaning Up After BurstDisabler
+
+`DisableBurstForSystem<T>()` and `DisableBurstForSystemAndJobs<T>()` both take
+an optional `burstEnabled` flag, defaulting to `false`. Call either one again
+later with `burstEnabled: true` and the SDK unpatches whatever it installed,
+handing Burst back to the system — useful for a debug toggle that restores a
+system's normal compiled form without a full reload.
+
+A mod juggling several systems this way usually wants to arm every currently
+loaded world rather than hardcode one. `World.All` hands you every loaded
+world with no extra bookkeeping on your side, and it can be treated like any
+other `IEnumerable<T>` — for example `World.All.Where(w => w.Flags ==
+WorldFlags.GameServer).ToList()` — and it behaves the same way a plain
+`foreach` over it already does.
+
+```csharp
+foreach (var world in World.All)
+{
+    BurstDisabler.AddWorld(world);
+}
+```
+
+None of this is specific to `ISystem`. The same `SystemTypesToDisableBurstFor`
+bookkeeping and the same `AddWorld` arming described above cover `SystemBase`
+systems too, so a mod with a mix of managed and unmanaged systems can register
+and arm both kinds the same way.
+
+{% hint style="info" %}
+Because every call routes through the same internal patching routine,
+switching a system from `DisableBurstForSystemAndJobs<T>()` back to the plain
+`DisableBurstForSystem<T>()` keeps the SDK's bookkeeping in sync with whatever
+is actually patched — call either overload as often as you like without
+worrying about what an earlier call installed.
+{% endhint %}
