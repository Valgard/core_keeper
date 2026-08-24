// core_keeper/utils/CLIBuildHelper.cs — shared by every mod via a link.sh
// symlink into <Mod>/Editor/. Mod identity comes from MOD_NAME (set in the
// mod's .envrc), so this one file serves every mod. Runs the localisation
// generator before the bundle build. Also holds EnvPaths (bottom of this file),
// the resolver all three shared helpers use for path-valued env vars.
using System;
using System.IO;
using System.Linq;
using PugMod;
using UnityEditor;
using UnityEngine;

namespace CoreKeeperModUtils
{
    public static class CLIBuildHelper
    {
        public static void Build()
        {
            try
            {
                var modName = Environment.GetEnvironmentVariable("MOD_NAME");
                if (string.IsNullOrEmpty(modName))
                {
                    Fail("MOD_NAME not set");
                    return;
                }

                // Generate native TextDataBlock assets from localization.yaml first
                // (no-op when LOC_YAML/LOC_OUT are unset).
                LocalizationGenerator.GenerateFromEnv();

                // Regenerate <Mod>/Generated/DevFlags.generated.cs from MOD_DEV_FLAGS (a
                // comma-separated list of flag names, e.g. "TestFixtures") — see the method doc.
                GenerateDevFlags(modName);

                var settingsPath = $"Assets/{modName}.asset";
                var settings = AssetDatabase.LoadAssetAtPath<ModBuilderSettings>(settingsPath);
                if (settings == null)
                {
                    Fail($"No ModBuilderSettings at {settingsPath}");
                    return;
                }

                // Resolved, not read raw: a relative MOD_INSTALL_PATH would otherwise
                // create the staging dir under Unity's working directory while build.sh
                // and install-macos.sh use the caller's — two different places, and the
                // install step would report an empty build (see EnvPaths).
                var exportPath = EnvPaths.Get("MOD_INSTALL_PATH");
                if (string.IsNullOrEmpty(exportPath))
                {
                    Fail("MOD_INSTALL_PATH not set");
                    return;
                }
                Directory.CreateDirectory(exportPath);

                // Refresh + recursive-import: cheap insurance against stale
                // SourceAssetDB state. Note: if FindAssets still returns 0 for
                // a freshly-symlinked mod folder, the SourceAssetDB itself is
                // taub and only a `rm -rf Library/SourceAssetDB` triggers a
                // full reindex. See docs / project memory.
                AssetDatabase.Refresh(ImportAssetOptions.ForceUpdate | ImportAssetOptions.ForceSynchronousImport);
                AssetDatabase.ImportAsset(settings.modPath, ImportAssetOptions.ImportRecursive | ImportAssetOptions.ForceSynchronousImport);

                Debug.Log($"[CLIBuildHelper] Building {modName} → {exportPath}");
                ModBuilder.BuildMod(
                    settings,
                    exportPath,
                    ok =>
                    {
                        Debug.Log($"[CLIBuildHelper] Build {(ok ? "succeeded" : "FAILED")}");
                        EditorApplication.Exit(ok ? 0 : 1);
                    }
                );
            }
            catch (Exception e)
            {
                Debug.LogError($"[CLIBuildHelper] Exception: {e}");
                EditorApplication.Exit(2);
            }
        }

        private static void Fail(string msg)
        {
            Debug.LogError($"[CLIBuildHelper] {msg}");
            EditorApplication.Exit(1);
        }

        // Regenerates Assets/{modName}/Generated/DevFlags.generated.cs from the MOD_DEV_FLAGS
        // env var (comma-separated flag names) EVERY build, so a normal build (env var unset)
        // always restores the safe "everything off" state — a flag left on by a previous dev
        // build cannot silently survive into a publish build, because the very next ordinary
        // build regenerates the file back to empty before it.
        //
        // No-op for any mod that has never opted in (no committed Generated/DevFlags.generated.cs
        // in its own unity/<Mod>/ tree): the write is skipped unless the env var is set OR the
        // file already exists, so this never creates a new, untracked file in a mod that doesn't
        // use the mechanism. Mods that DO opt in commit the generated file with an empty (all
        // flags off) default — required so the shared Editor project still compiles on a fresh
        // checkout before any build has run (unlike the gitignored Localization/Generated assets,
        // this is C# SOURCE other code in the mod references, so it must always exist).
        //
        // Consumed at mod RUNTIME as plain source text, not as a compiled-DLL preprocessor
        // define: this SDK's mods ship Scripts/*.cs and are compiled at LOAD TIME by the game's
        // own sandboxed Roslyn compiler on each player's machine (see the parent CLAUDE.md,
        // "RoslynCSharp sandbox"), so a Unity Editor-side #if/PlayerSettings scripting-define
        // would never reach that compile pass. Baking the flag into ordinary source text, decided
        // fresh at package time, is the only mechanism that actually reaches what ships.
        private static void GenerateDevFlags(string modName)
        {
            // Application.dataPath, not a bare "Assets/..." string passed to System.IO —
            // raw File/Directory calls resolve against the OS process's current working
            // directory, and that is Unity's own, never the invoking shell's: a -batchmode
            // Editor sits in -projectPath, i.e. the SDK clone (measured on a running publish,
            // 2026-08-24), and an Editor menu item sits somewhere else again. Application.dataPath
            // is Unity's own absolute path to <project>/Assets and is what LocalizationGenerator
            // uses for the identical reason (see its own "packed" path resolution). Paths that
            // arrive from the caller take the other route — EnvPaths, below.
            var generatedPath = Path.Combine(Application.dataPath, modName, "Generated", "DevFlags.generated.cs");
            var envValue = Environment.GetEnvironmentVariable("MOD_DEV_FLAGS");
            if (string.IsNullOrEmpty(envValue) && !File.Exists(generatedPath))
                return;

            var flags = (envValue ?? "").Split(',').Select(f => f.Trim()).Where(f => f.Length > 0).Distinct().OrderBy(f => f, StringComparer.Ordinal);
            var initializer = string.Join(", ", flags.Select(f => $"\"{f}\""));

            var text =
                "// AUTO-GENERATED by CLIBuildHelper.Build() from the MOD_DEV_FLAGS environment\n"
                + "// variable (see .envrc.example) — do not edit by hand, a build overwrites it.\n"
                + "// This checked-in state is always the safe \"everything off\" default: a normal\n"
                + "// build (MOD_DEV_FLAGS unset) regenerates this file back to empty, so a flag left\n"
                + "// on by a previous dev build cannot survive into a publish build unnoticed.\n"
                + "using System.Collections.Generic;\n\n"
                + $"namespace {modName}\n"
                + "{\n"
                + "    internal static class DevFlags\n"
                + "    {\n"
                + $"        private static readonly HashSet<string> Enabled = new HashSet<string> {{ {initializer} }};\n\n"
                + "        public static bool Is(string flag) => Enabled.Contains(flag);\n"
                + "    }\n"
                + "}\n";

            Directory.CreateDirectory(Path.GetDirectoryName(generatedPath) ?? ".");
            File.WriteAllText(generatedPath, text);
            Debug.Log(
                string.IsNullOrEmpty(envValue)
                    ? "[CLIBuildHelper] DevFlags regenerated: none enabled."
                    : $"[CLIBuildHelper] DevFlags regenerated: {string.Join(", ", flags)}"
            );
        }
    }

    // Resolves the path-valued environment variables the CLI helpers read:
    // MOD_REPO_ROOT, MOD_INSTALL_PATH, MODIO_DEPS_MAP, LOC_YAML/LOC_OUT/LOC_TABLE.
    //
    // An environment variable survives the jump from the shell into Unity; the working
    // directory does not. A relative value therefore arrives stripped of the one thing
    // that gave it meaning and resolves against whatever directory Unity's process
    // happens to sit in — which is not the caller's, and not the same for a batchmode
    // run and an Editor menu item. build.sh and upload.sh export MOD_CALLER_CWD="$PWD"
    // for exactly this, so a relative path keeps meaning what it meant where it was
    // typed. Passing `.` for the mod repo used to die two minutes into a publish with
    // "No CHANGELOG.md at ./CHANGELOG.md", naming a file that is plainly there.
    //
    // For real filesystem paths only. AssetDatabase paths ("Assets/<Mod>/…") are
    // project-relative by contract and must stay exactly as they are.
    //
    // Lives in this file rather than one of its own on purpose: link.sh symlinks each
    // shared helper into every mod, and each one costs two .gitignore lines in every
    // mod repo plus a matching entry in new_mod.py. This file is the one that is always
    // linked, carries no #if, and already calls into the other helpers.
    public static class EnvPaths
    {
        public const string AnchorVariable = "MOD_CALLER_CWD";

        private static string _anchor;

        /// Reads a path-valued environment variable and resolves it. An unset variable
        /// passes through as null, so a caller's own "not set" check still reads plainly.
        public static string Get(string variableName) => Resolve(Environment.GetEnvironmentVariable(variableName));

        /// Absolute in, normalised absolute out; relative in, resolved against the caller's
        /// directory. Idempotent, so resolving a value twice costs nothing and is safe.
        public static string Resolve(string value)
        {
            if (string.IsNullOrEmpty(value))
                return value;

            // A "~/…" value is not rooted, so combining it with the anchor would produce
            // <anchor>/~/… — nonsense that surfaces much later, in a message naming a path
            // nobody recognises. A shell expands ~ long before a variable carries one, so
            // this only ever fires for a value the shell never looked at.
            if (value == "~" || value.StartsWith("~/", StringComparison.Ordinal))
            {
                var home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
                if (!string.IsNullOrEmpty(home))
                    value = value.Length == 1 ? home : Path.Combine(home, value.Substring(2));
            }

            return Path.IsPathRooted(value) ? Path.GetFullPath(value) : Path.GetFullPath(Path.Combine(Anchor(), value));
        }

        // Resolved once per Unity run, and only when a relative value actually needs it —
        // a setup that hands over absolute paths never sees a line of this.
        private static string Anchor()
        {
            if (_anchor != null)
                return _anchor;

            var caller = Environment.GetEnvironmentVariable(AnchorVariable);
            var processCwd = Directory.GetCurrentDirectory();
            if (!string.IsNullOrEmpty(caller) && Path.IsPathRooted(caller))
            {
                _anchor = Path.GetFullPath(caller);
                Debug.Log($"[EnvPaths] relative paths resolve against {AnchorVariable}={_anchor} (Unity's own working directory is {processCwd})");
            }
            else
            {
                _anchor = processCwd;
                Debug.LogWarning(
                    $"[EnvPaths] {AnchorVariable} "
                        + (string.IsNullOrEmpty(caller) ? "is not set" : $"is not absolute ('{caller}')")
                        + $" — falling back to Unity's own working directory {processCwd}, which is NOT the one you "
                        + "called from. Invoke through build.sh/upload.sh, or configure absolute paths."
                );
            }
            return _anchor;
        }
    }
}
