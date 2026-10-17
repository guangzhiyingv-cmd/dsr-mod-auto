"""Run with Blender to verify A-to-T normalization before DSR conversion."""

from pathlib import Path
import sys
import unittest

try:
    import bpy
except ModuleNotFoundError:
    raise unittest.SkipTest("T-pose tests require Blender's Python runtime.")
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _pose_core as pose
import _tpose_core as tpose


def fixture(elevation=-40, rotated=False):
    import math
    bpy.ops.wm.read_factory_settings(use_empty=True)
    data = bpy.data.armatures.new("Fixture")
    rig = bpy.data.objects.new("Fixture", data)
    bpy.context.scene.collection.objects.link(rig)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    def bone(name, head, tail, parent=None):
        item = data.edit_bones.new(name)
        item.head, item.tail = head, tail
        item.roll = len(data.edit_bones) * .17
        if parent:
            item.parent = data.edit_bones[parent]
    bone("pelvis", (0, 0, 1), (0, 0, 1.1))
    bone("spine_01", (0, 0, 1.1), (0, 0, 1.4), "pelvis")
    bone("neck", (0, 0, 1.4), (0, 0, 1.5), "spine_01")
    bone("head", (0, 0, 1.5), (0, 0, 1.7), "neck")
    for side, sign in (("L", 1), ("R", -1)):
        root = Vector((sign * .2, 0, 1.4))
        segment = Vector((sign * .3 * math.cos(math.radians(elevation)), 0, .3 * math.sin(math.radians(elevation))))
        elbow, wrist = root + segment, root + 2 * segment
        bone("upperarm_" + side, root, elbow, "spine_01")
        bone("forearm_" + side, elbow, wrist, "upperarm_" + side)
        bone("hand_" + side, wrist, wrist + segment * .25, "forearm_" + side)
        bone("thigh_" + side, (sign * .1, 0, 1), (sign * .1, 0, .55), "pelvis")
        bone("shin_" + side, (sign * .1, 0, .55), (sign * .1, -.02, .1), "thigh_" + side)
        bone("foot_" + side, (sign * .1, -.02, .1), (sign * .1, -.18, .05), "shin_" + side)
        bone("toe_" + side, (sign * .1, -.18, .05), (sign * .1, -.25, .05), "foot_" + side)
    bpy.ops.object.mode_set(mode="OBJECT")
    mesh = bpy.data.meshes.new("FixtureMesh")
    mesh.from_pydata([(.2, 0, 1.4), (.35, -.03, 1.2), (.35, .03, 1.2)], [], [(0, 1, 2)])
    obj = bpy.data.objects.new("FixtureMesh", mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.parent = rig
    group = obj.vertex_groups.new(name="upperarm_L")
    group.add([0, 1, 2], 1, "REPLACE")
    modifier = obj.modifiers.new("Armature", "ARMATURE")
    modifier.object = rig
    if rotated:
        rig.matrix_world = Matrix.Translation((3, -2, .5)) @ Matrix.Rotation(.7, 4, "Z") @ Matrix.Scale(.6, 4)
    bpy.context.view_layer.update()
    return rig, obj


class TposeTests(unittest.TestCase):
    def test_a_to_t_preserves_source_and_lower_body(self):
        rig, obj = fixture(rotated=True)
        before = {b.name: b.matrix_local.copy() for b in rig.data.bones}
        points = [v.co.copy() for v in obj.data.vertices]
        target, meshes, report = tpose.convert(rig, "AUTO")
        self.assertEqual(report["source_pose"], "A")
        self.assertEqual(report["sequence"], "A -> T -> DSR")
        for values in report["arms_after"].values():
            self.assertLess(values["upper_t_error_degrees"], .1)
            self.assertLess(values["forearm_t_error_degrees"], .1)
        for name in ("pelvis", "neck", "head", "thigh_L", "shin_R", "foot_L", "toe_R"):
            self.assertLess(max(abs(target.data.bones[name].matrix_local[i][j] - before[name][i][j])
                                for i in range(4) for j in range(4)), 1e-5)
        self.assertEqual(points, [v.co for v in obj.data.vertices])
        self.assertEqual(len(meshes[0].data.polygons), 1)
        self.assertEqual([g.name for g in meshes[0].vertex_groups], ["upperarm_L"])

    def test_t_pose_passes_without_rotations(self):
        rig, _ = fixture(elevation=0)
        _, _, report = tpose.convert(rig, "AUTO")
        self.assertEqual(report["source_pose"], "T")
        self.assertEqual(report["rotated_semantic_joints"], [])

    def test_ambiguous_pose_does_not_create_copies(self):
        rig, _ = fixture(elevation=30)
        count = len(bpy.data.objects)
        with self.assertRaises(ValueError):
            tpose.convert(rig, "AUTO")
        self.assertEqual(len(bpy.data.objects), count)

    def test_declared_t_rejects_a_pose(self):
        rig, _ = fixture()
        with self.assertRaises(ValueError):
            tpose.convert(rig, "AUTO", "T")

    def test_t_intermediate_then_dsr_rest_conversion(self):
        rig, _ = fixture()
        intermediate, _, first = tpose.convert(rig, "AUTO")
        result, _, second = pose.convert_armature(intermediate)
        self.assertEqual(first["sequence"], "A -> T -> DSR")
        self.assertEqual(second["source"], intermediate.name)
        self.assertEqual(second["leg_mode"], "spread_only_preserve_pitch_and_foot_orientation")
        self.assertTrue(result["dsr_pose_baked_to_rest"])

    def test_static_freeze_keeps_visible_morph_and_constrained_pose(self):
        import _raw_model
        rig, obj = fixture()
        obj.shape_key_add(name="Basis")
        shape = obj.shape_key_add(name="VisibleExpression")
        shape.data[1].co.z += .07
        shape.value = .6
        control = bpy.data.objects.new("Control", None)
        bpy.context.scene.collection.objects.link(control)
        control.rotation_euler.z = .12
        constraint = rig.pose.bones["upperarm_L"].constraints.new("COPY_ROTATION")
        constraint.target = control
        constraint.mix_mode = "ADD"
        bpy.context.view_layer.update()
        before = _raw_model.evaluated_points(obj)
        work = Path.cwd() / "extracted/dsr_skill_validation/static_current_mix"
        _raw_model.freeze({"input": "fixture.blend", "rig_object": "Fixture", "mesh_objects": ["FixtureMesh"],
                           "static_morph_policy": "current_visible"}, work)
        result = bpy.data.objects["FixtureMesh"]
        self.assertIsNone(result.data.shape_keys)
        self.assertTrue(all(not b.constraints for b in bpy.data.objects["DSR_Rig"].pose.bones))
        self.assertLess(max((a - b).length for a, b in zip(before, _raw_model.evaluated_points(result))), 1e-5)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(TposeTests))
    if not result.wasSuccessful():
        raise RuntimeError("T-pose normalization tests failed.")
