#if PUG_USE_MODIO
// core_keeper/utils/CLIPublishHelper.cs — shared by every mod via a link.sh
// symlink into <Mod>/Editor/. Mod identity from MOD_NAME (set in the mod's
// .envrc). Builds the mod and drives the mod.io plugin to create/update the
// profile and upload a modfile. mod.io calls are async, so upload.sh omits
// -quit and this class calls EditorApplication.Exit on every path.
using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
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
        private static string _descriptionHtml;
        private static string _buildDir;
        private static ModBuilderSettings _builder;
        private static string _depsMapPath;

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
                _depsMapPath = Environment.GetEnvironmentVariable("MODIO_DEPS_MAP");

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

                // Optional mod.io profile description from modio-description.md
                // (Markdown -> HTML; mod.io's description field is HTML). An
                // absent file leaves the existing mod.io description untouched.
                var descPath = Path.Combine(repoRoot, "modio-description.md");
                _descriptionHtml = File.Exists(descPath)
                    ? MarkdownToHtml(File.ReadAllText(descPath))
                    : "";
                if (string.IsNullOrEmpty(_descriptionHtml))
                    Debug.Log("[CLIPublishHelper] no modio-description.md — "
                              + "leaving the mod.io description unchanged.");

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

        /// <summary>
        /// Minimal Markdown -> HTML for mod.io profile descriptions. Covers the
        /// constructs the mod-family descriptions use: #/##/### headings,
        /// - bullet lists, --- horizontal rules, blank-line paragraphs, and
        /// inline **bold** / *italic* / `code`. Text is HTML-escaped first.
        /// </summary>
        public static string MarkdownToHtml(string md)
        {
            if (string.IsNullOrEmpty(md)) return "";
            var lines = md.Replace("\r\n", "\n").Replace("\r", "\n").Split('\n');
            var sb = new StringBuilder();
            var para = new List<string>();
            bool inList = false;

            void FlushPara()
            {
                if (para.Count == 0) return;
                sb.Append("<p>").Append(Inline(string.Join(" ", para))).Append("</p>\n");
                para.Clear();
            }
            void CloseList()
            {
                if (inList) { sb.Append("</ul>\n"); inList = false; }
            }

            foreach (var raw in lines)
            {
                var t = raw.Trim();
                if (t.Length == 0) { FlushPara(); CloseList(); continue; }
                if (t == "---" || t == "***" || t == "___")
                {
                    FlushPara(); CloseList(); sb.Append("<hr>\n"); continue;
                }
                var h = Regex.Match(t, @"^(#{1,4})\s+(.*)$");
                if (h.Success)
                {
                    FlushPara(); CloseList();
                    int level = h.Groups[1].Value.Length;
                    sb.Append($"<h{level}>").Append(Inline(h.Groups[2].Value))
                      .Append($"</h{level}>\n");
                    continue;
                }
                var li = Regex.Match(t, @"^[-*+]\s+(.*)$");
                if (li.Success)
                {
                    FlushPara();
                    if (!inList) { sb.Append("<ul>\n"); inList = true; }
                    sb.Append("<li>").Append(Inline(li.Groups[1].Value)).Append("</li>\n");
                    continue;
                }
                CloseList();
                para.Add(t);
            }
            FlushPara(); CloseList();
            return sb.ToString().Trim();
        }

        private static string Inline(string text)
        {
            var s = text.Replace("&", "&amp;").Replace("<", "&lt;").Replace(">", "&gt;");
            s = Regex.Replace(s, @"\*\*(.+?)\*\*", "<strong>$1</strong>");
            s = Regex.Replace(s, @"\*(.+?)\*", "<em>$1</em>");
            s = Regex.Replace(s, @"`(.+?)`", "<code>$1</code>");
            return s;
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
            _builder = builder;
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
                    EnsureDependenciesThenTag(modIo);
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
                if (!string.IsNullOrEmpty(_descriptionHtml))
                    details.description = _descriptionHtml;
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
                    EnsureDependenciesThenTag(modIo);
                });
            }
            else
            {
                if (_dryRun)
                {
                    Debug.Log($"[CLIPublishHelper] dry run: would update profile "
                              + $"{modIo.modId} and upload v{_version}.");
                    EnsureDependenciesThenTag(modIo);
                    return;
                }
                var details = new ModProfileDetails
                {
                    modId = new ModId(modIo.modId),
                    name = displayName,
                    summary = summary,
                };
                if (logo != null) details.logo = logo;
                if (!string.IsNullOrEmpty(_descriptionHtml))
                    details.description = _descriptionHtml;
                ModIOUnity.EditModProfile(details, edited =>
                {
                    if (!edited.Succeeded())
                    {
                        Fail($"EditModProfile failed: {edited.message}");
                        return;
                    }
                    EnsureDependenciesThenTag(modIo);
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

        // ---- mod.io dependency sync (from the .asset metadata.dependencies) ----

        // JsonUtility cannot (de)serialise dictionaries, so the cache is a list
        // of {modName, modId} entries rather than a flat {name: id} object.
        [Serializable]
        private class DepMapEntry { public string modName; public long modId; }

        [Serializable]
        private class DepMap { public List<DepMapEntry> entries = new List<DepMapEntry>(); }

        private static DepMap LoadDepMap()
        {
            if (string.IsNullOrEmpty(_depsMapPath) || !File.Exists(_depsMapPath))
                return new DepMap();
            try
            {
                return JsonUtility.FromJson<DepMap>(File.ReadAllText(_depsMapPath))
                       ?? new DepMap();
            }
            catch (Exception e)
            {
                Debug.LogWarning($"[CLIPublishHelper] Could not read deps map "
                    + $"{_depsMapPath}: {e.Message}. Treating as empty.");
                return new DepMap();
            }
        }

        // Persisting a newly-resolved ID is allowed even in dry-run (it is a
        // harmless local-file write that saves the network call on the real run).
        private static void SaveDepMap(DepMap map)
        {
            if (string.IsNullOrEmpty(_depsMapPath))
            {
                Debug.LogWarning("[CLIPublishHelper] MODIO_DEPS_MAP not set — "
                    + "resolved dependency ID not cached.");
                return;
            }
            File.WriteAllText(_depsMapPath, JsonUtility.ToJson(map, prettyPrint: true));
        }

        // Case-insensitive, whitespace-insensitive name comparison key, so the
        // loader identity "CoreLib" matches a mod.io title "Core Lib".
        private static string Normalize(string s) =>
            (s ?? string.Empty).Replace(" ", string.Empty).ToLowerInvariant();

        // Insert spaces before each uppercase letter that follows a lowercase
        // one, mapping our PascalCase loader names to the Title-Case display
        // names used on mod.io. "CoreLib" → "Core Lib", "SimpleCraftingPool­
        // Extender" → "Simple Crafting Pool Extender". Single-word names with
        // no internal capital pass through unchanged.
        private static string SplitCamelCase(string s)
        {
            if (string.IsNullOrEmpty(s)) return s ?? string.Empty;
            var sb = new System.Text.StringBuilder(s.Length + 8);
            for (int i = 0; i < s.Length; i++)
            {
                if (i > 0 && char.IsUpper(s[i]) && char.IsLower(s[i - 1]))
                    sb.Append(' ');
                sb.Append(s[i]);
            }
            return sb.ToString();
        }

        // Returns true if the caller may continue (optional dep skipped); for a
        // required dep it calls Fail() (which exits) and returns false. The
        // .asset 'required' flag is NOT sent to mod.io (the API has no such
        // field) — it is reused here purely as the failure-severity threshold.
        private static bool HandleUnresolved(ModMetadata.Dependency dep, string reason)
        {
            if (dep.required)
            {
                Fail($"Required dependency '{dep.modName}' could not be resolved "
                    + $"to a mod.io id: {reason}. Add it to {_depsMapPath} manually "
                    + "and re-run.");
                return false;
            }
            Debug.LogWarning($"[CLIPublishHelper] Optional dependency "
                + $"'{dep.modName}' could not be resolved: {reason}. Skipping.");
            return true;
        }

        private static void EnsureDependenciesThenTag(ModSettings modIo)
        {
            var deps = _builder.metadata.dependencies;
            if (deps == null || deps.Count == 0)
            {
                // No declared dependencies: still sync, so any stale mod.io
                // dependency gets removed.
                SyncDependencies(modIo, new List<long>());
                return;
            }
            var map = LoadDepMap();
            ResolveNext(modIo, deps, 0, map, new List<long>());
        }

        // Resolution is callback-based per cache miss, so it runs sequentially
        // (resolve one, continue in its callback). On the last index it hands the
        // resolved ID list to SyncDependencies.
        private static void ResolveNext(ModSettings modIo,
            List<ModMetadata.Dependency> deps, int index, DepMap map,
            List<long> resolved)
        {
            if (index >= deps.Count)
            {
                SyncDependencies(modIo, resolved);
                return;
            }
            var dep = deps[index];

            // 1. Cache hit. Case-insensitive so a `.asset`-side casing drift
            // (e.g. "Corelib" vs the cached "CoreLib") still resolves.
            var hit = map.entries.Find(e =>
                string.Equals(e.modName, dep.modName, StringComparison.OrdinalIgnoreCase));
            if (hit != null)
            {
                resolved.Add(hit.modId);
                ResolveNext(modIo, deps, index + 1, map, resolved);
                return;
            }

            // 2. Cache miss: live search (read-only; allowed in dry-run).
            // mod.io rejects a filter without pagination params (error 20201);
            // page size 100 is the API max and the first page suffices for an
            // exact name match.
            //
            // mod.io's `name` field stores the Mod's display name literally
            // ("Simple Crafting Pool Extender"); our `.asset`-dependency
            // carries the Loader identity ("SimpleCraftingPoolExtender",
            // PascalCase). Passing dep.modName verbatim therefore finds
            // nothing for any mod whose display name diverges from the
            // Loader name. CamelCase-split bridges the convention: "CoreLib"
            // stays unchanged (display = "CoreLib"), and
            // "SimpleCraftingPoolExtender" becomes "Simple Crafting Pool
            // Extender" — which matches the mod.io display string. The
            // Normalize() step below still maps candidates and dep.modName
            // back to the same identity for the eventual exact-match.
            var filter = new SearchFilter();
            filter.SetPageIndex(0);
            filter.SetPageSize(100);
            filter.AddSearchPhrase(SplitCamelCase(dep.modName));
            ModIOUnity.GetMods(filter, page =>
            {
                if (!page.result.Succeeded())
                {
                    if (!HandleUnresolved(dep, $"GetMods failed: {page.result.message}"))
                        return;
                    ResolveNext(modIo, deps, index + 1, map, resolved);
                    return;
                }

                var profiles = page.value.modProfiles ?? new ModProfile[0];
                var matches = new List<ModProfile>();
                foreach (var p in profiles)
                    if (Normalize(p.name) == Normalize(dep.modName))
                        matches.Add(p);

                if (matches.Count == 1)
                {
                    long id = matches[0].id;
                    resolved.Add(id);
                    map.entries.Add(new DepMapEntry { modName = dep.modName, modId = id });
                    SaveDepMap(map);
                    Debug.Log($"[CLIPublishHelper] Resolved dependency "
                        + $"'{dep.modName}' -> mod.io id {id} (cached).");
                    ResolveNext(modIo, deps, index + 1, map, resolved);
                    return;
                }

                var candidates = string.Join(", ",
                    Array.ConvertAll(profiles, p => $"{p.id}:{p.name}"));
                var reason = matches.Count == 0
                    ? $"no exact name match among [{candidates}]"
                    : $"ambiguous: {matches.Count} name matches among [{candidates}]";
                if (!HandleUnresolved(dep, reason))
                    return;
                ResolveNext(modIo, deps, index + 1, map, resolved);
            });
        }

        private static void SyncDependencies(ModSettings modIo, List<long> target)
        {
            // A not-yet-created profile (dry-run) has no id to sync against.
            if (_dryRun && modIo.modId == 0)
            {
                Debug.Log("[CLIPublishHelper] dry run: profile not yet created; "
                    + $"would set dependencies [{string.Join(",", target)}] after "
                    + "creation.");
                Succeed();
                return;
            }

            var modId = new ModId(modIo.modId);
            ModIOUnity.GetModDependencies(modId, depRes =>
            {
                var current = new List<long>();
                if (depRes.result.Succeeded() && depRes.value != null)
                {
                    foreach (var d in depRes.value) current.Add(d.modId);
                }
                else if (!depRes.result.Succeeded())
                {
                    Debug.LogWarning("[CLIPublishHelper] GetModDependencies failed: "
                        + $"{depRes.result.message}. Assuming none currently set.");
                }

                var toAdd = target.FindAll(id => !current.Contains(id));
                var toRemove = current.FindAll(id => !target.Contains(id));
                Debug.Log($"[CLIPublishHelper] Dependency sync plan: "
                    + $"+[{string.Join(",", toAdd)}] -[{string.Join(",", toRemove)}]");

                if (_dryRun)
                {
                    Debug.Log("[CLIPublishHelper] dry run: skipping dependency "
                        + "add/remove calls.");
                    Succeed();
                    return;
                }
                ApplyAdds(modIo, modId, toAdd, toRemove);
            });
        }

        private static void ApplyAdds(ModSettings modIo, ModId modId,
            List<long> toAdd, List<long> toRemove)
        {
            if (toAdd.Count == 0)
            {
                ApplyRemoves(modIo, modId, toRemove);
                return;
            }
            var ids = toAdd.ConvertAll(id => new ModId(id));
            ModIOUnity.AddDependenciesToMod(modId, ids, res =>
            {
                if (!res.Succeeded())
                {
                    Fail($"AddDependenciesToMod failed: {res.message}");
                    return;
                }
                Debug.Log($"[CLIPublishHelper] Added dependencies "
                    + $"[{string.Join(",", toAdd)}].");
                ApplyRemoves(modIo, modId, toRemove);
            });
        }

        private static void ApplyRemoves(ModSettings modIo, ModId modId,
            List<long> toRemove)
        {
            if (toRemove.Count == 0)
            {
                EnsureTagThenUpload(modIo);
                return;
            }
            var ids = toRemove.ConvertAll(id => new ModId(id));
            ModIOUnity.RemoveDependenciesFromMod(modId, ids, res =>
            {
                if (!res.Succeeded())
                {
                    Fail($"RemoveDependenciesFromMod failed: {res.message}");
                    return;
                }
                Debug.Log($"[CLIPublishHelper] Removed dependencies "
                    + $"[{string.Join(",", toRemove)}].");
                EnsureTagThenUpload(modIo);
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
