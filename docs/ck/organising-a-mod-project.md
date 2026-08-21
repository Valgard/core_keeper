# Organising a mod project

The SDK decides where a mod's files live, and its answer does not survive
contact with version control. This chapter is about the gap that opens there and
the moving parts of any arrangement that closes it.

**No arrangement here is required.** A single mod, built by hand and kept in one
place, needs almost none of it; the pressure rises with the number of mods
sharing one SDK clone. What is worth carrying between projects is the reasoning
— which problem each piece answers — rather than any particular layout.

The requirements underneath all of this are in [toolchain requirements](toolchain.md).

One implementation of everything below — the scripts, the variables, the exact
commands — is public at <https://github.com/Valgard/core_keeper>, if a worked
example is more use to you than a description. It is one solution to these
problems, not the solution.

## The gap: the Editor writes outside your repository

The "Create New Mod" wizard puts a mod's files inside the SDK clone, under
`Assets/<Mod>/`. That is fine until the mod belongs in its own git repository:
its sources then live in a tree nobody versions, one `git clean` or re-clone
away from being gone.

Copying files back and forth does not close the gap, because the set of files is
not fixed. The Editor keeps writing new ones — a `.meta` for every asset,
regenerated `.asmdef` references, the ModBuilderSettings `.asset` — and any
scheme that enumerates what to copy will miss whatever it writes next.

**Symlinking a mirror closes it without enumerating anything.** Keep the mod's
tree in its own repository, laid out the way the SDK expects, and link that
directory into the SDK clone. A *directory* symlink captures every file the
Editor writes into it, now and later, so nothing has to be registered by hand.

Two properties of this follow directly and are worth knowing before relying on
it:

- **Symlinks encode absolute paths**, so they dangle after the repository moves
  or after switching to a git worktree. Re-creating them as part of every build
  turns that from a repair into a non-event.
- **Unity's AssetDatabase does not watch a symlink's target.** Editing a file
  through one path while the Editor holds a compiled copy from another is how a
  change appears to have no effect at all.

## Identity belongs to the mod, machine paths do not

Anything that names a location on *this* computer — where Unity is installed,
where the SDK clone sits, where a decompiler lives — is worthless in anyone
else's checkout and must not be committed. Anything that identifies the *mod* —
its name, its ids, what it declares to the loader — is exactly what should be.

Separating the two along that line means machine values are configured once and
inherited, rather than repeated per mod and drifting. Whatever performs the
inheritance, one property matters: **a missing value must fail loudly.** A build
that proceeds with a blank where a path belonged does not stop; it produces
something subtly wrong and reports success.

**Trap: a nested working directory can break inheritance silently.** A scheme
that looks for its parent configuration a fixed number of levels up is wrong the
moment the build runs from a git worktree, which sits deeper than the repository
root. The mod's own values still load — the machine's do not, and nothing says
so. That failure mode has shipped a mod whose localisation table came out empty:
the generator ran, found no table configured, and wrote nothing.

## A gate that blocks rather than rewrites

Formatting checked at commit and at push, in *checking* mode, keeps a diff
attributable to whoever wrote it — a hook that reformats silently rewrites code
nobody reviewed. The cost is one rejected commit and a re-run; the benefit is
that `git blame` keeps meaning something.

Two mechanics behind such a gate are easy to get wrong:

- **A formatter's ignore file is usually searched for upward, and does not stop
  at a repository boundary.** A mod nested inside a larger tree can therefore
  inherit a parent's ignore rules, under which every file in the mod falls out
  of scope. The hook still passes — it has simply checked nothing. Measured in a
  repository holding one misformatted file: `Checked 0 files` without a local
  ignore file, `Checked 1 files` with one. A gate that cannot fail is worse than
  no gate, because it is believed.
- **Hook installers refuse to run while `core.hooksPath` is set**, even when
  that setting merely points at the repository's own hooks directory.

## Pin the tools that produce shipped bytes

Any script that generates a binary asset shipping inside a mod — a sprite sheet,
a font atlas — should be pinned to an exact library version, not a compatible
range.

The reason is verification. The way to check such an artifact is to regenerate
it and compare bytes against the committed copy, and PNG output is
encoder-dependent: a different library version can produce a different file from
identical input. Without pinning, "the source changed" and "my encoder differs"
are the same failure, and the check stops meaning anything. Making the suite
refuse to run on the wrong version turns that into an immediate, legible error —
and catches the likelier accident of running it outside the project environment
entirely.

## When this kind of arrangement misbehaves

Both failures below are consequences of building through symlinks rather than
from files the Editor owns, so they only occur where something like this is in
place:

| Symptom | Where |
|---|---|
| A newly linked mod builds to an empty file list | [Troubleshooting](troubleshooting.md#a-newly-linked-mod-builds-to-an-empty-file-list) |
| An edit to a shared editor helper appears to have no effect | [Troubleshooting](troubleshooting.md#an-edit-to-a-shared-editor-helper-appears-to-have-no-effect) |
