// Which mod.io Game Version tag a shipped build is published under.
//
// Worth a test of its own because nothing downstream can catch a wrong answer:
// whatever Resolve returns is taken from the live taxonomy, so it is a valid
// tag by construction and passes the validation that follows. A rule that maps
// too eagerly publishes a mod under a version it was never checked against,
// without a word.
//
// The tag and build lists are excerpts of the real ones (mod.io's taxonomy and
// ck-game-versions.json as of the 1.3 update), because the cases that matter
// are the real neighbourhoods: 1.3.0 with no .0 build behind it, and 1.1.2
// with one.

using CoreKeeperModUtils;

namespace PublishHelperTests;

public class GameVersionTagsTests
{
    private static readonly string[] Tags = { "1.3.0", "1.2.1.5", "1.2.1.0", "1.1.2.10", "1.1.2.1", "1.1.2", "0.9.9.9.9", "0.9.9.9" };

    private static readonly HashSet<string> Shipped = new()
    {
        "1.3.0.2",
        "1.3.0.1",
        "1.2.1.5",
        "1.2.1.2",
        "1.2.1.0",
        "1.1.2.10",
        "1.1.2.1",
        "1.1.2.0",
        "0.9.9.9",
    };

    [Fact]
    public void A_build_with_its_own_tag_keeps_it()
    {
        Assert.Equal("1.2.1.5", GameVersionTags.Resolve("1.2.1.5", Tags, Shipped));
    }

    [Fact]
    public void A_build_without_a_tag_is_published_under_the_update_tag()
    {
        // 1.3.0.0 never shipped, so 1.3.0 can only mean the update.
        Assert.Equal("1.3.0", GameVersionTags.Resolve("1.3.0.2", Tags, Shipped));
        Assert.Equal("1.3.0", GameVersionTags.Resolve("1.3.0.1", Tags, Shipped));
    }

    [Fact]
    public void A_short_tag_that_names_a_shipped_build_stands_in_for_nothing()
    {
        // 1.1.2 is build 1.1.2.0. A later hotfix without its own tag must fail
        // loudly rather than be listed under a build it was not tested on.
        var shipped = new HashSet<string>(Shipped) { "1.1.2.11" };

        Assert.Null(GameVersionTags.Resolve("1.1.2.11", Tags, shipped));
    }

    [Fact]
    public void A_build_that_never_shipped_gets_no_stand_in()
    {
        // The typo case: 1.3.0.20 starts with 1.3.0 and must still fail.
        Assert.Null(GameVersionTags.Resolve("1.3.0.20", Tags, Shipped));
    }

    [Fact]
    public void Without_the_shipped_list_nothing_gets_a_stand_in()
    {
        // The list is what the stand-in rule is decided on; guessing without it
        // is exactly the silent mapping the rule exists to prevent.
        Assert.Null(GameVersionTags.Resolve("1.3.0.2", Tags, new HashSet<string>()));
        Assert.Null(GameVersionTags.Resolve("1.3.0.2", Tags, null));
        Assert.Equal("1.2.1.5", GameVersionTags.Resolve("1.2.1.5", Tags, null));
    }

    [Fact]
    public void A_prefix_must_end_on_a_segment_boundary()
    {
        var shipped = new HashSet<string>(Shipped) { "1.3.01.0" };

        Assert.Null(GameVersionTags.Resolve("1.3.01.0", Tags, shipped));
    }

    [Fact]
    public void A_build_with_no_tag_and_no_stand_in_resolves_to_nothing()
    {
        // 1.2.1.2 is the CK_MODIO_VERSION_UNLISTED case: there is no 1.2.1 tag.
        Assert.Null(GameVersionTags.Resolve("1.2.1.2", Tags, Shipped));
    }

    [Fact]
    public void The_longest_stand_in_wins()
    {
        var tags = new[] { "1.4", "1.4.0" };
        var shipped = new HashSet<string> { "1.4.0.3" };

        Assert.Equal("1.4.0", GameVersionTags.Resolve("1.4.0.3", tags, shipped));
    }
}
