# -*- coding: utf-8 -*-
r"""验收：腮红是不是**只加在脸上**。

    # 一次性配置（不碰已装副本；脚本里有安全闸）
    $env:BLENDER_USER_CONFIG=...; $env:BLENDER_USER_SCRIPTS=...; $env:BLENDER_USER_EXTENSIONS=...
    blender -b --factory-startup --python tools\check_blush_face.py -- <zip> [出图目录]

渲三张同机位图：

1. `1-no-blush.png`          —— 一键卡渲后、**没加腮红**
2. `2-face-blush.png`        —— 点「添加腮红（只给脸）」
3. `3-blush-everywhere.png`  —— **对照**：手动把腮红写到所有卡渲材质上（模拟改之前的行为）

断言（关键在第三条 —— 没有它，前两条可能是"假通过"）：

* 只加脸那张**确实有变化**（腮红看得见）
* 只加脸那张的变化**全部落在头部那一条**里（衣服/裙子/腿不许有变化）
* **对照**那张必须出现"头部以下"的变化 —— 否则说明这套测法根本检测不出跑偏的腮红

出图：三张全图 + 一张头部放大裁图（`tools/crop_png.py`，3 倍）。
"""

import os
import subprocess
import sys

import bpy
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
def _newest_zip():
    """默认用 dist 里**最新**的那个 zip（别再写死版本号，改一次忘一次）。"""
    import glob
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    found = glob.glob(os.path.join(root, "dist", "BV-Toon-*.zip"))
    if not found:
        raise SystemExit("找不到 dist\\BV-Toon-*.zip，先跑 tools\\package_bv_toon.py")
    return max(found, key=os.path.getmtime)


ZIP = argv[0] if argv else _newest_zip()
OUT = os.path.abspath(argv[1]) if len(argv) > 1 else os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_blush_demo")
ODETTE = os.path.join(os.path.expanduser("~"), "Desktop",
                      "\u65b0\u5efa\u6587\u4ef6\u5939",
                      "\u5965\u9edb\u5854 \u539f\u6a21\u578b.pmx")
TOOLS = os.path.dirname(os.path.abspath(__file__))

#: 头部那一条：模型高度的上面这么多（含头发；保守取宽一点）
HEAD_BAND = 0.35

FAIL = []


def chk(name, ok, detail=""):
    print("  [%s] %s%s" % ("ok  " if ok else "FAIL", name,
                           ("  (%s)" % detail) if detail else ""))
    if not ok:
        FAIL.append(name)


def main():
    real = os.path.join(os.path.expanduser("~"), "AppData", "Roaming",
                        "Blender Foundation")
    scripts = bpy.utils.user_resource("SCRIPTS") or ""
    if os.path.realpath(scripts).lower().startswith(os.path.realpath(real).lower()):
        print("BLUSH_ABORT scripts dir 落在真实用户配置里：%s" % scripts)
        return 2
    if not os.path.isfile(ZIP):
        print("BLUSH_ABORT 找不到 zip：%s" % ZIP)
        return 2
    if not os.path.isfile(ODETTE):
        print("BLUSH_ABORT 找不到模型：%s" % ODETTE)
        return 2
    os.makedirs(OUT, exist_ok=True)

    print("BLUSH install ->", bpy.ops.preferences.addon_install(filepath=ZIP,
                                                                overwrite=True))
    print("BLUSH enable  ->", bpy.ops.preferences.addon_enable(module="BV-Toon"))
    import addon_utils
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for key in ("bl_ext.blender_org.mmd_tools", "mmd_tools"):
        try:
            addon_utils.enable(key, default_set=True, persistent=True)
            break
        except Exception as error:
            print("BLUSH mmd_tools 启用失败：%r" % (error,))
    if not hasattr(bpy.ops.mmd_tools, "import_model"):
        print("BLUSH_ABORT mmd_tools 没真的启用（隔离配置里没拷到它）")
        return 2
    addon_utils.enable("BV-Toon", default_set=True, persistent=True)
    module = sys.modules["BV-Toon"]
    materials_api = module.bv_materials

    scene = bpy.context.scene
    for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            scene.render.engine = engine
            break
        except Exception:
            continue
    scene.render.resolution_x = 900
    scene.render.resolution_y = 1200
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    try:
        scene.eevee.taa_render_samples = 16
    except Exception:
        pass
    world = bpy.data.worlds.new("blush_black") if not bpy.data.worlds \
        else bpy.data.worlds[0]
    scene.world = world
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    if background is not None:
        background.inputs[0].default_value = (0.0, 0.0, 0.0, 1.0)
        background.inputs[1].default_value = 0.0
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "Standard"

    bpy.ops.mmd_tools.import_model(filepath=ODETTE, scale=0.08, clean_model=True)
    model = [obj for obj in scene.objects
             if obj.type == "MESH" and obj.data is not None
             and getattr(obj, "mmd_type", "NONE") == "NONE"]
    bpy.ops.object.select_all(action='DESELECT')
    for obj in model:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = model[0]
    scene.bv_mode = "REPLACE_MODEL"
    print("BLUSH one_click=%s" % (bpy.ops.bvtoon.one_click(),))

    # 正交相机框住整个人（与 tools/render_toon_ab.py 同一套算法），并算出"头部那一条"的行号
    from mathutils import Vector
    points = [obj.matrix_world @ Vector(corner)
              for obj in model for corner in obj.bound_box]
    low = Vector((min(p.x for p in points), min(p.y for p in points),
                  min(p.z for p in points)))
    high = Vector((max(p.x for p in points), max(p.y for p in points),
                   max(p.z for p in points)))
    centre = (low + high) / 2.0
    size = max(high.z - low.z, high.x - low.x) * 1.15
    camera_data = bpy.data.cameras.new("blush_cam")
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = size
    camera = bpy.data.objects.new("blush_cam", camera_data)
    scene.collection.objects.link(camera)
    camera.location = centre + Vector((0.0, -(high.y - low.y) * 2.0 - size, 0.0))
    camera.rotation_euler = (1.5707963, 0.0, 0.0)
    scene.camera = camera

    height = scene.render.resolution_y
    z_bottom = centre.z - size / 2.0
    head_z = high.z - HEAD_BAND * (high.z - low.z)
    head_row = int(round((head_z - z_bottom) / size * height))     # 行号从下往上
    print("BLUSH 头部那一条：行 >= %d / %d（模型上沿往下 %.0f%%）"
          % (head_row, height, HEAD_BAND * 100))

    def shoot(name):
        path = os.path.join(OUT, name)
        scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        image = bpy.data.images.load(path, check_existing=False)
        buffer = np.empty(len(image.pixels), dtype=np.float32)
        image.pixels.foreach_get(buffer)
        shape = tuple(image.size)
        bpy.data.images.remove(image)
        return path, buffer.reshape(shape[1], shape[0], 4)

    shadable = [mat for mat in bpy.data.materials
                if mat.node_tree is not None
                and mat.node_tree.nodes.get("bv_shading") is not None]
    print("BLUSH 卡渲材质 %d 个" % len(shadable))

    _, frame_none = shoot("1-no-blush.png")

    print("BLUSH add_blush -> %s" % (bpy.ops.bvtoon.add_blush(),))
    face, why = materials_api.face_materials(
        shadable, [obj for obj in scene.objects if obj.type == "MESH"])
    print("BLUSH 认出的脸材质：%s（%s）" % ([mat.name for mat in face], why))
    print("BLUSH 面板记下的脸材质：%s" % scene.get("bv_face_materials"))
    chk("认得出脸部材质", bool(face), why[:70])
    chk("脸材质是「颜」系的名字", any("颜" in mat.name or "顔" in mat.name
                                     for mat in face),
        str([mat.name for mat in face]))
    chk("脸部材质腮红 > 0",
        all((materials_api.blush_amount(mat) or 0) > 0 for mat in face),
        str([materials_api.blush_amount(mat) for mat in face]))
    others = [mat.name for mat in shadable
              if mat not in face and (materials_api.blush_amount(mat) or 0) > 0]
    chk("非脸部材质上没有腮红", not others, str(others[:6]))
    chk("加腮红的材质数远少于卡渲材质数",
        len(face) < max(1, len(shadable) // 2), "%d / %d" % (len(face), len(shadable)))

    _, frame_face = shoot("2-face-blush.png")

    # 模型自带腮红贴图（照れ）当遮罩的那条路：对同一批脸部材质把遮罩摘掉再渲一张，
    # 两张一比就知道"贴图有没有真的起作用"（贴图版应该更集中，而且落在着色器版的范围里）
    texture, why = materials_api.blush_texture(shadable)
    print("BLUSH 腮红贴图：%s（%s）" % (getattr(texture, "name", None), why))
    masked_sources = {mat.name: materials_api.blush_mask_source(mat)
                      for mat in face if materials_api.blush_mask_source(mat)}
    print("BLUSH 脸部材质的遮罩来源：%s" % masked_sources)
    shader_only = None
    if texture is not None:
        chk("认得出模型自带腮红贴图", True, getattr(texture, "name", "?"))
        chk("脸部材质都接上了贴图遮罩",
            len(masked_sources) == len(face), "%d / %d" % (len(masked_sources), len(face)))
        for mat in face:
            materials_api.clear_blush_mask(mat)
        _, shader_only = shoot("2b-face-blush-shaderonly.png")
        for mat in face:
            materials_api.wire_blush_mask(mat, texture)
    else:
        print("BLUSH note: 这个模型没有腮红贴图，只有着色器腮红（也测）")

    # 对照：把腮红写到所有卡渲材质上（改之前的行为）
    for mat in shadable:
        materials_api.set_blush(mat, materials_api.BLUSH_STRENGTH)
    _, frame_all = shoot("3-blush-everywhere.png")

    def rows_changed(a, b):
        mask = np.abs(a - b).max(axis=2) > 0.05
        rows = np.nonzero(mask)[0]
        return mask.sum(), (int(rows.min()), int(rows.max())) if len(rows) else None

    face_px, face_rows = rows_changed(frame_none, frame_face)
    all_px, all_rows = rows_changed(frame_none, frame_all)
    print("BLUSH 只加脸：变了 %d 个像素，行范围 %s（头部那条从 %d 行起）"
          % (face_px, face_rows, head_row))
    print("BLUSH 全都加：变了 %d 个像素，行范围 %s" % (all_px, all_rows))

    # 贴图遮罩版本来就窄 —— 作者画的就是两个脸颊点（实测 ~190 像素），
    # 所以"看得见"不能只按像素数判，还要看**强度**（变化像素里最大通道差的均值）。
    def strength_of(a, b):
        delta = np.abs(a[:, :, :3] - b[:, :, :3]).max(axis=2)
        picked = delta > 0.05
        return float(delta[picked].mean()) if picked.any() else 0.0

    face_strength = strength_of(frame_none, frame_face)
    chk("只加脸：腮红确实画到了图上", face_px > 80, "%d 个像素" % face_px)
    # 强度不设"绝对阈值" —— 那是我拍脑袋定的（0.06 / 0.08 都试过，纯属巧合地卡在边界）。
    # 真正有意义的是**跟参照比**：不比已经认可的着色器腮红淡，见下面那条。
    print("BLUSH 贴图遮罩版强度：%.3f（变化像素的最大通道差均值）" % face_strength)
    chk("只加脸：变化全在头部那一条里",
        bool(face_rows) and face_rows[0] >= head_row,
        "最低变化行 %s / 头部线 %d" % (face_rows[0] if face_rows else "-", head_row))
    chk("对照（全都加）：头部以下确实会变 —— 说明这套测法测得出跑偏",
        bool(all_rows) and all_rows[0] < head_row,
        "最低变化行 %s / 头部线 %d" % (all_rows[0] if all_rows else "-", head_row))
    chk("只加脸的变化范围明显小于全都加",
        face_px < all_px * 0.5, "%d vs %d" % (face_px, all_px))

    if shader_only is not None:
        shader_px, shader_rows = rows_changed(frame_none, shader_only)
        shader_strength = strength_of(frame_none, shader_only)
        print("BLUSH 摘掉贴图遮罩（纯着色器腮红）：变了 %d 个像素，行范围 %s，强度 %.3f"
              % (shader_px, shader_rows, shader_strength))
        chk("贴图版不比着色器版淡（强度至少一半）",
            face_strength > 0.5 * shader_strength,
            "贴图版 %.3f ｜ 着色器版 %.3f" % (face_strength, shader_strength))
        # 1.7.1 起"着色器腮红"= `腮红保底 + (1-保底) × 脸颊圈`（整块脸有底色、两颊最浓），
        # 贴图版是作者画的形状 —— 两者**位置要重合**（都在同一条脸颊带上），
        # 但不再要求谁包含谁：贴图版可以更窄，着色器版会铺满整块脸材质。
        chk("贴图版与着色器版落在同一条脸颊带上（行范围重叠）",
            bool(face_rows) and bool(shader_rows)
            and face_rows[0] <= shader_rows[1] and shader_rows[0] <= face_rows[1],
            "贴图版 %s ｜ 着色器版 %s" % (face_rows, shader_rows))
        chk("没贴图时着色器腮红也看得见",
            shader_px > 80, "%d 个像素（强度 %.3f）" % (shader_px, shader_strength))
        chk("两版都要在头部那一条里",
            bool(shader_rows) and shader_rows[0] >= head_row,
            "着色器版最低行 %s / 头部线 %d" % (shader_rows[0] if shader_rows else "-",
                                              head_row))

    # 头部放大裁图，方便一眼看腮红
    box = "0,%d,%d,%d" % (max(0, head_row - 40), 900, 1200)
    process = subprocess.run([bpy.app.binary_path, "-b", "--factory-startup",
                              "--python", os.path.join(TOOLS, "crop_png.py"), "--",
                              "--in", os.path.join(OUT, "2-face-blush.png"),
                              "--out", os.path.join(OUT, "2-face-blush-head.png"),
                              "--box", box, "--zoom", "2"],
                             capture_output=True, text=True, encoding="utf-8",
                             errors="replace")
    for line in (process.stdout or "").splitlines():
        if line.startswith("CROP"):
            print("BLUSH %s" % line)

    print("BLUSH_SUMMARY failures=%d" % len(FAIL))
    for item in FAIL:
        print("BLUSH_FAIL", item)
    print("BLUSH_END")
    return 1 if FAIL else 0


sys.exit(main())
