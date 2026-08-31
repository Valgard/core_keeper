--- a/code-examples/burstdisabler-example.md
+++ b/code-examples/burstdisabler-example.md
@@ -1,0 +1,27 @@
+## Dedicated Servers
+
+The `AddWorld` pass in `Init()` above is what makes the patch take effect on a dedicated server. Without it the Harmony patch still binds, but the prefix simply never runs — no error, no log line, so the mod looks like it works in single-player and quietly does nothing in multiplayer. `SpawnEnvironmentObjectsInNewAreaSystem` only ever runs in the server world, so in this example there is no client-side copy left to do the work.
+
+`DisableBurstForSystem<T>()` records the system type, and `BurstDisabler.AddWorld(world)` is what arms it for a particular world. The game calls `AddWorld` itself while ECS starts up, and that call reads the recorded types once — nothing back-fills it afterwards. On the client, `Init()` runs before that point, so your registration is picked up. On a dedicated server the order is reversed: the worlds are set up first and `Init()` runs afterwards, by which time the arming has already happened with nothing to arm.
+
+`AddWorld` only sees what was registered before it runs, so register every system you need first and do the pass once afterwards. Writing it unconditionally is safe — on the client it arms nothing that the regular startup would not arm anyway.
+
+{% hint style="warning" %}
+Moving this to `EarlyInit()` does not help, for the same reason `DisableBurstForSystem<T>()` cannot be called there: the type initialization it relies on has not happened yet.
+{% endhint %}
