"""Protect the standalone animation repair requirement."""

from pathlib import Path
import unittest
from unittest.mock import patch

import animation_fix
import dsr_job
import test_contract


class AnimationFixTests(unittest.TestCase):
    def test_fix_is_optional(self):
        fixture = test_contract.ContractTests()
        fixture.setUp()
        try:
            fixture.config.pop("animation_fix", None)
            fixture.config["skeleton_correction"] = False
            self.assertFalse(fixture.load()["animation_fix"])
            fixture.config["animation_fix"] = True
            self.assertTrue(fixture.load()["animation_fix"])
            fixture.config["animation_fix"] = "yes"
            with self.assertRaisesRegex(ValueError, "true or false"):
                fixture.load()
        finally:
            fixture.doCleanups()

    def test_fix_disabled_keeps_geometry_body(self):
        geometry = {"path": "geometry"}
        report = {"package": geometry}
        with patch("skeleton_correction.build") as skeleton:
            dsr_job.finish_packages({"animation_fix": False, "skeleton_correction": False},
                                    Path("config.json"), report)
        skeleton.assert_not_called()
        self.assertIs(report["package"], geometry)
        self.assertIs(report["body_package"], geometry)
        self.assertFalse(report["animation_fix"]["enabled"])

    def test_animation_fix_is_recorded_as_a_separate_package_never_merged(self):
        for enabled, mode in ((True, "merged"), (True, "split"), (False, "merged")):
            with self.subTest(enabled=enabled, mode=mode):
                geometry, merged = {"path": "geometry"}, {"path": "merged"}
                correction = {"package": merged, "applied": True}
                config = {"animation_fix": True, "skeleton_correction": enabled,
                          "skeleton_package_mode": mode}
                report = {"package": geometry}
                with patch("skeleton_correction.build", return_value=correction) as skeleton:
                    dsr_job.finish_packages(config, Path("config.json"), report)
                self.assertIs(report["geometry_package"], geometry)
                self.assertIs(report["body_package"], geometry)
                self.assertIs(report["package"], merged if enabled else geometry)
                self.assertTrue(report["animation_fix"]["enabled"])
                self.assertTrue(report["animation_fix"]["separate_package"])
                self.assertFalse(report["animation_fix"]["merged"])
                self.assertEqual(report["animation_fix"]["package_name"], animation_fix.PACKAGE_NAME)
                if enabled:
                    self.assertIs(skeleton.call_args.args[2], geometry)
                else:
                    skeleton.assert_not_called()

    def test_disabled_requirement_names_no_package(self):
        requirement = animation_fix.requirement({"animation_fix": False})
        self.assertFalse(requirement["enabled"])
        self.assertFalse(requirement["required"])
        self.assertIsNone(requirement["package_name"])

    def test_verify_rejects_merged_delivery(self):
        with self.assertRaisesRegex(ValueError, "separate package"):
            animation_fix.verify({"enabled": True, "merged": True})
        verified = animation_fix.verify({"enabled": True, "required": True,
                                         "separate_package": True, "merged": False,
                                         "package_name": animation_fix.PACKAGE_NAME})
        self.assertTrue(verified["enabled"])
        self.assertFalse(verified["merged"])

    def test_new_configs_do_not_reference_a_bundled_repair_asset(self):
        fixture = test_contract.ContractTests()
        fixture.setUp()
        try:
            config = fixture.load()
            self.assertFalse(config["animation_fix"])
            self.assertNotIn("animation_fix_archive", config)
            self.assertNotIn("animation_fix_manifest", config)
            self.assertNotIn("animation_fix_mod", config)
        finally:
            fixture.doCleanups()

    def test_old_head_compensation_reports_are_rejected(self):
        from skeleton_correction import verify
        with self.assertRaisesRegex(ValueError, "no longer supported"):
            verify({"mode": "matched_head_visual_offset"})


if __name__ == "__main__":
    unittest.main()
