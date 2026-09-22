# -*- coding: utf-8 -*-
"""MikuMikuToon -- 朦胧泛光（合成器）。

泛光源是渲染的 Emit 通道（角色自带自发光）+ 画面里亮过阈值的部分。卡渲全身自发光，
不打光也出效果，亮背景不跟着糊。参数挂在合成器组节点上（强度 / 阈值 / 大小 / 外发光）。

© 2025 BVan / DEEPSEEK
"""

import os

import bpy

from . import mmt_compat

GLOW_GROUP = "MikuMikuToon_Glow"
GLOW_PREFIX = "MMT_GLOW"
#: 场景标记「本插件建的合成器树」，须与 mmt_compat.TREE_FLAG 同键，否则「移除泛光」清不掉
SCENE_TREE_FLAG = mmt_compat.TREE_FLAG

GLOW_STRENGTH = 0.10      # 泛光往画面上加多少
GLOW_THRESHOLD = 0.95     # 画面里亮过这个值的部分也一起发光（自发光不受它管）
GLOW_WIDE_SIZE = 8        # 大半径那层（1..9）
GLOW_CORE_SIZE = 4        # 贴着亮部那层
GLOW_SATURATION = 0.85    # 泛光去饱和一点，别变成彩色雾
GLOW_TINT = (1.0, 0.98, 0.94, 1.0)
#: Glare 质量档：两层 Glare 是整条链最贵的部分，泛光低频，金字塔少一层看不出来
GLOW_QUALITY = "MEDIUM"
GLOW_MODE = "BLOOM"       # 4.4+ 的灯光型 glare

#: 泛光在几分之一的画布上算（1.0 = 全分辨率，不降）；降画布只对 CPU 合成器省时间，GPU 上不省
GLOW_CANVAS = 1.0
#: 4.5 的合成器默认走 CPU，5.2 默认已是 GPU；用户原设置记在这里，摘泛光时还回去
SCENE_DEVICE_FLAG = "mikumikutoon_glow_device"

GLOW_AURA_SPREAD = 7.0   # 外发光模糊半径（画面百分比）
GLOW_AURA_WEIGHT = 0.12    # 外发光相对亮部泛光的强度
GLOW_AURA_FLOOR = 0.60    # 自发光高过它才算"亮部"（门槛太低会把整个人物糊一遍，画面发白）
GLOW_AURA_TINT = (1.0, 0.96, 0.92, 1.0)

GLOW_HALO_TARGET = 0.16   # 目标：剪影外那圈光平均提亮多少
GLOW_STRENGTH_MIN = 0.03  # 自动强度的夹紧范围（太小的模型量出来会抖）
GLOW_STRENGTH_MAX = 2.50
GLOW_LOOK_FACTOR = 2.0
GLOW_LOOK_MIN = 0.05      # 收力后的下限（别收到看不见）
#: 量泛光时用的分辨率；取样外圈按画面比例取（模糊半径也是画面百分比），取宽了会把亮芯算进来
GLOW_MEASURE_RES = 192
EXPOSURE_TRIGGER = 0.25
EXPOSURE_STOP = 0.03
EXPOSURE_STEP = 0.05
EXPOSURE_FLOOR = 0.75
EXPOSURE_ROUNDS = 4
GLOW_MEASURE_MARGIN = 2
GLOW_ITERATIONS = 3


STRUCTURAL_NODES = {"CompositorNodeRLayers", "CompositorNodeComposite",
                    "NodeGroupOutput", "NodeGroupInput", "NodeReroute",
                    "CompositorNodeViewer", "CompositorNodeOutputFile"}


# ---- 跨版本的小工具 ----

def _glare_node(nodes, label, size, location):
    """一层 glare。阈值固定 0：交给它的东西全部参与泛光（含暗的自发光），画面阈值在源那步做。"""
    node = nodes.new("CompositorNodeGlare")
    node.name = "%s_%s" % (GLOW_PREFIX, label)
    node.label = label
    node.location = location
    # 老版本（<=4.4）用属性，4.5/5.x 在插座上且枚举首字母大写（'Bloom'）；设不上会留默认
    # 'Streaks'，出现绿色重影。
    mmt_compat.set_value(node, "glare_type", GLOW_MODE)
    for socket_name, value in (("Type", GLOW_MODE.title()),
                               ("Quality", GLOW_QUALITY.title()),
                               ("Threshold", 0.0), ("Strength", 1.0),
                               ("Saturation", GLOW_SATURATION),
                               ("Tint", GLOW_TINT),
                               ("Size", float(size) / 9.0)):
        socket = node.inputs.get(socket_name)
        if socket is None:
            continue
        try:
            socket.default_value = value
        except Exception as error:
            print("[MikuMikuToon] Glare 插座 %s 设不上：%s" % (socket_name, error))
    mmt_compat.set_value(node, "quality", GLOW_QUALITY)
    mmt_compat.set_value(node, "mix", 0.0)
    mmt_compat.set_value(node, "threshold", 0.0)
    mmt_compat.set_value(node, "size", int(size))
    mmt_compat.set_value(node, "Type", GLOW_MODE)
    mmt_compat.set_value(node, "Quality", GLOW_QUALITY)
    for name, value in (("Threshold", 0.0), ("Smoothness", 0.0),
                        ("Clamp", False), ("Maximum", 10.0),
                        ("Saturation", 1.0), ("Strength", 1.0), ("Fade", 1.0),
                        ("Color Modulation", 1.0)):
        mmt_compat.set_value(node, name, value)
    tint = mmt_compat.socket_in(node, "Tint", "RGBA")
    if tint is not None:
        tint.default_value = GLOW_TINT
    return node


def _scale_node(nodes, label, title, location, factor):
    """合成器「缩放」节点：4.5 模式在属性 space 上，5.x 在菜单插座 Type 上；设不上泛光会画在全分辨率。"""
    node = nodes.new("CompositorNodeScale")
    node.name = "%s_%s" % (GLOW_PREFIX, label)
    node.label = title
    node.location = location
    if mmt_compat.has(node, "space"):
        mmt_compat.set_value(node, "space", "RELATIVE")
    else:
        menu = node.inputs.get("Type")
        for candidate in ("RELATIVE", "Relative"):
            try:
                menu.default_value = candidate
                break
            except Exception:
                continue   # 试下一个候选枚举值（旧版 RELATIVE，新版 Relative）
    for name in ("X", "Y"):
        socket = node.inputs.get(name)
        if socket is None:
            continue
        try:
            socket.default_value = float(factor)
        except Exception as error:
            print("[MikuMikuToon] 缩放节点 %s 设不上：%s" % (name, error))
    return node


# ---- 组本体 ----

def glow_group():
    group = bpy.data.node_groups.get(GLOW_GROUP)
    if group is not None and len(group.nodes):
        return group
    if group is None:
        group = bpy.data.node_groups.new(GLOW_GROUP, "CompositorNodeTree")
    for name, kind in (("图像", "NodeSocketColor"), ("自发光", "NodeSocketColor"),
                       ("强度", "NodeSocketFloat"), ("阈值", "NodeSocketFloat"),
                       ("大小", "NodeSocketFloat"), ("外发光", "NodeSocketFloat"),
                       ("增益", "NodeSocketFloat")):
        group.interface.new_socket(name, in_out="INPUT", socket_type=kind)
    group.interface.new_socket("泛光", in_out="OUTPUT",
                              socket_type="NodeSocketColor")
    defaults = {"强度": GLOW_STRENGTH, "阈值": GLOW_THRESHOLD,
                "大小": float(GLOW_WIDE_SIZE), "外发光": GLOW_AURA_WEIGHT,
                "增益": 1.0}
    for socket in group.interface.items_tree:
        if socket.name in defaults and hasattr(socket, "default_value"):
            socket.default_value = defaults[socket.name]

    nodes, links = group.nodes, group.links
    source = nodes.new("NodeGroupInput")
    source.location = (-1000, 0)
    sink = nodes.new("NodeGroupOutput")
    sink.location = (900, 0)

    # 降分辨率算泛光（见 GLOW_CANVAS）：前段都在 GLOW_CANVAS 倍的画布上做，
    # 只有最后"加到画面上"那步回到全分辨率，画面本身不经过降采样。
    small = GLOW_CANVAS < 0.999
    small_image = small_emit = canvas_up = None
    if small:
        small_image = _scale_node(nodes, "canvas_dn", "画面降采样", (-1000, -460),
                                  GLOW_CANVAS)
        links.new(source.outputs["图像"], small_image.inputs["Image"])
        small_emit = _scale_node(nodes, "canvas_emit", "自发光降采样", (-1000, -620),
                                 GLOW_CANVAS)
        links.new(source.outputs["自发光"], small_emit.inputs["Image"])
        canvas_up = _scale_node(nodes, "canvas_up", "泛光升采样", (620, -460),
                                1.0 / GLOW_CANVAS)
    image_in = small_image.outputs["Image"] if small else source.outputs["图像"]
    emit_in = small_emit.outputs["Image"] if small else source.outputs["自发光"]

    # 增益：把"模型自己的平均自发光"归一到同一量级；必须在外发光门槛之前，门槛才相对这个模型
    gain_fill = mmt_compat.new_node(nodes, "CompositorNodeCombineColor", "ShaderNodeCombineColor")
    gain_fill.name = "%s_gain_color" % GLOW_PREFIX
    gain_fill.label = "增益"
    gain_fill.location = (-820, 900)
    if mmt_compat.has(gain_fill, "mode"):
        try:
            gain_fill.mode = "RGB"
        except Exception:
            pass   # 这个版本的节点没有该属性，跳过即可
    # 插座名各版本不完全一样（合成器里颜色插座叫 Image），按名字找不到就退回"前三个数值插槽"
    channels = [gain_fill.inputs.get(name) for name in ("Red", "Green", "Blue")]
    if any(item is None for item in channels):
        channels = [socket for socket in gain_fill.inputs if socket.type == "VALUE"][:3]
    for socket in channels:
        if socket is not None:
            links.new(source.outputs["增益"], socket)
    gained, gained_a, gained_b, gained_out = mmt_compat.mix_node(group, "MULTIPLY", 1.0)
    gained.name = "%s_gain" % GLOW_PREFIX
    gained.label = "自发光 × 增益"
    gained.location = (-620, 880)
    links.new(emit_in, gained_a)
    fill_out = mmt_compat.socket_out(gain_fill)
    if fill_out is None:
        raise RuntimeError("合成器里没有可用的「合并颜色」节点")
    links.new(fill_out, gained_b)

    # 源 = 自发光 + (图像 - 阈值)，负数用 LIGHTEN 黑压掉
    over, over_a, over_b, over_out = mmt_compat.mix_node(group, "SUBTRACT", 1.0)
    over.name = "%s_over" % GLOW_PREFIX
    over.label = "图像 - 阈值"
    over.location = (-820, -320)
    links.new(image_in, over_a)
    over_b.default_value = (1.0, 1.0, 1.0, 1.0)
    factor = mmt_compat.factor_socket(over)
    if factor is None:
        factor = over.inputs[0]
    links.new(source.outputs["阈值"], factor)

    floor, floor_a, floor_b, floor_out = mmt_compat.mix_node(group, "LIGHTEN", 1.0)
    floor.name = "%s_floor" % GLOW_PREFIX
    floor.label = "压到黑"
    floor.location = (-620, -320)
    links.new(over_out, floor_a)
    floor_b.default_value = (0.0, 0.0, 0.0, 1.0)

    src, src_a, src_b, src_out = mmt_compat.mix_node(group, "ADD", 1.0)
    src.name = "%s_source" % GLOW_PREFIX
    src.label = "自发光 × 增益 + 高光"
    src.location = (-420, -180)
    links.new(floor_out, src_a)
    links.new(gained_out, src_b)

    scale = mmt_compat.new_node(nodes, "CompositorNodeMath", "ShaderNodeMath")
    scale.name = "%s_size" % GLOW_PREFIX
    scale.label = "大小 ÷ 9"
    scale.operation = "MULTIPLY"
    scale.location = (-820, 260)
    scale.inputs[1].default_value = 1.0 / 9.0
    links.new(source.outputs["大小"], scale.inputs[0])

    wide = _glare_node(nodes, "wide", GLOW_WIDE_SIZE, (-620, 320))
    core = _glare_node(nodes, "core", GLOW_CORE_SIZE, (-620, 80))
    for node in (wide, core):
        links.new(src_out, node.inputs["Image"])
        size = mmt_compat.socket_in(node, "Size", "VALUE")
        if size is not None:
            links.new(scale.outputs[0], size)

    total, total_a, total_b, total_out = mmt_compat.mix_node(group, "ADD", 1.0)
    total.name = "%s_sum" % GLOW_PREFIX
    total.label = "两个半径相加"
    total.location = (-420, 200)
    links.new(mmt_compat.socket_out(wide, "Glare"), total_a)
    links.new(mmt_compat.socket_out(core, "Glare"), total_b)

    separator = mmt_compat.new_node(nodes, "CompositorNodeSeparateColor")
    separator.name = "%s_aura_sep" % GLOW_PREFIX
    separator.label = "自发光 RGB（× 增益后）"
    separator.location = (-820, 640)
    if mmt_compat.has(separator, "mode"):
        separator.mode = "RGB"
    links.new(gained_out, separator.inputs["Image"])

    def _math(label, operation, value=None, location=(-620, 640)):
        node = mmt_compat.new_node(nodes, "CompositorNodeMath", "ShaderNodeMath")
        node.name = "%s_%s" % (GLOW_PREFIX, label)
        node.label = label
        node.operation = operation
        node.location = location
        if value is not None and len(node.inputs) > 1:
            node.inputs[1].default_value = value
        return node

    peak_a = _math("aura_max1", "MAXIMUM", location=(-620, 640))
    links.new(separator.outputs["Red"], peak_a.inputs[0])
    links.new(separator.outputs["Green"], peak_a.inputs[1])
    peak_b = _math("aura_max2", "MAXIMUM", location=(-450, 640))
    links.new(peak_a.outputs[0], peak_b.inputs[0])
    links.new(separator.outputs["Blue"], peak_b.inputs[1])
    gate = _math("aura_gate", "GREATER_THAN", GLOW_AURA_FLOOR, (-280, 640))
    links.new(peak_b.outputs[0], gate.inputs[0])

    tinted, tint_a, tint_b, tint_out = mmt_compat.mix_node(group, "MIX", 1.0)
    tinted.name = "%s_aura_tint" % GLOW_PREFIX
    tinted.label = "剪影染色"
    tinted.location = (-100, 640)
    tint_a.default_value = (0.0, 0.0, 0.0, 1.0)
    tint_b.default_value = GLOW_AURA_TINT
    gate_factor = mmt_compat.factor_socket(tinted)
    if gate_factor is None:
        gate_factor = tinted.inputs[0]
    links.new(gate.outputs[0], gate_factor)

    aura = mmt_compat.new_node(nodes, "CompositorNodeBlur")
    aura.name = "%s_aura" % GLOW_PREFIX
    aura.label = "外发光"
    aura.location = (100, 640)
    if mmt_compat.has(aura, "filter_type"):
        for name in ("GAUSS", "GAUSSIAN", "FAST_GAUSS"):
            try:
                aura.filter_type = name
                break
            except Exception:
                continue   # 读到什么算什么，读不到就算了
    if mmt_compat.has(aura, "use_relative"):
        aura.use_relative = True
    for name in ("size_x", "size_y"):
        if mmt_compat.has(aura, name):
            try:
                setattr(aura, name, int(GLOW_AURA_SPREAD))
            except Exception:
                pass              # 设不上就保持默认
    links.new(tint_out, aura.inputs["Image"])

    glow_mix, glow_a, glow_b, glow_out = mmt_compat.mix_node(group, "ADD", GLOW_AURA_WEIGHT)
    glow_mix.name = "%s_aura_mix" % GLOW_PREFIX
    glow_mix.label = "叠上外发光"
    glow_mix.location = (320, 380)
    links.new(total_out, glow_a)
    links.new(aura.outputs["Image"], glow_b)
    weight = mmt_compat.factor_socket(glow_mix)
    if weight is None:
        weight = glow_mix.inputs[0]
    links.new(source.outputs["外发光"], weight)

    bleach = nodes.new("CompositorNodeHueSat")
    bleach.name = "%s_bleach" % GLOW_PREFIX
    bleach.label = "去饱和"
    bleach.location = (520, 200)
    bleach.inputs["Saturation"].default_value = GLOW_SATURATION
    bleach.inputs["Fac"].default_value = 1.0
    links.new(glow_out, bleach.inputs["Image"])
    if small:
        links.new(canvas_up.inputs["Image"], bleach.outputs["Image"])
        glow_final = canvas_up.outputs["Image"]
    else:
        glow_final = bleach.outputs["Image"]

    add, add_a, add_b, add_out = mmt_compat.mix_node(group, "ADD", GLOW_STRENGTH)
    add.name = "%s_add" % GLOW_PREFIX
    add.label = "加到画面上"
    add.location = (700, 0)
    # 这一步必须是原图（全分辨率），所以走 source 而不是降采样那份
    links.new(source.outputs["图像"], add_a)
    links.new(glow_final, add_b)
    strength = mmt_compat.factor_socket(add)
    if strength is None:
        strength = add.inputs[0]
    links.new(source.outputs["强度"], strength)
    links.new(add_out, sink.inputs["泛光"])
    return group


# ---- 接进场景的合成器 ----

def _read_png(path):
    """读一张渲好的 PNG（绝对路径：Blender 图像加载不认相对路径）。"""
    import numpy as np

    image = bpy.data.images.load(os.path.abspath(path), check_existing=False)
    buffer = np.empty(len(image.pixels), dtype=np.float32)
    image.pixels.foreach_get(buffer)
    shape = tuple(image.size)
    bpy.data.images.remove(image)
    return buffer.reshape(shape[1], shape[0], 4)


def _dilate(mask, rounds):
    import numpy as np

    grown = mask.copy()
    for _ in range(int(rounds)):
        shifted = np.zeros_like(grown)
        shifted[1:, :] |= grown[:-1, :]
        shifted[:-1, :] |= grown[1:, :]
        shifted[:, 1:] |= grown[:, :-1]
        shifted[:, :-1] |= grown[:, 1:]
        grown = shifted
    return grown


def _suspend_stamp():
    """临时摘掉强制署名处理器（量泛光的小图不要水印，白字会干扰测量）。"""
    removed = [handler for handler in bpy.app.handlers.render_pre
               if getattr(handler, "__name__", "") == "force_watermark"]
    for handler in removed:
        bpy.app.handlers.render_pre.remove(handler)
    return removed


def _resume_stamp(handlers):
    for handler in handlers or ():
        if handler not in bpy.app.handlers.render_pre:
            bpy.app.handlers.render_pre.append(handler)


def measure_halo(scene, node, cache=None):
    """在当前强度下量"剪影外那圈光"被提亮多少，返回 ``(均值, 每单位强度, 说明)``。

    临时压分辨率到 :data:`GLOW_MEASURE_RES`、关署名，渲强度 0 与当前值两张取外圈均值；
    ``cache`` 可放上一轮的"强度 0"。"""
    import tempfile

    sock = node.inputs.get("强度") if node is not None else None
    if sock is None:
        return None, None, "泛光组没有「强度」输入"
    if getattr(scene, "camera", None) is None:
        return None, None, "场景里没有相机，量不了泛光（强度保持默认）"
    render = scene.render
    saved = {name: getattr(render, name, None)
             for name in ("resolution_x", "resolution_y", "resolution_percentage",
                          "filepath", "use_stamp")}
    saved_format = render.image_settings.file_format
    strength = float(sock.default_value)
    width, height = int(saved["resolution_x"] or 1920), int(saved["resolution_y"] or 1080)
    ratio = float(width) / float(height or 1)
    if ratio >= 1.0:
        small = (GLOW_MEASURE_RES, max(8, int(round(GLOW_MEASURE_RES / ratio))))
    else:
        small = (max(8, int(round(GLOW_MEASURE_RES * ratio))), GLOW_MEASURE_RES)
    handlers = _suspend_stamp()
    folder = tempfile.mkdtemp(prefix="mikumikutoon_glow_")
    off = (cache or {}).get("off")
    on = None
    try:
        render.resolution_x, render.resolution_y = small
        render.resolution_percentage = 100
        render.use_stamp = False
        render.image_settings.file_format = "PNG"
        for tag, value in (("off", 0.0), ("on", strength)):
            if tag == "off" and off is not None:
                continue
            sock.default_value = value
            path = os.path.join(folder, "%s.png" % tag)
            render.filepath = path
            bpy.ops.render.render(write_still=True)
            frame = _read_png(path)
            if tag == "off":
                off = frame
                if cache is not None:
                    cache["off"] = frame
            else:
                on = frame
    except Exception as error:
        return None, None, "量泛光失败（%s），强度保持 %s" % (error, round(strength, 3))
    finally:
        sock.default_value = strength
        for name, value in saved.items():
            if value is not None:
                try:
                    setattr(render, name, value)
                except Exception:
                    pass          # 只是还原渲染设置，失败不影响出图
        render.image_settings.file_format = saved_format
        _resume_stamp(handlers)
        try:
            import shutil
            shutil.rmtree(folder, ignore_errors=True)
        except Exception:
            pass   # 临时目录清不掉就留给系统，不影响出图

    if off is None or on is None:
        return None, None, "量泛光失败（没渲出图）"
    base = off[:, :, :3].mean(axis=2)
    lit = on[:, :, :3].mean(axis=2)
    body = base > 0.02
    if not body.any():
        return None, None, "量泛光时画面里没有角色（相机没框住？），强度保持 %s" % round(strength, 3)
    halo = _dilate(body, GLOW_MEASURE_MARGIN) & ~body & (lit > 0.02)
    count = int(halo.sum())
    if count < 12:
        return None, None, "剪影外量不到光（只找到 %d 个像素），强度保持 %s" % (
            count, round(strength, 3))
    mean = float(lit[halo].mean())
    per_unit = mean / max(strength, 1e-4)
    return mean, per_unit, "剪影外 %d 个像素、强度 %.2f 时提亮 %.3f（每单位 %.2f）" % (
        count, strength, mean, per_unit)


def _frame_camera(scene, objects):
    """临时建一个正交相机把 ``objects`` 整体框住（正面），返回相机对象（用完要删）。
    不用用户的相机：取景一变爆白结果就变，固定按整个模型量。"""
    import math
    from mathutils import Vector

    points = []
    for obj in objects:
        if obj.type != "MESH" or obj.data is None:
            continue
        for corner in obj.bound_box:
            points.append(obj.matrix_world @ Vector(corner))
    if not points:
        return None
    low = Vector((min(p.x for p in points), min(p.y for p in points),
                  min(p.z for p in points)))
    high = Vector((max(p.x for p in points), max(p.y for p in points),
                   max(p.z for p in points)))
    size = max(high.x - low.x, high.y - low.y, high.z - low.z, 1e-3)
    data = bpy.data.cameras.new("mmt_exposure_cam")
    data.type = "ORTHO"
    data.ortho_scale = size * 1.05
    cam = bpy.data.objects.new("mmt_exposure_cam", data)
    scene.collection.objects.link(cam)
    centre = (low + high) / 2.0
    cam.location = Vector((centre.x, low.y - size * 2.5, centre.z))
    cam.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    return cam


def measure_blown(scene, objects=None, resolution=GLOW_MEASURE_RES, alpha_min=0.9):
    """量"角色区域里有多少像素被削顶"（爆白占比）。返回 ``(占比, 说明)``。

    ``objects`` 给了就用临时全身取景相机量（取景无关），否则退回场景相机。临时压分辨率、
    关署名、``film_transparent = True``，按 alpha 认角色，统计三分量最大值是否 >= 0.97。"""
    import tempfile

    cam = None
    saved_camera = getattr(scene, "camera", None)
    if objects:
        cam = _frame_camera(scene, objects)
        if cam is not None:
            scene.camera = cam
    if getattr(scene, "camera", None) is None:
        return None, "场景里没有相机，量不了曝光"
    render = scene.render
    saved = {name: getattr(render, name, None)
             for name in ("resolution_x", "resolution_y", "resolution_percentage",
                          "filepath", "use_stamp", "film_transparent")}
    saved_format = render.image_settings.file_format
    width, height = int(saved["resolution_x"] or 1920), int(saved["resolution_y"] or 1080)
    ratio = float(width) / float(height or 1)
    if ratio >= 1.0:
        small = (resolution, max(8, int(round(resolution / ratio))))
    else:
        small = (max(8, int(round(resolution * ratio))), resolution)
    handlers = _suspend_stamp()
    folder = tempfile.mkdtemp(prefix="mikumikutoon_exp_")
    path = os.path.join(folder, "probe.png")
    try:
        render.resolution_x, render.resolution_y = small
        render.resolution_percentage = 100
        render.use_stamp = False
        render.film_transparent = True          # 用 alpha 认角色
        render.image_settings.file_format = "PNG"
        render.filepath = path
        bpy.ops.render.render(write_still=True)
        pixels = _read_png(path)
    except Exception as error:
        return None, "量曝光失败：%s" % error
    finally:
        for name, value in saved.items():
            if value is None:
                continue
            try:
                setattr(render, name, value)
            except Exception:
                pass              # 只是还原渲染设置，失败不影响出图
        render.image_settings.file_format = saved_format
        _resume_stamp(handlers)
        if cam is not None:                    # 收拾临时相机
            try:
                scene.camera = saved_camera
                bpy.data.objects.remove(cam, do_unlink=True)
                bpy.data.cameras.remove(cam.data, do_unlink=True)
            except Exception:
                pass              # 临时相机清不掉不算错
        try:
            import shutil
            shutil.rmtree(folder, ignore_errors=True)
        except Exception:
            pass   # 临时目录清不掉就留给系统
    if pixels is None:
        return None, "量曝光失败（没渲出图）"
    body = pixels[:, :, 3] > alpha_min
    if not body.any():
        return None, "画面里没有角色（相机没框住？）"
    peak = pixels[:, :, :3].max(axis=2)
    return float((peak[body] >= 0.97).mean()), "角色 %d 个像素" % int(body.sum())


def apply_strength(scene):
    """测量这个模型的画面，把泛光强度调到"深色角色不明显偏暗"。返回 ``(强度, 说明)``。

    泛光在亮部会顶到 1.0，响应非线性，一次测量不够准；所以闭环迭代「量 → 按比例外推 → 再量」，
    最多 :data:`GLOW_ITERATIONS` 轮。"""
    state, _api, node = glow_state(scene)
    if not state or node is None:
        return GLOW_STRENGTH, "场景里没有泛光节点（强度保持默认）"
    sock = node.inputs.get("强度")
    if sock is None:
        return GLOW_STRENGTH, "泛光组是旧版（没有「强度」输入）"
    floor = max(float(sock.default_value), GLOW_STRENGTH_MIN)
    cache = {}
    why = "没量成"
    for _ in range(GLOW_ITERATIONS):
        mean, per_unit, why = measure_halo(scene, node, cache)
        if mean is None:
            return max(float(sock.default_value), GLOW_STRENGTH), why
        if mean >= GLOW_HALO_TARGET * 0.92:
            break
        want = float(sock.default_value) * (GLOW_HALO_TARGET / max(mean, 1e-3))
        want = min(max(want, floor), GLOW_STRENGTH_MAX)
        if abs(want - float(sock.default_value)) < 0.01:
            break
        sock.default_value = want
    strength = max(float(sock.default_value), GLOW_STRENGTH)   # 只往上调，不往下压
    sock.default_value = strength
    return strength, "%s ⇒ 强度 %.2f（目标：剪影外 %.2f，默认 %.2f）" % (
        why, strength, GLOW_HALO_TARGET, GLOW_STRENGTH)


def _source(tree, sink):
    """(喂给输出的图像插槽, 渲染层节点)。实现在 mmt_compat.find_source。"""
    return mmt_compat.find_source(tree, sink)


def _emit_socket(layers):
    """Emit 通道：4.5 叫 Emit，5.x 叫 Emission（要先开 use_pass_emit）。"""
    for name in ("Emit", "Emission"):
        socket = mmt_compat.socket_out(layers, name)
        if socket is not None:
            return socket
    return None


def _glow_nodes(tree):
    return [node for node in tree.nodes if node.name.startswith(GLOW_PREFIX)]


#: 各游戏的"看家泛光参数"，面板上用按钮套用。键名 = 泛光组上的插座名。
LOOKS = (
    ("终末地泛光", {"强度": 1.10, "阈值": 0.55, "大小": 9.0,
                    "外发光": 0.24, "增益": 1.0}),
    ("原神泛光", {"强度": 0.08, "阈值": 1.20, "大小": 9.0,
                  "外发光": 0.24, "增益": 1.0}),
    ("绝区零泛光", {"强度": 0.10, "阈值": 1.30, "大小": 9.0,
                    "外发光": 0.24, "增益": 1.0}),
)


def look_names():
    return [name for name, _ in LOOKS]


def look_values(name):
    for label, values in LOOKS:
        if label == name:
            return dict(values)
    return None


def apply_look(scene, name, add_if_missing=True, tame=True):
    """把某个游戏的泛光参数套到场景里的泛光组节点上。返回 ``(成功, 说明)``。

    没有泛光节点时按 ``add_if_missing`` 先加一个（等价于点「添加泛光」）。``tame`` 默认开：
    预设是在有光照的管线里定的（泛光源只占少数高光像素），我们是全自发光，照搬会糊白，
    所以先量这个模型的自动强度，把 强度 收到 ``自动值 × GLOW_LOOK_FACTOR`` 以内。"""
    values = look_values(name)
    if values is None:
        return False, "没有这个泛光预设：%s" % name
    present, _api, node = glow_state(scene)
    if not present and add_if_missing:
        if not insert_glow(scene):
            return False, "无法建立合成器节点树"
        present, _api, node = glow_state(scene)
    if not present or node is None:
        return False, "场景里没有泛光（先点「添加泛光」）"

    requested = float(values.get("强度", GLOW_STRENGTH))
    used, note = requested, ""
    if tame and requested > GLOW_LOOK_MIN:
        try:
            base, why = apply_strength(scene)      # 量这个模型：剪影外目标 0.16 对应的强度
            cap = min(GLOW_STRENGTH_MAX, base * GLOW_LOOK_FACTOR)
            if requested > cap:
                used = max(GLOW_LOOK_MIN, cap)
                note = ("按这个模型收到 %.2f（自动值 %.2f × %.1f；原值 %.2f）"
                        % (used, base, GLOW_LOOK_FACTOR, requested))
        except Exception as error:
            note = "没能按模型收力（%s），用原值 %.2f" % (error, requested)

    written = []
    for socket_name, value in values.items():
        socket = node.inputs.get(socket_name)
        if socket is None:
            continue
        try:
            socket.default_value = float(used if socket_name == "强度" else value)
            written.append(socket_name)
        except Exception as error:
            return False, "写 %s 失败：%s" % (socket_name, error)
    scene["mmt_glow_look"] = name                    # 记一下现在套的是哪个（面板显示用）
    scene["mmt_glow_note"] = "已套用「%s」：%s%s" % (
        name, "、".join("%s %.2f" % (k, values[k]) for k in ("强度", "阈值", "大小",
                                                            "外发光", "增益")
                        if k in values),
        ("　" + note) if note else "")
    return True, "%s（%s%s）" % (name, "、".join(written),
                                ("；" + note) if note else "")


def glow_state(scene):
    tree = mmt_compat.existing_tree(scene)
    api = mmt_compat.TREE_API
    if tree is None:
        return False, api, None
    node = next((n for n in _glow_nodes(tree)
                 if n.bl_idname == "CompositorNodeGroup"), None)
    return node is not None, api, node


def _fast_compositor(scene):
    """把合成器切到 GPU（只在 4.5 这种默认 CPU 的版本上有意义）。
    CPU / GPU 合成结果逐像素一致；用户原设置记在 :data:`SCENE_DEVICE_FLAG`，摘泛光时还回去。"""
    render = getattr(scene, "render", None)
    if render is None or not hasattr(render, "compositor_device"):
        return None
    try:
        if render.compositor_device == "CPU":
            scene[SCENE_DEVICE_FLAG] = "CPU"
            render.compositor_device = "GPU"
            return "GPU"
    except Exception as error:
        # 切不过去不是错：Blender 自己会退回 CPU，只是慢一点
        print("[MikuMikuToon] 合成器切 GPU 失败（画面不受影响）：%s" % (error,))
    return None


def _restore_compositor(scene):
    """把合成器设备还给用户原来的设置（没记过就什么都不做）。"""
    saved = scene.get(SCENE_DEVICE_FLAG)
    if saved is None:
        return
    render = getattr(scene, "render", None)
    try:
        if render is not None and hasattr(render, "compositor_device"):
            render.compositor_device = saved
    except Exception:
        pass   # 属性不存在/被移除时不用还原
    mmt_compat.forget_key(scene, SCENE_DEVICE_FLAG)


def insert_glow(scene):
    tree, api = mmt_compat.scene_tree(scene)
    sink = mmt_compat.find_sink(tree)
    target = mmt_compat.sink_input(sink)
    if target is None:
        return False
    remove_glow(scene, keep_tree=True)
    source, layers = _source(tree, sink)

    # Emit 通道要在本场景每个视图层上开：只开 bpy.context 那个，换视图层渲染就没泛光
    for layer in scene.view_layers:
        if hasattr(layer, "use_pass_emit"):
            layer.use_pass_emit = True
    context_layer = getattr(bpy.context, "view_layer", None)
    if context_layer is not None and hasattr(context_layer, "use_pass_emit"):
        context_layer.use_pass_emit = True
    # 合成器要真的开着：use_compositing 关着的话节点连好也不参与渲染
    try:
        scene.render.use_compositing = True
    except Exception:
        pass   # 老版本没有这个属性
    # 顺手把合成器换到 GPU（4.5 默认 CPU）
    _fast_compositor(scene)

    node = tree.nodes.new("CompositorNodeGroup")
    node.name = "%s_group" % GLOW_PREFIX
    node.label = "MikuMikuToon 泛光"
    node.node_tree = glow_group()
    node.location = (60, 0)
    for link in list(target.links):
        tree.links.remove(link)
    tree.links.new(source, node.inputs["图像"])
    emit = _emit_socket(layers)
    if emit is not None:
        tree.links.new(emit, node.inputs["自发光"])
    tree.links.new(node.outputs["泛光"], target)
    return True


def remove_glow(scene, keep_tree=False):
    tree = mmt_compat.existing_tree(scene)
    if tree is None:
        return False
    api = mmt_compat.TREE_API
    nodes = _glow_nodes(tree)
    if not nodes:
        return False
    group = next((n for n in nodes if n.bl_idname == "CompositorNodeGroup"), None)
    source = None
    if group is not None:
        # 只认「图像」入口：组输入里还有自发光 / 强度，按"第一个连上的插座"取会把 Emit 接回去
        for name in ("图像", "Image"):
            socket = mmt_compat.socket_in(group, name, "RGBA")
            if socket is not None and socket.is_linked:
                source = socket.links[0].from_socket
                break
        if source is None:
            print("[MikuMikuToon] 泛光组的「图像」入口没接东西，"
                  "移除泛光时不再猜上游（渲染层保持原样）")
    sink = mmt_compat.find_sink(tree)
    target = mmt_compat.sink_input(sink)
    if target is not None:
        for link in list(target.links):
            tree.links.remove(link)
        if source is not None:
            tree.links.new(source, target)
        else:
            layers = tree.nodes.new("CompositorNodeRLayers")
            layers.location = (-200, 0)
            tree.links.new(mmt_compat.socket_out(layers, "Image"), target)
    for node in nodes:
        tree.nodes.remove(node)

    untouched = all(node.bl_idname in STRUCTURAL_NODES for node in tree.nodes)
    if not keep_tree:
        _restore_compositor(scene)
    if not keep_tree and untouched and scene.get(SCENE_TREE_FLAG):
        mmt_compat.drop_tree(scene, tree)     # 里面已经把标记一起清掉了
    return True
