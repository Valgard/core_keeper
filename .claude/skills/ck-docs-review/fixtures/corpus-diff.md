--- a/code-examples/burstdisabler-in-practice.md
+++ b/code-examples/burstdisabler-in-practice.md
@@ -1,0 +1,47 @@
+## BurstDisabler in Practice
+
+`DisableBurstForSystem<T>()` registers a system type so the SDK's gate on
+`WorldUnmanagedImpl.UpdateSystem` can flip Burst off around that system's
+update. `DisableBurstForSystemAndJobs<T>()` registers the same type and
+additionally installs a postfix on `OnUpdate` that completes the system's
+outstanding dependency before the update call returns.
+
+Which of the two a mod needs follows from where its patch target sits, and the
+reachable range is narrower than it first looks. A method that only ever runs
+inside a job the system schedules cannot be patched from a mod at all: the job
+body executes after the gate has closed again, so the patch binds cleanly and
+never fires. Pick a target `OnUpdate` calls itself and the question does not
+arise.
+
+Registering the type is only half of it. The bypass is armed per world by
+`BurstDisabler.AddWorld`, which reads the registered types once, so a mod that
+has to work on a dedicated server follows the registration with a pass of its
+own over the worlds that exist by then. Every mod in this family that touches
+`BurstDisabler` makes both calls from `Init()`; none of them attempts it from
+`EarlyInit()`, where the type machinery is not up yet.
+
+Four mods here carry that pass — `DisableDurability`, `FasterTalents`,
+`AutoRailBridges` and `ReusableCattleBox` — and they write it the same way, a
+`foreach` over `World.All` calling `AddWorld` once per world.
+`ReusableCattleBox` goes one step further and counts how many worlds the pass
+actually reached, because `AddWorld` returns nothing and logs nothing whether
+it armed a system or found none to arm.
+
+Not every published mod bothers. `SceneBuilder` calls the plain variant for
+`DungeonApplySpawnedObjectsSystem` and never calls `AddWorld` at all, and
+`PlacementPlus` does the same for `EquipmentUpdateSystem` with the `AndJobs`
+variant. That two shipped mods rely on it is evidence enough that the loader
+arms each world as it creates it, and that the extra pass is defensive rather
+than load-bearing.
+
+`FasterPetTalents` needs none of it. `PetHandlerSystem` is a managed
+`SystemBase` rather than an unmanaged `ISystem`, so
+`DisableBurstForSystemInternal` hands it to `PatchManagedSystem`, which patches
+the system's own lifecycle methods directly and never reaches the per-world
+registry `AddWorld` fills.
+
+{% hint style="info" %}
+None of this needs elevated access: every mod named above ships with
+`skipSafetyChecks` off, and both `World.All` and `BurstDisabler` are reachable
+from inside the Roslyn sandbox.
+{% endhint %}
