// How a dependency sync turns into the publish's exit code.
//
// A file of its own, and deliberately free of Steamworks: everything else in
// this tool runs behind SteamClient.Init and a successful SubmitAsync, so it
// can only be exercised by creating a public Workshop item or modifying a live
// one — which no test may do. The rule below depends on nothing but what
// happened to each dependency, so it can be driven as plain data, and
// ck-workshop-tests does exactly that. Program.cs calls this rather than
// deciding inline, so the rule under test is the rule that runs.
//
// By the time any of this is decided the item is already live and nothing can
// be undone. Saying precisely what happened is the whole of what is left.

using System.Collections.Generic;

namespace CoreKeeperModUtils;

// What became of one dependency operation. Two of these describe something
// other than a call's result. SyncSkipped is not another flavour of failure but
// the absence of them all: the query that lists what the item carries did not
// answer, so nothing was attempted at all. AlreadyAttached is the opposite —
// the item was found to be in the wanted state, so no call was needed.
//
// AlreadyAttached exists because AddDependency reports failure for it.
// Measured against a live item: calling it for a child the item already
// carries returns false, the same value a genuine failure returns. Adding
// unconditionally therefore graded a correct state as a required-dependency
// failure on every submit after the first, which is exit 9 — and for a
// backfill, a run that stops after every single version.
internal enum DependencyOutcome
{
    Attached,
    AlreadyAttached,
    AttachFailed,
    Removed,
    RemoveFailed,
    SyncSkipped,
}

// `Required` is the .asset's own flag, carried through from the bundle. It is
// meaningful only for the declared dependencies: a removal targets a child the
// mod does NOT declare, so nothing about it can be required, and its results
// are constructed with false. See why that matters in ExitCodeFor.
internal readonly record struct DependencyResult(DependencyOutcome Outcome, bool Required);

internal static class DependencyDecision
{
    // 0 clean, 7 something failed, 9 something required failed.
    //
    // The single rule, stated once: a failure escalates to 9 only when the
    // thing that failed was required. That is what separates the two codes —
    // an optional dependency that did not attach costs a subscriber a
    // convenience, a required one costs them a mod that does not run.
    //
    // A failed REMOVAL can therefore never reach 9, and not because it is
    // filtered out here: it carries Required = false by construction, since a
    // surplus child is by definition one the mod does not declare. A
    // dependency the item wrongly kept installs something unwanted, which is a
    // different complaint from a mod that cannot start, and borrowing the loud
    // code for it would make 9 stop meaning anything.
    internal static int ExitCodeFor(IEnumerable<DependencyResult> results)
    {
        var failed = false;
        foreach (var result in results)
        {
            if (result.Outcome is DependencyOutcome.Attached or DependencyOutcome.AlreadyAttached or DependencyOutcome.Removed)
            {
                continue;
            }
            // Safe to return at once, because 9 is the highest severity there
            // is — nothing later in the list could outrank it. The lesser one
            // is accumulated instead of returned, so that a required failure
            // anywhere still wins no matter where it sits in the list.
            if (result.Required)
            {
                return 9;
            }
            failed = true;
        }
        return failed ? 7 : 0;
    }
}
