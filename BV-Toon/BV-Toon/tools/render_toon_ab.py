# -*- coding: utf-8 -*-
"""第 1 项验收（下半）：渐变贴图开 / 关 的观感 A/B。

    blender -b --python tools/render_toon_ab.py -- [--pmx <model.pmx>]

同一机位、同一无光环境渲两张（渐变强度 0 / 1），再逐像素比对并把统计打出来。
两张 PNG 落在 docs/ 下，可以直接看图。
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
TAG = argv[argv.index("--tag") + 1] if "--tag" in argv else "toonramp"


def setup_scene():
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
    scene.render.resolution_x = 720
    scene.render.resolution_y = 900
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    try:
        scene.eevee.taa_render_samples = 16
    except Exception:
        pass
    # 无光环境：卡渲本来就是全自发光，背景要黑，这样看得清模型自己
    world = bpy.data.worlds.new("bv_black") if not bpy.data.worlds else bpy.data.worlds[0]
    scene.world = world
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    if background is not None:
        background.inputs[0].default_value = (0.0, 0.0, 0.0, 1.0)
        background.inputs[1].default_value = 0.0
    scene.render.film_transparent = True
    return scene


def add_camera(scene, objects):
    """正交相机，正面框住整个模型（范围可预测，不用猜焦距）。"""
    from mathutils import Vector
    points = []
    for obj in objects:
        for corner in obj.bound_box:
            points.append(obj.matrix_world @ Vector(corner))
    if not points:
        return None
    low = Vector((min(p.x for p in points), min(p.y for p in points),
                  min(p.z for p in points)))
    high = Vector((max(p.x for p in points), max(p.y for p in points),
                   max(p.z for p in points)))
    centre = (low + high) / 2.0
    size = max(high.z - low.z, high.x - low.x) * 1.15

    camera_data = bpy.data.cameras.new("bv_cam")
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = size
    camera = bpy.data.objects.new("bv_cam", camera_data)
    scene.collection.objects.link(camera)
    camera.location = centre + Vector((0.0, -(high.y - low.y) * 2.0 - size, 0.0))
    camera.rotation_euler = (1.5707963, 0.0, 0.0)
    scene.camera = camera
    return camera


def set_ramp(value):
    """把每个材质的「渐变强度」设成 value（没有渐变遮罩的保持 0）。"""
    touched = 0
    for mat in bpy.data.materials:
        if mat.node_tree is None:
            continue
        node = mat.node_tree.nodes.get("bv_shading")
        if node is None:
            continue
        socket = node.inputs.get("渐变强度")
        mask = node.inputs.get("渐变遮罩")
        if socket is None:
            continue
        has_mask = mask is not None and bool(mask.links)
        socket.default_value = value if has_mask else 0.0
        touched += 1 if has_mask else 0
    return touched


def shoot(scene, name):
    scene.render.filepath = os.path.join(OUT, name)
    bpy.ops.render.render(write_still=True)
    print("   wrote %s" % scene.render.filepath)
    scene.render.film_transparent = True
    return scene.render.filepath + ".png" if not name.endswith(".png") \
        else scene.render.filepath


def stats(path):
    image = bpy.data.images.load(path, check_existing=False)
    pixels = list(image.pixels)
    width, height = image.size
    lum = []
    for index in range(0, len(pixels), 4):
        if pixels[index + 3] <= 0.5:
            continue
        r, g, b = pixels[index], pixels[index + 1], pixels[index + 2]
        lum.append(0.2126 * r + 0.7152 * g + 0.0722 * b)
    bpy.data.images.remove(image)
    return lum, pixels, width, height


def main():
    print("TOONAB_START model=%s" % PMX)
    if not os.path.isfile(PMX):
        print("TOONAB_SKIP model not found")
        return
    os.makedirs(OUT, exist_ok=True)
    scene = setup_scene()
    bpy.ops.mmd_tools.import_model(filepath=PMX, scale=0.08, clean_model=True)
    model = [obj for obj in scene.objects
             if obj.type == "MESH" and obj.data is not None
             and getattr(obj, "mmd_type", "NONE") == "NONE"]
    bpy.ops.object.select_all(action='DESELECT')
    for obj in model:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = model[0]
    if hasattr(scene, "bv_mode"):
        scene.bv_mode = "REPLACE_MODEL"       # 自研版的属性名
    elif hasattr(scene, "bvtoon_mode"):
        scene.bvtoon_mode = "REPLACE_MODEL"
    print("TOONAB one_click=%s" % (bpy.ops.bvtoon.one_click(),))
    add_camera(scene, model)

    linked = set_ramp(0.0)
    print("TOONAB materials_with_ramp=%d" % linked)
    off = shoot(scene, TAG + "_off.png")
    set_ramp(1.0)
    on = shoot(scene, TAG + "_on.png")

    off_lum, off_px, width, height = stats(off)
    on_lum, on_px, _, _ = stats(on)
    total = len(off_lum)
    diff = [abs(a - b) for a, b in zip(off_lum, on_lum)]
    changed = sum(1 for value in diff if value > 0.05)
    off_sorted = sorted(off_lum)
    on_sorted = sorted(on_lum)

    def pct(values, ratio):
        return values[min(len(values) - 1, int(len(values) * ratio))]

    print("TOONAB size=%dx%d pixels=%d" % (width, height, total))
    print("TOONAB mean_lum off=%.4f on=%.4f" % (sum(off_lum) / total,
                                                sum(on_lum) / total))
    print("TOONAB mean_abs_diff=%.4f changed_gt_0.05=%.2f%%"
          % (sum(diff) / total, 100.0 * changed / total))
    print("TOONAB lum_p05 off=%.3f on=%.3f | p50 off=%.3f on=%.3f | p95 off=%.3f on=%.3f"
          % (pct(off_sorted, 0.05), pct(on_sorted, 0.05),
             pct(off_sorted, 0.50), pct(on_sorted, 0.50),
             pct(off_sorted, 0.95), pct(on_sorted, 0.95)))
    verdict = "CHANGED" if changed > total * 0.02 else "NO_VISIBLE_CHANGE"
    print("TOONAB_VERDICT %s" % verdict)
    print("TOONAB_END")


main()
