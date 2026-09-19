# -*- coding: utf-8 -*-
"""BVToon -- 材质层：把卡渲套到 MMD 材质上、还原、目影。

原则：**只为底色和球面建自己的节点**（bv_util 负责），着色交给自己的节点组；
不删除、不改写别家插件的节点，所以原始数据一直在，随时能还原。

© 2025 BVan / DEEPSEEK
"""

import bpy
from mathutils import Vector

from . import bv_shading as shading
from . import bv_util as util

#: 目影材质关键词
EYE_SHADOW_HINTS = ("目影", "眼睛", "eye_shadow", "eye shadow")


# ---------------------------------------------------------------------------
# 卡渲套用 / 还原
# ---------------------------------------------------------------------------

def find_group_node(mat):
    tree = mat.node_tree if mat.use_nodes else None
    if tree is None:
        return None
    for node in tree.nodes:
        if node.bl_idname == "ShaderNodeGroup" and node.node_tree is not None \
                and node.node_tree.name == shading.SHADING_GROUP:
            return node
    return None


def material_output(tree):
    node = next((n for n in tree.nodes if n.type == "OUTPUT_MATERIAL"
                 and n.is_active_output), None)
    if node is None:
        node = next((n for n in tree.nodes if n.type == "OUTPUT_MATERIAL"), None)
    if node is None:
        node = tree.nodes.new("ShaderNodeOutputMaterial")
        node.location = (1700, 0)
    return node


def apply_preset(mat, preset_index=0, sphere_strength=1.0, report=None):
    """把一个预设套到这个材质上。返回 True 表示材质被处理过。"""
    # mmd_edge.* 是 mmd_tools 的描边材质（也带 mmd_material），绝对不能套卡渲，
    # 否则描边材质被改掉 -> 描边直接消失（实测踩过）
    if mat.name.startswith("mmd_edge"):
        return False
    if not util.is_mmd(mat) or not mat.use_nodes or mat.node_tree is None:
        return False
    data = util.mmd(mat)
    tree = mat.node_tree

    _name, values = shading.preset_values(preset_index)
    # 预设里可以带一个"球面强度"（不是组输入，接球面层时用）
    strength = float(values.get("球面强度", sphere_strength))

    textures = util.texture_nodes(mat, report=report)
    base = textures["base"]
    base_socket = base.outputs["Color"] if base is not None else None
    if base_socket is not None:
        # 球面强度按 MMD 模式分开：加算(2)是闪片/宝石那层，压低了闪片就不闪、宝石就没了；
        # 乘算(1)是布料上的柔和球面，用预设值（压低它才是"去油腻"该做的）
        sphere_mode = int(getattr(data, "sphere_texture_type", 0))
        if sphere_mode == 2:
            sphere_strength = 1.0
        elif sphere_mode == 3:
            sphere_strength = 0.3
        else:
            sphere_strength = strength
        base_socket = util.sphere_stage(mat, base_socket, sphere_strength)

    node = find_group_node(mat)
    if node is None:
        node = tree.nodes.new("ShaderNodeGroup")
        node.name = "bv_shading"
        node.label = "BVToon 卡渲"
        node.location = (400, 200)
        node.node_tree = shading.shading_group()

    shading.apply_preset(node, values)

    # 渐变贴图（MMD toon ramp）：在材质树里查表，再把算好的暗部遮罩送进组。
    # 查表方式照 MMD：U=0.5、V=受光程度（组的接口不支持图片插座，所以放在这边）。
    toon = textures.get("toon")
    mask_socket = node.inputs.get("渐变遮罩")
    # MMD 的环境色（ambient）就是它的"暗部色调"：掺进 暗部色（有环境色的材质才动）
    ambient = tuple(getattr(data, "ambient_color", ()) or ())
    # 注意：只有环境色**带颜色信息**（三通道不等）时才动暗部色。
    # 实测奥黛塔 49 个材质的环境色全是统一的 0.502 灰 —— 那是"暗部亮度"，
    # 不是颜色；拿它去染暗部只会均匀压暗，还会跟预设的冷色暗部打架。
    if len(ambient) >= 3 and (max(float(x) for x in ambient[:3])
                              - min(float(x) for x in ambient[:3])) > 0.02:
        dark = node.inputs.get("暗部色")
        if dark is not None and not dark.links:
            base = values.get("暗部色", (1.0, 1.0, 1.0, 1.0))
            dark.default_value = tuple(
                min(1.0, float(base[i]) * (0.35 + float(ambient[i])))
                for i in range(3)) + (1.0,)
    strength_socket = node.inputs.get("渐变强度")
    has_toon = toon is not None and getattr(toon, "image", None) is not None
    if mask_socket is not None and strength_socket is not None and has_toon:
        mask = tree.nodes.get("bv_toon_mask")
        if mask is None:
            geometry = tree.nodes.new("ShaderNodeNewGeometry"); geometry.name = "bv_toon_geo"
            geometry.location = (node.location.x - 900, node.location.y - 600)
            geometry.label = "渐变查表（受光程度）"
            turn = tree.nodes.new("ShaderNodeVectorRotate"); turn.name = "bv_toon_turn"
            turn.location = (geometry.location.x + 180, geometry.location.y)
            turn.rotation_type = "AXIS_ANGLE"
            turn.inputs["Axis"].default_value = (0.0, 0.0, 1.0)
            tree.links.new(geometry.outputs["Normal"], turn.inputs["Vector"])
            degrees = None
            turn_socket = node.inputs.get("受光方向")
            if turn_socket is not None:
                degrees = tree.nodes.new("ShaderNodeMath"); degrees.name = "bv_toon_angle"
                degrees.location = (geometry.location.x, geometry.location.y - 220)
                degrees.operation = "MULTIPLY"
                degrees.inputs[1].default_value = 6.283185
                degrees.inputs[0].default_value = float(turn_socket.default_value)
                tree.links.new(degrees.outputs[0],
                               turn.inputs["Angle"])
            split = tree.nodes.new("ShaderNodeSeparateXYZ"); split.name = "bv_toon_split"
            split.location = (turn.location.x + 180, geometry.location.y)
            tree.links.new(turn.outputs["Vector"], split.inputs["Vector"])
            to_v = tree.nodes.new("ShaderNodeMath"); to_v.name = "bv_toon_v"
            to_v.location = (split.location.x + 160, geometry.location.y)
            to_v.operation = "MULTIPLY_ADD"
            to_v.inputs[1].default_value = 0.25
            to_v.inputs[2].default_value = 0.25
            tree.links.new(split.outputs["X"], to_v.inputs[0])
            uv = tree.nodes.new("ShaderNodeCombineXYZ"); uv.name = "bv_toon_uv"
            uv.location = (to_v.location.x + 160, geometry.location.y)
            uv.inputs["X"].default_value = 0.5
            tree.links.new(to_v.outputs[0], uv.inputs["Y"])
            sample = tree.nodes.new("ShaderNodeTexImage")
            sample.location = (uv.location.x + 180, geometry.location.y)
            sample.name = "bv_toon_sample"
            sample.label = "渐变贴图（MMD toon）"
            sample.extension = "EXTEND"
            sample.image = toon.image
            tree.links.new(uv.outputs["Vector"], sample.inputs["Vector"])
            grey = tree.nodes.new("ShaderNodeRGBToBW"); grey.name = "bv_toon_grey"
            grey.location = (sample.location.x + 180, geometry.location.y)
            tree.links.new(sample.outputs["Color"], grey.inputs["Color"])
            mask = tree.nodes.new("ShaderNodeMath")
            mask.location = (grey.location.x + 160, geometry.location.y)
            mask.name = "bv_toon_mask"
            mask.label = "渐变 → 暗部遮罩"
            mask.operation = "MULTIPLY_ADD"   # K×(1−灰度)
            mask.use_clamp = True
            mask.inputs[1].default_value = -7.0
            mask.inputs[2].default_value = 7.0
            tree.links.new(grey.outputs["Val"], mask.inputs[0])
        else:
            sample = tree.nodes.get("bv_toon_sample")
            if sample is not None:
                sample.image = toon.image
        for link in list(mask_socket.links):
            tree.links.remove(link)
        tree.links.new(mask.outputs[0], mask_socket)
    # MMD 的环境色（ambient）就是它的"暗部色调"：掺进 暗部色（有环境色的材质才动）
    ambient = tuple(getattr(data, "ambient_color", ()) or ())
    # 注意：只有环境色**带颜色信息**（三通道不等）时才动暗部色。
    # 实测奥黛塔 49 个材质的环境色全是统一的 0.502 灰 —— 那是"暗部亮度"，
    # 不是颜色；拿它去染暗部只会均匀压暗，还会跟预设的冷色暗部打架。
    if len(ambient) >= 3 and (max(float(x) for x in ambient[:3])
                              - min(float(x) for x in ambient[:3])) > 0.02:
        dark = node.inputs.get("暗部色")
        if dark is not None and not dark.links:
            base = values.get("暗部色", (1.0, 1.0, 1.0, 1.0))
            dark.default_value = tuple(
                min(1.0, float(base[i]) * (0.35 + float(ambient[i])))
                for i in range(3)) + (1.0,)
    strength_socket = node.inputs.get("渐变强度")
    if strength_socket is not None:
        strength_socket.default_value = float(
            values.get("渐变强度", 1.0 if has_toon else 0.0))

    if base_socket is not None:
        socket = node.inputs.get("底色")
        if socket is not None:
            for link in list(socket.links):
                tree.links.remove(link)
            tree.links.new(base_socket, socket)

    _wire_alpha(mat, node)
    _wire_output(tree, node)
    _set_blend_from_mmd(mat, data)
    if report is not None:
        report.append("已卡渲：%s" % mat.name)
    return True


def _wire_alpha(mat, node):
    """Alpha 两级：MMD 的 alpha（整体）与贴图 alpha（逐像素）。"""
    tree = mat.node_tree
    data = util.mmd(mat)
    alpha = node.inputs.get("Alpha")
    base_alpha = node.inputs.get("Base Alpha")
    for socket in (alpha, base_alpha):
        if socket is None:
            continue
        for link in list(socket.links):
            tree.links.remove(link)
    if alpha is not None:
        alpha.default_value = float(getattr(data, "alpha", 1.0))
    base = tree.nodes.get(util.BASE_TEX)
    if base_alpha is not None:
        if base is not None and base.image is not None \
                and base.image.depth in {32, 64}:
            for link in list(base_alpha.links):
                tree.links.remove(link)
            tree.links.new(base.outputs["Alpha"], base_alpha)
        else:
            base_alpha.default_value = 1.0


def _wire_output(tree, node):
    output = material_output(tree)
    socket = output.inputs.get("Surface")
    if socket is None:
        return
    for link in list(socket.links):
        tree.links.remove(link)
    tree.links.new(node.outputs["着色"], socket)


def base_has_alpha(mat):
    """底色贴图自带 alpha 通道吗？（MMD 靠它抠出叠加层：闪片、睫毛、目光…）"""
    if mat.node_tree is None:
        return False
    base = mat.node_tree.nodes.get(util.BASE_TEX)
    if base is None:
        base = next((n for n in mat.node_tree.nodes
                     if n.type == "TEX_IMAGE" and n.image is not None), None)
    return (base is not None and base.image is not None
            and base.image.depth in {32, 64})


def _set_blend_from_mmd(mat, data):
    """按 MMD 的透明度决定混合模式。

    这三条都是渲染实测出来的（每一条都对应一次"画面整片发黑"）：

    * **贴图 alpha 要参与判断**。pmx 里 alpha=1.0 的材质（头发闪片 ``髮+``、目光
      叠加 ``目光2`` 等）在 MMD 里靠**贴图自己的 alpha** 抠形状，贴图黑的地方本来
      不该出现；只按 pmx alpha 判断会设成 OPAQUE，Alpha 输入被忽略 -> 脸上盖一块
      黑面具。
    * **有 alpha 的用 BLEND，不用 HASHED**。抖动+双面一起画会把头发糊成一团黑。
    * **不做背面剔除**。MMD 的"单面"标志按它自己的正面约定写，照搬到 Blender 会把
      **正面**剔掉（胸衣、裙摆正面变黑，看到的是模型内侧）。
    """
    alpha = float(getattr(data, "alpha", 1.0))
    try:
        if alpha < 1.0 or base_has_alpha(mat):
            mat.blend_method = "BLEND"
            mat.show_transparent_back = False
        else:
            mat.blend_method = "HASHED"
            mat.show_transparent_back = True
        mat.use_backface_culling = False
    except Exception:
        pass


def restore(mat):
    """还原成基本材质：只搭一个 Principled + 底色贴图，不给别家节点动刀。"""
    if mat is None or mat.node_tree is None:
        return False
    tree = mat.node_tree
    for node in list(tree.nodes):
        if node.bl_idname == "ShaderNodeGroup" and node.node_tree is not None \
                and node.node_tree.name == shading.SHADING_GROUP:
            tree.nodes.remove(node)
    stage = tree.nodes.get("bv_sphere_stage")
    if stage is not None:
        tree.nodes.remove(stage)

    principled = next((n for n in tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if principled is None:
        principled = tree.nodes.new("ShaderNodeBsdfPrincipled")
        principled.location = (600, 900)
    base = tree.nodes.get(util.BASE_TEX)
    if base is None:
        base = next((n for n in tree.nodes
                     if n.type == "TEX_IMAGE" and n.image is not None), None)
    if base is not None:
        for link in list(principled.inputs["Base Color"].links):
            tree.links.remove(link)
        tree.links.new(base.outputs["Color"], principled.inputs["Base Color"])
        if "Alpha" in principled.inputs and base.image is not None \
                and base.image.depth in {32, 64}:
            for link in list(principled.inputs["Alpha"].links):
                tree.links.remove(link)
            tree.links.new(base.outputs["Alpha"], principled.inputs["Alpha"])
    output = material_output(tree)
    for link in list(output.inputs["Surface"].links):
        tree.links.remove(link)
    tree.links.new(principled.outputs["BSDF"], output.inputs["Surface"])
    return True

FACE_HINTS = ("颜", "顔", "顏", "脸", "臉", "脸部", "面部", "面", "フェイス", "かお", "カオ",
              "face")
#: 脸部**底色贴图**关键词（材质名认不出时看贴图名）
FACE_TEXTURE_HINTS = ("颜", "顔", "顏", "face", "kao", "かお")
#: 肤色关键词：**弱**（多半是身体，不是脸）—— 只在别的证据都没有时才用
SKIN_HINTS = ("肌", "はだ", "皮肤", "肌色", "skin")
#: **明显不是脸**的（头发 / 眼睛 / 睫毛 / 眉 / 口齿舌 / 耳 / 衣物 / 配饰 / 武器）
#: 实测：胡桃的脸叫「面」/「面1」、而「肌」是全身皮肤 —— 没有排除项时会把腮红糊到全身。
NOT_FACE_HINTS = ("髪", "发", "髮", "hair", "目", "眼", "eye", "瞳", "白目", "睫", "lash",
                  "眉", "brow", "口", "mouth", "齿", "歯", "teeth", "舌", "tongue",
                  "耳", "ear", "爪", "nail", "衣", "服", "裙", "裤", "鞋", "靴", "袜",
                  "帽", "饰", "飾", "アクセ", "宝石", "金属", "武器", "剑", "剣", "刀",
                  "rigid", "physics")
#: 头骨的名字（MMD 标准骨名，**连 2013 年的 PMD 都有**）—— 认不出名字时按它定"头部区域"
HEAD_BONES = ("頭", "头", "head", "Head")
NECK_BONES = ("首", "neck", "Neck", "上半身2", "上半身")


def _hit(text, hints):
    low = (text or "").lower()
    return any(hint in low for hint in hints)


def _polygon_count(mat, objects=()):
    """这块材质一共管多少个面（"猜的脸"太小的时候用来提醒人）。"""
    total = 0
    for obj in objects or ():
        if obj.type != "MESH" or obj.data is None:
            continue
        slots = {index for index, slot in enumerate(obj.material_slots)
                 if slot.material is mat}
        if not slots:
            continue
        total += sum(1 for poly in obj.data.polygons if poly.material_index in slots)
    return total


def set_eye_shadow(mat):
    """目影材质：纯黑半透明，压住眼睛上方的阴影。"""
    if mat is None:
        return False
    if not mat.use_nodes:
        mat.use_nodes = True
    tree = mat.node_tree
    for node in list(tree.nodes):
        tree.nodes.remove(node)
    principled = tree.nodes.new("ShaderNodeBsdfPrincipled")
    principled.location = (-300, 0)
    principled.inputs["Base Color"].default_value = (0.0, 0.0, 0.0, 1.0)
    if "Alpha" in principled.inputs:
        principled.inputs["Alpha"].default_value = 0.5
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    output.location = (0, 0)
    tree.links.new(principled.outputs["BSDF"], output.inputs["Surface"])
    try:
        mat.blend_method = "BLEND"
    except Exception:
        pass
    return True


def is_eye_shadow(mat):
    if mat is None:
        return False
    return any(hint in (mat.name or "") for hint in EYE_SHADOW_HINTS)


def edge_settings(mat):
    """MMD 材质自带的描边色与粗细（edge_color / edge_weight）。"""
    data = util.mmd(mat)
    if data is None:
        return None
    colour = tuple(float(x) for x in getattr(data, "edge_color", (0.0, 0.0, 0.0)))[:3]
    return colour, float(getattr(data, "edge_weight", 1.0))



def apply_edge_preview(materials, thickness=0.08):
    """按材质自带的描边参数（edge_color / edge_weight）设置 mmd_tools 的描边。

    mmd_tools 的描边是：一个叫 mmd_edge_preview 的 SOLIDIFY 修改器（粗细全局）
    + 每个材质一个 mmd_edge.<材质名> 描边材质（颜色各自不同）。
    """
    touched = 0
    weights = []
    for mat in materials:
        data = util.mmd(mat)
        if data is None:
            continue
        weights.append(float(getattr(data, "edge_weight", 1.0)))
        colour = tuple(float(x) for x in getattr(data, "edge_color", (0.0, 0.0, 0.0)))[:3]
        for name in ("mmd_edge." + mat.name, "mmd_edge." + mat.name.split(".")[0]):
            edge = bpy.data.materials.get(name)
            if edge is None or not edge.use_nodes or edge.node_tree is None:
                continue
            edge.diffuse_color = (colour[0], colour[1], colour[2], 1.0)
            for node in edge.node_tree.nodes:
                if node.bl_idname == "ShaderNodeGroup" and node.node_tree is not None:
                    for socket in node.inputs:
                        if socket.type == "RGBA" and not socket.links:
                            socket.default_value = (colour[0], colour[1], colour[2], 1.0)
            touched += 1
    weight = (sum(weights) / len(weights)) if weights else 1.0
    thickness = max(0.001, float(thickness))   # 绝对值：面板上的「描边粗细」就是它
    for obj in bpy.data.objects:
        for modifier in obj.modifiers:
            if modifier.type == "SOLIDIFY" or "edge" in modifier.name.lower():
                if hasattr(modifier, "thickness"):
                    modifier.thickness = thickness
                    touched += 1
    print("[BV-Toon] 描边：套到 %d 处，粗细 %.3f（MMD 原始 0.08）"
          % (touched, thickness))
    return touched

#: mmd_tools 原来那套节点的名字/标签（卡渲接管后清掉）



def drop_all_nodes(mat):
    """清空材质树（只留 Material Output）—— 还原用：交给 mmd_tools 重建原来的那套。"""
    if not mat.use_nodes or mat.node_tree is None:
        return 0
    tree = mat.node_tree
    removed = 0
    for node in list(tree.nodes):
        if node.bl_idname == "ShaderNodeOutputMaterial":
            continue
        tree.nodes.remove(node)
        removed += 1
    return removed


def remove_edge_preview():
    """摘掉 mmd_tools 的边缘预览（描边材质 + 描边修改器）。"""
    removed = 0
    try:
        bpy.ops.mmd_tools.edge_preview_setup(action="CLEAN")
        removed += 1
    except Exception as error:
        print("[BV-Toon] edge_preview CLEAN 失败：%s" % error)
    for obj in list(bpy.data.objects):
        for modifier in list(getattr(obj, "modifiers", [])):
            if "edge" in (modifier.name or "").lower():
                try:
                    obj.modifiers.remove(modifier)
                    removed += 1
                except Exception as error:
                    print("[BV-Toon] 删描边修改器失败：%s" % error)
    for mat in list(bpy.data.materials):
        if (mat.name or "").startswith("mmd_edge"):
            try:
                bpy.data.materials.remove(mat)
                removed += 1
            except Exception as error:
                print("[BV-Toon] 删描边材质失败：%s" % error)
    return removed






def drop_other_nodes(mat):
    """白名单清理：只留卡渲自己的节点（bv_*）和 Material Output，其余全删。

    比按名字猜原来的节点可靠 —— mmd_tools 每个版本命名的花样都不一样。
    """
    if not mat.use_nodes or mat.node_tree is None:
        return 0
    tree = mat.node_tree
    if tree.nodes.get("bv_shading") is None:
        return 0                      # 没被卡渲接管过的材质不动
    removed = 0
    for node in list(tree.nodes):
        if node.name.startswith("bv_"):
            continue
        if node.bl_idname == "ShaderNodeOutputMaterial":
            continue
        tree.nodes.remove(node)
        removed += 1
    return removed