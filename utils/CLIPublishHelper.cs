#if PUG_USE_MODIO
// core_keeper/utils/CLIPublishHelper.cs — shared by every mod via a link.sh
// symlink into <Mod>/Editor/. Mod identity from MOD_NAME (set in the mod's
// .envrc). Builds the mod and drives the mod.io plugin to create/update the
// profile and upload a modfile. mod.io calls are async, so upload.sh omits
// -quit and this class calls EditorApplication.Exit on every path.
using System;
using System.IO;
using System.Text.RegularExpressions;
using ModIO;
using PugMod;
using PugMod.ModIO;
using UnityEditor;
using UnityEngine;

namespace CoreKeeperModUtils
{
    public static class CLIPublishHelper
    {
        private static string _modName;
        private static string _settingsPath;
        private static string _modIoSettingsPath;
        private static string _logoAssetPath;

        private static bool _dryRun;
        private static string _version;
        private static string _changelog;
        private static string _buildDir;

        public static void Publish()
        {
            try
            {
                _modName = Environment.GetEnvironmentVariable("MOD_NAME");
                if (string.IsNullOrEmpty(_modName)) { Fail("MOD_NAME not set"); return; }
                _settingsPath = $"Assets/{_modName}.asset";
                _modIoSettingsPath = $"Assets/{_modName}/Editor/{_modName}_modio.asset";
                _logoAssetPath = $"Assets/{_modName}/Editor/logo.png";

                _dryRun = Environment.GetEnvironmentVariable("PUBLISH_DRY_RUN") == "1";

                var repoRoot = Environment.GetEnvironmentVariable("MOD_REPO_ROOT");
                if (string.IsNullOrEmpty(repoRoot)) { Fail("MOD_REPO_ROOT not set"); return; }

                var changelogPath = Path.Combine(repoRoot, "CHANGELOG.md");
                if (!File.Exists(changelogPath))
                {
                    Fail($"No CHANGELOG.md at {changelogPath}"); return;
                }
                if (!TryParseChangelog(File.ReadAllText(changelogPath),
                        out _version, out _changelog))
                {
                    Fail("CHANGELOG.md has no '## [x.y.z]' entry"); return;
                }
                Debug.Log($"[CLIPublishHelper] {_modName} v{_version}"
                          + (_dryRun ? " (dry run)" : ""));

                var settings = AssetDatabase.LoadAssetAtPath<ModBuilderSettings>(_settingsPath);
                if (settings == null) { Fail($"No ModBuilderSettings at {_settingsPath}"); return; }

                _buildDir = Path.Combine(Application.temporaryCachePath,
                    Guid.NewGuid().ToString());
                Directory.CreateDirectory(_buildDir);

                ModBuilder.BuildMod(settings, _buildDir, buildOk =>
                {
                    if (!buildOk) { Fail("Build failed"); return; }
                    OnBuilt();
                }, installInSubDirectory: false);
            }
            catch (Exception e) { Fail($"Exception: {e}"); }
        }

        /// <summary>
        /// Extracts the topmost "## [x.y.z]" entry of a Keep-a-Changelog file:
        /// its version and the body text up to the next "## " header.
        /// </summary>
        public static bool TryParseChangelog(string content, out string version,
            out string changelog)
        {
            version = null;
            changelog = null;
            var header = Regex.Match(content,
                @"^##\s*\[(\d+\.\d+\.\d+)\].*$", RegexOptions.Multiline);
            if (!header.Success) return false;
            version = header.Groups[1].Value;

            int bodyStart = header.Index + header.Length;
            var next = Regex.Match(content.Substring(bodyStart),
                @"^##\s", RegexOptions.Multiline);
            changelog = (next.Success
                ? content.Substring(bodyStart, next.Index)
                : content.Substring(bodyStart)).Trim();
            return true;
        }

        private static void OnBuilt()
        {
            if (!ModIOUnity.IsInitialized())
            {
                var init = ModIOUnity.InitializeForUser("PugModSDKUser");
                if (!init.Succeeded()) { Fail("mod.io init failed"); return; }
            }
            ModIOUnity.IsAuthenticated(auth =>
            {
                if (!auth.Succeeded())
                {
                    Fail("Not authenticated. Log in once via the SDK window's "
                         + "'Log in' tab.");
                    return;
                }
                ResolveSettingsAndPublish();
            });
        }

        private static void ResolveSettingsAndPublish()
        {
            var modIo = AssetDatabase.LoadAssetAtPath<ModSettings>(_modIoSettingsPath);
            var builder = AssetDatabase.LoadAssetAtPath<ModBuilderSettings>(_settingsPath);
            if (builder == null) { Fail($"No ModBuilderSettings at {_settingsPath}"); return; }
            if (modIo == null)
            {
                modIo = ScriptableObject.CreateInstance<ModSettings>();
                modIo.modSettings = builder;
                AssetDatabase.CreateAsset(modIo, _modIoSettingsPath);
                AssetDatabase.SaveAssets();
            }

            var logo = AssetDatabase.LoadAssetAtPath<Texture2D>(_logoAssetPath);
            var summary = Environment.GetEnvironmentVariable("MOD_SUMMARY") ?? "";
            // mod.io listing title: prefer the human display name ("Item
            // Checklist") over the internal identity name ("ItemChecklist",
            // which drives namespace/asmdef/dependency modName). Fall back to
            // name when no displayName is set.
            var displayName = string.IsNullOrEmpty(builder.metadata.displayName)
                ? builder.metadata.name
                : builder.metadata.displayName;

            if (modIo.modId == 0)
            {
                if (_dryRun)
                {
                    Debug.Log("[CLIPublishHelper] dry run: would create a new "
                              + "mod profile."
                              + (logo == null ? " (no logo asset yet)" : ""));
                    Succeed();
                    return;
                }
                if (logo == null)
                {
                    Fail($"No logo for new profile — add {_logoAssetPath}");
                    return;
                }
                var token = ModIOUnity.GenerateCreationToken();
                var details = new ModProfileDetails
                {
                    name = displayName,
                    summary = summary,
                    logo = logo,
                    visible = false,
                };
                ModIOUnity.CreateModProfile(token, details, created =>
                {
                    if (!created.result.Succeeded())
                    {
                        Fail($"CreateModProfile failed: {created.result.message}");
                        return;
                    }
                    modIo.modId = created.value;
                    EditorUtility.SetDirty(modIo);
                    AssetDatabase.SaveAssets();
                    Debug.Log($"[CLIPublishHelper] Created mod.io profile, "
                              + $"id={modIo.modId}");
                    EnsureTagThenUpload(modIo);
                });
            }
            else
            {
                if (_dryRun)
                {
                    Debug.Log($"[CLIPublishHelper] dry run: would update profile "
                              + $"{modIo.modId} and upload v{_version}.");
                    Succeed();
                    return;
                }
                var details = new ModProfileDetails
                {
                    modId = new ModId(modIo.modId),
                    name = displayName,
                    summary = summary,
                };
                if (logo != null) details.logo = logo;
                ModIOUnity.EditModProfile(details, edited =>
                {
                    if (!edited.Succeeded())
                    {
                        Fail($"EditModProfile failed: {edited.message}");
                        return;
                    }
                    EnsureTagThenUpload(modIo);
                });
            }
        }

        private static void EnsureTagThenUpload(ModSettings modIo)
        {
            // CK_GAME_VERSION is a space-separated list of one or more game
            // versions the mod is compatible with (e.g. "1.2.1.2 1.2.1.4").
            // Each becomes a separate mod.io version tag.
            var gameVersionsRaw = Environment.GetEnvironmentVariable("CK_GAME_VERSION");
            var gameVersions = (gameVersionsRaw ?? string.Empty)
                .Split(new[] { ' ', '\t' }, StringSplitOptions.RemoveEmptyEntries);
            if (gameVersions.Length == 0)
            {
                Fail("CK_GAME_VERSION not set"); return;
            }
            ModIOUnity.AddTags(new ModId(modIo.modId), gameVersions, tagRes =>
            {
                if (!tagRes.Succeeded())
                {
                    Debug.LogWarning($"[CLIPublishHelper] Could not add version "
                        + $"tag(s) '{string.Join(", ", gameVersions)}': {tagRes.message}. "
                        + "Verify the exact tag value(s) on the mod.io website.");
                }
                Upload(modIo);
            });
        }

        private static void Upload(ModSettings modIo)
        {
            var file = new ModfileDetails
            {
                modId = new ModId(modIo.modId),
                directory = _buildDir,
                version = _version,
                changelog = _changelog,
            };
            ModIOUnity.UploadModfile(file, uploaded =>
            {
                if (!uploaded.Succeeded())
                {
                    Fail($"UploadModfile failed: {uploaded.message}");
                    return;
                }
                Debug.Log($"[CLIPublishHelper] Uploaded {_modName} v{_version}. "
                          + "Review and set the profile visible on mod.io.");
                Succeed();
            });
        }

        private static void Succeed()
        {
            Debug.Log("[CLIPublishHelper] Done.");
            EditorApplication.Exit(0);
        }

        private static void Fail(string message)
        {
            Debug.LogError($"[CLIPublishHelper] {message}");
            EditorApplication.Exit(1);
        }
    }
}
#endif
