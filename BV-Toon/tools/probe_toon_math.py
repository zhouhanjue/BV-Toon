# -*- coding: utf-8 -*-
"""第 7 轮：用数值（不渲染）查清两件事。

    blender -b --python tools/probe_toon_math.py -- [--pmx <model.pmx>]

1. 材质采样到的 toon 图**是不是渐变**：打印图的尺寸、色彩空间，以及 u=0.5 这一列
   在 v=0.05/0.5/0.95 处的灰度（若三者几乎相同 → 图是平的，查表自然出常数）
2. **V 坐标在模型上会不会变**：按组里那条链的算法（世界法线 → 绕竖轴转 受光方向×2π
   → 取 X → ×0.5+0.5）在全部顶点上算一遍，打印分位数
"""

import os
import sys

import bpy

WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ODETTE = os.path.join(os.path.expanduser("~"), "Desktop",
                      "\u65b0\u5efa\u6587\u4ef6\u5939",
                      "\u5965\u9edb\u5854 \u539f\u6a21\u578b.pmx")
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
PMX = argv[argv.index("--pmx") + 1] if "--pmx" in argv else ODETTE


def column_greys(image):
    """u=0.5 这一列上若干 v 处的灰度。"""
    width, height = image.size
    pixels = image.pixels[:]
    out = []
    for v in (0.05, 0.25, 0.5, 0.75, 0.95):
        x = min(width - 1, int(width * 0.5))
        y = min(height - 1, int(height * v))
        index = (y * width + x) * 4
        r, g, b = pixels[index], pixels[index + 1], pixels[index + 2]
        out.append(round(0.2126 * r + 0.7152 * g + 0.0722 * b, 4))
    return out


def main():
    import addon_utils
    import math
    from mathutils import Vector

    print("MATH_START model=%s" % PMX)
    if not os.path.isfile(PMX):
        print("MATH_SKIP")
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
    scene = bpy.context.scene
    if hasattr(scene, "bv_mode"):
        scene.bv_mode = "REPLACE_MODEL"
    print("MATH one_click=%s" % (bpy.ops.bvtoon.one_click(),))

    # ---- ① 采样到的 toon 图是不是渐变 ----
    seen = []
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
        if sample.image.name in [s[0] for s in seen]:
            continue
        seen.append((sample.image.name, sample.image.colorspace_settings.name,
                     tuple(sample.image.size), column_greys(sample.image)))
        if len(seen) >= 6:
            break
    for name, space, size, greys in seen:
        print("MATH image=%-22s space=%-10s size=%sx%s  u=0.5 列 v=0.05/0.25/0.5/0.75/0.95 -> %s"
              % (name, space, size[0], size[1], greys))

    # ---- ② V 坐标在模型上会不会变 ----
    angle = 0.42 * 2.0 * math.pi          # 预设里的「受光方向」
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    vs = []
    for obj in model:
        matrix = obj.matrix_world.to_3x3()
        for vert in obj.data.vertices:
            n = (matrix @ vert.normal)
            if n.length < 1e-6:
                continue
            n = n.normalized()
            x = n.x * cos_a - n.y * sin_a       # 绕竖轴转，再取 X
            vs.append(x * 0.5 + 0.5)
    if vs:
        vs.sort()
        pick = lambda r: round(vs[min(len(vs) - 1, int(len(vs) * r))], 4)
        print("MATH V(受光程度) 顶点数=%d min=%.4f p05=%.4f p50=%.4f p95=%.4f max=%.4f"
              % (len(vs), vs[0], pick(0.05), pick(0.50), pick(0.95), vs[-1]))
        span = pick(0.95) - pick(0.05)
        print("MATH V_SPAN p95-p05 = %.4f  %s"
              % (span, "OK(会变)" if span > 0.3 else "TOO_FLAT(V 几乎不变 → 查表必然出常数)"))
    print("MATH_END")


main()
