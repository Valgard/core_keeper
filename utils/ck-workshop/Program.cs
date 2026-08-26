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
//   2  the bundle on stdin is unusable (not JSON, empty, no contentPath)
//   3  Steam would not initialise — client not running, or the native library
//   4  the target item does not exist, or belongs to another account
//   5  the submit failed; an id may still have been emitted for a created item
//   6  an unexpected exception
//   7  published, but the dependency sync had failures
//
// 1 is not assigned here; upload.sh uses it for its own failures (assembling
// the bundle, persisting an id). 8 is NOT free either, though nothing below
// returns it: upload.sh means "Steam never started, because its preflight
// failed" by it — a state this tool cannot report, since in it the tool never
// runs. Taking 8 here would merge two outcomes an operator has to tell apart,
// so a new code goes to 9 or higher.

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

        if (bundle == null || string.IsNullOrEmpty(bundle.ContentPath))
        {
            Console.Error.WriteLine("bundle is empty or has no contentPath");
            return 2;
        }

        Console.Error.WriteLine($"  Title:   {bundle.Title}");
        Console.Error.WriteLine($"  Version: {bundle.Version}");
        Console.Error.WriteLine($"  Tags:    {string.Join(", ", bundle.Tags ?? Array.Empty<string>())}");
        Console.Error.WriteLine($"  Content: {bundle.ContentPath}");
        // Worded from Visibility, not from FileId == 0: that's the field the
        // gating logic below actually reads, so the log can't go stale if the
        // two ever decouple.
        Console.Error.WriteLine(bundle.Visibility == "hidden" ? "  Item:    new (hidden)" : $"  Item:    {bundle.FileId}");

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
            // the real EmitResult below overwrites this — upload.sh takes
            // only the LAST '{'-prefixed line in the result file.
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

            if (File.Exists(bundle.PreviewPath))
            {
                editor = editor.WithPreviewFile(bundle.PreviewPath);
            }

            foreach (var tag in bundle.Tags ?? Array.Empty<string>())
            {
                editor = editor.WithTag(tag);
            }

            // The bundle is the single source of truth for visibility, not the
            // creating/updating distinction: Task 3 already encodes "an existing
            // item's visibility was chosen by a person and is not this tool's to
            // change" as "unchanged", so this only ever fires for a new item.
            if (bundle.Visibility == "hidden")
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

            var dependenciesOk = await SyncDependencies(fileId.Value, bundle.Dependencies);

            EmitResult(fileId.Value, created: creating, success: true);
            return dependenciesOk ? 0 : 7;
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

    // Full sync rather than additive, so the Workshop list mirrors the .asset:
    // what is declared is added, what is not is removed. Returns false when
    // any single add/remove call failed, so the caller can tell "published,
    // but not fully synced" apart from a clean run instead of reporting
    // success regardless of what AddDependency/RemoveDependency actually did.
    private static async Task<bool> SyncDependencies(ulong publishedFileId, Bundle.Dependency[] dependencies)
    {
        if (dependencies == null)
        {
            return true;
        }

        // Item.GetAsync (see its use above) only asks for WithLongDescription,
        // never WithChildren, so it always comes back with Children == null.
        // Querying directly with WithChildren(true) is the only way to see
        // what the item already carries, which the removal side needs to know.
        var page = await Query.All.WithFileId(publishedFileId).WithChildren(true).GetPageAsync(1);
        if (!page.HasValue)
        {
            Console.Error.WriteLine($"  dependency sync skipped — could not query Workshop item {publishedFileId}");
            return false;
        }

        using (page.Value)
        {
            if (page.Value.ResultCount == 0)
            {
                // Silent here would contradict "full sync, not additive": the
                // publish still reports success while no dependency was
                // added or removed at all.
                Console.Error.WriteLine($"  dependency sync skipped — Workshop item {publishedFileId} not found (0 results)");
                return false;
            }

            var item = page.Value.Entries.First();
            var wanted = new HashSet<ulong>();
            var ok = true;

            foreach (var dep in dependencies)
            {
                wanted.Add(dep.FileId);
                if (await item.AddDependency(dep.FileId))
                {
                    Console.Error.WriteLine($"  dependency + {dep.Name} ({dep.FileId})");
                }
                else
                {
                    Console.Error.WriteLine($"  dependency + {dep.Name} ({dep.FileId}) FAILED");
                    ok = false;
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
                    Console.Error.WriteLine($"  dependency - {child.Value} FAILED");
                    ok = false;
                }
            }

            return ok;
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
