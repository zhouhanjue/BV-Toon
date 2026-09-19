# -*- coding: utf-8 -*-
"""第 8 轮：MMD 渐变图的渐变方向（U 还是 V）。

    blender -b --python tools/probe_toon_axis.py -- [--pmx <model.pmx>]

打印每张被用到的 toon 图：整幅的 min/max 灰度、**最暗像素的坐标**、
以及 u=0.5 的一列 与 v=0.5 的一行。最暗像素落在哪条边，渐变轴就是哪条。
"""

import os
import sys

import bpy

ODETTE = os.path.join(os.path.expanduser("~"), "Desktop",
                      "\u65b0\u5efa\u6587\u4ef6\u5939",
                      "\u5965\u9edb\u5854 \u539f\u6a21\u578b.pmx")
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
PMX = argv[argv.index("--pmx") + 1] if "--pmx" in argv else ODETTE


def grey(pixels, index):
    r, g, b = pixels[index], pixels[index + 1], pixels[index + 2]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def scan(image):
    width, height = image.size
    pixels = image.pixels[:]
    darkest = (2.0, 0, 0)
    brightest = (-1.0, 0, 0)
    for y in range(height):
        for x in range(width):
            value = grey(pixels, (y * width + x) * 4)
            if value < darkest[0]:
                darkest = (value, x, y)
            if value > brightest[0]:
                brightest = (value, x, y)
    row = []
    column = []
    for step in (0.05, 0.35, 0.65, 0.95):
        x = min(width - 1, int(width * step))
        y = min(height - 1, int(height * 0.5))
        row.append(round(grey(pixels, (y * width + x) * 4), 3))
        x2 = min(width - 1, int(width * 0.5))
        y2 = min(height - 1, int(height * step))
        column.append(round(grey(pixels, (y2 * width + x2) * 4), 3))
    return width, height, darkest, brightest, row, column


def main():
    import addon_utils
    print("AXIS_START")
    if not os.path.isfile(PMX):
        print("AXIS_SKIP")
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
    print("AXIS one_click=%s" % (bpy.ops.bvtoon.one_click(),))

    done = set()
    for mat in bpy.data.materials:
        if mat.node_tree is None:
            continue
        sample = mat.node_tree.nodes.get("bv_toon_sample")
        group = mat.node_tree.nodes.get("bv_shading")
        if sample is None or group is None or sample.image is None:
            continue
        strength = group.inputs.get("渐变强度")
        if strength is not None and float(strength.default_value) <= 0.0:
            continue
        if sample.image.name in done:
            continue
        done.add(sample.image.name)
        width, height, darkest, brightest, row, column = scan(sample.image)
        axis_u = "U" if darkest[1] != brightest[1] else "-"
        print("AXIS %-20s %dx%d  最暗=%.3f@(%d,%d)  最亮=%.3f@(%d,%d)"
              % (sample.image.name, width, height, darkest[0], darkest[1],
                 darkest[2], brightest[0], brightest[1], brightest[2]))
        print("AXIS     行(v=0.5) u=0.05/0.35/0.65/0.95 -> %s" % row)
        print("AXIS     列(u=0.5) v=0.05/0.35/0.65/0.95 -> %s" % column)
        print("AXIS     渐变明显在: U=%s V=%s"
              % (axis_u, "V" if darkest[2] != brightest[2] else "-"))
        if len(done) >= 5:
            break
    print("AXIS_END")


main()
