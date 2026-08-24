// core_keeper/utils/LocalizationGenerator.cs — shared by every mod via a
// link.sh symlink into <Mod>/Editor/. Editor-only (unsandboxed → System.IO OK).
//
// Option II: parse a readable localization.yaml + the committed
// ck-language-addresses.json table, and TEMPLATE native Core Keeper
// TextDataBlock .asset files directly. Runs in batchmode (the real CK-SDK
// localisation API is unusable at build time — LanguageDataBlocks are
// runtime-only; verified Phase-0a). Asset structure mirrors Item Browser's
// committed TextDataBlocks (the golden reference).
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using UnityEditor;
using UnityEngine;

namespace CoreKeeperModUtils
{
    public static class LocalizationGenerator
    {
        // TextDataBlock MonoBehaviour ref. fileID is the portable class-name hash;
        // the guid is the ScriptableData.dll .meta guid, which is PER-SDK-CLONE-LOCAL
        // — resolved dynamically (NEVER hardcode: Item Browser's value differs and
        // breaks asset loading → "couldn't load ... from asset bundle").
        private const long TextDataBlockScriptFileId = 2108018792;
        private const string ScriptableDataDllPath = "Assets/Plugins/CoreKeeperModSDK/ScriptableData.dll";

        public static void GenerateFromEnv()
        {
            var yaml = Environment.GetEnvironmentVariable("LOC_YAML");
            var outDir = Environment.GetEnvironmentVariable("LOC_OUT");
            if (string.IsNullOrEmpty(yaml) || string.IsNullOrEmpty(outDir))
            {
                Debug.Log("[LocGen] LOC_YAML/LOC_OUT not set — skipping localisation generation.");
                return;
            }
            var tablePath = Environment.GetEnvironmentVariable("LOC_TABLE");
            if (string.IsNullOrEmpty(tablePath))
                throw new Exception("[LocGen] LOC_TABLE env var not set (path to utils/ck-language-addresses.json).");
            Generate(yaml, outDir, tablePath);
        }

        public static void Generate(string yamlPath, string outDir, string tablePath)
        {
            // Resolved here rather than at the env-var read, because this is where the
            // paths are used and outDir is deleted RECURSIVELY below. A relative value
            // resolves against Unity's working directory, which is not the caller's, so
            // that delete would otherwise run somewhere nobody named. EnvPaths.Resolve is
            // idempotent, so an already-absolute path just gets normalised.
            yamlPath = EnvPaths.Resolve(yamlPath);
            outDir = EnvPaths.Resolve(outDir);
            tablePath = EnvPaths.Resolve(tablePath);

            // Still fatal, deliberately: LOC_YAML pointing at nothing is a
            // contradiction — localisation configured, source absent — and the likely
            // cause is a moved or renamed file, where a silent skip would ship a mod
            // whose text quietly fell back to raw keys. An empty file is the supported
            // way to say "no terms yet".
            if (!File.Exists(yamlPath))
                throw new FileNotFoundException(
                    $"[LocGen] YAML not found: {yamlPath} — create it (an empty one is fine, generation then "
                        + "skips) or remove LOC_YAML/LOC_OUT from the mod's .envrc."
                );
            if (!File.Exists(tablePath))
                throw new FileNotFoundException($"[LocGen] address table not found: {tablePath}");

            var langs = LangTable.Load(tablePath); // ISO -> (low, high), + primary
            var yamlText = File.ReadAllText(yamlPath);
            var terms = LocYaml.Parse(yamlText); // throws on U+2026 / U+2014

            // An empty table and a broken one are different situations, and treating
            // both as fatal made "has no in-game text yet" a build failure — which is
            // why a scaffolded mod could not carry its localisation wiring from the
            // start. The failure worth keeping is the one where terms were authored
            // and none arrived: those would render as raw keys in game.
            if (terms.Count == 0)
            {
                if (LocYaml.HasAuthoredContent(yamlText))
                    throw new Exception(
                        $"[LocGen] {yamlPath} has content but yielded 0 terms — a term is a `Leaf:` at "
                            + "indent 2 under a namespace at indent 0, so a file of namespace headers alone "
                            + "defines nothing. Every term would fall back to its raw key in game."
                    );
                // Clear what an earlier run produced: without this, emptying the table
                // would keep shipping its stale assets, since the bundle packs whatever
                // the AssetDatabase still sees under the mod's tree.
                if (Directory.Exists(outDir))
                {
                    Directory.Delete(outDir, true);
                    AssetDatabase.Refresh(); // let the packer see them go, not just the disk
                }
                Debug.Log($"[LocGen] {yamlPath} holds no terms yet — skipping localisation generation.");
                return;
            }

            var scriptGuid = AssetDatabase.AssetPathToGUID(ScriptableDataDllPath);
            if (string.IsNullOrEmpty(scriptGuid))
                throw new Exception($"[LocGen] could not resolve ScriptableData.dll guid at {ScriptableDataDllPath} — adjust the path for this SDK clone.");

            // Stamped BEFORE the first write, so VerifyVisibleToUnity can tell assets
            // this run produced from ones a previous (correct) build left behind. The
            // slack absorbs any skew between DateTime.UtcNow and the filesystem's
            // timestamp granularity: erring early only widens what counts as "fresh",
            // whereas erring late would fail a perfectly good build.
            var startedUtc = DateTime.UtcNow.AddSeconds(-5);

            // outDir is the mod's real unity/ path; it surfaces under the SDK's
            // Assets/ tree via link.sh's directory symlink, so File writes + an
            // AssetDatabase.Refresh() import the generated assets.
            if (Directory.Exists(outDir))
                Directory.Delete(outDir, true); // clean regen
            Directory.CreateDirectory(outDir);

            foreach (var t in terms)
            {
                foreach (var iso in t.ByLang.Keys)
                    if (!langs.ByIso.ContainsKey(iso))
                        Debug.LogWarning($"[LocGen] unknown language '{iso}' in {t.Namespace}/{t.Leaf} (not in address table)");

                var nsDir = Path.Combine(outDir, t.Namespace);
                Directory.CreateDirectory(nsDir);
                var assetPath = Path.Combine(nsDir, t.Leaf + ".asset");
                File.WriteAllText(assetPath, BuildAsset(t, langs, scriptGuid));
                File.WriteAllText(assetPath + ".meta", BuildMeta(t));
            }
            AssetDatabase.Refresh();
            Debug.Log($"[LocGen] Generated {terms.Count} TextDataBlock terms into {outDir}");
            VerifyVisibleToUnity(terms, outDir, startedUtc);
        }

        // Writing the files is not the same as getting them into the bundle, and the
        // difference is invisible: ModBuilder packs what the AssetDatabase sees under
        // Assets/<Mod>/, so assets written outside that tree are simply absent from
        // the bundle, no step fails, and at runtime every term falls back to its raw
        // key (Loc.T's `?? term` renders "ItemChecklist-General/Shown" instead of
        // "128 shown").
        //
        // The way this happens in practice: LOC_OUT is derived from $PWD in the mod's
        // .envrc, and .envrc is gitignored — so a build from a git worktree that has
        // no .envrc of its own makes direnv walk up to the main repo's, where $PWD is
        // the MAIN tree, while link.sh correctly symlinks the WORKTREE into the SDK.
        // The generator then writes (and clean-deletes!) the main tree's assets and
        // the worktree's bundle ships with none. Nothing in the environment is
        // missing, so the "LOC_YAML/LOC_OUT not set" guard above never fires.
        //
        // So check the tree Unity actually packs, via Application.dataPath (= the
        // project's Assets folder — no assumption about the process CWD). Opening a
        // path under it follows link.sh's directory symlink at the OS level, so the
        // question "did my write land in the tree being packed?" becomes a plain file
        // test.
        //
        // Existence alone is NOT enough, and a first version of this check that only
        // probed for a file was silent on exactly the failure it was written for: an
        // earlier correct build leaves a full set of assets in the symlinked tree, so
        // the probe found stale-but-present files. Hence the freshness stamp — assets
        // older than this run were not produced by it.
        private static void VerifyVisibleToUnity(List<LocTerm> terms, string outDir, DateTime startedUtc)
        {
            // Unreachable through Generate(), which decides between skipping and
            // failing before it writes anything; kept because the probe below indexes
            // terms[0], so a direct caller must not get an IndexOutOfRange instead.
            if (terms.Count == 0)
                throw new ArgumentException("[LocGen] the visibility probe needs at least one term.", nameof(terms));

            var modName = Environment.GetEnvironmentVariable("MOD_NAME");
            if (string.IsNullOrEmpty(modName))
            {
                // Both CLI helpers fail on a missing MOD_NAME before they get here;
                // a direct Generate() call has nothing to anchor the check to.
                Debug.LogWarning("[LocGen] MOD_NAME not set — skipping the bundle-visibility check.");
                return;
            }

            var relative = Path.Combine(modName, "Localization", "Generated", terms[0].Namespace, terms[0].Leaf + ".asset");
            var packed = Path.Combine(Application.dataPath, relative);
            var reason =
                !File.Exists(packed) ? "no such file — the mod's Assets tree holds no generated localisation at all"
                : File.GetLastWriteTimeUtc(packed) < startedUtc
                    ? $"left over from an earlier build ({File.GetLastWriteTimeUtc(packed):u}, this run started {startedUtc:u})"
                : null;
            if (reason == null)
                return;

            throw new Exception(
                $"[LocGen] wrote {terms.Count} terms to {outDir}, but Assets/{relative} is {reason}. "
                    + "The bundle would ship without them and every term would render as its raw key in game "
                    + "(e.g. \"ItemChecklist-General/Shown\" instead of \"128 shown\"). "
                    + "LOC_OUT points at a different tree than the one link.sh symlinked into the SDK: a git "
                    + "worktree needs its own .envrc (it is gitignored) plus `direnv allow` before the first build."
            );
        }

        private static string BuildAsset(LocTerm t, LangTable langs, string scriptGuid)
        {
            var sb = new StringBuilder();
            var (al, ah) = DeterministicAddress(t.Namespace + "/" + t.Leaf);
            var prim = langs.Primary;
            t.ByLang.TryGetValue(prim.Iso, out var primVal);

            sb.Append("%YAML 1.1\n%TAG !u! tag:unity3d.com,2011:\n--- !u!114 &11400000\nMonoBehaviour:\n");
            sb.Append("  m_ObjectHideFlags: 0\n  m_CorrespondingSourceObject: {fileID: 0}\n");
            sb.Append("  m_PrefabInstance: {fileID: 0}\n  m_PrefabAsset: {fileID: 0}\n  m_GameObject: {fileID: 0}\n");
            sb.Append("  m_Enabled: 1\n  m_EditorHideFlags: 0\n");
            sb.Append($"  m_Script: {{fileID: {TextDataBlockScriptFileId}, guid: {scriptGuid}, type: 3}}\n");
            sb.Append($"  m_Name: {t.Leaf}\n  m_EditorClassIdentifier: \n");
            sb.Append("  m_overload:\n    m_address:\n      m_low: 0\n      m_high: 0\n");
            sb.Append($"  m_address:\n    m_low: {al}\n    m_high: {ah}\n");
            sb.Append("  m_dynamicCollections:\n    m_list: []\n");
            sb.Append("  m_localizedTexts:\n    keys:\n");
            foreach (var l in langs.Ordered)
                sb.Append($"    - m_low: {l.Low}\n      m_high: {l.High}\n");
            sb.Append("    values:\n");
            foreach (var l in langs.Ordered)
            {
                t.ByLang.TryGetValue(l.Iso, out var v);
                sb.Append("    - m_language:\n        m_address:\n");
                sb.Append($"          m_low: {l.Low}\n          m_high: {l.High}\n");
                sb.Append($"      title: {Yaml(v.Title)}\n      description: {Yaml(v.Desc)}\n");
            }
            sb.Append($"  m_localizationHint: {Yaml(t.Hint)}\n");
            sb.Append("  m_prevImportPrimaryEntry:\n    m_language:\n      m_address:\n");
            sb.Append($"        m_low: {prim.Low}\n        m_high: {prim.High}\n");
            sb.Append($"    title: {Yaml(primVal.Title)}\n    description: {Yaml(primVal.Desc)}\n");
            sb.Append("  m_shouldBeLocalized: 1\n");
            sb.Append($"  m_header: {t.Namespace}\n");
            sb.Append("  references:\n    version: 2\n    RefIds: []\n");
            return sb.ToString();
        }

        private static string BuildMeta(LocTerm t)
        {
            var guid = DeterministicGuid("meta:" + t.Namespace + "/" + t.Leaf);
            return "fileFormatVersion: 2\n"
                + $"guid: {guid}\n"
                + "NativeFormatImporter:\n  externalObjects: {}\n  mainObjectFileID: 11400000\n"
                + "  userData: \n  assetBundleName: \n  assetBundleVariant: \n";
        }

        // Single-quote non-empty values (handles leading '{', ':' etc.); empty -> bare.
        private static string Yaml(string s)
        {
            if (string.IsNullOrEmpty(s))
                return "";
            return "'" + s.Replace("'", "''") + "'";
        }

        private static (long, long) DeterministicAddress(string key)
        {
            var b = MD5.Create().ComputeHash(Encoding.UTF8.GetBytes("addr:" + key));
            return (BitConverter.ToInt64(b, 0), BitConverter.ToInt64(b, 8));
        }

        private static string DeterministicGuid(string key)
        {
            var b = MD5.Create().ComputeHash(Encoding.UTF8.GetBytes(key));
            return BitConverter.ToString(b).Replace("-", "").ToLowerInvariant();
        }
    }

    internal sealed class LangEntry
    {
        public string Iso;
        public long Low;
        public long High;
        public int Order;
    }

    internal sealed class LangTable
    {
        public Dictionary<string, LangEntry> ByIso;
        public List<LangEntry> Ordered;
        public LangEntry Primary;

        public static LangTable Load(string path)
        {
            // Minimal JSON read via Unity's JsonUtility wrapper types.
            var raw = File.ReadAllText(path);
            var parsed = JsonUtility.FromJson<Wrapper>(WrapForJsonUtility(raw));
            var list = parsed
                .languages.Select(l => new LangEntry
                {
                    Iso = l.iso,
                    Low = l.low,
                    High = l.high,
                    Order = l.order,
                })
                .ToList();
            return new LangTable
            {
                Ordered = list.OrderBy(l => l.Order).ToList(),
                ByIso = list.ToDictionary(l => l.Iso),
                Primary = list.OrderBy(l => l.Order).First(),
            };
        }

        // JsonUtility can't read a top-level object with a leading "_comment"; strip
        // unknown keys is automatic, but it needs the array under a named field —
        // our file already has {"languages":[...]}, so pass through.
        private static string WrapForJsonUtility(string raw) => raw;

        [Serializable]
        private class Wrapper
        {
            public Lang[] languages;
        }

        [Serializable]
        private class Lang
        {
            public string iso;
            public long low;
            public long high;
            public int order;
        }
    }

    internal sealed class LocTerm
    {
        public string Namespace,
            Leaf,
            Hint = "";
        public readonly Dictionary<string, (string Title, string Desc)> ByLang = new();
    }

    internal static class LocYaml
    {
        public static List<LocTerm> Parse(string text)
        {
            var terms = new List<LocTerm>();
            string ns = null;
            LocTerm cur = null;
            int lineNo = 0;
            foreach (var rawLine in text.Replace("\r", "").Split('\n'))
            {
                lineNo++;
                var line = StripComment(rawLine);
                if (line.Trim().Length == 0)
                    continue;
                int indent = line.Length - line.TrimStart(' ').Length;
                var body = line.Trim();

                if (indent == 0)
                {
                    ns = body.TrimEnd(':').Trim();
                    continue;
                }
                if (ns == null)
                    throw new Exception($"[LocGen] line {lineNo}: entry before any namespace");

                if (indent == 2)
                {
                    int c = body.IndexOf(':');
                    if (c < 0)
                        throw new Exception($"[LocGen] line {lineNo}: expected 'Leaf:'");
                    cur = new LocTerm { Namespace = ns, Leaf = body[..c].Trim() };
                    terms.Add(cur);
                    var rest = body[(c + 1)..].Trim();
                    var map = MapBody(rest);
                    if (map != null)
                        foreach (var kv in map)
                            SetLang(cur, kv.Key, kv.Value, lineNo);
                    continue;
                }
                if (indent == 4)
                {
                    if (cur == null)
                        throw new Exception($"[LocGen] line {lineNo}: value before any term");
                    int c = body.IndexOf(':');
                    if (c < 0)
                        throw new Exception($"[LocGen] line {lineNo}: expected 'key: value'");
                    var k = body[..c].Trim();
                    var v = body[(c + 1)..].Trim();
                    if (k == "hint")
                        cur.Hint = Ascii(Unquote(v), lineNo);
                    else
                        SetLang(cur, k, v, lineNo);
                    continue;
                }
                throw new Exception($"[LocGen] line {lineNo}: unexpected indent {indent}");
            }
            return terms;
        }

        private static void SetLang(LocTerm t, string lang, string val, int lineNo)
        {
            var map = MapBody(val);
            if (map != null)
                t.ByLang[lang] = (Ascii(map.GetValueOrDefault("title", ""), lineNo), Ascii(map.GetValueOrDefault("desc", ""), lineNo));
            else
                t.ByLang[lang] = (Ascii(Unquote(val), lineNo), "");
        }

        private static string Ascii(string s, int lineNo)
        {
            if (s.IndexOf('…') >= 0)
                throw new Exception($"[LocGen] line {lineNo}: U+2026 ellipsis forbidden (CK thinTiny font crashes — docs/gotchas.md). Use '...'.");
            if (s.IndexOf('—') >= 0)
                throw new Exception($"[LocGen] line {lineNo}: U+2014 em-dash renders as hyphen (docs/gotchas.md). Use '-' or '--'.");
            return s;
        }

        // Whether the source holds anything a term could have come from. Uses the
        // parser's own comment stripping, so "empty" here means exactly what Parse
        // sees as empty — a file of nothing but comments is a mod that has not
        // written its table yet, while content that yields no term is a mistake.
        public static bool HasAuthoredContent(string text)
        {
            foreach (var rawLine in text.Replace("\r", "").Split('\n'))
                if (StripComment(rawLine).Trim().Length > 0)
                    return true;
            return false;
        }

        private static string StripComment(string l)
        {
            // Only strip '#' when not inside quotes (our values may contain none, but be safe).
            bool q = false;
            for (int i = 0; i < l.Length; i++)
            {
                if (l[i] == '\'')
                    q = !q;
                if (l[i] == '#' && !q)
                    return l[..i];
            }
            return l;
        }

        private static string Unquote(string v)
        {
            v = v.Trim();
            if (v.Length >= 2 && v[0] == '\'' && v[^1] == '\'')
                return v[1..^1].Replace("''", "'");
            if (v.Length >= 2 && v[0] == '"' && v[^1] == '"')
                return v[1..^1];
            return v;
        }

        private static Dictionary<string, string> MapBody(string v)
        {
            v = v.Trim();
            if (v.Length < 2 || v[0] != '{' || v[^1] != '}')
                return null;
            var d = new Dictionary<string, string>();
            foreach (var part in SplitTop(v[1..^1]))
            {
                int c = part.IndexOf(':');
                if (c < 0)
                    continue;
                d[part[..c].Trim()] = Unquote(part[(c + 1)..].Trim());
            }
            return d;
        }

        private static IEnumerable<string> SplitTop(string s)
        {
            var sb = new StringBuilder();
            bool q = false;
            foreach (var ch in s)
            {
                if (ch == '\'')
                    q = !q;
                if (ch == ',' && !q)
                {
                    yield return sb.ToString();
                    sb.Clear();
                }
                else
                    sb.Append(ch);
            }
            if (sb.Length > 0)
                yield return sb.ToString();
        }
    }
}
