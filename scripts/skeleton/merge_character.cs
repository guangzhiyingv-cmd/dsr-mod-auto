// Merge validated body and skeleton inputs into one FBMOD and compare raw payloads.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;

internal static class MergeCharacter
{
    private static readonly BindingFlags PrivateStatic = BindingFlags.NonPublic | BindingFlags.Static;

    private static int Main(string[] args)
    {
        try { Run(args); Console.Out.Flush(); Environment.Exit(0); }
        catch (Exception error) { Console.Error.WriteLine(error); Console.Error.Flush(); Environment.Exit(1); }
        return 1;
    }

    private static Dictionary<string, byte[]> Payloads(string directory)
    {
        var result = new Dictionary<string, byte[]>(StringComparer.OrdinalIgnoreCase);
        foreach (string row in File.ReadAllLines(Path.Combine(directory, "manifest.tsv")))
        {
            string[] fields = row.Split('\t');
            if (fields.Length < 7 || Path.GetFileName(fields[6]) != fields[6])
                throw new InvalidDataException("Unexpected readback manifest row.");
            result.Add(fields[1] + "\t" + fields[2], File.ReadAllBytes(Path.Combine(directory, fields[6])));
        }
        return result;
    }

    private static void Run(string[] args)
    {
        if (args.Length != 7)
            throw new ArgumentException("Expected CLI directory, game, body FBMOD, skeleton FBMOD, new directory, stem and title.");
        string cli = Path.GetFullPath(args[0]), output = Path.GetFullPath(args[4]);
        if (Directory.Exists(output)) throw new IOException("Output directory must be new.");
        if (args[5] != Path.GetFileName(args[5])) throw new InvalidDataException("Invalid package stem.");
        AppDomain.CurrentDomain.AssemblyResolve += (sender, request) => {
            string path = Path.Combine(cli, new AssemblyName(request.Name).Name + ".dll");
            return File.Exists(path) ? Assembly.LoadFrom(path) : null;
        };
        Environment.CurrentDirectory = cli;
        Type program = Assembly.LoadFrom(Path.Combine(cli, "DsrCli.exe")).GetType("DeadSpaceCli.Program", true);
        program.GetField("s_exeDir", PrivateStatic).SetValue(null, cli);
        program.GetField("s_sdkDir", PrivateStatic).SetValue(null, Path.Combine(cli, "Profiles"));
        object manager = program.GetMethod("LoadGame", PrivateStatic).Invoke(null,
            new object[] { Path.GetFullPath(args[1]), Path.Combine(cli, "deadspace.key") });
        Directory.CreateDirectory(output);
        var expected = new Dictionary<string, byte[]>(StringComparer.OrdinalIgnoreCase);
        for (int i = 0; i < 2; ++i)
        {
            string mod = Path.GetFullPath(args[2 + i]);
            string folder = Path.Combine(output, i == 0 ? "body_input" : "skeleton_input");
            int result = (int)program.GetMethod("RunExtractMod", PrivateStatic).Invoke(null,
                new object[] { manager, new List<string> { "extract-mod", mod }, folder });
            if (result != 0) throw new InvalidDataException("Input extraction failed.");
            var entries = Payloads(folder);
            if (i == 1 && (entries.Count != 2 ||
                !entries.ContainsKey("Ebx\tgame/anim/rigging/player/player_skeleton") ||
                !entries.ContainsKey("Res\tanimations/antanimations/configurations/sharedbundles/globals_sharedbundle_win32_antstate")))
                throw new InvalidDataException("Unexpected skeleton override set.");
            foreach (var entry in entries)
                if (expected.ContainsKey(entry.Key)) throw new InvalidDataException("Inputs overlap: " + entry.Key);
                else expected.Add(entry.Key, entry.Value);
            result = (int)program.GetMethod("RunExportModAssets", PrivateStatic).Invoke(null,
                new object[] { manager, new List<string> { "inspect-mod-assets", mod },
                    Path.Combine(output, "load_" + i), "", true });
            if (result != 0) throw new InvalidDataException("Input activation failed.");
        }
        string final = Path.Combine(output, args[5] + ".fbmod");
        program.GetMethod("WriteCharacterMod", PrivateStatic).Invoke(null, new object[] {
            manager, final, args[6], "Character replacement",
            "Single character package with model, textures, matched skeleton and required animation repair; no fixed Head visual compensation. Runtime untested for this build.",
            "Local pipeline"
        });
        string readback = Path.Combine(output, "readback");
        int extracted = (int)program.GetMethod("RunExtractMod", PrivateStatic).Invoke(null,
            new object[] { manager, new List<string> { "extract-mod", final }, readback });
        var actual = Payloads(readback);
        if (extracted != 0 || actual.Count != expected.Count || expected.Any(entry =>
            !actual.ContainsKey(entry.Key) || !entry.Value.SequenceEqual(actual[entry.Key])))
            throw new InvalidDataException("Merged payloads differ from the verified inputs.");
        File.WriteAllText(Path.Combine(output, "merge_validation.txt"),
            "Exact resource union; every raw payload equals its source input.\nNo game installation performed.\n");
        Console.WriteLine("VERIFIED_SINGLE_CHARACTER_PACKAGE " + final);
    }
}
