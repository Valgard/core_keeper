# The build environment — what runs the build, and what hangs it

How a mod is built here is in `README.md` (§ Build & install): `utils/build.sh`
drives the Unity Editor in batch mode over the shared `CoreKeeperModSDK`
project. **What the SDK demands of any setup** — the exact Unity version, the
modules, the wizard steps, the project lock — is [`docs/ck/toolchain.md`](ck/toolchain.md).

This file is the third thing: what goes wrong with that arrangement on this
machine, how to tell the failures apart, and which tools exist for it.

## A build that hangs is almost always the ILPP runner

A batch-mode build normally finishes in **one to three minutes**. One that has
been running for twenty is not slow, it is stuck, and the cause has been the
same both times it happened: Unity waits forever for its IL Post Processor
subprocess, which never starts.

**Diagnose it in three numbers, not by guessing.** All three have to line up:

```bash
ps -o pid,etime,%cpu,state -p <unity-pid>   # ~0 % CPU, state S -> waiting, not working
ls -la /tmp/ilpp.sock-*                     # the socket exists
pgrep -fl "dotnet.*Unity"                   # ...but NO runner process is alive
```

That combination — a socket with nobody behind it — is the signature. A build
that is merely slow shows real CPU (100 %+, state `R`), and there is nothing to
fix.

**Recovery, and the part that actually matters.** Clearing the artifacts alone
does **not** fix it; that was verified the first time this was hit. The
decisive step is restarting Unity Hub, because the wedged Hub/licensing IPC is
what stops the ILPP runner from launching:

```bash
kill -9 <unity-pid>                      # safe: a batch build has no unsaved state
rmtrash -rf CoreKeeperModSDK/Temp \
           CoreKeeperModSDK/Library/Bee  # lockfile + ILPP/build cache, both regenerate
rm -f /tmp/ilpp.sock-*
```

…then **quit and restart Unity Hub**, then build again. Measured on
2026-08-23: the same build went from a 24-minute hang to **75 seconds** after
the Hub restart, with nothing else changed. The first build afterwards is
slower than usual because `Library/Bee` has to be rebuilt.

Two cautions on the cleanup:

- **`Library/Bee` is shared.** Every mod builds against the one SDK clone, so
  deleting it while another session is building costs that session a full cache
  rebuild. Check for a foreign Unity process first — and if one is running,
  its build is not yours to kill (see the concurrency note in `CLAUDE.md`).
- **Use `rmtrash`, not `rm`.** A local hook enforces this, and it is right to:
  both directories are recoverable from the Trash if something turns out to
  have been needed.

## `Access token is unavailable` is noise, not a diagnosis

```
[Licensing::Module] Error: Access token is unavailable; failed to update
```

This line appears in **successful** builds too — it was present in the 75-second
run above. It is tempting to read it as the cause when a build then fails or
hangs, and that reading sends you after the licensing system instead of the
ILPP runner. Treat it as background noise unless something else corroborates.

## Keep the full log, or you will have nothing to read

`build.sh` streams a very long log. Piping it straight into `grep` **buffers**,
so a hung build shows no output at all while it hangs, and a failed one shows
only what the pattern happened to match. Tee it first:

```bash
utils/build.sh 2>&1 | tee "$SCRATCH/pch-build.log" | grep -E "✓ Build|✗ Build|error CS"
```

The filtered view stays readable, and the full log survives for the diagnosis
you did not know you would need.

## The Unity CLI: a wrapper, not a replacement

Unity Hub 3.21 ships a CLI at

```
/Applications/Unity Hub.app/Contents/Resources/cli/unity
```

(currently `1.0.0-beta.5`, documented under Unity Production Pipeline and
labelled **experimental**). Its `build` command describes itself precisely:

> Build a Unity project from the command line. **Spawns the editor in batch
> mode** and forwards conventional CI flags.

And it takes `--execute-method <method>` — which is exactly what `build.sh`
already passes. **So it would not have prevented the hang above:** same editor,
same batch mode, same licensing IPC. Switching to it is a change of spelling,
not of mechanism.

It is worth knowing about anyway, for three things this setup currently hand-
rolls:

| Feature | What it would replace |
|---|---|
| `--log-file`, default `Logs/build-<target>-<timestamp>.log` | the `tee` above |
| `doctor` / `diagnose` (redacted, paste-safe) | reading `ps`/`pgrep` by hand |
| `job` — detached editor command jobs | polling loops that wait for the lock |
| `--json` / `--non-interactive` | grepping human-readable log lines |

Deliberately **not** adopted for now: it is beta, the current script works, and
a build system is a bad thing to change in the middle of an iteration. If it is
picked up later, `doctor` is the piece with the clearest immediate value — it is
the information that was missing while diagnosing the licensing line above.
