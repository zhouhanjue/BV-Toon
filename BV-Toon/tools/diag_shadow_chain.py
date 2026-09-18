# -*- coding: utf-8 -*-
"""第 3 轮诊断：分界/暗部这条链到底有没有在起作用，落点在哪。

    blender -b --python tools/diag_shadow_chain.py -- [--pmx <model.pmx>]

渲四张（同机位、无光黑背景）：
  1. baseline             —— 现在的默认值
  2. 宽分界 + 暗部强弱=1 + 暗部色=纯红   —— 暗部会变成显眼的红块，
     红块出现 = 这条链在起作用；红块的位置/大小 = 分界落在哪
  3. 同 2，但 渐变强度=1（用 MMD 渐变贴图）
  4. 同 2，但 渐变强度=0（自建条带）
比较 3 / 4 的差异，就能判断"渐变贴图换掉条带"到底能不能看出来。
"""

import os
import sys

import bpy

WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(WORKSPACE, "docs")
ODETTE = os.path.join(os.path.expanduser("~"), "Desktop",
                      "\u65b0\u5efa\u6587\u4ef6\u5939",
                      "\u5965\u9edb\u5854 \u539f\u6a21\u578b.pmx")

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
PMX = argv[argv.index("--pmx") + 1] if "--pmx" in argv else ODETTE


def setup():
    import addon_utils
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for key in ("bl_ext.blender_org.mmd_tools", "mmd_tools"):
        try:
            addon_utils.enable(key, default_set=True, persistent=True)
            break
        except Exception:
            continue
    addon_utils.enable("BV-Toon", default_set=True, persistent=True)
    scene = bpy.context.scene
    for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            scene.render.engine = engine
            break
        except Exception:
            continue
    scene.render.resolution_x = 480
    scene.render.resolution_y = 600
    scene.render.image_settings.file_format = "PNG"
    world = bpy.data.worlds[0] if bpy.data.worlds else bpy.data.worlds.new("w")
    scene.world = world
    world.use_nodes = True
    node = world.node_tree.nodes.get("Background")
    if node is not None:
        node.inputs[0].default_value = (0.0, 0.0, 0.0, 1.0)
        node.inputs[1].default_value = 0.0
    return scene


def camera(scene, objects):
    from mathutils import Vector
    points = [obj.matrix_world @ Vector(c) for obj in objects for c in obj.bound_box]
    low = Vector((min(p.x for p in points), min(p.y for p in points),
                  min(p.z for p in points)))
    high = Vector((max(p.x for p in points), max(p.y for p in points),
                   max(p.z for p in points)))
    centre = (low + high) / 2.0
    size = max(high.z - low.z, high.x - low.x) * 1.15
    data = bpy.data.cameras.new("probe_cam")
    data.type = "ORTHO"
    data.ortho_scale = size
    cam = bpy.data.objects.new("probe_cam", data)
    scene.collection.objects.link(cam)
    cam.location = centre + Vector((0.0, -(high.y - low.y) * 2.0 - size, 0.0))
    cam.rotation_euler = (1.5707963, 0.0, 0.0)
    scene.camera = cam


def groups():
    for mat in bpy.data.materials:
        if mat.node_tree is None:
            continue
        node = mat.node_tree.nodes.get("bv_shading")
        if node is not None:
            yield mat, node


def force(settings, ramp):
    """settings: 组输入名 -> 值；ramp: 渐变强度（只给有遮罩的材质）。"""
    touched = 0
    for _mat, node in groups():
        for name, value in settings.items():
            socket = node.inputs.get(name)
            if socket is not None:
                socket.default_value = value
        strength = node.inputs.get("渐变强度")
        mask = node.inputs.get("渐变遮罩")
        if strength is not None:
            has_mask = mask is not None and bool(mask.links)
            strength.default_value = ramp if has_mask else 0.0
            touched += 1 if has_mask else 0
    return touched


def shoot(scene, name):
    scene.render.filepath = os.path.join(OUT, name)
    bpy.ops.render.render(write_still=True)
    print("   wrote %s" % scene.render.filepath)


def lum(path):
    image = bpy.data.images.load(path, check_existing=False)
    pixels = image.pixels[:]
    red = 0
    values = []
    for index in range(0, len(pixels), 4):
        r, g, b = pixels[index], pixels[index + 1], pixels[index + 2]
        values.append(0.2126 * r + 0.7152 * g + 0.0722 * b)
        if r > 0.25 and r > g * 1.8 and r > b * 1.8:
            red += 1
    bpy.data.images.remove(image)
    return values, red


def main():
    print("DIAG_START model=%s" % PMX)
    if not os.path.isfile(PMX):
        print("DIAG_SKIP")
        return
    scene = setup()
    bpy.ops.mmd_tools.import_model(filepath=PMX, scale=0.08, clean_model=True)
    model = [obj for obj in scene.objects if obj.type == "MESH"
             and obj.data is not None and getattr(obj, "mmd_type", "NONE") == "NONE"]
    bpy.ops.object.select_all(action='DESELECT')
    for obj in model:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = model[0]
    if hasattr(scene, "bv_mode"):
        scene.bv_mode = "REPLACE_MODEL"
    print("DIAG one_click=%s" % (bpy.ops.bvtoon.one_click(),))
    camera(scene, model)

    # 1. baseline
    touched = force({}, 0.0)
    print("DIAG materials_with_ramp=%d" % touched)
    shoot(scene, "diag_0_baseline.png")
    base, _ = lum(os.path.join(OUT, "diag_0_baseline.png"))

    # 2/3/4. 夸张参数：宽分界 + 暗部染红
    loud = {"分界宽度": 0.5, "暗部深浅": 1.0, "暗部色": (1.0, 0.0, 0.0, 1.0)}
    force(loud, 0.0)
    shoot(scene, "diag_1_band_red.png")
    band, band_red = lum(os.path.join(OUT, "diag_1_band_red.png"))
    force(loud, 1.0)
    shoot(scene, "diag_2_ramp_red.png")
    ramp, ramp_red = lum(os.path.join(OUT, "diag_2_ramp_red.png"))

    total = len(base)
    delta_loud = sum(abs(a - b) for a, b in zip(base, band)) / total
    delta_ramp = sum(abs(a - b) for a, b in zip(band, ramp)) / total
    print("DIAG red_pixels band=%d ramp=%d (total=%d)" % (band_red, ramp_red, total))
    print("DIAG mean_diff baseline->wideband = %.4f" % delta_loud)
    print("DIAG mean_diff wideband->ramp     = %.4f" % delta_ramp)
    if band_red < total * 0.02:
        print("DIAG_VERDICT CHAIN_DEAD  (夸张参数下都没有红色暗部 → 这条链没接到输出)")
    elif delta_ramp > 0.01:
        print("DIAG_VERDICT CHAIN_OK_RAMP_DIFFERS  (暗部能出来，且渐变贴图与条带明显不同)")
    else:
        print("DIAG_VERDICT CHAIN_OK_RAMP_SAME  (暗部能出来，但两种遮罩结果接近)")
    print("DIAG_END")


main()
