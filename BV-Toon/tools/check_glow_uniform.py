# -*- coding: utf-8 -*-
r"""验收：泛光**跨模型一致**（深色角色不能比别人暗）。

    blender -b --factory-startup --python tools\check_glow_uniform.py -- <zip> [出图目录] <模型…>

背景：泛光整条链吃的是**绝对亮度**，所以深色角色几乎不发光。实测（640×853 同机位）奥黛塔
剪影外那圈光 +0.160，而胡桃只有 +0.017 —— 差 7 倍。1.7.2 起「添加泛光」会渲两张 192×192
**实测**剪影外那圈光，再闭环把强度调到目标值（默认只往上调，不把本来就亮的压暗）。

本脚本对每个模型：导入 → 一键卡渲 → 加泛光 → 渲一张"关"、一张"开"，量
**剪影外那圈光被提亮多少**，断言：

* 每个模型都要 **≥ 0.10**（看得见，深色角色不能再"没泛光"）
* 每个模型都要 **≤ 0.45**（别糊成一团白雾）
* 被自动调过强度的模型之间，最大/最小 **≤ 1.6 倍**（这才叫"统一"）

出图：`<名字>-0-noglow.png` / `<名字>-1-glow.png`
"""
import os
import sys

import bpy
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:]
ZIP = argv[0] if argv else None
OUT = os.path.abspath(argv[1]) if len(argv) > 1 else os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_glow_demo")
MODELS = argv[2:]
FAIL = []
HALO_FLOOR = 0.10
HALO_CEIL = 0.45
HALO_TARGET = 0.16        # 和插件里 GLOW_HALO_TARGET 一致（"跟奥黛塔一个量级"）
SPREAD = 1.6

real = os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "Blender Foundation")
if os.path.realpath(bpy.utils.user_resource("SCRIPTS") or "").lower().startswith(
        os.path.realpath(real).lower()):
    print("GLU_ABORT 落在真实用户配置里")
    sys.exit(2)
if not ZIP or not os.path.isfile(ZIP):
    print("GLU_ABORT 找不到 zip：%s" % ZIP)
    sys.exit(2)
os.makedirs(OUT, exist_ok=True)

print("GLU install ->", bpy.ops.preferences.addon_install(filepath=ZIP, overwrite=True))
print("GLU enable  ->", bpy.ops.preferences.addon_enable(module="BV-Toon"))
import addon_utils
from mathutils import Vector


def fresh():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for key in ("bl_ext.blender_org.mmd_tools", "mmd_tools"):
        try:
            addon_utils.enable(key, default_set=True, persistent=True)
            break
        except Exception as error:
            print("GLU mmd_tools 失败：%r" % (error,))
    addon_utils.enable("BV-Toon", default_set=True, persistent=True)
    module = sys.modules["BV-Toon"]
    scene = bpy.context.scene
    for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            scene.render.engine = engine
            break
        except Exception:
            continue
    scene.render.resolution_x = 640
    scene.render.resolution_y = 853
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    try:
        scene.eevee.taa_render_samples = 8
    except Exception:
        pass
    world = bpy.data.worlds.new("glu") if not bpy.data.worlds else bpy.data.worlds[0]
    scene.world = world
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    if background is not None:
        background.inputs[0].default_value = (0.0, 0.0, 0.0, 1.0)
        background.inputs[1].default_value = 0.0
    scene.render.film_transparent = False
    try:
        scene.view_settings.view_transform = "Standard"
    except Exception:
        pass
    return module


def shoot(scene, path):
    scene.render.filepath = os.path.abspath(path)
    bpy.ops.render.render(write_still=True)
    image = bpy.data.images.load(os.path.abspath(path), check_existing=False)
    buffer = np.empty(len(image.pixels), dtype=np.float32)
    image.pixels.foreach_get(buffer)
    shape = tuple(image.size)
    bpy.data.images.remove(image)
    return buffer.reshape(shape[1], shape[0], 4)


def dilate(mask, rounds):
    grown = mask.copy()
    for _ in range(rounds):
        shifted = np.zeros_like(grown)
        shifted[1:, :] |= grown[:-1, :]
        shifted[:-1, :] |= grown[1:, :]
        shifted[:, 1:] |= grown[:, :-1]
        shifted[:, :-1] |= grown[:, 1:]
        grown = shifted
    return grown


fresh()
halos = {}
for path in MODELS:
    label = os.path.splitext(os.path.basename(path))[0]
    print("=" * 78)
    print("GLU 模型 %s" % label)
    if not os.path.isfile(path):
        print("GLU   跳过（文件不存在）")
        continue
    module = fresh()
    scene = bpy.context.scene
    glow = module.bv_glow
    bpy.ops.mmd_tools.import_model(filepath=path, scale=0.08, clean_model=True)
    model = [obj for obj in scene.objects
             if obj.type == "MESH" and obj.data is not None
             and getattr(obj, "mmd_type", "NONE") == "NONE"]
    bpy.ops.object.select_all(action='DESELECT')
    for obj in model:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = model[0]
    scene.bv_mode = "REPLACE_MODEL"
    bpy.ops.bvtoon.one_click()

    points = [obj.matrix_world @ Vector(corner) for obj in model for corner in obj.bound_box]
    low = Vector((min(p.x for p in points), min(p.y for p in points), min(p.z for p in points)))
    high = Vector((max(p.x for p in points), max(p.y for p in points), max(p.z for p in points)))
    centre = (low + high) / 2.0
    size = max(high.z - low.z, high.x - low.x) * 1.15
    cam_data = bpy.data.cameras.new("glu_cam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = size
    cam = bpy.data.objects.new("glu_cam", cam_data)
    scene.collection.objects.link(cam)
    cam.location = centre + Vector((0.0, -(high.y - low.y) * 2.0 - size, 0.0))
    cam.rotation_euler = (1.5707963, 0.0, 0.0)
    scene.camera = cam

    off = shoot(scene, os.path.join(OUT, "%s-0-noglow.png" % label))
    print("GLU   add_glow=%s" % (bpy.ops.bvtoon.add_glow(),))
    on = shoot(scene, os.path.join(OUT, "%s-1-glow.png" % label))
    state, _api, node = glow.glow_state(scene)
    strength = float(node.inputs["强度"].default_value) if node is not None else -1.0
    print("GLU   自动强度 %.2f ｜ %s" % (strength, scene.get("bv_glow_note", "-")))
    if strength < 0:
        FAIL.append("%s：没接上泛光" % label)
        continue
    handlers = [h for h in bpy.app.handlers.render_pre
                if getattr(h, "__name__", "") == "force_watermark"]
    print("  [%s] 量完之后强制署名处理器还在（挂 %d 个）"
          % ("ok  " if handlers else "FAIL", len(handlers)))
    if not handlers:
        FAIL.append("%s：量泛光把强制署名处理器弄丢了" % label)

    base = off[:, :, :3].mean(axis=2)
    lit = on[:, :, :3].mean(axis=2)
    body = base > 0.02
    halo = dilate(body, 6) & ~body & (lit > 0.02)
    if not halo.any():
        print("  [FAIL] 剪影外量不到光")
        FAIL.append("%s：剪影外量不到光" % label)
        continue
    value = float(lit[halo].mean())
    halos[label] = value
    inside = float((lit - base)[body].mean())
    print("GLU   剪影外 %d 像素：平均亮度 %.4f（泛光 %+.4f）｜ 角色上泛光 %+.4f"
          % (int(halo.sum()), value, value - float(base[halo].mean()), inside))
    print("  [%s] 剪影外的光看得见（≥ %.2f）  (%.3f)"
          % ("ok  " if value >= HALO_FLOOR else "FAIL", HALO_FLOOR, value))
    print("  [%s] 剪影外的光没糊成一片（≤ %.2f）  (%.3f)"
          % ("ok  " if value <= HALO_CEIL else "FAIL", HALO_CEIL, value))
    if value < HALO_FLOOR:
        FAIL.append("%s：泛光太弱（%.3f）" % (label, value))
    if value > HALO_CEIL:
        FAIL.append("%s：泛光过曝（%.3f）" % (label, value))

if len(halos) >= 2:
    # 只比"需要归一化"的那批：本来就比目标亮的角色**故意不动**（只往上调，不把亮的压暗），
    # 把它们算进"统一"里会误判（实测 初音ミク 0.27 是设计如此）。
    normalised = {name: value for name, value in halos.items()
                  if value <= HALO_TARGET * 1.3}
    print("=" * 78)
    print("GLU 跨模型：%s" % "、".join("%s %.3f" % item for item in sorted(halos.items())))
    print("GLU   参与「统一」比较的（≤ %.3f）：%s"
          % (HALO_TARGET * 1.3, "、".join("%s %.3f" % item
                                          for item in sorted(normalised.items()))))
    if len(normalised) >= 2:
        spread = max(normalised.values()) / max(min(normalised.values()), 1e-6)
        print("  [%s] 归一化过的模型之间 ≤ %.1f 倍  (%.2f 倍)"
              % ("ok  " if spread <= SPREAD else "FAIL", SPREAD, spread))
        if spread > SPREAD:
            FAIL.append("归一化过的模型之间差 %.2f 倍（上限 %.1f）" % (spread, SPREAD))
    for name, value in halos.items():
        if value < HALO_FLOOR:
            FAIL.append("%s：泛光太弱（%.3f）" % (name, value))

print("=" * 78)
print("GLU_SUMMARY failures=%d" % len(FAIL))
for item in FAIL:
    print("GLU_FAIL", item)
print("GLU_END" if not FAIL else "GLU_END_FAIL")
