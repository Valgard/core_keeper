#if PUG_USE_MODIO
// core_keeper/utils/CLIPublishHelper.cs — shared by every mod via a link.sh
// symlink into <Mod>/Editor/. Mod identity from MOD_NAME (set in the mod's
// .envrc). Builds the mod and drives the mod.io plugin to create/update the
// profile and upload a modfile. mod.io calls are async, so upload.sh omits
// -quit and this class calls EditorApplication.Exit on every path.
using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Text;
using System.Text.RegularExpressions;
using ModIO;
using PugMod;
using PugMod.ModIO;
using UnityEditor;
using UnityEngine;
using UnityEngine.Networking;

namespace CoreKeeperModUtils
{
    public static class CLIPublishHelper
    {
        private static string _modName;
        private static string _settingsPath;
        private static string _modIoSettingsPath;
        private static string _logoAssetPath;

        private static bool _dryRun;
        private static bool _profileOnly;
        private static bool _changelogOnly;
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
                if (string.IsNullOrEmpty(_modName))
                {
                    Fail("MOD_NAME not set");
                    return;
                }
                _settingsPath = $"Assets/{_modName}.asset";
                _modIoSettingsPath = $"Assets/{_modName}/Editor/{_modName}_modio.asset";
                _logoAssetPath = $"Assets/{_modName}/Editor/logo.png";

                _dryRun = Environment.GetEnvironmentVariable("PUBLISH_DRY_RUN") == "1";
                _profileOnly = Environment.GetEnvironmentVariable("PUBLISH_PROFILE_ONLY") == "1";
                _changelogOnly = Environment.GetEnvironmentVariable("PUBLISH_CHANGELOG_ONLY") == "1";
                if (_profileOnly && _changelogOnly)
                {
                    Fail("--profile-only and --changelog-only are separate modes; pick one.");
                    return;
                }
                _depsMapPath = Environment.GetEnvironmentVariable("MODIO_DEPS_MAP");

                var repoRoot = Environment.GetEnvironmentVariable("MOD_REPO_ROOT");
                if (string.IsNullOrEmpty(repoRoot))
                {
                    Fail("MOD_REPO_ROOT not set");
                    return;
                }

                var changelogPath = Path.Combine(repoRoot, "CHANGELOG.md");
                if (!File.Exists(changelogPath))
                {
                    Fail($"No CHANGELOG.md at {changelogPath}");
                    return;
                }
                if (!TryParseChangelog(File.ReadAllText(changelogPath), out _version, out _changelog))
                {
                    Fail("CHANGELOG.md has no '## [x.y.z]' entry");
                    return;
                }

                // Optional mod.io profile description from modio-description.md
                // (Markdown -> HTML; mod.io's description field is HTML). An
                // absent file leaves the existing mod.io description untouched.
                var descPath = Path.Combine(repoRoot, "modio-description.md");
                _descriptionHtml = File.Exists(descPath) ? MarkdownToHtml(File.ReadAllText(descPath)) : "";
                if (string.IsNullOrEmpty(_descriptionHtml))
                    Debug.Log("[CLIPublishHelper] no modio-description.md — " + "leaving the mod.io description unchanged.");

                Debug.Log($"[CLIPublishHelper] {_modName} v{_version}" + (_dryRun ? " (dry run)" : ""));

                var settings = AssetDatabase.LoadAssetAtPath<ModBuilderSettings>(_settingsPath);
                if (settings == null)
                {
                    Fail($"No ModBuilderSettings at {_settingsPath}");
                    return;
                }

                // Profile-only: refresh everything that is profile METADATA —
                // description, name, summary, logo via EditModProfile, plus the
                // dependency and tag sync — but no build and no modfile upload.
                // Tags belong here because they describe the mod, not the
                // release; that is what lets a published mod's tags be corrected
                // without a pointless version bump. Used to push an edited
                // modio-description.md or retag without cutting a new release.
                if (_profileOnly)
                {
                    Debug.Log(
                        "[CLIPublishHelper] profile-only: skipping the build and "
                            + "the modfile upload; updating the mod.io profile, "
                            + "dependencies and tags only."
                    );
                    OnBuilt();
                    return;
                }

                // Changelog-only: rewrite the CURRENT modfile's changelog text and
                // nothing else. Needed because a changelog belongs to the modfile,
                // not the profile, so --profile-only cannot reach it and a wrong
                // release note would otherwise sit there until the next version.
                if (_changelogOnly)
                {
                    Debug.Log("[CLIPublishHelper] changelog-only: no build, no upload; rewriting the published modfile's changelog.");
                    OnBuilt();
                    return;
                }

                // Regenerate native TextDataBlock loc assets from localization.yaml
                // before the bundle build, mirroring CLIBuildHelper.Build — the
                // publish path must never ship the stale Generated/ assets that
                // happen to be on disk (that shipped 1.3.0 without the Iter-40
                // tracker-tooltip terms). No-op when LOC_YAML/LOC_OUT are unset,
                // and skipped above for --profile-only (no build). See the
                // reference_ck_mod_loc_csv_persistence project memory.
                LocalizationGenerator.GenerateFromEnv();

                _buildDir = Path.Combine(Application.temporaryCachePath, Guid.NewGuid().ToString());
                Directory.CreateDirectory(_buildDir);

                ModBuilder.BuildMod(
                    settings,
                    _buildDir,
                    buildOk =>
                    {
                        if (!buildOk)
                        {
                            Fail("Build failed");
                            return;
                        }
                        OnBuilt();
                    },
                    installInSubDirectory: false
                );
            }
            catch (Exception e)
            {
                Fail($"Exception: {e}");
            }
        }

        /// <summary>
        /// Extracts the topmost "## [x.y.z]" entry of a Keep-a-Changelog file:
        /// its version and the body text up to the next "## " header.
        /// </summary>
        public static bool TryParseChangelog(string content, out string version, out string changelog)
        {
            version = null;
            changelog = null;
            var header = Regex.Match(content, @"^##\s*\[(\d+\.\d+\.\d+)\].*$", RegexOptions.Multiline);
            if (!header.Success)
                return false;
            version = header.Groups[1].Value;

            int bodyStart = header.Index + header.Length;
            var next = Regex.Match(content.Substring(bodyStart), @"^##\s", RegexOptions.Multiline);
            changelog = (next.Success ? content.Substring(bodyStart, next.Index) : content.Substring(bodyStart)).Trim();
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
            if (string.IsNullOrEmpty(md))
                return "";
            var lines = md.Replace("\r\n", "\n").Replace("\r", "\n").Split('\n');
            var sb = new StringBuilder();
            var para = new List<string>();
            var item = new List<string>();
            bool inList = false;

            void FlushItem()
            {
                if (item.Count == 0)
                    return;
                sb.Append("<li>").Append(Inline(string.Join(" ", item))).Append("</li>\n");
                item.Clear();
            }
            void FlushPara()
            {
                if (para.Count == 0)
                    return;
                sb.Append("<p>").Append(Inline(string.Join(" ", para))).Append("</p>\n");
                para.Clear();
            }
            void CloseList()
            {
                FlushItem();
                if (inList)
                {
                    sb.Append("</ul>\n");
                    inList = false;
                }
            }

            foreach (var raw in lines)
            {
                var t = raw.Trim();
                if (t.Length == 0)
                {
                    FlushPara();
                    CloseList();
                    continue;
                }
                if (t == "---" || t == "***" || t == "___")
                {
                    FlushPara();
                    CloseList();
                    sb.Append("<hr>\n");
                    continue;
                }
                var h = Regex.Match(t, @"^(#{1,4})\s+(.*)$");
                if (h.Success)
                {
                    FlushPara();
                    CloseList();
                    // mod.io's description renderer drops <h1> (only h2+ render),
                    // so shift every heading down one level: '# Title' -> <h2>,
                    // '## Section' -> <h3>, ... (capped at <h6>). The source
                    // modio-description.md keeps its clean '# H1' house format.
                    int level = Math.Min(h.Groups[1].Value.Length + 1, 6);
                    sb.Append($"<h{level}>").Append(Inline(h.Groups[2].Value)).Append($"</h{level}>\n");
                    continue;
                }
                var li = Regex.Match(t, @"^[-*+]\s+(.*)$");
                if (li.Success)
                {
                    FlushPara();
                    FlushItem();
                    if (!inList)
                    {
                        sb.Append("<ul>\n");
                        inList = true;
                    }
                    item.Add(li.Groups[1].Value);
                    continue;
                }
                // Lazy continuation: a non-empty, marker-less line belongs to the
                // open block (its list item, or otherwise the current paragraph).
                // The mod-family descriptions soft-wrap long list items and
                // paragraphs purely to keep source lines short; without this they
                // would split the <li> and prematurely close the <ul>.
                if (inList)
                {
                    item.Add(t);
                    continue;
                }
                para.Add(t);
            }
            FlushPara();
            CloseList();
            return sb.ToString().Trim();
        }

        private static string Inline(string text)
        {
            var s = text.Replace("&", "&amp;").Replace("<", "&lt;").Replace(">", "&gt;");

            // Images before links: the link pattern would otherwise swallow the
            // "[alt](url)" half of an image and leave a stray "!" in front of it.
            // Both run before the emphasis rules so a URL containing '*' cannot be
            // mangled into <em> on its way into the attribute.
            //
            // These two are why raw HTML is not an option in modio-description.md:
            // the escaping above turns a hand-written <img> into &lt;img&gt;, which
            // mod.io then shows as literal text. Markdown is the only route in.
            s = Regex.Replace(s, @"!\[([^\]]*)\]\(([^)\s]+)\)", "<img src=\"$2\" alt=\"$1\">");
            s = Regex.Replace(s, @"\[([^\]]+)\]\(([^)\s]+)\)", "<a href=\"$2\">$1</a>");

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
                if (!init.Succeeded())
                {
                    Fail("mod.io init failed");
                    return;
                }
            }
            ModIOUnity.IsAuthenticated(auth =>
            {
                if (!auth.Succeeded())
                {
                    Fail("Not authenticated. Log in once via the SDK window's " + "'Log in' tab.");
                    return;
                }
                ResolveSettingsAndPublish();
            });
        }

        private static void ResolveSettingsAndPublish()
        {
            var modIo = AssetDatabase.LoadAssetAtPath<ModSettings>(_modIoSettingsPath);
            var builder = AssetDatabase.LoadAssetAtPath<ModBuilderSettings>(_settingsPath);
            if (builder == null)
            {
                Fail($"No ModBuilderSettings at {_settingsPath}");
                return;
            }
            _builder = builder;
            if (modIo == null)
            {
                modIo = ScriptableObject.CreateInstance<ModSettings>();
                modIo.modSettings = builder;
                AssetDatabase.CreateAsset(modIo, _modIoSettingsPath);
                AssetDatabase.SaveAssets();
            }

            if (_changelogOnly)
            {
                UpdateChangelogOnly(modIo);
                return;
            }

            var logo = AssetDatabase.LoadAssetAtPath<Texture2D>(_logoAssetPath);
            var summary = Environment.GetEnvironmentVariable("MOD_SUMMARY") ?? "";
            // mod.io listing title: prefer the human display name ("Item
            // Checklist") over the internal identity name ("ItemChecklist",
            // which drives namespace/asmdef/dependency modName). Fall back to
            // name when no displayName is set.
            var displayName = string.IsNullOrEmpty(builder.metadata.displayName) ? builder.metadata.name : builder.metadata.displayName;

            if (modIo.modId == 0)
            {
                if (_profileOnly)
                {
                    Fail("profile-only needs an existing published mod, but " + $"{_modName} has no modId yet. Run a normal publish " + "first.");
                    return;
                }
                if (_dryRun)
                {
                    Debug.Log("[CLIPublishHelper] dry run: would create a new " + "mod profile." + (logo == null ? " (no logo asset yet)" : ""));
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
                ModIOUnity.CreateModProfile(
                    token,
                    details,
                    created =>
                    {
                        if (!created.result.Succeeded())
                        {
                            Fail($"CreateModProfile failed: {created.result.message}");
                            return;
                        }
                        modIo.modId = created.value;
                        EditorUtility.SetDirty(modIo);
                        AssetDatabase.SaveAssets();
                        Debug.Log($"[CLIPublishHelper] Created mod.io profile, " + $"id={modIo.modId}");
                        EnsureDependenciesThenTag(modIo);
                    }
                );
            }
            else
            {
                if (_dryRun)
                {
                    if (_profileOnly)
                    {
                        Debug.Log(
                            "[CLIPublishHelper] dry run (profile-only): " + $"would update the description of profile " + $"{modIo.modId}; no modfile upload."
                        );
                        EnsureDependenciesThenTag(modIo);
                    }
                    else
                    {
                        Debug.Log("[CLIPublishHelper] dry run: would update " + $"profile {modIo.modId} and upload v{_version}.");
                        EnsureDependenciesThenTag(modIo);
                    }
                    return;
                }
                var details = new ModProfileDetails
                {
                    modId = new ModId(modIo.modId),
                    name = displayName,
                    summary = summary,
                };
                if (logo != null)
                    details.logo = logo;
                if (!string.IsNullOrEmpty(_descriptionHtml))
                    details.description = _descriptionHtml;
                ModIOUnity.EditModProfile(
                    details,
                    edited =>
                    {
                        if (!edited.Succeeded())
                        {
                            Fail($"EditModProfile failed: {edited.message}");
                            return;
                        }
                        if (_profileOnly)
                        {
                            Debug.Log(
                                "[CLIPublishHelper] profile-only: updated the "
                                    + $"description of {_modName} (modId "
                                    + $"{modIo.modId}). Syncing dependencies and tags next; no modfile upload."
                            );
                            EnsureDependenciesThenTag(modIo);
                            return;
                        }
                        EnsureDependenciesThenTag(modIo);
                    }
                );
            }
        }

        // ---- mod.io tag sync (four groups) ----

        // The four Core Keeper tag groups this pipeline owns. Every tag on the
        // mod that belongs to one of them is *synchronised* — surplus removed,
        // missing added — while a tag from any other group (or from no group
        // mod.io knows about) is left completely alone.
        private const string TagGroupGameVersion = "Game Version";
        private const string TagGroupType = "Type";
        private const string TagGroupApplicationType = "Application Type";
        private const string TagGroupAccessType = "Access Type";

        // One synchronised group: the values we want on the mod, plus the diff
        // against what mod.io currently has (filled in by SyncTags).
        private class TagGroupPlan
        {
            public string group;
            public List<string> desired;
            public readonly List<string> toAdd = new List<string>();
            public readonly List<string> toRemove = new List<string>();
        }

        private static void EnsureTagThenUpload(ModSettings modIo)
        {
            // Four mod.io tag groups are synchronised rather than merely added
            // to. Two are configured through the environment, two are derived
            // from the ModBuilderSettings metadata so they can never drift from
            // what the mod actually is:
            //
            //   Game Version      CK_GAME_VERSION — space-separated list of the
            //                     game versions the mod is compatible with
            //                     (e.g. "1.2.1.5 1.2.1.4"); one tag each.
            //   Type              CK_MODIO_TYPE — PIPE-separated, because the
            //                     values contain spaces ("Visual|Quality of Life").
            //   Application Type  metadata.requiredOn ([Flags]: Client=1,
            //                     Server=2; 0 is valid and means no tag).
            //   Access Type       metadata.skipSafetyChecks (false -> "Script",
            //                     true -> "Script (Elevated Access)"). "Asset" is
            //                     never produced here — these are script mods, so
            //                     a hand-set "Asset" tag is surplus and removed.
            var gameVersionsRaw = Environment.GetEnvironmentVariable("CK_GAME_VERSION");
            var gameVersions = new List<string>((gameVersionsRaw ?? string.Empty).Split(new[] { ' ', '\t' }, StringSplitOptions.RemoveEmptyEntries));
            if (gameVersions.Count == 0)
            {
                Fail("CK_GAME_VERSION not set");
                return;
            }

            // CK_GAME_VERSION says what the mod runs on. mod.io's Game Version
            // vocabulary is a *subset* of the builds that shipped, and the guard
            // further down rightly refuses a value the live taxonomy does not
            // know. Naming the untagged builds in CK_MODIO_VERSION_UNLISTED (the
            // parent .envrc.example carries the list and the reasoning) drops
            // them here, so CK_GAME_VERSION stays honest for everything that
            // reads it — utils/discord_post.py renders the Discord post from it.
            //
            // This does soften the guard for exactly what it names, which is why
            // utils/tests/test_discord_post_content.py checks every entry
            // against utils/ck-game-versions.json: a build that never shipped is
            // a typo, and a typo parked here would disable the guard forever,
            // since the staleness check below only fires for entries mod.io
            // later offers.
            //
            // Note the taxonomy spells some builds with three segments (1.1.2,
            // 0.7.4) where this repo writes four, and the comparison below is
            // exact-string — extending CK_GAME_VERSION back past 1.1.2 will hit
            // that before it hits anything else.
            var unlistedRaw = Environment.GetEnvironmentVariable("CK_MODIO_VERSION_UNLISTED");
            var unlisted = new HashSet<string>((unlistedRaw ?? string.Empty).Split(new[] { ' ', '\t' }, StringSplitOptions.RemoveEmptyEntries));
            gameVersions.RemoveAll(v => unlisted.Contains(v));
            if (gameVersions.Count == 0)
            {
                Fail($"CK_MODIO_VERSION_UNLISTED removed every value of CK_GAME_VERSION ('{gameVersionsRaw}') — nothing left to tag.");
                return;
            }

            var types = new List<string>();
            foreach (var raw in (Environment.GetEnvironmentVariable("CK_MODIO_TYPE") ?? string.Empty).Split('|'))
            {
                var value = raw.Trim();
                if (value.Length > 0)
                    types.Add(value);
            }
            if (types.Count == 0)
            {
                Fail("CK_MODIO_TYPE not set — pipe-separated mod.io 'Type' tags, " + "e.g. CK_MODIO_TYPE=\"Visual|Quality of Life\"");
                return;
            }

            var appTypes = new List<string>();
            var requiredOn = _builder.metadata.requiredOn;
            if ((requiredOn & ModMetadata.ModExistsOn.Client) != 0)
                appTypes.Add("Client");
            if ((requiredOn & ModMetadata.ModExistsOn.Server) != 0)
                appTypes.Add("Server");
            // An empty set is legitimate rather than an error: a mod neither
            // side is required to have — a pure client-side diagnostic, say —
            // carries no Application Type, and mod.io models the group as a
            // checkbox set, where none ticked is a valid state. Publishing it
            // therefore *removes* any Application Type tag the mod still has.
            //
            // It still earns a line, because 0 is equally what an unset field
            // reads as: ModExistsOn.None and "forgot to fill it in" are the
            // same value, and only the author can tell them apart.
            if (appTypes.Count == 0)
                Debug.LogWarning(
                    $"[CLIPublishHelper] metadata.requiredOn is {requiredOn} in {_settingsPath} — publishing with no "
                        + "'Application Type' tag, and removing any it currently has. Set 1 (Client), 2 (Server) or "
                        + "3 (ClientAndServer) if that was not intended."
                );

            var accessTypes = new List<string> { _builder.metadata.skipSafetyChecks ? "Script (Elevated Access)" : "Script" };

            var plans = new List<TagGroupPlan>
            {
                new TagGroupPlan { group = TagGroupGameVersion, desired = gameVersions },
                new TagGroupPlan { group = TagGroupType, desired = types },
                new TagGroupPlan { group = TagGroupApplicationType, desired = appTypes },
                new TagGroupPlan { group = TagGroupAccessType, desired = accessTypes },
            };
            SyncTags(modIo, plans, unlisted);
        }

        private static void SyncTags(ModSettings modIo, List<TagGroupPlan> plans, HashSet<string> unlisted)
        {
            var modId = new ModId(modIo.modId);
            ModIOUnity.GetTagCategories(catRes =>
            {
                if (!catRes.result.Succeeded() || catRes.value == null)
                {
                    FallBackToAdditiveTags(modIo, plans, $"GetTagCategories failed: {catRes.result.message}");
                    return;
                }

                // Group membership comes from the live taxonomy, never from a
                // hardcoded value list — the game keeps adding Game Version
                // values, and a stale list would leave them stranded on the mod.
                var groupValues = new Dictionary<string, List<string>>(StringComparer.Ordinal);
                foreach (var category in catRes.value)
                {
                    var values = new List<string>();
                    foreach (var tag in category.tags ?? new Tag[0])
                        values.Add(tag.name);
                    groupValues[category.name ?? string.Empty] = values;
                }

                // A group missing from the live taxonomy means we cannot tell
                // which of the mod's tags belong to it, so removing anything
                // would be guesswork — degrade to additive instead.
                foreach (var plan in plans)
                {
                    if (!groupValues.ContainsKey(plan.group))
                    {
                        FallBackToAdditiveTags(modIo, plans, $"mod.io reports no '{plan.group}' tag group " + $"(got [{string.Join(", ", groupValues.Keys)}])");
                        return;
                    }
                }

                // An entry in CK_MODIO_VERSION_UNLISTED that mod.io meanwhile
                // offers is worse than a stale comment: the publish keeps
                // excluding a tag it could now set, so the listing quietly
                // advertises one version fewer than it supports.
                //
                // Deliberately checked across the whole list, not just the
                // entries that filtered something here: it lives in the shared
                // parent .envrc, so the first mod published after mod.io
                // backfills a tag is the one that reports it, whichever mod that
                // is. The fix is deleting a word — but the abort lands after the
                // build and after EditModProfile has run, so --dry-run (which
                // reaches this check) is the cheap way to find out.
                var nowListed = new List<string>();
                foreach (var value in unlisted)
                {
                    if (groupValues[TagGroupGameVersion].Contains(value))
                        nowListed.Add(value);
                }
                if (nowListed.Count > 0)
                {
                    Fail($"mod.io now offers [{string.Join(", ", nowListed)}] as '{TagGroupGameVersion}' tags — remove them from CK_MODIO_VERSION_UNLISTED.");
                    return;
                }

                // Validate BEFORE changing anything: mod.io accepts an unknown
                // tag value and silently drops it, so a typo like "Quality of
                // live" would otherwise just vanish without a trace.
                foreach (var plan in plans)
                {
                    var valid = groupValues[plan.group];
                    foreach (var value in plan.desired)
                    {
                        if (!valid.Contains(value))
                        {
                            Fail($"'{value}' is not a valid mod.io '{plan.group}' tag. " + $"Valid values: [{string.Join(", ", valid)}].");
                            return;
                        }
                    }
                }

                ModIOUnity.GetMod(
                    modId,
                    modRes =>
                    {
                        if (!modRes.result.Succeeded())
                        {
                            FallBackToAdditiveTags(modIo, plans, $"GetMod failed: {modRes.result.message}");
                            return;
                        }

                        // ModProfile.tags is a flat string[] of raw tag names
                        // across every group (the plugin's ResponseTranslator
                        // maps ModTagObject.name straight through), which is why
                        // the groupValues lookup above is needed to tell them
                        // apart. Nothing earlier in this run mutates tags, so a
                        // ResponseCache hit here is still accurate.
                        var current = new List<string>(modRes.value.tags ?? new string[0]);
                        foreach (var plan in plans)
                        {
                            var valid = groupValues[plan.group];
                            foreach (var value in plan.desired)
                                if (!current.Contains(value))
                                    plan.toAdd.Add(value);
                            foreach (var value in current)
                                if (valid.Contains(value) && !plan.desired.Contains(value))
                                    plan.toRemove.Add(value);
                        }
                        LogTagPlan(plans);

                        if (_dryRun)
                        {
                            Debug.Log("[CLIPublishHelper] dry run: skipping tag " + "add/remove calls.");
                            Succeed();
                            return;
                        }
                        ApplyTagAdds(modIo, modId, plans);
                    }
                );
            });
        }

        // Could not establish what the mod currently carries: add the desired
        // tags and remove nothing, so a read failure can never be mistaken for
        // "the mod has no tags" and wipe the lot.
        private static void FallBackToAdditiveTags(ModSettings modIo, List<TagGroupPlan> plans, string reason)
        {
            Debug.LogWarning($"[CLIPublishHelper] {reason}. Falling back to additive " + "tagging: adding the configured tags, removing nothing.");
            foreach (var plan in plans)
            {
                plan.toAdd.Clear();
                plan.toAdd.AddRange(plan.desired);
                plan.toRemove.Clear();
            }
            LogTagPlan(plans);

            if (_dryRun)
            {
                Debug.Log("[CLIPublishHelper] dry run: skipping tag add/remove calls.");
                Succeed();
                return;
            }
            ApplyTagAdds(modIo, new ModId(modIo.modId), plans);
        }

        private static void LogTagPlan(List<TagGroupPlan> plans)
        {
            foreach (var plan in plans)
                Debug.Log($"[CLIPublishHelper] Tag sync plan [{plan.group}]: " + $"+[{string.Join(",", plan.toAdd)}] -[{string.Join(",", plan.toRemove)}]");
        }

        // Adds and removes are two separate mod.io calls, so they run in
        // sequence: every group's adds in one call, then every group's removes,
        // then the modfile upload. A tag call that fails only warns — a tagging
        // hiccup must not abort an otherwise good release (existing behaviour).
        private static void ApplyTagAdds(ModSettings modIo, ModId modId, List<TagGroupPlan> plans)
        {
            var toAdd = new List<string>();
            foreach (var plan in plans)
                toAdd.AddRange(plan.toAdd);
            if (toAdd.Count == 0)
            {
                ApplyTagRemoves(modIo, modId, plans);
                return;
            }
            ModIOUnity.AddTags(
                modId,
                toAdd.ToArray(),
                res =>
                {
                    if (!res.Succeeded())
                    {
                        Debug.LogWarning(
                            $"[CLIPublishHelper] Could not add tag(s) "
                                + $"'{string.Join(", ", toAdd)}': {res.message}. "
                                + "Verify the exact tag value(s) on the mod.io website."
                        );
                    }
                    else
                    {
                        Debug.Log($"[CLIPublishHelper] Added tags " + $"[{string.Join(",", toAdd)}].");
                    }
                    ApplyTagRemoves(modIo, modId, plans);
                }
            );
        }

        private static void ApplyTagRemoves(ModSettings modIo, ModId modId, List<TagGroupPlan> plans)
        {
            var toRemove = new List<string>();
            foreach (var plan in plans)
                toRemove.AddRange(plan.toRemove);
            if (toRemove.Count == 0)
            {
                FinishAfterTags(modIo);
                return;
            }
            ModIOUnity.DeleteTags(
                modId,
                toRemove.ToArray(),
                res =>
                {
                    if (!res.Succeeded())
                        Debug.LogWarning($"[CLIPublishHelper] Could not remove tag(s) " + $"'{string.Join(", ", toRemove)}': {res.message}.");
                    else
                        Debug.Log($"[CLIPublishHelper] Removed tags " + $"[{string.Join(",", toRemove)}].");
                    FinishAfterTags(modIo);
                }
            );
        }

        /// <summary>
        /// The single point where the dependency+tag chain decides how to end. Tags are profile
        /// metadata, not release content, so --profile-only syncs them and then stops here instead
        /// of uploading a modfile — that is what lets an already-published mod's tags be corrected
        /// without a pointless version bump.
        /// </summary>
        private static void FinishAfterTags(ModSettings modIo)
        {
            if (_profileOnly)
            {
                Debug.Log("[CLIPublishHelper] profile-only: dependencies and tags synced. " + "No modfile uploaded.");
                Succeed();
                return;
            }
            Upload(modIo);
        }

        // ---- changelog-only: correct a published release's notes in place ----

        // A changelog belongs to the modfile, not to the mod profile, so
        // --profile-only cannot touch it. The plugin cannot either: its API offers
        // UploadModfile (which creates a NEW modfile, i.e. a new release) and no
        // way to edit an existing one. mod.io's REST layer does — PUT on the file
        // resource — so this is the only path in this class that calls the API
        // directly instead of going through ModIOUnity.
        //
        // Reflection for the OAuth token is fine here and nowhere else in this
        // project: this is Unity editor code, outside the Roslyn sandbox that
        // forbids it in a mod's runtime sources.
        [Serializable]
        private class ModfileBrief
        {
            public long id;
            public string version;
            public string changelog;
        }

        [Serializable]
        private class ModBrief
        {
            public ModfileBrief modfile;
        }

        private static void UpdateChangelogOnly(ModSettings modIo)
        {
            if (modIo.modId == 0)
            {
                Fail($"changelog-only needs a published mod, but {_modName} has no modId yet. Run a normal publish first.");
                return;
            }

            var server = ModIO.Implementation.Settings.server;
            if (string.IsNullOrEmpty(server.serverURL) || string.IsNullOrEmpty(server.gameKey))
            {
                Fail("mod.io server settings are empty — cannot resolve the API endpoint.");
                return;
            }

            var modUrl = $"{server.serverURL}/games/{server.gameId}/mods/{modIo.modId}";
            var probe = UnityWebRequest.Get($"{modUrl}?api_key={server.gameKey}");
            probe.SendWebRequest().completed += _ =>
            {
                try
                {
                    if (probe.result != UnityWebRequest.Result.Success)
                    {
                        Fail($"could not read the published mod ({probe.responseCode}): {probe.error}");
                        return;
                    }
                    var live = JsonUtility.FromJson<ModBrief>(probe.downloadHandler.text)?.modfile;
                    if (live == null || live.id == 0)
                    {
                        Fail("the published mod has no active modfile — nothing to correct.");
                        return;
                    }

                    // The guard that makes this safe to automate: CHANGELOG.md's
                    // topmost entry describes ONE release. If the live modfile is a
                    // different version, writing this text would put the wrong
                    // notes on an older release — the opposite of the fix.
                    if (live.version != _version)
                    {
                        Fail(
                            $"CHANGELOG.md's topmost entry is {_version} but the published modfile is {live.version}. "
                                + "Refusing to write: this mode corrects the notes OF the published release, it does not publish a new one."
                        );
                        return;
                    }

                    if ((live.changelog ?? "") == _changelog)
                    {
                        Debug.Log($"[CLIPublishHelper] changelog for {live.version} already matches CHANGELOG.md — nothing to do.");
                        Succeed();
                        return;
                    }

                    var token = ReadOAuthToken();
                    if (_dryRun)
                    {
                        Debug.Log(
                            $"[CLIPublishHelper] dry run: would PUT {modUrl}/files/{live.id} "
                                + $"(version {live.version}), replacing {(live.changelog ?? "").Length} chars of changelog with {_changelog.Length}. "
                                + $"OAuth token from the plugin: {(string.IsNullOrEmpty(token) ? "MISSING — the real run would fail" : "present")}."
                        );
                        Succeed();
                        return;
                    }
                    if (string.IsNullOrEmpty(token))
                    {
                        Fail("no OAuth token in the mod.io plugin's user data — log in once via the SDK window's 'Log in' tab.");
                        return;
                    }

                    var put = UnityWebRequest.Put($"{modUrl}/files/{live.id}", "changelog=" + UnityWebRequest.EscapeURL(_changelog));
                    put.SetRequestHeader("Content-Type", "application/x-www-form-urlencoded");
                    put.SetRequestHeader("Authorization", "Bearer " + token);
                    put.SetRequestHeader("Accept", "application/json");
                    put.SendWebRequest().completed += __ =>
                    {
                        if (put.result != UnityWebRequest.Result.Success)
                        {
                            // Print the body: mod.io explains a rejected field there,
                            // and this endpoint's editable-field list is the one thing
                            // this mode cannot verify without trying.
                            Fail($"PUT failed ({put.responseCode}): {put.error} — {put.downloadHandler?.text}");
                            return;
                        }
                        Debug.Log(
                            $"[CLIPublishHelper] changelog of {_modName} {live.version} (modfile {live.id}) rewritten. No new modfile, no version change."
                        );
                        Succeed();
                    };
                }
                catch (Exception e)
                {
                    Fail($"changelog-only failed: {e.Message}");
                }
            };
        }

        /// <summary>
        /// The plugin's live OAuth token, or null. <c>ModIO.Implementation.UserData</c>
        /// is internal, so reflection is the only route; the assembly is found by
        /// scanning rather than by name so a plugin rename cannot silently break it.
        /// The token is never logged or written to disk.
        /// </summary>
        private static string ReadOAuthToken()
        {
            foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
            {
                var type = asm.GetType("ModIO.Implementation.UserData");
                if (type == null)
                    continue;
                var instance = type.GetField("instance", BindingFlags.Public | BindingFlags.Static)?.GetValue(null);
                if (instance == null)
                    return null;
                return type.GetField("oAuthToken", BindingFlags.Public | BindingFlags.Instance)?.GetValue(instance) as string;
            }
            return null;
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
            ModIOUnity.UploadModfile(
                file,
                uploaded =>
                {
                    if (!uploaded.Succeeded())
                    {
                        Fail($"UploadModfile failed: {uploaded.message}");
                        return;
                    }
                    Debug.Log($"[CLIPublishHelper] Uploaded {_modName} v{_version}. " + "Review and set the profile visible on mod.io.");
                    Succeed();
                }
            );
        }

        // ---- mod.io dependency sync (from the .asset metadata.dependencies) ----

        // JsonUtility cannot (de)serialise dictionaries, so the cache is a list
        // of {modName, modId} entries rather than a flat {name: id} object.
        [Serializable]
        private class DepMapEntry
        {
            public string modName;
            public long modId;
        }

        [Serializable]
        private class DepMap
        {
            public List<DepMapEntry> entries = new List<DepMapEntry>();
        }

        private static DepMap LoadDepMap()
        {
            if (string.IsNullOrEmpty(_depsMapPath) || !File.Exists(_depsMapPath))
                return new DepMap();
            try
            {
                return JsonUtility.FromJson<DepMap>(File.ReadAllText(_depsMapPath)) ?? new DepMap();
            }
            catch (Exception e)
            {
                Debug.LogWarning($"[CLIPublishHelper] Could not read deps map " + $"{_depsMapPath}: {e.Message}. Treating as empty.");
                return new DepMap();
            }
        }

        // Persisting a newly-resolved ID is allowed even in dry-run (it is a
        // harmless local-file write that saves the network call on the real run).
        private static void SaveDepMap(DepMap map)
        {
            if (string.IsNullOrEmpty(_depsMapPath))
            {
                Debug.LogWarning("[CLIPublishHelper] MODIO_DEPS_MAP not set — " + "resolved dependency ID not cached.");
                return;
            }
            File.WriteAllText(_depsMapPath, JsonUtility.ToJson(map, prettyPrint: true));
        }

        // Case-insensitive, whitespace-insensitive name comparison key, so the
        // loader identity "CoreLib" matches a mod.io title "Core Lib".
        private static string Normalize(string s) => (s ?? string.Empty).Replace(" ", string.Empty).ToLowerInvariant();

        // Insert spaces before each uppercase letter that follows a lowercase
        // one, mapping our PascalCase loader names to the Title-Case display
        // names used on mod.io. "CoreLib" → "Core Lib", "SimpleCraftingPool­
        // Extender" → "Simple Crafting Pool Extender". Single-word names with
        // no internal capital pass through unchanged.
        private static string SplitCamelCase(string s)
        {
            if (string.IsNullOrEmpty(s))
                return s ?? string.Empty;
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
                Fail(
                    $"Required dependency '{dep.modName}' could not be resolved "
                        + $"to a mod.io id: {reason}. Add it to {_depsMapPath} manually "
                        + "and re-run."
                );
                return false;
            }
            Debug.LogWarning($"[CLIPublishHelper] Optional dependency " + $"'{dep.modName}' could not be resolved: {reason}. Skipping.");
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
        private static void ResolveNext(ModSettings modIo, List<ModMetadata.Dependency> deps, int index, DepMap map, List<long> resolved)
        {
            if (index >= deps.Count)
            {
                SyncDependencies(modIo, resolved);
                return;
            }
            var dep = deps[index];

            // 1. Cache hit. Case-insensitive so a `.asset`-side casing drift
            // (e.g. "Corelib" vs the cached "CoreLib") still resolves.
            var hit = map.entries.Find(e => string.Equals(e.modName, dep.modName, StringComparison.OrdinalIgnoreCase));
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
            ModIOUnity.GetMods(
                filter,
                page =>
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
                        Debug.Log($"[CLIPublishHelper] Resolved dependency " + $"'{dep.modName}' -> mod.io id {id} (cached).");
                        ResolveNext(modIo, deps, index + 1, map, resolved);
                        return;
                    }

                    var candidates = string.Join(", ", Array.ConvertAll(profiles, p => $"{p.id}:{p.name}"));
                    var reason =
                        matches.Count == 0 ? $"no exact name match among [{candidates}]" : $"ambiguous: {matches.Count} name matches among [{candidates}]";
                    if (!HandleUnresolved(dep, reason))
                        return;
                    ResolveNext(modIo, deps, index + 1, map, resolved);
                }
            );
        }

        private static void SyncDependencies(ModSettings modIo, List<long> target)
        {
            // A not-yet-created profile (dry-run) has no id to sync against.
            if (_dryRun && modIo.modId == 0)
            {
                Debug.Log(
                    "[CLIPublishHelper] dry run: profile not yet created; " + $"would set dependencies [{string.Join(",", target)}] after " + "creation."
                );
                Succeed();
                return;
            }

            var modId = new ModId(modIo.modId);
            ModIOUnity.GetModDependencies(
                modId,
                depRes =>
                {
                    var current = new List<long>();
                    if (depRes.result.Succeeded() && depRes.value != null)
                    {
                        foreach (var d in depRes.value)
                            current.Add(d.modId);
                    }
                    else if (!depRes.result.Succeeded())
                    {
                        Debug.LogWarning("[CLIPublishHelper] GetModDependencies failed: " + $"{depRes.result.message}. Assuming none currently set.");
                    }

                    var toAdd = target.FindAll(id => !current.Contains(id));
                    var toRemove = current.FindAll(id => !target.Contains(id));
                    Debug.Log($"[CLIPublishHelper] Dependency sync plan: " + $"+[{string.Join(",", toAdd)}] -[{string.Join(",", toRemove)}]");

                    if (_dryRun)
                    {
                        // Skip the writes but carry on into the tag sync, so a
                        // dry run prints the full plan (dependencies *and*
                        // tags); its own _dryRun branch ends the run there.
                        Debug.Log("[CLIPublishHelper] dry run: skipping dependency " + "add/remove calls.");
                        EnsureTagThenUpload(modIo);
                        return;
                    }
                    ApplyAdds(modIo, modId, toAdd, toRemove);
                }
            );
        }

        private static void ApplyAdds(ModSettings modIo, ModId modId, List<long> toAdd, List<long> toRemove)
        {
            if (toAdd.Count == 0)
            {
                ApplyRemoves(modIo, modId, toRemove);
                return;
            }
            var ids = toAdd.ConvertAll(id => new ModId(id));
            ModIOUnity.AddDependenciesToMod(
                modId,
                ids,
                res =>
                {
                    if (!res.Succeeded())
                    {
                        Fail($"AddDependenciesToMod failed: {res.message}");
                        return;
                    }
                    Debug.Log($"[CLIPublishHelper] Added dependencies " + $"[{string.Join(",", toAdd)}].");
                    ApplyRemoves(modIo, modId, toRemove);
                }
            );
        }

        private static void ApplyRemoves(ModSettings modIo, ModId modId, List<long> toRemove)
        {
            if (toRemove.Count == 0)
            {
                EnsureTagThenUpload(modIo);
                return;
            }
            var ids = toRemove.ConvertAll(id => new ModId(id));
            ModIOUnity.RemoveDependenciesFromMod(
                modId,
                ids,
                res =>
                {
                    if (!res.Succeeded())
                    {
                        Fail($"RemoveDependenciesFromMod failed: {res.message}");
                        return;
                    }
                    Debug.Log($"[CLIPublishHelper] Removed dependencies " + $"[{string.Join(",", toRemove)}].");
                    EnsureTagThenUpload(modIo);
                }
            );
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
