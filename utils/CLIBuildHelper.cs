// core_keeper/utils/CLIBuildHelper.cs — shared by every mod via a link.sh
// symlink into <Mod>/Editor/. Mod identity comes from MOD_NAME (set in the
// mod's .envrc), so this one file serves every mod. Runs the localisation
// generator before the bundle build.
using System;
using System.IO;
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
                if (string.IsNullOrEmpty(modName)) { Fail("MOD_NAME not set"); return; }

                // Generate native TextDataBlock assets from localization.yaml first
                // (no-op when LOC_YAML/LOC_OUT are unset).
                LocalizationGenerator.GenerateFromEnv();

                var settingsPath = $"Assets/{modName}.asset";
                var settings = AssetDatabase.LoadAssetAtPath<ModBuilderSettings>(settingsPath);
                if (settings == null) { Fail($"No ModBuilderSettings at {settingsPath}"); return; }

                var exportPath = Environment.GetEnvironmentVariable("MOD_INSTALL_PATH");
                if (string.IsNullOrEmpty(exportPath)) { Fail("MOD_INSTALL_PATH not set"); return; }
                Directory.CreateDirectory(exportPath);

                // Refresh + recursive-import: cheap insurance against stale
                // SourceAssetDB state. Note: if FindAssets still returns 0 for
                // a freshly-symlinked mod folder, the SourceAssetDB itself is
                // taub and only a `rm -rf Library/SourceAssetDB` triggers a
                // full reindex. See docs / project memory.
                AssetDatabase.Refresh(ImportAssetOptions.ForceUpdate | ImportAssetOptions.ForceSynchronousImport);
                AssetDatabase.ImportAsset(settings.modPath,
                    ImportAssetOptions.ImportRecursive | ImportAssetOptions.ForceSynchronousImport);

                Debug.Log($"[CLIBuildHelper] Building {modName} → {exportPath}");
                ModBuilder.BuildMod(settings, exportPath, ok =>
                {
                    Debug.Log($"[CLIBuildHelper] Build {(ok ? "succeeded" : "FAILED")}");
                    EditorApplication.Exit(ok ? 0 : 1);
                });
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
    }
}
