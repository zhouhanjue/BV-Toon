# -*- coding: utf-8 -*-
"""BVToon -- 朦胧泛光（合成器）。

* **吃自发光**：泛光的源是渲染的 Emit 通道（角色自己的自发光）+ 画面里亮过阈值的
  部分。卡渲本来就自发光照亮自己，所以**不打光也出效果**；亮背景不会跟着糊。
* **向四周扩散**：把 Emit 变成剪影遮罩，染成暖白，大半径模糊，再叠上去，于是光围着
  整个剪影往外散（深色部位外侧也有）。
* 最后是**相加**而不是 Glare 自带的 mix —— 那个是往"只有泛光的图"做 lerp，会压暗暗部。
* 参数挂在合成器里的组节点上（强度 / 阈值 / 大小 / 外发光），随时可调。

© 2025 BVan / DEEPSEEK
"""

import os

import bpy

GLOW_GROUP = "BVToon_Glow"
GLOW_PREFIX = "BV_GLOW"
SCENE_TREE_FLAG = "bvtoon_glow_tree"

GLOW_STRENGTH = 0.10      # 泛光往画面上加多少
GLOW_THRESHOLD = 0.95     # 画面里亮过这个值的部分也一起发光（自发光不受它管）
GLOW_WIDE_SIZE = 8        # 大半径那层（1..9）
GLOW_CORE_SIZE = 4        # 贴着亮部那层
GLOW_SATURATION = 0.85    # 泛光去饱和一点，别变成彩色雾
GLOW_TINT = (1.0, 0.98, 0.94, 1.0)
GLOW_QUALITY = "HIGH"
GLOW_MODE = "BLOOM"       # 4.4+ 的灯光型 glare

GLOW_AURA_SPREAD = 7.0   # 外发光模糊半径（画面百分比，固定值）
GLOW_AURA_WEIGHT = 0.12    # 外发光相对亮部泛光的强度
GLOW_AURA_FLOOR = 0.60    # 多少自发光才算"亮部"：卡渲是全自发光材质，门槛太低会把整个人物糊一遍再加回来（画面发白）
GLOW_AURA_TINT = (1.0, 0.96, 0.92, 1.0)

#: 泛光**按模型实测自动定强度**（2026-09-19 加）—— 解决"泛光吃模型亮度"这个老大难。
#: 泛光整条链吃的都是**绝对亮度**：自发光越亮泛光越亮。同一套参数实测（640×853，同机位）：
#:
#: ============  ==============  ==================  ==================
#: 模型          角色平均亮度    角色上的泛光增量    剪影外那圈光
#: ============  ==============  ==================  ==================
#: 奥黛塔        0.735           +0.0497             +0.160
#: 芙宁娜        0.586           +0.0075             +0.028
#: 胡桃          0.421           +0.0060             +0.017
#: 初音ミク      0.964           +0.0099             +0.227
#: ============  ==============  ==================  ==================
#:
#: 奥黛塔（皮肤衣服都白）比胡桃（深色衣服）亮了 **7 倍**，观感就是"胡桃没泛光"。
#: 按"材质平均底色"折算增益试过，**不准**（材质的平均亮度预测不了屏幕上的亮部占比：
#: 胡桃按材质算只要 1.44 倍，实测要 ~9 倍才追平）。所以改成**直接量**：
#: 点「添加泛光」时用 96×96 渲两张（强度 0 / 1.0），量"剪影外那圈光"被提亮多少，
#: 再按 :data:`GLOW_HALO_TARGET` 反推强度 —— 量的是屏幕上真正看得见的那件事。
GLOW_HALO_TARGET = 0.16   # 目标：剪影外那圈光平均提亮多少（奥黛塔实测 0.160）
#: 自动强度**只往上调，不往下压**：泛光本来就比奥黛塔强的角色（实测 初音ミク 剪影外 0.27）
#: 保持原样 —— 用户的诉求是"别让深色角色比别人暗"，不是"把亮的也压下去"。
GLOW_STRENGTH_MIN = 0.03  # 自动强度的夹紧范围（太小的模型量出来会抖）
GLOW_STRENGTH_MAX = 2.50
#: 量的时候用多大分辨率、看剪影外多宽的一圈。
#: ⚠️ 这一圈必须按**画面比例**取（192 取 2 px ≈ 1%），不能取绝对值：
#: 泛光的模糊半径是"画面百分比"，取宽了就把靠近剪影的亮芯算进来，量出的响应会偏大
#: （实测 96 px 取 3 px = 3%，胡桃被量成 0.265，全分辨率其实只有 0.166）。
GLOW_MEASURE_RES = 192
GLOW_MEASURE_MARGIN = 2
#: 闭环迭代次数：每次量一遍"剪影外提亮了多少"，不够就按比例加，最多重来这么多轮。
#: 一次测量的响应不是线性的（亮部会被顶到 1.0），深色模型实测会低估约 2 倍 —— 迭代补上。
GLOW_ITERATIONS = 3


STRUCTURAL_NODES = {"CompositorNodeRLayers", "CompositorNodeComposite",
                    "NodeGroupOutput", "NodeGroupInput", "NodeReroute",
                    "CompositorNodeViewer", "CompositorNodeOutputFile"}


# ---------------------------------------------------------------------------
# 跨版本的小工具
# ---------------------------------------------------------------------------

def _has(node, name):
    return node.bl_rna.properties.get(name) is not None


def _set(node, name, value):
    """设置属性或插槽，谁在这个版本里存在就设谁。"""
    if _has(node, name):
        try:
            setattr(node, name, value)
            return True
        except Exception:
            pass
    socket = node.inputs.get(name)
    if socket is None:
        return False
    fits = ((socket.type == "VALUE" and isinstance(value, (int, float))
             and not isinstance(value, bool))
            or (socket.type == "BOOLEAN" and isinstance(value, bool))
            or (socket.type == "INT" and isinstance(value, int)
                and not isinstance(value, bool))
            or (socket.type == "RGBA" and isinstance(value, (tuple, list))))
    if not fits:
        return False
    try:
        socket.default_value = value
        return True
    except Exception:
        return False


def _socket(node, name, kind=None):
    for socket in node.inputs:
        if socket.name == name and (kind is None or socket.type == kind):
            return socket
    return None


def _output(node, name=None, kind="RGBA"):
    for socket in node.outputs:
        if (name is None or socket.name == name) and socket.type == kind:
            return socket
    return None


def _new_node(nodes, *names):
    for name in names:
        try:
            return nodes.new(name)
        except Exception:
            continue
    raise RuntimeError("这些节点类型在本版本都不存在：%s" % ", ".join(names))


def _factor_socket(node):
    for socket in node.inputs:
        if socket.name in {"Fac", "Factor"} and socket.type == "VALUE":
            return socket
    return None


def _mix(tree, blend_type, factor=1.0):
    """图像混合节点（4.5 用 CompositorNodeMixRGB，5.x 用 ShaderNodeMix）。"""
    if hasattr(bpy.types, "CompositorNodeMixRGB"):
        node = tree.nodes.new("CompositorNodeMixRGB")
        node.blend_type = blend_type
        node.inputs[0].default_value = factor
        return node, node.inputs[1], node.inputs[2], node.outputs[0]
    node = tree.nodes.new("ShaderNodeMix")
    node.data_type = "RGBA"
    node.blend_type = blend_type
    fac = _factor_socket(node)
    if fac is not None:
        fac.default_value = factor
    colors = [s for s in node.inputs if s.type == "RGBA"]
    return node, colors[0], colors[1], _output(node)


def _glare_node(nodes, label, size, location):
    """一层 glare。它自己的阈值固定 0：交给它的东西全部参与泛光（含暗的自发光）；
    画面的阈值只在源那一步做。"""
    node = nodes.new("CompositorNodeGlare")
    node.name = "%s_%s" % (GLOW_PREFIX, label)
    node.label = label
    node.location = location
    # 老版本（<=4.4）用属性；4.5/5.x 全在**插座**上，而且枚举首字母大写（'Bloom' 不是 'BLOOM'）。
    # 这里以前是静默失败 -> 节点保持默认 'Streaks'/'Ghosts' -> 画面出现绿色重影（实测踩到）。
    _set(node, "glare_type", GLOW_MODE)
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
            print("[BV-Toon] Glare 插座 %s 设不上：%s" % (socket_name, error))
    _set(node, "quality", GLOW_QUALITY)
    _set(node, "mix", 0.0)
    _set(node, "threshold", 0.0)
    _set(node, "size", int(size))
    _set(node, "Type", GLOW_MODE)
    _set(node, "Quality", GLOW_QUALITY)
    for name, value in (("Threshold", 0.0), ("Smoothness", 0.0),
                        ("Clamp", False), ("Maximum", 10.0),
                        ("Saturation", 1.0), ("Strength", 1.0), ("Fade", 1.0),
                        ("Color Modulation", 1.0)):
        _set(node, name, value)
    tint = _socket(node, "Tint", "RGBA")
    if tint is not None:
        tint.default_value = GLOW_TINT
    return node


# ---------------------------------------------------------------------------
# 组本体
# ---------------------------------------------------------------------------

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

    # 增益：把"模型自己的平均自发光"归一到同一个量级（详见 GLOW_TARGET 那段注释）。
    # 放在**外发光门槛之前**，于是门槛自然变成"相对这个模型"的门槛 ——
    # 深色角色也能拿到剪影外那圈光（实测胡桃原来外圈只有 +0.017，奥黛塔 +0.149）。
    gain_fill = _new_node(nodes, "CompositorNodeCombineColor", "ShaderNodeCombineColor")
    gain_fill.name = "%s_gain_color" % GLOW_PREFIX
    gain_fill.label = "增益"
    gain_fill.location = (-820, 900)
    if _has(gain_fill, "mode"):
        try:
            gain_fill.mode = "RGB"
        except Exception:
            pass
    # 插座名各版本不完全一样（合成器里颜色插座叫 Image），按名字找不到就退回"前三个数值插槽"
    channels = [gain_fill.inputs.get(name) for name in ("Red", "Green", "Blue")]
    if any(item is None for item in channels):
        channels = [socket for socket in gain_fill.inputs if socket.type == "VALUE"][:3]
    for socket in channels:
        if socket is not None:
            links.new(source.outputs["增益"], socket)
    gained, gained_a, gained_b, gained_out = _mix(group, "MULTIPLY", 1.0)
    gained.name = "%s_gain" % GLOW_PREFIX
    gained.label = "自发光 × 增益"
    gained.location = (-620, 880)
    links.new(source.outputs["自发光"], gained_a)
    fill_out = _output(gain_fill)
    if fill_out is None:
        raise RuntimeError("合成器里没有可用的「合并颜色」节点")
    links.new(fill_out, gained_b)

    # 源 = 自发光 + (图像 - 阈值)，负数用 LIGHTEN 黑压掉
    over, over_a, over_b, over_out = _mix(group, "SUBTRACT", 1.0)
    over.name = "%s_over" % GLOW_PREFIX
    over.label = "图像 - 阈值"
    over.location = (-820, -320)
    links.new(source.outputs["图像"], over_a)
    over_b.default_value = (1.0, 1.0, 1.0, 1.0)
    factor = _factor_socket(over)
    if factor is None:
        factor = over.inputs[0]
    links.new(source.outputs["阈值"], factor)

    floor, floor_a, floor_b, floor_out = _mix(group, "LIGHTEN", 1.0)
    floor.name = "%s_floor" % GLOW_PREFIX
    floor.label = "压到黑"
    floor.location = (-620, -320)
    links.new(over_out, floor_a)
    floor_b.default_value = (0.0, 0.0, 0.0, 1.0)

    src, src_a, src_b, src_out = _mix(group, "ADD", 1.0)
    src.name = "%s_source" % GLOW_PREFIX
    src.label = "自发光 × 增益 + 高光"
    src.location = (-420, -180)
    links.new(floor_out, src_a)
    links.new(gained_out, src_b)

    # 两个半径
    scale = _new_node(nodes, "CompositorNodeMath", "ShaderNodeMath")
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
        size = _socket(node, "Size", "VALUE")
        if size is not None:
            links.new(scale.outputs[0], size)

    total, total_a, total_b, total_out = _mix(group, "ADD", 1.0)
    total.name = "%s_sum" % GLOW_PREFIX
    total.label = "两个半径相加"
    total.location = (-420, 200)
    links.new(_output(wide, "Glare"), total_a)
    links.new(_output(core, "Glare"), total_b)

    # 外发光：自发光 → 剪影遮罩 → 暖白 → 大半径模糊 → ×权重
    separator = _new_node(nodes, "CompositorNodeSeparateColor")
    separator.name = "%s_aura_sep" % GLOW_PREFIX
    separator.label = "自发光 RGB（× 增益后）"
    separator.location = (-820, 640)
    if _has(separator, "mode"):
        separator.mode = "RGB"
    links.new(gained_out, separator.inputs["Image"])

    def _math(label, operation, value=None, location=(-620, 640)):
        node = _new_node(nodes, "CompositorNodeMath", "ShaderNodeMath")
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

    tinted, tint_a, tint_b, tint_out = _mix(group, "MIX", 1.0)
    tinted.name = "%s_aura_tint" % GLOW_PREFIX
    tinted.label = "剪影染色"
    tinted.location = (-100, 640)
    tint_a.default_value = (0.0, 0.0, 0.0, 1.0)
    tint_b.default_value = GLOW_AURA_TINT
    gate_factor = _factor_socket(tinted)
    if gate_factor is None:
        gate_factor = tinted.inputs[0]
    links.new(gate.outputs[0], gate_factor)

    aura = _new_node(nodes, "CompositorNodeBlur")
    aura.name = "%s_aura" % GLOW_PREFIX
    aura.label = "外发光"
    aura.location = (100, 640)
    if _has(aura, "filter_type"):
        for name in ("GAUSS", "GAUSSIAN", "FAST_GAUSS"):
            try:
                aura.filter_type = name
                break
            except Exception:
                continue
    if _has(aura, "use_relative"):
        aura.use_relative = True
    for name in ("size_x", "size_y"):
        if _has(aura, name):
            try:
                setattr(aura, name, int(GLOW_AURA_SPREAD))
            except Exception:
                pass
    links.new(tint_out, aura.inputs["Image"])

    glow_mix, glow_a, glow_b, glow_out = _mix(group, "ADD", GLOW_AURA_WEIGHT)
    glow_mix.name = "%s_aura_mix" % GLOW_PREFIX
    glow_mix.label = "叠上外发光"
    glow_mix.location = (320, 380)
    links.new(total_out, glow_a)
    links.new(aura.outputs["Image"], glow_b)
    weight = _factor_socket(glow_mix)
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

    add, add_a, add_b, add_out = _mix(group, "ADD", GLOW_STRENGTH)
    add.name = "%s_add" % GLOW_PREFIX
    add.label = "加到画面上"
    add.location = (700, 0)
    links.new(source.outputs["图像"], add_a)
    links.new(bleach.outputs["Image"], add_b)
    strength = _factor_socket(add)
    if strength is None:
        strength = add.inputs[0]
    links.new(source.outputs["强度"], strength)
    links.new(add_out, sink.inputs["泛光"])
    return group


# ---------------------------------------------------------------------------
# 接进场景的合成器
# ---------------------------------------------------------------------------

def _read_png(path):
    """读一张渲好的 PNG（**绝对路径**：Blender 的图像加载不认相对路径）。"""
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
    """临时摘掉强制署名处理器（量泛光的两张小图不要水印，白字还会干扰测量）。"""
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

    临时把分辨率压到 :data:`GLOW_MEASURE_RES`、关掉署名，渲两张（强度 0 / 当前值），
    取"本来黑、开了泛光才亮、而且贴着剪影"的像素求平均。量的是**屏幕上看得见的那件事**。
    ``cache`` 里可以放上一轮渲好的"强度 0"那张（它在整个迭代里都一样，不必重渲）。
    """
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
    folder = tempfile.mkdtemp(prefix="bvtoon_glow_")
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
                    pass
        render.image_settings.file_format = saved_format
        _resume_stamp(handlers)
        try:
            import shutil
            shutil.rmtree(folder, ignore_errors=True)
        except Exception:
            pass

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


def apply_strength(scene):
    """按实测把泛光强度调到"别比奥黛塔暗"。返回 ``(强度, 说明)``。

    一次测量不够准（泛光在亮部会顶到 1.0，响应不是线性的；深色模型实测会低估 2 倍左右），
    所以**闭环迭代**：量 → 按比例外推 → 再量，最多 :data:`GLOW_ITERATIONS` 轮。
    """
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


def scene_tree(scene):
    """(合成器树, API 名)。5.0 起改用 compositing_node_group。"""
    if hasattr(scene, "compositing_node_group"):
        tree = scene.compositing_node_group
        if tree is None:
            tree = bpy.data.node_groups.new("Compositor", "CompositorNodeTree")
            scene[SCENE_TREE_FLAG] = 1
            scene.compositing_node_group = tree
        return tree, "compositing_node_group"
    if not scene.use_nodes:
        scene[SCENE_TREE_FLAG] = 1
    scene.use_nodes = True
    return scene.node_tree, "use_nodes"


def existing_tree(scene):
    """只在场景已经有合成器树时返回它（不产生副作用）。"""
    if hasattr(scene, "compositing_node_group"):
        return scene.compositing_node_group
    if scene.use_nodes and scene.node_tree is not None:
        return scene.node_tree
    return None


def _sink(tree, api):
    if api == "compositing_node_group":
        outputs = [item for item in tree.interface.items_tree
                   if item.in_out == "OUTPUT"]
        if not outputs:
            tree.interface.new_socket("Image", in_out="OUTPUT",
                                      socket_type="NodeSocketColor")
        node = next((n for n in tree.nodes if n.bl_idname == "NodeGroupOutput"),
                    None)
        if node is None:
            node = tree.nodes.new("NodeGroupOutput")
            node.location = (400, 0)
        return node
    node = next((n for n in tree.nodes
                 if n.bl_idname == "CompositorNodeComposite"), None)
    if node is None:
        node = tree.nodes.new("CompositorNodeComposite")
        node.location = (400, 0)
    return node


def _sink_input(sink):
    for name in ("Image", "图像"):
        socket = sink.inputs.get(name)
        if socket is not None:
            return socket
    return sink.inputs[0] if len(sink.inputs) else None


def _render_layers(tree):
    node = next((n for n in tree.nodes
                 if n.bl_idname == "CompositorNodeRLayers"), None)
    if node is None:
        node = tree.nodes.new("CompositorNodeRLayers")
        node.location = (-200, 0)
    return node


def _resolve_reroutes(socket):
    """穿透 Reroute，**始终返回一个上游的输出插槽**。

    合成器里 RLayers 后面常挂一个 Reroute，直接拿它的输出当源会连不上（实测：节点
    连好了但泛光完全不起作用）；反过来如果把传进来的**输入**插槽原样返回，第二次点
    「添加泛光」就会报 "Same input/output direction of sockets"。
    """
    seen = 0
    while socket is not None and socket.is_linked and seen < 32:
        link = socket.links[0]
        upstream_node, upstream_socket = link.from_node, link.from_socket
        socket = upstream_socket
        if upstream_node.bl_idname != "NodeReroute":
            break
        seen += 1
    return socket


def _source(tree, sink):
    """(喂给输出的图像插槽, 渲染层节点)。"""
    socket = _sink_input(sink)
    if socket is not None and socket.is_linked:
        upstream = _resolve_reroutes(socket)
        layers = upstream.node if upstream.node.bl_idname == "CompositorNodeRLayers" \
            else _render_layers(tree)
        return upstream, layers
    layers = next((n for n in tree.nodes if n.bl_idname == "CompositorNodeRLayers"
                   and not any(out.is_linked for out in n.outputs)), None)
    if layers is None:
        layers = _render_layers(tree)
    return _output(layers, "Image"), layers


def _emit_socket(layers):
    """Emit 通道：4.5 叫 Emit，5.x 叫 Emission（要先开 use_pass_emit）。"""
    for name in ("Emit", "Emission"):
        socket = _output(layers, name)
        if socket is not None:
            return socket
    return None


def _glow_nodes(tree):
    return [node for node in tree.nodes if node.name.startswith(GLOW_PREFIX)]


def glow_state(scene):
    tree = existing_tree(scene)
    api = ("compositing_node_group" if hasattr(scene, "compositing_node_group")
           else "use_nodes")
    if tree is None:
        return False, api, None
    node = next((n for n in _glow_nodes(tree)
                 if n.bl_idname == "CompositorNodeGroup"), None)
    return node is not None, api, node


def insert_glow(scene):
    tree, api = scene_tree(scene)
    sink = _sink(tree, api)
    target = _sink_input(sink)
    if target is None:
        return False
    remove_glow(scene, keep_tree=True)
    source, layers = _source(tree, sink)

    # Emit 通道要开着，而且要在**这个场景的每个视图层**上开：只看
    # bpy.context.view_layer 的话，在别的场景/别的视图层渲染时拿不到 Emit，
    # 泛光就等于没接（实测踩过）
    for layer in scene.view_layers:
        if hasattr(layer, "use_pass_emit"):
            layer.use_pass_emit = True
    context_layer = getattr(bpy.context, "view_layer", None)
    if context_layer is not None and hasattr(context_layer, "use_pass_emit"):
        context_layer.use_pass_emit = True
    # 合成器要真的开着：节点连好了但 use_compositing 关着，渲染时完全不参与
    try:
        scene.render.use_compositing = True
    except Exception:
        pass

    node = tree.nodes.new("CompositorNodeGroup")
    node.name = "%s_group" % GLOW_PREFIX
    node.label = "BVToon 泛光"
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
    tree = existing_tree(scene)
    if tree is None:
        return False
    api = ("compositing_node_group" if hasattr(scene, "compositing_node_group")
           else "use_nodes")
    nodes = _glow_nodes(tree)
    if not nodes:
        return False
    group = next((n for n in nodes if n.bl_idname == "CompositorNodeGroup"), None)
    source = None
    if group is not None:
        for socket in group.inputs:
            if socket.is_linked:
                source = socket.links[0].from_socket
                break
    sink = _sink(tree, api)
    target = _sink_input(sink)
    if target is not None:
        for link in list(target.links):
            tree.links.remove(link)
        if source is not None:
            tree.links.new(source, target)
        else:
            layers = tree.nodes.new("CompositorNodeRLayers")
            layers.location = (-200, 0)
            tree.links.new(_output(layers, "Image"), target)
    for node in nodes:
        tree.nodes.remove(node)

    untouched = all(node.bl_idname in STRUCTURAL_NODES for node in tree.nodes)
    if not keep_tree and untouched and scene.get(SCENE_TREE_FLAG):
        if api == "compositing_node_group":
            scene.compositing_node_group = None
            if tree.users == 0:
                bpy.data.node_groups.remove(tree)
        else:
            scene.use_nodes = False
        del scene[SCENE_TREE_FLAG]
    return True
