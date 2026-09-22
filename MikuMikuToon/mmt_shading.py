# -*- coding: utf-8 -*-
"""MikuMikuToon -- 卡渲着色节点组：全部用 Python 现场生成，不加载任何 .blend 资源。

写法三件事：

1. 明暗分界与灯光无关：世界法线转相机空间 → 清零上下分量、只留左右 → 按
   ``受光方向`` 绕竖轴转一个角度，得到一条竖直的、方向可调的条带，软过渡当遮罩。
   再乘一层 Fresnel，免得条带绕到剪影上。
2. 阴影 / 高光 / 轮廓光全部走 Emission：不打光也出效果，也正好喂给自发光泛光。
3. 球面层在反照率上：球面/副纹理由调用方接进"底色"入口，与 MMD 算法一致。

© 2025 BVan / DEEPSEEK
"""

import os

import bpy

#: 节点组名（自己的，与任何第三方无关）
SHADING_GROUP = "MikuMikuToon_Shading"

#: 组接口：中文名，面板与预设都按名字读写
INPUTS = (
    ("底色", "NodeSocketColor", (1.0, 1.0, 1.0, 1.0)),
    ("色调", "NodeSocketColor", (1.0, 0.97, 0.93, 1.0)),
    ("亮度", "NodeSocketFloat", 1.0),
    ("反差", "NodeSocketFloat", 0.20),
    ("暗部色", "NodeSocketColor", (0.78, 0.80, 0.94, 1.0)),
    ("暗部深浅", "NodeSocketFloat", 0.85),
    ("受光方向", "NodeSocketFloat", 0.0),
    ("分界宽度", "NodeSocketFloat", 0.03),
    ("分界暖边", "NodeSocketFloat", 0.35),
    ("暖边色", "NodeSocketColor", (1.0, 0.85, 0.45, 1.0)),
    ("高光色", "NodeSocketColor", (1.0, 1.0, 1.0, 1.0)),
    ("高光强弱", "NodeSocketFloat", 0.25),
    ("高光集中", "NodeSocketFloat", 0.55),
    ("轮廓色", "NodeSocketColor", (1.0, 0.88, 0.78, 1.0)),
    ("轮廓宽度", "NodeSocketFloat", 0.30),
    ("轮廓强度", "NodeSocketFloat", 0.0),
    ("Alpha", "NodeSocketFloat", 1.0),
    ("Base Alpha", "NodeSocketFloat", 1.0),
    # 渐变贴图（MMD toon ramp）查出来的暗部遮罩，由材质树送进来
    # （组的接口不支持图片插座，查表只能在材质树上做）
    ("渐变遮罩", "NodeSocketFloat", 0.0),
    ("渐变强度", "NodeSocketFloat", 0.0),
)

OUTPUTS = (
    ("着色", "NodeSocketShader"),
    ("颜色", "NodeSocketColor"),
)

#: 预设 = 上面那组接口取不同值
PRESETS = (
    ("一键卡渲", {
        "球面强度": 0.30,          # sphere 是 MMD 的光泽层，给 0.5 衣服会发亮发油
        "受光方向": 0.42,
        "色调": (1.00, 0.99, 0.97, 1.0),
        "暗部色": (0.42, 0.50, 0.86, 1.0),
        "亮度": 1.05,
        "反差": 0.00,     # 0 = 完全不往"底色²"的暗版混
        "暗部深浅": 0.00,
        "分界宽度": 0.03,          # 硬两段：三渲二要的是硬分界，不是渐变
        "分界暖边": 0.00,          # 分界外侧那圈暖色
        "高光强弱": 0.0,           # 关掉 Fresnel 大面积柔光（油腻的主因）
        "轮廓色": (1.00, 0.88, 0.78, 1.0),
        "轮廓强度": 0.0,
    }),
    ("冷调", {
        "球面强度": 0.30,
        "受光方向": 0.42,
        "色调": (0.97, 0.99, 1.03, 1.0),
        "暗部色": (0.52, 0.60, 1.00, 1.0),
        "亮度": 1.05,
        "反差": 0.00,     # 0 = 完全不往"底色²"的暗版混
        "暗部深浅": 0.00,
        "分界宽度": 0.03,
        "分界暖边": 0.00,
        "高光强弱": 0.0,
        "轮廓色": (0.82, 0.90, 1.00, 1.0),
        "轮廓强度": 0.0,
    }),
    ("夜色暖", {
        "球面强度": 0.30,
        "受光方向": 0.42,
        "色调": (1.06, 0.97, 0.86, 1.0),
        "暗部色": (0.42, 0.44, 0.78, 1.0),
        "亮度": 0.95,
        "反差": 0.05,
        "暗部深浅": 0.00,
        "分界宽度": 0.03,
        "分界暖边": 0.00,
        "高光强弱": 0.0,
        "轮廓色": (1.00, 0.74, 0.48, 1.0),
        "轮廓强度": 0.60,
    }),
)


def preset_names():
    return [name for name, _ in PRESETS]

def preset_values(index):
    if not 0 <= index < len(PRESETS):
        return "", {}
    name, values = PRESETS[index]
    return name, values


# ---------------------------------------------------------------------------
# 小组件
# ---------------------------------------------------------------------------

def _color_inputs(node):
    return [socket for socket in node.inputs if socket.type == "RGBA"]


def _color_output(node):
    return next((socket for socket in node.outputs if socket.type == "RGBA"),
                node.outputs[0])


def _factor_input(node):
    return next((socket for socket in node.inputs
                 if socket.name in {"Factor", "Fac"} and socket.type == "VALUE"),
                None)


def mix(nodes, blend_type, factor=1.0, label="", location=(0, 0)):
    """颜色混合节点：(节点, Fac, A, B, 输出)。"""
    node = nodes.new("ShaderNodeMix")
    node.data_type = "RGBA"
    node.blend_type = blend_type
    node.label = label
    node.location = location
    fac = _factor_input(node)
    if fac is not None:
        fac.default_value = float(factor)
    colors = _color_inputs(node)
    return (node, fac, colors[0] if colors else None,
            colors[1] if len(colors) > 1 else None, _color_output(node))


def math_node(nodes, operation, value=None, label="", location=(0, 0),
              clamp=False):
    node = nodes.new("ShaderNodeMath")
    node.operation = operation
    node.label = label
    node.location = location
    node.use_clamp = clamp
    if value is not None and len(node.inputs) > 1:
        node.inputs[1].default_value = float(value)
    return node


def combine(nodes, location, label=""):
    """把一个浮点变成 (v,v,v,1) 的颜色，用来当乘/加的操作数。"""
    node = nodes.new("ShaderNodeCombineColor")
    node.mode = "RGB"
    node.location = location
    node.label = label
    return node


def ramp(nodes, location, elements, label=""):
    node = nodes.new("ShaderNodeValToRGB")
    node.location = location
    node.label = label
    color_ramp = node.color_ramp
    while len(color_ramp.elements) > 1:
        color_ramp.elements.remove(color_ramp.elements[-1])
    color_ramp.elements[0].position = elements[0][0]
    color_ramp.elements[0].color = elements[0][1]
    for position, color in elements[1:]:
        element = color_ramp.elements.new(position)
        element.color = color
    return node


def fresnel(nodes, ior, location, label=""):
    node = nodes.new("ShaderNodeFresnel")
    node.location = location
    node.label = label
    node.inputs["IOR"].default_value = ior
    return node


def soft_step(nodes, value_socket, centre_socket, width_socket, location,
              label=""):
    """clamp((value - centre) / width)：一条宽度可调的软边。"""
    links = nodes.id_data.links
    width = math_node(nodes, "MAXIMUM", 0.02, "%s 宽度" % label,
                      (location[0] - 180, location[1] - 160))
    links.new(width_socket, width.inputs[0])
    offset = math_node(nodes, "SUBTRACT", None, "%s 起点" % label,
                       (location[0] - 180, location[1]))
    links.new(value_socket, offset.inputs[0])
    links.new(centre_socket, offset.inputs[1])
    step = math_node(nodes, "DIVIDE", None, label, location, clamp=True)
    links.new(offset.outputs[0], step.inputs[0])
    links.new(width.outputs[0], step.inputs[1])
    return step


#: 卡渲节点组装进这个资产（插件目录下的相对路径，运行时 append 进来）。
#: 直接打开这个 .blend 手改着色，比给每个材质现搭几十个节点好调。
ASSET_DIR = "MikuMikuToonData"
ASSET_NAME = "MikuMikuToonShading.blend"


def asset_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        ASSET_DIR, ASSET_NAME)


def _load_from_asset():
    """从资产 append 节点组；没有资产就返回 None（回退到现场建）。"""
    path = asset_path()
    if not os.path.isfile(path):
        return None
    try:
        with bpy.data.libraries.load(path, link=False) as (source, target):
            if SHADING_GROUP in source.node_groups:
                target.node_groups = [SHADING_GROUP]
    except Exception as error:
        print("[MikuMikuToon] 资产读取失败，改用现场建组：%s" % error)
        return None
    group = bpy.data.node_groups.get(SHADING_GROUP)
    if group is not None:
        try:
            group.use_fake_user = True   # 没有使用者时保存会把它丢掉
        except Exception:
            pass   # 老版本没有这个类属性，有意忽略
    return group


def shading_group():
    """取卡渲节点组：内存里有就用，否则从资产 append，再不行现场建一个。"""
    group = bpy.data.node_groups.get(SHADING_GROUP)
    if group is not None and len(group.nodes):
        return group
    group = _load_from_asset()
    if group is not None and len(group.nodes):
        return group
    print("[MikuMikuToon] 没找到 %s/%s，改为现场生成节点组" % (ASSET_DIR, ASSET_NAME))
    return build_shading_group()


def build_shading_group():
    """现场生成卡渲节点组（也是生成资产用的那支笔）。"""
    group = bpy.data.node_groups.get(SHADING_GROUP)
    if group is not None and len(group.nodes):
        return group
    if group is None:
        group = bpy.data.node_groups.new(SHADING_GROUP, "ShaderNodeTree")
    for name, kind, _ in INPUTS:
        group.interface.new_socket(name, in_out="INPUT", socket_type=kind)
    for name, kind in OUTPUTS:
        group.interface.new_socket(name, in_out="OUTPUT", socket_type=kind)
    for socket in group.interface.items_tree:
        if socket.in_out != "INPUT":
            continue
        for name, _kind, default in INPUTS:
            if socket.name == name and hasattr(socket, "default_value"):
                socket.default_value = default

    nodes, links = group.nodes, group.links
    source = nodes.new("NodeGroupInput")
    source.location = (-1500, 0)
    sink = nodes.new("NodeGroupOutput")
    sink.location = (1500, 0)

    # ---- 底色：亮度 → 色调 → 反差 --------------------------------------
    level = combine(nodes, (-1300, 340), "亮度")
    for channel in ("Red", "Green", "Blue"):
        links.new(source.outputs["亮度"], level.inputs[channel])

    bright, _, bright_a, bright_b, bright_out = mix(
        nodes, "MULTIPLY", 1.0, "× 亮度", (-1120, 300))
    links.new(source.outputs["底色"], bright_a)
    links.new(level.outputs["Color"], bright_b)

    tinted, _, tint_a, tint_b, tint_out = mix(
        nodes, "MULTIPLY", 1.0, "× 色调", (-940, 240))
    links.new(bright_out, tint_a)
    links.new(source.outputs["色调"], tint_b)

    squared, _, sq_a, sq_b, sq_out = mix(
        nodes, "MULTIPLY", 1.0, "底色²", (-940, 440))
    links.new(tint_out, sq_a)
    links.new(tint_out, sq_b)

    contrast, contrast_fac, contrast_a, contrast_b, contrast_out = mix(
        nodes, "MIX", 0.2, "反差", (-740, 320))
    links.new(tint_out, contrast_a)
    links.new(sq_out, contrast_b)
    links.new(source.outputs["反差"], contrast_fac)

    # ---- 阴影遮罩：相机空间竖直条带 ------------------------------------
    geometry = nodes.new("ShaderNodeNewGeometry")
    geometry.location = (-1300, -140)
    to_camera = nodes.new("ShaderNodeVectorTransform")
    to_camera.vector_type = "NORMAL"
    to_camera.convert_from = "WORLD"
    to_camera.convert_to = "CAMERA"
    to_camera.location = (-1120, -140)
    split = nodes.new("ShaderNodeSeparateXYZ")
    split.location = (-940, -140)
    flat = nodes.new("ShaderNodeCombineXYZ")
    flat.location = (-760, -140)
    flat.label = "清零上下分量"
    rotate = nodes.new("ShaderNodeMapping")
    rotate.vector_type = "POINT"
    rotate.location = (-580, -140)
    rotate.label = "受光方向"
    rotate.inputs["Rotation"].default_value = (0.0, 0.0, 0.0)
    back = nodes.new("ShaderNodeSeparateXYZ")
    back.location = (-400, -140)
    links.new(geometry.outputs["Normal"], to_camera.inputs["Vector"])
    links.new(to_camera.outputs["Vector"], split.inputs["Vector"])
    links.new(split.outputs["X"], flat.inputs["X"])
    links.new(split.outputs["Z"], flat.inputs["Z"])
    links.new(flat.outputs["Vector"], rotate.inputs["Vector"])
    links.new(rotate.outputs["Vector"], back.inputs["Vector"])

    # 受光方向 0..1 → 绕竖轴 -180°..180°
    turn = math_node(nodes, "SUBTRACT", 0.5, "旋转居中", (-940, -340))
    links.new(source.outputs["受光方向"], turn.inputs[0])
    turn.inputs[1].default_value = 0.5
    turn_rad = math_node(nodes, "MULTIPLY", 6.283185, "→ 弧度", (-760, -340))
    links.new(turn.outputs[0], turn_rad.inputs[0])
    links.new(turn_rad.outputs[0], rotate.inputs["Rotation"])

    # 遮罩 = clamp((x - (0.5 - 柔和/2)) / 柔和)
    half = math_node(nodes, "MULTIPLY", 0.5, "柔和/2", (-400, -440))
    links.new(source.outputs["分界宽度"], half.inputs[0])
    centre = math_node(nodes, "SUBTRACT", 0.5, "0.5 - 柔和/2", (-220, -440))
    links.new(half.outputs[0], centre.inputs[1])
    centre.inputs[0].default_value = 0.5

    band = soft_step(nodes, back.outputs["X"], centre.outputs[0],
                     source.outputs["分界宽度"], (0, -140), "阴影分界")

    # ---- 渐变贴图（MMD toon ramp）---------------------------------------
    # MMD 查表不用模型 UV，而是 U=0.5、V=受光程度；受光程度要玩家里的旋转法线，
    # 只能在组内算，所以只收材质树送来的「渐变遮罩」（1 = 暗部）。
    # 渐变强度=0 时它完全不参与，退回自建条带
    blended, blend_fac, blend_a, blend_b, blended_out = mix(
        nodes, "MIX", 0.0, "条带 / 渐变贴图", (200, -400))
    links.new(band.outputs[0], blend_a)
    links.new(source.outputs["渐变遮罩"], blend_b)
    links.new(source.outputs["渐变强度"], blend_fac)

    edge_fade = fresnel(nodes, 1.45, (0, -340), "别绕到剪影")
    mask = math_node(nodes, "MULTIPLY", None, "× Fresnel", (200, -240))
    links.new(blended_out, mask.inputs[0])
    links.new(edge_fade.outputs["Fac"], mask.inputs[1])
    strength = math_node(nodes, "MULTIPLY", None, "× 暗部深浅", (380, -240))
    links.new(mask.outputs[0], strength.inputs[0])
    links.new(source.outputs["暗部深浅"], strength.inputs[1])

    # ---- 分界暖边：分界外侧一圈暖色（MMD 卡渲的标志之一） ----------------
    # 同一条分界再算一次、宽度放大若干倍，相减即得外侧那一圈。
    wide_width = math_node(nodes, "MULTIPLY", 9.0, "黄边宽度 = 柔和 × 9",
                           (200, -460))
    links.new(source.outputs["分界宽度"], wide_width.inputs[0])
    band_wide = soft_step(nodes, back.outputs["X"], centre.outputs[0],
                          wide_width.outputs[0], (380, -460), "黄边分界")
    edge = math_node(nodes, "SUBTRACT", None, "黄边 = 宽分界 - 硬分界",
                     (560, -460), clamp=True)
    links.new(band_wide.outputs[0], edge.inputs[0])
    links.new(band.outputs[0], edge.inputs[1])
    edge_amount = math_node(nodes, "MULTIPLY", None, "× 分界暖边", (740, -460),
                            clamp=True)
    links.new(edge.outputs[0], edge_amount.inputs[0])
    links.new(source.outputs["分界暖边"], edge_amount.inputs[1])

    shadow_color, _, shadow_a, shadow_b, shadow_out = mix(
        nodes, "MULTIPLY", 1.0, "底色 × 暗部色", (-540, 60))
    links.new(contrast_out, shadow_a)
    links.new(source.outputs["暗部色"], shadow_b)

    shaded, shaded_fac, shaded_a, shaded_b, shaded_out = mix(
        nodes, "MIX", 0.0, "上阴影", (560, 160))
    links.new(contrast_out, shaded_a)
    links.new(shadow_out, shaded_b)
    links.new(strength.outputs[0], shaded_fac)

    # ---- 高光：Fresnel 收成一条柔亮边 ----------------------------------
    spec_edge = fresnel(nodes, 1.60, (560, -340), "高光边缘")
    spec_sharp = math_node(nodes, "POWER", 0.55, "高光集中", (740, -340),
                           clamp=True)
    links.new(spec_edge.outputs["Fac"], spec_sharp.inputs[0])
    links.new(source.outputs["高光集中"], spec_sharp.inputs[1])
    spec_level = math_node(nodes, "MULTIPLY", None, "× 高光强弱", (920, -340),
                           clamp=True)
    links.new(spec_sharp.outputs[0], spec_level.inputs[0])
    links.new(source.outputs["高光强弱"], spec_level.inputs[1])

    lit, lit_fac, lit_a, lit_b, lit_out = mix(
        nodes, "ADD", 0.0, "加高光", (1100, 160))
    links.new(shaded_out, lit_a)
    links.new(source.outputs["高光色"], lit_b)
    links.new(spec_level.outputs[0], lit_fac)

    # 黄边叠在最后（它属于分界，不该被高光盖住）
    ringed, _ring_fac, ring_a, ring_b, ringed_out = mix(
        nodes, "ADD", 0.0, "加分界暖边", (1280, 160))
    links.new(lit_out, ring_a)
    links.new(source.outputs["暖边色"], ring_b)
    links.new(edge_amount.outputs[0], _ring_fac)
    # ---- 轮廓光：Fresnel 环带 × 宽度 × 强度 ----------------------------
    rim_edge = fresnel(nodes, 2.0, (560, -560), "轮廓边缘")
    rim_start = math_node(nodes, "SUBTRACT", 1.0, "1 - 轮廓宽度", (740, -560))
    links.new(source.outputs["轮廓宽度"], rim_start.inputs[1])
    rim_start.inputs[0].default_value = 1.0
    rim_width = soft_step(nodes, rim_edge.outputs["Fac"], rim_start.outputs[0],
                          source.outputs["轮廓宽度"], (920, -560), "轮廓宽度")
    rim_level = math_node(nodes, "MULTIPLY", None, "× 轮廓强度", (1120, -560),
                          clamp=True)
    links.new(rim_width.outputs[0], rim_level.inputs[0])
    links.new(source.outputs["轮廓强度"], rim_level.inputs[1])

    main_shader = nodes.new("ShaderNodeEmission")
    main_shader.location = (1100, 420)
    main_shader.label = "主着色"
    main_shader.inputs["Strength"].default_value = 1.0
    links.new(ringed_out, main_shader.inputs["Color"])

    rim_shader = nodes.new("ShaderNodeEmission")
    rim_shader.location = (1100, 560)
    rim_shader.label = "轮廓光"
    rim_shader.inputs["Strength"].default_value = 1.0
    links.new(source.outputs["轮廓色"], rim_shader.inputs["Color"])

    rim_mix = nodes.new("ShaderNodeMixShader")
    rim_mix.location = (1300, 480)
    links.new(rim_level.outputs[0], rim_mix.inputs["Fac"])
    links.new(main_shader.outputs["Emission"], rim_mix.inputs[1])
    links.new(rim_shader.outputs["Emission"], rim_mix.inputs[2])

    clear = nodes.new("ShaderNodeBsdfTransparent")
    clear.location = (1300, 220)
    alpha_mix = nodes.new("ShaderNodeMixShader")
    alpha_mix.location = (1400, 380)
    links.new(source.outputs["Alpha"], alpha_mix.inputs["Fac"])
    links.new(clear.outputs["BSDF"], alpha_mix.inputs[1])
    links.new(rim_mix.outputs["Shader"], alpha_mix.inputs[2])

    clear2 = nodes.new("ShaderNodeBsdfTransparent")
    clear2.location = (1300, 60)
    base_alpha_mix = nodes.new("ShaderNodeMixShader")
    base_alpha_mix.location = (1400, 200)
    links.new(source.outputs["Base Alpha"], base_alpha_mix.inputs["Fac"])
    links.new(clear2.outputs["BSDF"], base_alpha_mix.inputs[1])
    links.new(alpha_mix.outputs["Shader"], base_alpha_mix.inputs[2])

    links.new(base_alpha_mix.outputs["Shader"], sink.inputs["着色"])
    links.new(ringed_out, sink.inputs["颜色"])
    return group


def apply_preset(group_node, values):
    """把预设的值写进组节点的输入（表里没写的项保持默认）。"""
    for name, value in values.items():
        socket = group_node.inputs.get(name)
        if socket is None:
            continue
        try:
            if socket.type == "RGBA":
                socket.default_value = tuple(value)
            elif socket.type in ("VALUE", "INT"):
                socket.default_value = float(value)
            else:
                # 预设表里不该有非数值/非颜色的项；往没有 default_value 的插座写，
                # Blender 会刷 "RNA_float_set: NodeSocket.default_value not found."
                print("[MikuMikuToon] 预设项 %s 对应的插座是 %s 类型，跳过" % (name, socket.type))
        except Exception as error:
            print("[MikuMikuToon] 预设项 %s 写不进去：%s" % (name, error))
