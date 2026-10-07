// Whether a publish is about to upload a mod without its DOTS codegen.
//
// The same rule as utils/check_dots_codegen.py, which guards build.sh and whose
// docstring holds the reasoning. It is tested twice because it exists twice: a
// publish builds and uploads inside one Unity session, so the shell check never
// sees that build, and a wrong answer here is the expensive one -- a modfile
// that cannot be taken back, throwing "This method should have been replaced
// by codegen" for every subscriber.

using System.Text;
using CoreKeeperModUtils;

namespace PublishHelperTests;

public class DotsCodegenTests : IDisposable
{
    private readonly string _root = Path.Combine(Path.GetTempPath(), "dots-codegen-" + Guid.NewGuid());

    public void Dispose() => Directory.Delete(_root, recursive: true);

    private string Dll(string content)
    {
        var path = Path.Combine(_root, "Library", "ScriptAssemblies", "SomeMod.dll");
        Directory.CreateDirectory(Path.GetDirectoryName(path));
        File.WriteAllBytes(path, Encoding.ASCII.GetBytes("MZ\0\0" + content + "\0"));
        return path;
    }

    private string Build(params string[] generated)
    {
        var scripts = Path.Combine(_root, "build", "Scripts");
        Directory.CreateDirectory(scripts);
        File.WriteAllText(Path.Combine(scripts, "SomeSystem.cs"), "// mod source");
        if (generated.Length > 0)
        {
            Directory.CreateDirectory(Path.Combine(scripts, "Generated"));
            foreach (var name in generated)
                File.WriteAllText(Path.Combine(scripts, "Generated", name), "// generated");
        }
        return Path.Combine(_root, "build");
    }

    [Fact]
    public void MissingAssemblyPassesWithAWarning()
    {
        Assert.True(DotsCodegen.Check(Path.Combine(_root, "Nope.dll"), Build(), out var message, out var skipped));
        Assert.True(skipped);
        Assert.Contains("not found", message);
    }

    [Fact]
    public void AssemblyWithoutCodegenPasses()
    {
        Assert.True(DotsCodegen.Check(Dll("HarmonyPatch"), Build(), out _, out _));
    }

    [Fact]
    public void CodegenWithGeneratedFilePasses()
    {
        Assert.True(DotsCodegen.Check(Dll("DOTSCompilerGeneratedAttribute"), Build("SomeSystem__System_1.g.cs"), out var message, out _));
        Assert.Contains("1 generated file", message);
    }

    [Fact]
    public void CodegenWithoutGeneratedFileFails()
    {
        Assert.False(DotsCodegen.Check(Dll("DOTSCompilerGeneratedAttribute"), Build(), out var message, out _));
        Assert.Contains("replaced by codegen", message);
    }

    [Fact]
    public void DevFlagsFileIsNotCodegen()
    {
        Assert.False(DotsCodegen.Check(Dll("DOTSCompilerGeneratedAttribute"), Build("DevFlags.generated.cs"), out _, out _));
    }

    [Fact]
    public void UnreadableAssemblyFails()
    {
        var dll = Dll("DOTSCompilerGeneratedAttribute");
        File.SetUnixFileMode(dll, UnixFileMode.None);
        try
        {
            Assert.False(DotsCodegen.Check(dll, Build("SomeSystem__System_1.g.cs"), out var message, out _));
            Assert.Contains("cannot read", message);
        }
        finally
        {
            File.SetUnixFileMode(dll, UnixFileMode.UserRead | UnixFileMode.UserWrite);
        }
    }
}
