// The mod.io reference file that CLIPublishHelper writes for utils/steam_guard.py.
//
// Worth a test of its own because the reader's whole contract is "this parses":
// the guard refuses on an "error" member, so a reference that does not parse at
// all is the one outcome nobody downstream is built to explain. Every shape is
// therefore checked with a real JSON parser rather than by string comparison,
// and the validator that decides whether mod.io's bodies may be spliced in is
// checked against that same parser.

using System.Text.Json;
using CoreKeeperModUtils;

namespace PublishHelperTests;

public class ModioReferenceTests
{
    // Trimmed from real responses: what steam_guard.py reads, and enough around it
    // to look like mod.io.
    private const string ModBody = """
        {"id": 6211950, "name": "Mod Settings Menu", "visible": 0,
         "modfile": {"id": 7010001, "version": "1.2.2", "filesize": 51234, "filesize_uncompressed": 116669,
                     "changelog": "Fixed \"Save\" -> works\n\u00e9"}}
        """;

    private const string FilesBody = """
        {"data": [{"id": 7010001, "version": "1.2.2", "filesize_uncompressed": 116669, "date_added": 1760000000},
                  {"id": 7000000, "version": "1.2.1", "filesize_uncompressed": 116001, "date_added": 1750000000}],
         "result_count": 2, "result_offset": 0, "result_limit": 100, "result_total": 2}
        """;

    private static JsonElement Parse(string json) => JsonDocument.Parse(json).RootElement;

    [Fact]
    public void A_mod_not_on_modio_is_modId_zero_and_nothing_else()
    {
        var root = Parse(ModioReference.NotOnModio());

        Assert.Equal(0, root.GetProperty("modId").GetInt64());
        Assert.Single(root.EnumerateObject());
    }

    [Fact]
    public void A_read_carries_both_bodies_verbatim()
    {
        var root = Parse(ModioReference.Read(6211950, ModBody, FilesBody, out var invalid));

        Assert.Null(invalid);
        Assert.Equal(6211950, root.GetProperty("modId").GetInt64());
        var modfile = root.GetProperty("mod").GetProperty("modfile");
        Assert.Equal("1.2.2", modfile.GetProperty("version").GetString());
        Assert.Equal(116669, modfile.GetProperty("filesize_uncompressed").GetInt64());
        Assert.Equal("Fixed \"Save\" -> works\n\u00e9", modfile.GetProperty("changelog").GetString());
        var files = root.GetProperty("files").GetProperty("data");
        Assert.Equal(2, files.GetArrayLength());
        Assert.Equal(1750000000, files[1].GetProperty("date_added").GetInt64());
    }

    [Fact]
    public void An_error_survives_quotes_backslashes_control_characters_and_non_ascii()
    {
        const string reason = "HTTP 401, \"Unauthorized\": C:\\path\ttab\r\nnext\u0001 — {\"error\":{\"code\":401}}";

        var json = ModioReference.Error(42, reason);
        var root = Parse(json);

        Assert.Equal(42, root.GetProperty("modId").GetInt64());
        Assert.Equal(reason, root.GetProperty("error").GetString());
        // Escaped, not written raw: the file stays ASCII whatever the reader assumes.
        Assert.All(json, c => Assert.InRange(c, ' ', '~'));
    }

    [Fact]
    public void An_error_with_no_reason_is_still_json()
    {
        Assert.Equal("", Parse(ModioReference.Error(7, null)).GetProperty("error").GetString());
    }

    [Fact]
    public void A_mod_body_that_is_not_json_becomes_the_error_shape()
    {
        var root = Parse(ModioReference.Read(7, "<html><body>502 Bad Gateway</body></html>", FilesBody, out var invalid));

        Assert.NotNull(invalid);
        Assert.Contains("for the mod", invalid);
        Assert.Contains("502 Bad Gateway", root.GetProperty("error").GetString());
        Assert.False(root.TryGetProperty("mod", out _));
    }

    [Fact]
    public void An_empty_files_body_becomes_the_error_shape()
    {
        var root = Parse(ModioReference.Read(7, ModBody, "", out var invalid));

        Assert.Contains("for the modfiles", invalid);
        Assert.Contains("(empty body)", root.GetProperty("error").GetString());
        Assert.False(root.TryGetProperty("files", out _));
    }

    [Fact]
    public void A_json_array_is_not_spliced_in_as_a_body()
    {
        // Valid JSON, but steam_guard.py indexes ["data"] and ["modfile"].
        Parse(ModioReference.Read(7, "[1, 2]", FilesBody, out var invalid));

        Assert.NotNull(invalid);
    }

    [Fact]
    public void An_excerpt_is_cut_and_marked()
    {
        var excerpt = ModioReference.Excerpt(new string('x', 500), 10);

        Assert.Equal(new string('x', 10) + "…", excerpt);
    }

    [Theory]
    [InlineData("{}")]
    [InlineData("  {\"a\" : [1, -0.5, 2e10, 3E-2, 0, true, false, null, \"\"]}\r\n")]
    [InlineData("{\"s\": \"\\\" \\\\ \\/ \\b \\f \\n \\r \\t \\u00e9 \\uD83D\\uDE00\"}")]
    [InlineData("{\"nested\": {\"deeper\": [{}, [], {\"x\": [[[]]]}]}}")]
    [InlineData("{\"raw\": \"é and 😀 unescaped\"}")]
    [InlineData("{\"dup\": 1, \"dup\": 2}")]
    [InlineData("[]")]
    [InlineData("\"just a string\"")]
    [InlineData("42")]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData("{")]
    [InlineData("{\"a\": 1,}")]
    [InlineData("{\"a\": [1, 2,]}")]
    [InlineData("{'a': 1}")]
    [InlineData("{a: 1}")]
    [InlineData("{\"a\" 1}")]
    [InlineData("{\"a\": 1 \"b\": 2}")]
    [InlineData("{\"a\": 01}")]
    [InlineData("{\"a\": 1.}")]
    [InlineData("{\"a\": .5}")]
    [InlineData("{\"a\": 1e}")]
    [InlineData("{\"a\": +1}")]
    [InlineData("{\"a\": -}")]
    [InlineData("{\"a\": NaN}")]
    [InlineData("{\"a\": tru}")]
    [InlineData("{\"a\": nulls}")]
    [InlineData("{\"a\": \"unterminated}")]
    [InlineData("{\"a\": \"bad \\x escape\"}")]
    [InlineData("{\"a\": \"short \\u12\"}")]
    [InlineData("{\"a\": \"raw\ttab\"}")]
    [InlineData("{\"a\": 1} trailing")]
    [InlineData("{\"a\": 1}{}")]
    [InlineData("<html>{\"a\": 1}</html>")]
    [InlineData("\uFEFF{\"a\": 1}")]
    public void The_validator_agrees_with_a_real_parser(string text)
    {
        bool parses;
        try
        {
            parses = JsonDocument.Parse(text).RootElement.ValueKind == JsonValueKind.Object;
        }
        catch (JsonException)
        {
            parses = false;
        }

        Assert.Equal(parses, ModioReference.IsJsonObject(text));
    }

    [Fact]
    public void Null_is_not_a_json_object()
    {
        Assert.False(ModioReference.IsJsonObject(null));
    }

    [Fact]
    public void Pathological_nesting_is_refused_rather_than_overflowing_the_stack()
    {
        var text = "{\"a\": " + new string('[', 100_000) + new string(']', 100_000) + "}";

        Assert.False(ModioReference.IsJsonObject(text));
    }
}
