// The one decision in the dependency path that can be tested at all.
//
// Everything around it runs behind SteamClient.Init and a successful
// SubmitAsync: reaching the sync itself means creating a public Workshop item
// or modifying a live one, so no test may go there. The decision it feeds —
// which of the three exit codes a publish ends with — depends on nothing but
// what happened to each dependency, so it lives in DependencyDecision and is
// driven here as plain data.
//
// What that buys: the outcomes below cannot be produced without Steam, but the
// rule that reads them can be, and the rule is where the reasoning is. What it
// does not buy: nothing here proves that the sync loop labels a real Steamworks
// failure with the right outcome.

using CoreKeeperModUtils;

namespace CkWorkshopTests;

public class DependencyDecisionTests
{
    private static DependencyResult Attached(bool required) => new(DependencyOutcome.Attached, required);

    private static DependencyResult AttachFailed(bool required) => new(DependencyOutcome.AttachFailed, required);

    [Fact]
    public void Nothing_declared_and_nothing_surplus_is_a_clean_publish()
    {
        // No dependencies to attach and no stale ones to remove: there is
        // nothing this step could have got wrong.
        Assert.Equal(0, DependencyDecision.ExitCodeFor(Array.Empty<DependencyResult>()));
    }

    [Fact]
    public void Everything_attached_is_a_clean_publish()
    {
        var results = new[] { Attached(required: true), Attached(required: false), new DependencyResult(DependencyOutcome.Removed, false) };

        Assert.Equal(0, DependencyDecision.ExitCodeFor(results));
    }

    [Fact]
    public void An_optional_dependency_that_did_not_attach_is_the_quiet_code()
    {
        // 7: the subscriber loses a convenience, not a working mod.
        var results = new[] { Attached(required: true), AttachFailed(required: false) };

        Assert.Equal(7, DependencyDecision.ExitCodeFor(results));
    }

    [Fact]
    public void A_required_dependency_that_did_not_attach_is_the_loud_code()
    {
        // 9: the item is live and a mod that cannot run is attached to it.
        var results = new[] { Attached(required: false), AttachFailed(required: true) };

        Assert.Equal(9, DependencyDecision.ExitCodeFor(results));
    }

    [Fact]
    public void A_required_failure_outranks_an_optional_one()
    {
        // Both kinds at once must not let the quieter code win by ordering.
        var results = new[] { AttachFailed(required: false), AttachFailed(required: true) };

        Assert.Equal(9, DependencyDecision.ExitCodeFor(results));
    }

    [Fact]
    public void A_sync_that_could_not_run_takes_the_severity_of_what_was_declared()
    {
        // The query failed, so nothing was attempted at all. With a required
        // dependency declared, that item may be missing it entirely.
        var skipped = new[] { new DependencyResult(DependencyOutcome.SyncSkipped, Required: true) };

        Assert.Equal(9, DependencyDecision.ExitCodeFor(skipped));
    }

    [Fact]
    public void A_sync_that_could_not_run_with_nothing_required_is_the_quiet_code()
    {
        // Still a failure — the removals it would have made did not happen —
        // but nothing a subscriber needs is missing.
        var skipped = new[] { new DependencyResult(DependencyOutcome.SyncSkipped, Required: false) };

        Assert.Equal(7, DependencyDecision.ExitCodeFor(skipped));
    }

    [Fact]
    public void A_removal_that_failed_never_escalates()
    {
        // The case worth pinning down. A surplus dependency the item kept
        // installs something unwanted; it does not stop the mod from running,
        // so it must not borrow the code that means "this mod is broken" —
        // not even alongside a required dependency that attached perfectly.
        var results = new[] { Attached(required: true), new DependencyResult(DependencyOutcome.RemoveFailed, false) };

        var code = DependencyDecision.ExitCodeFor(results);

        Assert.Equal(7, code);
        Assert.NotEqual(9, code);
    }

    [Fact]
    public void A_failed_removal_does_not_mask_a_required_failure_either()
    {
        // The other direction: a removal failure must not pull 9 down to 7.
        var results = new[] { new DependencyResult(DependencyOutcome.RemoveFailed, false), AttachFailed(required: true) };

        Assert.Equal(9, DependencyDecision.ExitCodeFor(results));
    }
}
