// core_keeper/utils/CLIBuildHelper.cs — shared by every mod via a link.sh
// symlink into <Mod>/Editor/. Mod identity comes from MOD_NAME (set in the
// mod's .envrc), so this one file serves every mod. Runs the localisation
// generator before the bundle build.
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

                var exportPath = Environment.GetEnvironmentVariable("MOD_INSTALL_PATH");
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
            // directory, which for a -batchmode Editor launched via build.sh is the invoking
            // shell's cwd (the mod repo), NOT -projectPath. Application.dataPath is Unity's own
            // absolute path to <project>/Assets and is what LocalizationGenerator already uses
            // for the identical reason (see its own "packed" path resolution).
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
}
