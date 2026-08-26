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

using System;
using System.IO;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading.Tasks;
using Steamworks;
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
            Console.WriteLine(JsonSerializer.Serialize(new { fileId = bundle.FileId, created = false }));
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

            var result = await editor.SubmitAsync(new Progress());
            if (!result.Success)
            {
                Console.Error.WriteLine($"Workshop submit failed: {result.Result}");
                return 5;
            }

            Console.WriteLine(JsonSerializer.Serialize(new { fileId = (ulong)result.FileId, created = creating }));
            return 0;
        }
        finally
        {
            SteamClient.Shutdown();
        }
    }

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
