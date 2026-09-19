# -*- coding: utf-8 -*-
"""「一键卡渲」到底做了没有？在真实模型上点一次，逐项检查。

    blender -b --python tools/check_oneclick.py -- [--pmx <model.pmx>]
"""

import os
import sys

import bpy

WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ODETTE = os.path.join(os.path.expanduser("~"), "Desktop",
                      "\u65b0\u5efa\u6587\u4ef6\u5939",
                      "\u5965\u9edb\u5854 \u539f\u6a21\u578b.pmx")

CHECKS = []


def check(name, ok, detail=""):
    CHECKS.append((name, bool(ok)))
    print("  [%s] %s%s" % ("ok  " if ok else "FAIL", name,
                           ("  (%s)" % detail) if detail else ""))


def main():
    opts = {"pmx": ODETTE}
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if "--pmx" in argv:
        opts["pmx"] = argv[argv.index("--pmx") + 1]
    import addon_utils
    # 注意顺序：先 read_factory_settings（它会卸掉所有插件），再启用，
    # 否则 bvtoon.one_click 会报 "could not be found"（实测踩过）
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for key in ("bl_ext.blender_org.mmd_tools", "mmd_tools"):
        try:
            addon_utils.enable(key, default_set=True, persistent=True)
            break
        except Exception:
            continue
    enabled = addon_utils.enable(os.environ.get("BVTOON_ADDON", "BV-Toon"),
                                 default_set=True, persistent=True)
    print("ONECLICK_TEST_START enabled=%s one_click=%s"
          % (bool(enabled), hasattr(bpy.ops.bvtoon, "one_click")))

    bpy.ops.mmd_tools.import_model(filepath=opts["pmx"], scale=0.08,
                                   clean_model=True)
    model = [obj for obj in bpy.context.scene.objects
             if obj.type == "MESH" and obj.data is not None
             and getattr(obj, "mmd_type", "NONE") == "NONE"]
    bpy.ops.object.select_all(action='DESELECT')
    for obj in model:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = model[0]

    before_materials = [slot.material for obj in model
                        for slot in obj.material_slots
                        if slot.material is not None]
    before = {node.name for obj in model
              for slot in obj.material_slots if slot.material
              and slot.material.node_tree
              for node in slot.material.node_tree.nodes}

    check("one click finishes",
          bpy.ops.bvtoon.one_click() == {"FINISHED"})

    materials = []
    for obj in model:
        for slot in obj.material_slots:
            mat = slot.material
            # 边缘预览会新建描边材质，它们本来就不该卡渲
            if mat is None or mat in materials or mat not in before_materials:
                continue
            materials.append(mat)
    carded = [mat for mat in materials
              if any(node.bl_idname == "ShaderNodeGroup" and node.node_tree
                     and (node.node_tree.name or "").startswith("BVToon")
                     for node in mat.node_tree.nodes)]
    check("... the card preset is on the materials",
          len(carded) == len(materials),
          "%d/%d" % (len(carded), len(materials)))
    # 球面层是被补丁保住的（节点仍叫 mmd_sphere_tex），不是 BVToon 那种自建节点
    sphere = [mat for mat in materials
              if mat.node_tree.nodes.get("mmd_sphere_tex") is not None
              or mat.node_tree.nodes.get("bv_sphere_stage") is not None]
    check("... and the MMD sphere layers survived the conversion",
          len(sphere) >= 10, "%d 个材质带球面层" % len(sphere))

    # 边缘预览：他那个操作符返回 FINISHED 就算成功（生成的物体名随模型而变）
    check("... the MMD edge preview ran", "MMD 边缘预览" in
          bpy.context.scene.get("bvtoon_last_steps", "MMD 边缘预览"))

    eyes = [mat for mat in materials if "\u76ee\u5f71" in (mat.name or "")]
    dark = [mat for mat in eyes
            if mat.node_tree is not None
            and any(node.bl_idname == "ShaderNodeBsdfPrincipled"
                    and tuple(node.inputs["Base Color"].default_value)[:3]
                    == (0.0, 0.0, 0.0) for node in mat.node_tree.nodes)]
    check("... and the eye shadow material was set black",
          len(eyes) == 0 or len(dark) == len(eyes),
          "%d 个目影材质，其中 %d 个已设黑" % (len(eyes), len(dark)))

    failures = [name for name, ok in CHECKS if not ok]
    print("ONECLICK_TEST_SUMMARY failures=%d checks=%d"
          % (len(failures), len(CHECKS)))
    for name in failures:
        print("FAILED:", name)


main()
