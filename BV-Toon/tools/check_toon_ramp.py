# -*- coding: utf-8 -*-
"""第 1 项验收（上半）：渐变贴图查表有没有真的接上。

    blender -b --python tools/check_toon_ramp.py -- [--pmx <model.pmx>]

看的是"接上了没有、有多少材质有渐变贴图"，不看观感（观感要渲 A/B，见下一步）。
"""

import os
import sys

import bpy

WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ODETTE = os.path.join(os.path.expanduser("~"), "Desktop",
                      "\u65b0\u5efa\u6587\u4ef6\u5939",
                      "\u5965\u9edb\u5854 \u539f\u6a21\u578b.pmx")


def main():
    opts = {"pmx": ODETTE}
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if "--pmx" in argv:
        opts["pmx"] = argv[argv.index("--pmx") + 1]
    import addon_utils
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for key in ("bl_ext.blender_org.mmd_tools", "mmd_tools"):
        try:
            addon_utils.enable(key, default_set=True, persistent=True)
            break
        except Exception:
            continue
    addon_utils.enable("BV-Toon", default_set=True, persistent=True)

    bpy.ops.mmd_tools.import_model(filepath=opts["pmx"], scale=0.08,
                                   clean_model=True)
    model = [obj for obj in bpy.context.scene.objects
             if obj.type == "MESH" and obj.data is not None
             and getattr(obj, "mmd_type", "NONE") == "NONE"]
    bpy.ops.object.select_all(action='DESELECT')
    for obj in model:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = model[0]
    scene = bpy.context.scene
    if hasattr(scene, "bvtoon_mode"):
        scene.bvtoon_mode = "REPLACE_MODEL"
    print("TOONRAMP_START one_click=%s" % bpy.ops.bvtoon.one_click())

    materials = []
    for obj in model:
        for slot in obj.material_slots:
            if slot.material is not None and slot.material not in materials:
                materials.append(slot.material)
    with_toon = [m for m in materials
                 if getattr(getattr(m, "mmd_material", None), "toon_texture", "")
                 or getattr(getattr(m, "mmd_material", None),
                            "is_shared_toon_texture", False)]
    sampled = [m for m in materials if m.node_tree is not None
               and m.node_tree.nodes.get("bv_toon_mask") is not None]
    linked = []
    strengths = []
    for mat in materials:
        node = mat.node_tree.nodes.get("bv_shading") if mat.node_tree else None
        if node is None:
            continue
        socket = node.inputs.get("渐变遮罩")
        if socket is not None and socket.links:
            linked.append(mat)
        strength = node.inputs.get("渐变强度")
        if strength is not None:
            strengths.append(round(float(strength.default_value), 3))

    print("TOONRAMP materials=%d with_toon=%d sampler_built=%d linked=%d"
          % (len(materials), len(with_toon), len(sampled), len(linked)))
    print("TOONRAMP strengths=%s" % sorted(set(strengths)))
    print("TOONRAMP sample_image=%s" % [m.node_tree.nodes["bv_toon_sample"].image.name
                                        for m in sampled[:3]
                                        if m.node_tree.nodes.get("bv_toon_sample")
                                        and m.node_tree.nodes["bv_toon_sample"].image])
    failures = []
    if not sampled:
        failures.append("没有任何材质建出渐变查表节点")
    if len(linked) < len(sampled):
        failures.append("有材质建了查表却没接到组输入")
    print("TOONRAMP_SUMMARY failures=%d checks=3" % len(failures))
    for line in failures:
        print("FAILED:", line)


main()
