# Answer Key — Planted Errors (SCORING ONLY)

⚠️ **This document is for scoring only.** It must never be given to a lane during a baseline or verification run. A lane that is handed the answers is not measuring anything. Destroy this file or withhold it from every agent that reviews the fixture.

---

## The four planted errors

Each was found by an independent adversarial pass and then confirmed by hand against the decompile at `~/Projects/checkouts/CoreKeeperDecompile/`.

| Sentence | Class | Evidence |
|---|---|---|
| "records the system type" | Understatement | `PugMod.SDK.Runtime:807-808` installs the SDK's gating Harmony patch; `:822` mutates `SystemBaseRegistry` |
| "does nothing in multiplayer" | Wrong scope | `Pug.Other:2654` creates the ServerWorld in a hosting client; armed at `:2673-2675` after `Init()` |
| "arms nothing that the regular startup would not arm anyway" | Overreach | `World.All` is backed by `Unity.Entities:66082 s_AllWorlds`, a superset of `ECSManager._allWorlds` |
| "nothing back-fills it afterwards" | Overreach | `ResetWorlds` (`PugMod.SDK.Runtime:841`) is called from `Pug.Other:2938` on world unload |
