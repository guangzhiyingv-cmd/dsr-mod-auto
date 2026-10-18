// Package ANT-only and matched bind/default add-ons without changing game files.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;

internal static class PackageDsrProportionTrial
{
    private static readonly BindingFlags PrivateStatic = BindingFlags.NonPublic | BindingFlags.Static;

    private static int Main(string[] args)
    {
        int result = 1;
        try { Run(args); result = 0; }
        catch (Exception error) { Console.Error.WriteLine(error); }
        Console.Out.Flush();
        Console.Error.Flush();
        Environment.Exit(result);
        return result;
    }

    private static void WriteAndCheck(Type program, object manager, string directory, string stem,
        string title, string description, byte[] expectedBank, bool expectSkeleton)
    {
        Directory.CreateDirectory(directory);
        string path = Path.Combine(directory, stem + ".fbmod");
        program.GetMethod("WriteCharacterMod", PrivateStatic).Invoke(null,
            new object[] { manager, path, title, "Research", description, "Local research" });
        string readback = Path.Combine(directory, "readback");
        object result = program.GetMethod("RunExtractMod", PrivateStatic).Invoke(null, new object[] {
            manager, new List<string> { "extract-mod", path }, readback });
        if ((int)result != 0) throw new InvalidDataException("Package extraction failed.");
        string[] resources = Directory.GetFiles(readback, "*.res");
        string[] ebx = Directory.GetFiles(readback, "*.ebx");
        if (resources.Length != 1 || !File.ReadAllBytes(resources[0]).SequenceEqual(expectedBank) ||
            ebx.Length != (expectSkeleton ? 1 : 0))
            throw new InvalidDataException("Package payload inventory or bank bytes differ.");
        string[] rows = File.ReadAllLines(Path.ChangeExtension(path, ".resources.tsv"));
        if (rows.Length != (expectSkeleton ? 3 : 2) ||
            rows.Skip(1).Any(row => !row.StartsWith("Res\tanimations/antanimations/configurations/sharedbundles/globals_sharedbundle_win32_antstate\t") &&
                                  !(expectSkeleton && row.StartsWith("Ebx\tgame/anim/rigging/player/player_skeleton\t"))))
            throw new InvalidDataException("Unexpected modified resource identity.");
        Console.WriteLine("VERIFIED_PROPORTION_ADDON " + path);
    }

    private static void Run(string[] args)
    {
        if (args.Length != 6 && args.Length != 9)
            throw new ArgumentException("Expected CLI directory, game directory, baseline bank, patched bank, bind FBMOD, new output directory, and optional stem/title/description.");
        string cliDirectory = Path.GetFullPath(args[0]);
        string gameDirectory = Path.GetFullPath(args[1]);
        string baselinePath = Path.GetFullPath(args[2]);
        string patchedPath = Path.GetFullPath(args[3]);
        string bindMod = Path.GetFullPath(args[4]);
        string output = Path.GetFullPath(args[5]);
        if (Directory.Exists(output)) throw new IOException("Output directory must be new.");
        byte[] baseline = File.ReadAllBytes(baselinePath), patched = File.ReadAllBytes(patchedPath);
        if (baseline.Length != patched.Length || baseline.SequenceEqual(patched))
            throw new InvalidDataException("Expected an in-place bank patch.");
        AppDomain.CurrentDomain.AssemblyResolve += (sender, request) => {
            string path = Path.Combine(cliDirectory, new AssemblyName(request.Name).Name + ".dll");
            return File.Exists(path) ? Assembly.LoadFrom(path) : null;
        };
        Environment.CurrentDirectory = cliDirectory;
        Type program = Assembly.LoadFrom(Path.Combine(cliDirectory, "DsrCli.exe")).GetType("DeadSpaceCli.Program", true);
        program.GetField("s_exeDir", PrivateStatic).SetValue(null, cliDirectory);
        program.GetField("s_sdkDir", PrivateStatic).SetValue(null, Path.Combine(cliDirectory, "Profiles"));
        object manager = program.GetMethod("LoadGame", PrivateStatic).Invoke(null,
            new object[] { gameDirectory, Path.Combine(cliDirectory, "deadspace.key") });
        Type managerType = manager.GetType();
        const string bankName = "animations/antanimations/configurations/sharedbundles/globals_sharedbundle_win32_antstate";
        object entry = managerType.GetMethod("GetResEntry", new[] { typeof(string) }).Invoke(manager, new object[] { bankName });
        if (entry == null) throw new InvalidDataException("Globals resource missing.");
        using (Stream stream = (Stream)managerType.GetMethod("GetRes").Invoke(manager, new[] { entry }))
        using (MemoryStream copy = new MemoryStream())
        {
            stream.CopyTo(copy);
            if (!copy.ToArray().SequenceEqual(baseline)) throw new InvalidDataException("Loaded bank differs from audited baseline.");
        }
        ulong rid = (ulong)entry.GetType().GetField("ResRid").GetValue(entry);
        byte[] meta = (byte[])entry.GetType().GetField("ResMeta").GetValue(entry);
        managerType.GetMethod("ModifyRes", new[] { typeof(ulong), typeof(byte[]), typeof(byte[]) })
            .Invoke(manager, new object[] { rid, patched, meta });
        Directory.CreateDirectory(output);
        if (args.Length == 6) WriteAndCheck(program, manager, Path.Combine(output, "ant_only"), "character_ant_only",
            "Character Proportion Trial - ANT Only",
            "Diagnostic add-on for the existing Character base mod. Changes Player_Rig default translations to the prepared model positions; original mesh binding remains. Runtime untested.", patched, false);
        object loaded = program.GetMethod("RunExportModAssets", PrivateStatic).Invoke(null, new object[] {
            manager, new List<string> { "inspect-mod-assets", bindMod },
            Path.Combine(output, "bind_load_check"), "", true });
        if ((int)loaded != 0) throw new InvalidDataException("Could not load the checked bind package.");
        WriteAndCheck(program, manager, Path.Combine(output, "matched"), args.Length == 9 ? args[6] : "character_matched_skeleton",
            args.Length == 9 ? args[7] : "Character Proportion Trial - Matched Bind and ANT",
            args.Length == 9 ? args[8] : "Experimental add-on for the existing Character base mod. Pairs native bind positions and Player_Rig default translations with the prepared model. Preserves original rotations and existing mesh geometry. Runtime untested.", patched, true);
    }
}
