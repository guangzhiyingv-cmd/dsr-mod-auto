"""Check job isolation, stage ordering, and normalized-runtime integrity."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dsr_common import check_runtime, load_config, sha256, write_json


class ContractTests(unittest.TestCase):
    def setUp(self):
        base = (Path(tempfile.gettempdir()) / "dsr_skill_validation/unit").resolve()
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        def cleanup():
            target = Path(self.temp.name).resolve()
            if target == base or not target.is_relative_to(base):
                raise ValueError("Test cleanup escaped its generated-output root.")
            self.temp.cleanup()
        self.addCleanup(cleanup)
        self.root = Path(self.temp.name)
        self.config_path = self.root / "job.json"
        self.config = {"schema": "dsr_mod_job_v1", "targets": ["isaac_lv1"], "name": "fixture",
            "workspace": str(self.root), "input": "input.blend", "output": "extracted/job",
            "release_dir": ".",
            "blender": "blender.exe", "game": "game", "cli": "runtime/DsrCli.exe",
            "runtime_manifest": "runtime/manifest.json", "source_preset": "mmd.json",
            "native_blend": "native.blend", "skeleton_xml": "native.xml",
            "stages": ["atlas", "rig", "split", "scale", "hands", "cleanup", "export"],
            "transparent_policy": "remove_zero_opacity", "mesh_objects": ["Body"],
            "rig_object": "Armature", "minimum_elbow_bend_degrees": 15, "maximum_arm_stretch": 1.25}

    def load(self):
        write_json(self.config_path, self.config)
        return load_config(self.config_path)

    def test_skeleton_correction_defaults_on_and_can_be_disabled(self):
        self.assertTrue(self.load()["skeleton_correction"])
        self.config["skeleton_correction"] = False
        config = self.load()
        self.assertFalse(config["skeleton_correction"])
        from skeleton_correction import dependencies
        self.assertIsNone(dependencies(config))

    def test_skeleton_option_rejects_non_boolean_values(self):
        self.config["skeleton_correction"] = "false"
        with self.assertRaisesRegex(ValueError, "true or false"):
            self.load()

    def test_split_mode_keeps_correction_enabled_and_rejects_conflicting_config(self):
        self.assertEqual(self.load()["skeleton_package_mode"], "merged")
        self.config["skeleton_package_mode"] = "split"
        self.assertTrue(self.load()["skeleton_correction"])
        self.config["skeleton_correction"] = False
        with self.assertRaisesRegex(ValueError, "Split packages require"):
            self.load()
        self.config["skeleton_correction"] = True
        self.config["skeleton_package_mode"] = "unknown"
        with self.assertRaisesRegex(ValueError, "merged or split"):
            self.load()

    def split_release_fixture(self):
        self.config["skeleton_package_mode"] = "split"
        self.config["animation_fix"] = True
        config = self.load()
        package = Path(config["output"]) / "package"
        package.mkdir(parents=True)
        items = {}
        for role in ("body", "skeleton", "merged"):
            path = package / (role + ".fbmod")
            path.write_bytes(role.encode())
            items[role] = {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size}
        correction = {"passed": True, "applied": True, "single_package": False,
                      "validation": str(package / "skeleton_validation.json"),
                      "skeleton_package": items["skeleton"],
                      "artifacts": {item["path"]: item["sha256"] for item in items.values()}}
        from animation_fix import requirement
        repair = requirement({"animation_fix": True})
        write_json(package / "build_manifest.json", {"package": items["merged"],
            "body_package": items["body"], "skeleton_correction": correction, "animation_fix": repair,
            "config_sha256": sha256(self.config_path)})
        write_json(package / "verification/final_validation.json", {"passed": True,
            "package_sha256": items["merged"]["sha256"], "skeleton_correction": {"passed": True}, "animation_fix": repair})
        return config, items

    def test_split_release_delivers_exact_inputs_without_merged_package(self):
        from dsr_job import release
        config, items = self.split_release_fixture()
        release(config, self.config_path)
        report = json.loads((self.root / "fixture.release.json").read_text(encoding="utf-8"))
        self.assertFalse(report["single_package"])
        self.assertEqual([p["role"] for p in report["packages"]], ["body", "skeleton"])
        for role in ("body", "skeleton"):
            self.assertEqual(sha256(self.root / ("fixture_" + role + ".fbmod")), items[role]["sha256"])
        self.assertFalse((self.root / "merged.fbmod").exists())

    def test_split_release_checks_all_collisions_before_copying(self):
        from dsr_job import release
        config, _ = self.split_release_fixture()
        (self.root / "fixture_skeleton.fbmod").write_bytes(b"existing release")
        with self.assertRaises(FileExistsError):
            release(config, self.config_path)
        self.assertFalse((self.root / "fixture_body.fbmod").exists())

    def test_split_release_rejects_tampered_skeleton(self):
        from dsr_job import release
        config, items = self.split_release_fixture()
        Path(items["skeleton"]["path"]).write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "artifact changed"):
            release(config, self.config_path)
        self.assertFalse((self.root / "fixture_body.fbmod").exists())

    def test_height_alignment_defaults_to_head_and_accepts_shoulders(self):
        self.assertEqual(self.load()["height_alignment"], "head")
        self.config["height_alignment"] = "shoulder"
        self.assertEqual(self.load()["height_alignment"], "shoulder")

    def test_height_alignment_rejects_unknown_or_empty_modes(self):
        for mode in ("Head", "hips", "", None, []):
            with self.subTest(mode=mode):
                self.config["height_alignment"] = mode
                with self.assertRaisesRegex(ValueError, "head or shoulder"):
                    self.load()

    def test_legacy_shoulder_state_cannot_resume_with_head_default(self):
        import dsr_job
        config = self.load()
        state = {"config_sha256": sha256(self.config_path)}
        write_json(Path(config["output"]) / "state.json", state)
        with patch.object(dsr_job, "preflight", return_value={"height_alignment": "head"}):
            with self.assertRaisesRegex(ValueError, "Job inputs changed"):
                dsr_job.run(config, self.config_path, "scale")

    def test_skeleton_validation_rejects_changed_final_package(self):
        from skeleton_correction import verify
        final = self.root / "single.fbmod"
        final.write_bytes(b"validated payload")
        report = {"passed": True, "applied": True, "validation": "report.json",
                  "artifacts": {str(final): sha256(final)}}
        self.assertTrue(verify(report)["single_package"])
        final.write_bytes(b"different payload")
        with self.assertRaisesRegex(ValueError, "artifact changed"):
            verify(report)

    def test_native_aligned_profile_does_not_require_fabricated_ant_edits(self):
        import sys
        core = str(Path(__file__).resolve().parent / "skeleton")
        if core not in sys.path:
            sys.path.insert(0, core)
        from prepare_matched import patch_defaults
        report = {"joints": [{"name": "Head", "parent_index": -1}],
                  "defaults": [{"name": "Head.t", "value": [0, 0, 0]},
                               {"name": "Head.q", "value": [0, 0, 0, 1]},
                               {"name": "Head.s", "value": [1, 1, 1]}]}
        payload, edits, before, after, error = patch_defaults(b"unchanged", report, {"Head": [0, 0, 0]})
        self.assertEqual(payload, b"unchanged")
        self.assertEqual(edits, [])
        self.assertEqual(before, after)
        self.assertEqual(error, 0)

    def test_relative_paths_resolve_against_job_file(self):
        config = self.load()
        self.assertEqual(Path(config["input"]), self.root / "input.blend")
        self.assertEqual(Path(config["output"]), self.root / "extracted/job")

    def test_reject_output_inside_game_or_source(self):
        for output in ("game/generated", "source/generated", "assets/generated", "skill/generated"):
            with self.subTest(output=output):
                self.config["output"] = output
                with self.assertRaises(ValueError):
                    self.load()

    def test_original_cannot_be_inside_generated_output(self):
        self.config["input"] = "extracted/job/original.blend"
        with self.assertRaises(ValueError):
            self.load()

    def test_wrong_target_or_stage_order_is_rejected(self):
        self.config["targets"] = ["legacy"]
        with self.assertRaises(ValueError):
            self.load()
        self.config["targets"] = ["isaac_lv1"]
        for stages in (["hands", "scale"], ["export", "export"], ["unknown"]):
            self.config["stages"] = stages
            with self.assertRaises(ValueError):
                self.load()

    def test_target_suit_list_is_validated(self):
        self.config["targets"] = ["isaac_lv1", "isaac_legacy"]
        self.assertEqual(self.load()["targets"], ["isaac_lv1", "isaac_legacy"])
        for targets in (["isaac_lv1", "nope"], ["isaac_lv1", "isaac_lv1"]):
            self.config["targets"] = targets
            with self.assertRaises(ValueError):
                self.load()
        self.config["targets"] = ["isaac_lv1"]

    def test_raw_input_enforces_a_t_dsr_stage_order(self):
        self.config["input"] = "source.pmx"
        self.config["source_pose"] = "AUTO"
        self.config["stages"] = ["import", "static", "tpose", "pose", "atlas", "rig", "split", "scale", "hands", "export"]
        self.assertEqual(Path(self.load()["input"]).suffix, ".pmx")
        for stages in (["import", "static", "pose", "atlas"], ["import", "static", "pose", "tpose", "scale"]):
            self.config["stages"] = stages
            with self.assertRaises(ValueError):
                self.load()

    def test_prepared_dsr_pose_cannot_be_converted_again(self):
        self.config["source_pose"] = "DSR"
        self.config["stages"] = ["tpose", "pose", "atlas"]
        with self.assertRaises(ValueError):
            self.load()

    def test_runtime_tampering_and_historical_runtime_are_rejected(self):
        config = self.load()
        runtime = self.root / "runtime"
        (runtime / "Plugins").mkdir(parents=True)
        files = [runtime / "DsrCli.exe", runtime / "Plugins/MeshSetPlugin.dll"]
        for path in files:
            path.write_bytes(b"fixture-binary")
        manifest = {"normalize_transformed_ntb": True,
                    "tools": [{"path": str(path), "sha256": sha256(path)} for path in files]}
        write_json(config["runtime_manifest"], manifest)
        self.assertEqual(check_runtime(config)["checked_files"], 2)
        files[1].write_bytes(b"changed-binary")
        with self.assertRaises(ValueError):
            check_runtime(config)
        manifest["normalize_transformed_ntb"] = False
        write_json(config["runtime_manifest"], manifest)
        with self.assertRaises(ValueError):
            check_runtime(config)


    def test_relative_runtime_manifest_paths_resolve_against_the_cli(self):
        config = self.load()
        runtime = self.root / "runtime"
        (runtime / "Plugins").mkdir(parents=True)
        files = [runtime / "DsrCli.exe", runtime / "Plugins/MeshSetPlugin.dll"]
        for path in files:
            path.write_bytes(b"fixture-binary")
        manifest = {"normalize_transformed_ntb": True,
                    "tools": [{"path": path.relative_to(runtime).as_posix(),
                               "sha256": sha256(path)} for path in files]}
        write_json(config["runtime_manifest"], manifest)
        self.assertEqual(check_runtime(config)["checked_files"], 2)

    def test_runtime_manifest_cannot_escape_the_cli_directory(self):
        config = self.load()
        runtime = self.root / "runtime"
        runtime.mkdir(parents=True)
        (runtime / "DsrCli.exe").write_bytes(b"fixture-binary")
        outside = self.root / "outside.dll"
        outside.write_bytes(b"fixture-binary")
        manifest = {"normalize_transformed_ntb": True,
                    "tools": [{"path": "DsrCli.exe", "sha256": sha256(runtime / "DsrCli.exe")},
                              {"path": "../outside.dll", "sha256": sha256(outside)}]}
        write_json(config["runtime_manifest"], manifest)
        with self.assertRaises(ValueError):
            check_runtime(config)


if __name__ == "__main__":
    unittest.main()
