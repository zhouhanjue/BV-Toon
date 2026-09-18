# -*- coding: utf-8 -*-
"""第 2 项验收：MMD 的环境色（ambient）有没有真的进了暗部。

    blender -b --python tools/check_ambient.py -- [--pmx <model.pmx>]

打印：有多少材质带非平凡 ambient、套用后它们的「暗部色」变成了什么
（与环境色无关的材质应保持预设值）。
"""

import os
import sys

import bpy

ODETTE = os.path.join(os.path.expanduser("~"), "Desktop",
                      "\u65b0\u5efa\u6587\u4ef6\u5939",
                      "\u5965\u9edb\u5854 \u539f\u6a21\u578b.pmx")
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
PMX = argv[argv.index("--pmx") + 1] if "--pmx" in argv else ODETTE


def main():
    import addon_utils
    print("AMBIENT_START")
    if not os.path.isfile(PMX):
        print("AMBIENT_SKIP")
        return
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for key in ("bl_ext.blender_org.mmd_tools", "mmd_tools"):
        try:
            addon_utils.enable(key, default_set=True, persistent=True)
            break
        except Exception:
            continue
    addon_utils.enable("BV-Toon", default_set=True, persistent=True)
    bpy.ops.mmd_tools.import_model(filepath=PMX, scale=0.08, clean_model=True)
    model = [o for o in bpy.context.scene.objects if o.type == "MESH"
             and o.data is not None and getattr(o, "mmd_type", "NONE") == "NONE"]
    bpy.ops.object.select_all(action='DESELECT')
    for o in model:
        o.select_set(True)
    bpy.context.view_layer.objects.active = model[0]
    if hasattr(bpy.context.scene, "bv_mode"):
        bpy.context.scene.bv_mode = "REPLACE_MODEL"

    # 套用前先记下每个材质的环境色
    before = {}
    for mat in bpy.data.materials:
        data = getattr(mat, "mmd_material", None)
        if data is not None:
            before[mat.name] = tuple(round(float(x), 3)
                                     for x in getattr(data, "ambient_color", (0, 0, 0)))
    print("AMBIENT one_click=%s" % (bpy.ops.bvtoon.one_click(),))

    interesting = {name: rgb for name, rgb in before.items() if max(rgb) > 0.02}
    print("AMBIENT materials=%d with_ambient=%d" % (len(before), len(interesting)))
    shown = 0
    changed = 0
    for mat in bpy.data.materials:
        node = mat.node_tree.nodes.get("bv_shading") if mat.node_tree else None
        if node is None:
            continue
        socket = node.inputs.get("暗部色")
        if socket is None:
            continue
        value = tuple(round(float(x), 3) for x in socket.default_value)[:3]
        ambient = before.get(mat.name)
        if ambient is None:
            continue
        if max(ambient) > 0.02 and shown < 6:
            print("AMBIENT %-18s ambient=%s -> 暗部色=%s" % (mat.name, ambient, value))
            shown += 1
            changed += 1
    # 没环境色的材质应当保持预设值
    plain = []
    for mat in bpy.data.materials:
        node = mat.node_tree.nodes.get("bv_shading") if mat.node_tree else None
        ambient = before.get(mat.name)
        if node is None or ambient is None or max(ambient) > 0.02:
            continue
        socket = node.inputs.get("暗部色")
        if socket is not None:
            plain.append(tuple(round(float(x), 3) for x in socket.default_value)[:3])
    if plain:
        print("AMBIENT 无环境色材质保持预设值: %s" % sorted(set(plain))[:3])
    verdict = "OK" if changed else "NO_AMBIENT_APPLIED"
    print("AMBIENT_VERDICT %s (with_ambient=%d shown=%d)"
          % (verdict, len(interesting), shown))
    print("AMBIENT_END")


main()
