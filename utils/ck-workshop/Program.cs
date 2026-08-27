// utils/ck-workshop — publish a built Core Keeper mod to the Steam Workshop.
//
// Reads a publish bundle as JSON on stdin (assembled by utils/steam_bundle.py)
// and performs the Steamworks calls. The split is deliberate: everything that
// can be derived and tested lives in Python, and this half — which needs a live
// Steam session and cannot be unit-tested — stays as small as possible.
//
// Why not the SDK's own Steam Workshop tab: it never writes a change note, it
// keys its stored File ID on the display title (CoreKeeperModSDK#11), and it
// finds its content through a five-entry UI ring buffer.
//
// Exit codes, which utils/upload.sh reports as the run's own:
//   0  published — or a dry run, which sends nothing and says so
//   2  the bundle on stdin is unusable — not JSON, or a field that reaches the
//      Workshop item is missing, blank, names a file that is not there, or is
//      one this tool cannot act on
//   3  Steam would not initialise — client not running, or the native library
//   4  the target item does not exist, or belongs to another account
//   5  the submit failed; an id may still have been emitted for a created item
//   6  an unexpected exception
//   7  published, but an OPTIONAL dependency did not sync
//   9  published, but a REQUIRED dependency may be missing from the item
//
// 1 is not assigned here; upload.sh uses it for its own failures (assembling
// the bundle, persisting an id). 8 is NOT free either, though nothing below
// returns it: upload.sh means "Steam never started, because its preflight
// failed" by it — a state this tool cannot report, since in it the tool never
// runs. Taking 8 here would merge two outcomes an operator has to tell apart,
// so a new code goes past it; 9 is now taken, and the next one is 10.

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading.Tasks;
using Steamworks;
using Steamworks.Data;
using Steamworks.Ugc;

internal sealed class Bundle
{
    [JsonPropertyName("fileId")]
    public ulong FileId { get; set; }

    [JsonPropertyName("title")]
    public string Title { get; set; }

    [JsonPropertyName("description")]
    public string Description { get; set; }

    [JsonPropertyName("tags")]
    public string[] Tags { get; set; }

    [JsonPropertyName("changelog")]
    public string Changelog { get; set; }

    [JsonPropertyName("version")]
    public string Version { get; set; }

    [JsonPropertyName("contentPath")]
    public string ContentPath { get; set; }

    [JsonPropertyName("previewPath")]
    public string PreviewPath { get; set; }

    [JsonPropertyName("visibility")]
    public string Visibility { get; set; }

    [JsonPropertyName("dependencies")]
    public Dependency[] Dependencies { get; set; }

    internal sealed class Dependency
    {
        [JsonPropertyName("name")]
        public string Name { get; set; }

        [JsonPropertyName("fileId")]
        public ulong FileId { get; set; }

        [JsonPropertyName("required")]
        public bool Required { get; set; }
    }
}

// The two values steam_bundle.py emits, and so the only two that mean
// anything here. There is deliberately no third one for "public": a new item
// is created hidden and an existing item's visibility was chosen by a person,
// so nothing in this tool ever puts an item into the catalogue.
internal enum ItemVisibility
{
    Unchanged,
    Hidden,
}

internal static class Program
{
    private const uint CoreKeeperAppId = 1621690;

    private static async Task<int> Main(string[] args)
    {
        var dryRun = Array.IndexOf(args, "--dry-run") >= 0;

        Bundle bundle;
        try
        {
            bundle = JsonSerializer.Deserialize<Bundle>(await Console.In.ReadToEndAsync());
        }
        catch (JsonException ex)
        {
            Console.Error.WriteLine($"bundle is not valid JSON: {ex.Message}");
            return 2;
        }

        var unusable = Validate(bundle, out var visibility);
        if (unusable != null)
        {
            Console.Error.WriteLine(unusable);
            return 2;
        }

        // Coalesced once, for both the line below and the tag loop further
        // down: a mod with no tags is a legitimate bundle, so this is the one
        // field that stays optional — but the log and the editor must not
        // disagree about what "no tags" means.
        var tags = bundle.Tags ?? Array.Empty<string>();

        Console.Error.WriteLine($"  Title:   {bundle.Title}");
        Console.Error.WriteLine($"  Version: {bundle.Version}");
        Console.Error.WriteLine($"  Tags:    {string.Join(", ", tags)}");
        Console.Error.WriteLine($"  Content: {bundle.ContentPath}");
        // Worded from visibility, not from FileId == 0: that's what the gating
        // logic below actually reads. Validate has just tied the two together,
        // so this line cannot describe one item while the code creates another.
        Console.Error.WriteLine(visibility == ItemVisibility.Hidden ? "  Item:    new (hidden)" : $"  Item:    {bundle.FileId}");

        if (dryRun)
        {
            Console.Error.WriteLine("  (dry run — nothing sent)");
            EmitResult(bundle.FileId, created: false, success: true);
            return 0;
        }

        try
        {
            SteamClient.Init(CoreKeeperAppId);
        }
        catch (Exception ex)
        {
            // The two failures worth naming, because neither says so itself:
            // no Steam running, or the native library missing/mismatched.
            Console.Error.WriteLine($"Steam could not be initialised: {ex.Message}");
            Console.Error.WriteLine("  Is the desktop Steam client running and signed in?");
            Console.Error.WriteLine("  Is libsteam_api.dylib installed? See utils/fetch_steam_lib.sh");
            return 3;
        }

        // Reported so upload.sh can put it in <Mod>_Steam.asset, where only the
        // SDK window reads it. AppOwner rather than SteamId because that is what
        // the window itself writes, and the two differ under Family Sharing.
        // Every EmitResult below picks it up from here; it stays 0 on the dry-run
        // path, which returns before this line ever runs, and 0 tells the shell
        // side there is no value to write rather than an owner of zero.
        _modOwner = SteamApps.AppOwner.Value;

        // Captured the moment CreateItem succeeds, independently of the value
        // SubmitAsync eventually returns: it also sets this on its return value
        // whenever creation succeeded, even if a later step then fails, but not
        // when a later step THROWS instead of returning — and the only way to
        // learn the id of an item that exists on Steam but never got to return
        // is this callback. Losing it here is exactly how a re-run creates a
        // second, duplicate public Workshop item over one that already exists.
        ulong? createdFileId = null;
        var needsWorkshopAgreement = false;

        void OnItemCreated(PublishResult created)
        {
            createdFileId = (ulong)created.FileId;
            needsWorkshopAgreement = created.NeedsWorkshopAgreement;

            // Written the moment the item exists on Steam, not just once the
            // whole publish finishes below: SubmitAsync still has uploading
            // and dependency-syncing left to do, and a timeout or a Ctrl-C
            // during that stretch kills this process with no chance to reach
            // either EmitResult call further down — the only other place
            // this id is reported. Console.Out is flushed on every
            // WriteLine, so this line reaches STEAM_RESULT on disk even if
            // nothing after it does. success is always false here because
            // the publish has not concluded yet; if it goes on to succeed,
            // the real EmitResult below supersedes this one — the reader
            // (utils/steam_result.py) scans the stream backwards for the
            // last line that both parses as JSON and carries a "fileId",
            // so the later of the two wins while a brace-leading diagnostic
            // printed after either cannot displace them.
            Console.Error.WriteLine($"  Workshop item {createdFileId} created, publish continuing...");
            EmitResult(createdFileId.Value, created: true, success: false);
        }

        try
        {
            var creating = bundle.FileId == 0;
            var editor = creating ? Editor.NewCommunityFile : new Editor(bundle.FileId);

            if (!creating)
            {
                var existing = await Item.GetAsync(bundle.FileId);
                if (!existing.HasValue)
                {
                    Console.Error.WriteLine($"Workshop item {bundle.FileId} not found.");
                    return 4;
                }
                if (existing.Value.Owner.Id != SteamClient.SteamId)
                {
                    Console.Error.WriteLine($"Workshop item {bundle.FileId} belongs to someone else.");
                    return 4;
                }
            }

            editor = editor.WithTitle(bundle.Title).WithDescription(bundle.Description).WithContent(bundle.ContentPath).WithChangeLog(bundle.Changelog);

            // Unconditional: Validate has already established that the file is
            // there. Guarding it here instead is what used to publish an item
            // with no preview and no complaint.
            editor = editor.WithPreviewFile(bundle.PreviewPath);

            foreach (var tag in tags)
            {
                editor = editor.WithTag(tag);
            }

            // The bundle is the single source of truth for visibility, not the
            // creating/updating distinction — an existing item's visibility was
            // chosen by a person and is not this tool's to change. Validate has
            // already established that "hidden" means fileId 0, so this fires
            // for a new item and for nothing else.
            if (visibility == ItemVisibility.Hidden)
            {
                editor = editor.WithPrivateVisibility();
            }

            var result = await editor.SubmitAsync(new Progress(), OnItemCreated);
            // SubmitAsync sets result.FileId as soon as CreateItem succeeds, and
            // keeps it set through a later failure — the callback above is the
            // fallback for the one path that doesn't return a result at all.
            var fileId = (ulong)result.FileId != 0 ? (ulong)result.FileId : createdFileId;
            needsWorkshopAgreement = needsWorkshopAgreement || result.NeedsWorkshopAgreement;

            if (!result.Success)
            {
                Console.Error.WriteLine($"Workshop submit failed: {result.Result}");
                if (needsWorkshopAgreement)
                {
                    Console.Error.WriteLine("  The Steam Workshop legal agreement has not been accepted for this account.");
                    Console.Error.WriteLine($"  Accept it at https://steamcommunity.com/sharedfiles/workshoplegalagreement/{CoreKeeperAppId} and re-run.");
                }
                // The item may already be live even though the publish failed —
                // report its id (if any) so upload.sh can still save it.
                EmitResult(fileId ?? 0, created: creating && fileId.HasValue, success: false);
                return 5;
            }

            var dependencySync = await SyncDependencies(fileId.Value, bundle.Dependencies);

            EmitResult(fileId.Value, created: creating, success: true);
            return dependencySync switch
            {
                DependencySync.Ok => 0,
                DependencySync.RequiredFailed => 9,
                _ => 7,
            };
        }
        catch (Exception ex)
        {
            // Content Folder missing/empty (thrown before any item exists, so
            // nothing to report) and any other Steamworks failure — a network
            // abort, a Ctrl-C — land here alike. If an item was already
            // created, its id must still reach stdout: that is the only way
            // upload.sh learns of a live item it would otherwise treat as
            // never having existed.
            Console.Error.WriteLine($"Workshop publish threw: {ex.GetType().Name}: {ex.Message}");
            if (createdFileId.HasValue)
            {
                EmitResult(createdFileId.Value, created: true, success: false);
            }
            return 6;
        }
        finally
        {
            SteamClient.Shutdown();
        }
    }

    // Everything the calls below assume about the bundle, checked in one place
    // before the first of them runs. steam_bundle.py does guarantee all of it —
    // but that guarantee lives in another language in another file, and nothing
    // on this side would notice it lapsing: these values travel straight into a
    // Workshop item, where a wrong one is not an error but a wrong item in a
    // public catalogue. Returns the message to print, or null when the bundle
    // is usable.
    //
    // It runs ahead of the dry-run branch, so a rehearsal rejects every bundle
    // a real run would reject — which is also what makes all of this reachable
    // from the test suite, with no Steam client anywhere. That is the reason
    // the one filesystem check below lives here rather than beside its use.
    private static string Validate(Bundle bundle, out ItemVisibility visibility)
    {
        visibility = ItemVisibility.Unchanged;

        if (bundle == null)
        {
            return "bundle is empty";
        }

        // Blank counts as missing only where a blank value is itself a wrong
        // item: an untitled entry in the catalogue, or a publish of nothing.
        // An empty description or changelog makes a sparse item rather than a
        // broken one, and steam_bundle.parse_changelog genuinely returns "" for
        // a version heading with nothing under it — so those two are required
        // to be present, not to be filled in.
        if (string.IsNullOrWhiteSpace(bundle.ContentPath))
        {
            return "bundle field \"contentPath\" is missing or blank";
        }
        if (string.IsNullOrWhiteSpace(bundle.Title))
        {
            return "bundle field \"title\" is missing or blank";
        }
        if (bundle.Description == null)
        {
            return "bundle field \"description\" is missing";
        }
        if (bundle.Changelog == null)
        {
            return "bundle field \"changelog\" is missing";
        }

        // The one filesystem question asked here, and asked because nothing
        // else asks it. A missing content folder is Steamworks' own error,
        // thrown loudly before any item exists; a preview file that is not
        // there produces no error anywhere — WithPreviewFile simply never runs
        // and the item goes into the catalogue with a placeholder where its
        // logo belongs. There is no metadata-only publish path on the Steam
        // side, so that costs a whole Workshop update to correct, while
        // refusing it here costs nothing: no item has been created yet.
        if (string.IsNullOrWhiteSpace(bundle.PreviewPath))
        {
            return "bundle field \"previewPath\" is missing or blank";
        }
        if (!File.Exists(bundle.PreviewPath))
        {
            return $"bundle field \"previewPath\" names no file: {bundle.PreviewPath}";
        }

        switch (bundle.Visibility)
        {
            case "unchanged":
                visibility = ItemVisibility.Unchanged;
                break;
            case "hidden":
                visibility = ItemVisibility.Hidden;
                break;
            default:
                // The failure this replaces was silent: anything unrecognised —
                // a typo, a missing key, a value from a later version of the
                // producer — fell through to "leave the visibility alone",
                // which on an item being created that same second means Steam's
                // own default. Public.
                return $"bundle field \"visibility\" is {Quoted(bundle.Visibility)}, expected \"hidden\" or \"unchanged\"";
        }

        // hidden ⇔ fileId == 0, and both directions are worth refusing.
        // "unchanged" on an item that does not exist yet is exactly how one
        // gets created public; "hidden" on one that does takes a live item out
        // of the catalogue that a person deliberately put there. The producer
        // derives each from the other, so a bundle where they disagree did not
        // come from it and this tool cannot tell which half to believe.
        if ((visibility == ItemVisibility.Hidden) != (bundle.FileId == 0))
        {
            return $"bundle field \"visibility\" is {Quoted(bundle.Visibility)} but fileId is {bundle.FileId} — "
                + "a new item (fileId 0) must be \"hidden\", an existing one \"unchanged\"";
        }

        // A null LIST stays usable: that is the producer's "unknown, change
        // nothing", and SyncDependencies early-returns on it rather than
        // removing what it cannot name. Its ENTRIES are a different matter —
        // each becomes an AddDependency call, and neither way of getting one
        // wrong announces itself. steam_bundle.py cannot produce either, but
        // that guarantee lives in another language, and an item published with
        // a dependency missing is not an error, it is a mod that does not run
        // for whoever subscribes to it.
        foreach (var dependency in bundle.Dependencies ?? Array.Empty<Bundle.Dependency>())
        {
            if (dependency == null)
            {
                return "bundle field \"dependencies\" has a null entry";
            }
            // Before the id check, because the id is what the message would
            // otherwise have to identify a nameless entry by.
            if (string.IsNullOrWhiteSpace(dependency.Name))
            {
                return $"bundle dependency {dependency.FileId} has no \"name\" — the log line reporting it is the only place its severity is visible";
            }
            // Also what an absent "fileId" key deserialises to, which is the
            // likelier of the two ways to arrive here: AddDependency(0) asks
            // Steam about an item that cannot exist.
            if (dependency.FileId == 0)
            {
                return $"bundle dependency \"{dependency.Name}\" has no \"fileId\" — 0 is not a Workshop item";
            }
        }

        return null;
    }

    // Tells a missing field from one that is present and wrong, which are two
    // different mistakes to go looking for in the producer.
    private static string Quoted(string value) => value == null ? "missing" : $"\"{value}\"";

    // Told apart because the two cost a subscriber different things: an
    // optional dependency that did not attach costs them a convenience, a
    // required one costs them a mod that does not work. By this point the item
    // is live and nothing can be undone, so saying which of the two happened
    // is the whole of what this side can still do about it.
    private enum DependencySync
    {
        Ok,
        Failed,
        RequiredFailed,
    }

    // Full sync rather than additive, so the Workshop list mirrors the .asset:
    // what is declared is added, what is not is removed. Reports any failed
    // add/remove call, so the caller can tell "published, but not fully synced"
    // apart from a clean run instead of reporting success regardless of what
    // AddDependency/RemoveDependency actually did.
    private static async Task<DependencySync> SyncDependencies(ulong publishedFileId, Bundle.Dependency[] dependencies)
    {
        if (dependencies == null)
        {
            return DependencySync.Ok;
        }

        // What either "sync skipped" below reports. A skipped sync attached
        // nothing at all this run, so a required dependency is missing from an
        // item that was just created and merely unconfirmed on one that already
        // existed. Both take the louder code: the two cannot be told apart from
        // here, and the expensive one to miss is the brand-new item that has no
        // hard dependency on it at all.
        var skipped = dependencies.Any(dependency => dependency.Required) ? DependencySync.RequiredFailed : DependencySync.Failed;

        // Item.GetAsync (see its use above) only asks for WithLongDescription,
        // never WithChildren, so it always comes back with Children == null.
        // Querying directly with WithChildren(true) is the only way to see
        // what the item already carries, which the removal side needs to know.
        var page = await Query.All.WithFileId(publishedFileId).WithChildren(true).GetPageAsync(1);
        if (!page.HasValue)
        {
            Console.Error.WriteLine($"  dependency sync skipped — could not query Workshop item {publishedFileId}");
            return skipped;
        }

        using (page.Value)
        {
            if (page.Value.ResultCount == 0)
            {
                // Silent here would contradict "full sync, not additive": the
                // publish still reports success while no dependency was
                // added or removed at all.
                Console.Error.WriteLine($"  dependency sync skipped — Workshop item {publishedFileId} not found (0 results)");
                return skipped;
            }

            var item = page.Value.Entries.First();
            var wanted = new HashSet<ulong>();
            var failed = false;
            var requiredFailed = false;

            foreach (var dep in dependencies)
            {
                wanted.Add(dep.FileId);
                if (await item.AddDependency(dep.FileId))
                {
                    Console.Error.WriteLine($"  dependency + {dep.Name} ({dep.FileId})");
                }
                else
                {
                    // Named on the line itself, not left to whoever thinks to
                    // open the .asset: this line is the only place the two
                    // severities are visible while the log is still on screen.
                    Console.Error.WriteLine($"  dependency + {dep.Name} ({dep.FileId}) FAILED{(dep.Required ? " — REQUIRED" : "")}");
                    failed = true;
                    requiredFailed = requiredFailed || dep.Required;
                }
            }

            foreach (var child in item.Children ?? Array.Empty<PublishedFileId>())
            {
                if (wanted.Contains(child.Value))
                {
                    continue;
                }
                if (await item.RemoveDependency(child.Value))
                {
                    Console.Error.WriteLine($"  dependency - {child.Value}");
                }
                else
                {
                    // Never the louder code: a surplus dependency the item kept
                    // is one too many, which installs something unwanted rather
                    // than leaving the mod unable to run.
                    Console.Error.WriteLine($"  dependency - {child.Value} FAILED");
                    failed = true;
                }
            }

            if (requiredFailed)
            {
                return DependencySync.RequiredFailed;
            }
            return failed ? DependencySync.Failed : DependencySync.Ok;
        }
    }

    // The one place that writes the result line upload.sh parses. success
    // travels alongside fileId/created so a caller can tell "published (or at
    // least created) but something else failed" from a clean run without
    // depending on the process exit code, which a shell pipeline can lose.
    // 0 until SteamClient.Init has run — see where it is assigned.
    private static ulong _modOwner;

    private static void EmitResult(ulong fileId, bool created, bool success) =>
        Console.WriteLine(
            JsonSerializer.Serialize(
                new
                {
                    fileId,
                    created,
                    success,
                    modOwner = _modOwner,
                }
            )
        );

    private sealed class Progress : IProgress<float>
    {
        private int _lastTenth = -1;

        public void Report(float value)
        {
            var tenth = (int)(value * 10);
            if (tenth == _lastTenth)
            {
                return;
            }
            _lastTenth = tenth;
            Console.Error.WriteLine($"  upload {value * 100:F0}%");
        }
    }
}
