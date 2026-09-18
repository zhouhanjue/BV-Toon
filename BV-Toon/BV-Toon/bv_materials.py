# -*- coding: utf-8 -*-
"""BVToon -- 材质层：把卡渲套到 MMD 材质上、还原、腮红、目影。

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


# ---------------------------------------------------------------------------
# 腮红：**只给脸加**（2026-09-19 改）
# 以前是无差别写到每个卡渲材质上 —— 实测这个模型 39 个材质全中，衣服、头发、
# 裙子、腿一起泛红。现在先认出"脸"，只写它，并把其余材质上的腮红清零。
# ---------------------------------------------------------------------------

#: 脸部材质关键词（**强**：命中基本可以确定是脸）
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

#: 模型自带"腮红贴图"的关键词（MMD 的 照れ 之类）。这种贴图用 **alpha** 画图案：
#: 实测 照れ.png 是 2048²、98% 全透明、RGB 几乎是均匀浅粉 —— 亮度当遮罩没用，必须用 alpha。
BLUSH_TEXTURE_HINTS = ("照れ", "テレ", "赤面", "blush", "cheek", "チーク", "红晕", "脸红",
                       "ほっぺ", "照脸红")
#: 我们自己往材质树里插的节点名（一律 bv_ 前缀，免得被白名单清理吃掉）
BLUSH_TEX_NODE = "bv_blush_tex"
BLUSH_MASK_NODE = "bv_blush_mask"
#: 把贴图 alpha 规整成遮罩：这个值以下当没有，这个值以上当满遮罩
BLUSH_ALPHA_FLOOR = 0.15
BLUSH_ALPHA_CEIL = 0.50

#: 点「添加腮红」时写进组输入的值。
#: ⚠️ 这套值是**在真实模型上量出来的**（`_scratch/probe_blush_*.py`、`probe_giant_cheek.py`）：
#: 腮红遮罩 = `保底 + (1-保底) × 脸颊圈`（**只看几何，不看明暗**）。
#: 早先按亮度卡阈值（先绝对、后相对）两次都栽了：老 PMD 模型的脸是纯白 × 亮度 1.05，
#: 绝对阈值够不着；换成"除以自己的峰值"之后，实测最终色比参考峰值亮 1.0~4.6 倍，
#: 阈值项还是恒 0 —— 把半径设成 100（遮罩恒 1）时腮红有 2300 像素、默认半径只有 21 像素。
#: 现在保底让"脸上看得见"，脸颊圈让"浓在两颊"，不再有可以整体归零的项。
BLUSH_STRENGTH = 0.80
#: 腮红色：**要跟肤色拉开距离**才看得见。早先的 (1.0, 0.62, 0.66) 跟肤色只差 0.2 左右，
#: 实测好几个模型上"开腮红前后"的最大像素差只有 0.05（人眼基本无感）；现在压深一点。
BLUSH_COLOR = (1.0, 0.52, 0.56, 1.0)
#: 整块脸上的保底浓度（0 = 只有两颊有；别给 0，认不出脸颊时就又什么都看不见了）
BLUSH_FLOOR = 0.35

#: 脸颊圈摆在哪：全部按"脸材质**自己**的包围盒"取相对比例，而且量的是**物体局部
#: 坐标**（就是卡渲组里 TexCoord.Object 那套）—— 所以模型多大、导入比例多少、
#: 物体有没有旋转缩放都不用改数字。四个比例在真实模型上量过（_scratch 里的探针）。
CHEEK_SIDE = 0.45      # 横向：脸半宽的 45%（左右各一团）
CHEEK_DROP = 0.05      # 纵向：从脸中心往下，脸半高的 5%（颊面大致在鼻子那一带）
CHEEK_SINK = 0.55      # 球心沿"脸朝向"往里压进半径的 55%（保证球切出一块圆盘，不是擦边）
CHEEK_RADIUS = 0.42    # 球半径 = 脸半宽 × 42%
CHEEK_SOFT = 0.55      # 边缘 55% 做软过渡（越靠外越淡）


def _hit(text, hints):
    low = (text or "").lower()
    return any(hint in low for hint in hints)


def _material_zone(objects):
    """每个材质在**头部区域**里的面积（用来给"名字认不出来"的模型认脸）。

    头部区域用 MMD 标准骨定：``頭``（没有就 ``首``/``上半身``）的世界 z 往上。
    返回 ``(区域面积字典, 依据说明)``；拿不到骨架就返回 ``({}, 原因)``。

    实测（2013 年的 初音ミク.pmd）：脸材质叫「材質7」、贴图是共享 toon —— 名字和贴图都没有
    线索；但它的面**完全落在颈部以上**，而头发「材質16」一直伸到脚踝 ⇒ 这个信号是可靠的。
    """
    meshes = []
    for obj in objects or ():
        if obj.type == "MESH" and obj.data is not None:
            meshes.append(obj)
    if not meshes:
        return {}, "没有网格"
    armature = None
    for obj in bpy.data.objects:
        if obj.type == "ARMATURE" and getattr(obj, "mmd_type", "NONE") in ("ARMATURE", None):
            armature = obj
            break
    if armature is None:
        for obj in bpy.data.objects:
            if obj.type == "ARMATURE":
                armature = obj
                break
    if armature is None:
        return {}, "没有骨架"
    zone_z = None
    bone_name = ""
    for names in (NECK_BONES, HEAD_BONES):
        for name in names:
            bone = armature.data.bones.get(name)
            if bone is not None:
                zone_z = (armature.matrix_world @ bone.head_local).z
                bone_name = name
                break
        if zone_z is not None:
            break
    if zone_z is None:
        return {}, "骨架里没有 頭/首 这类标准骨"

    # 一趟统计：每个材质的 min z（判断"是不是整块都在头上"）和头部区域里的面积
    min_z, area_above = {}, {}
    for obj in meshes:
        matrix = obj.matrix_world
        slots = obj.material_slots
        for poly in obj.data.polygons:
            slot = poly.material_index
            mat = slots[slot].material if slot < len(slots) else None
            if mat is None:
                continue
            name = mat.name
            centre_z = (matrix @ poly.center).z
            if name not in min_z or centre_z < min_z[name]:
                min_z[name] = centre_z
            if centre_z >= zone_z:
                area_above[name] = area_above.get(name, 0.0) + poly.area
    # "整个材质都在颈部以上"才算头部候选：只要有一块伸到脖子以下（比如长发）就排除
    area_in = {name: area for name, area in area_above.items()
               if min_z.get(name, 0.0) >= zone_z}
    return area_in, "按标准骨「%s」的 z=%.3f 划头部区域" % (bone_name, zone_z)


def _face_zone_scores(materials, objects):
    """名字认不出时的兜底：头部区域里**没被排除**的材质，按面积排序。"""
    area_in, why = _material_zone(objects)
    if not area_in:
        return [], why
    pool = [mat for mat in materials if mat.name in area_in
            and not _hit(mat.name, NOT_FACE_HINTS)]
    if not pool:
        return [], why
    pool.sort(key=lambda mat: area_in.get(mat.name, 0.0), reverse=True)
    return pool, why


def face_materials(materials, objects=()):
    """从一堆材质里认出"脸部"材质，返回 ``(列表, 依据说明)``。

    实测过的坑：胡桃的脸叫「面」/「面1」、「肌」是**全身皮肤**（没有排除项时腮红会糊到全身）；
    2013 年的 初音ミク.pmd 材质名全是「材質N」、贴图是共享 toon，名字和贴图都认不出来。
    所以现在是四步，**先准后宽**：

    1. **材质名**：命中脸部关键词，且没命中"明显不是脸"的词（头发/眼睛/衣饰…）
    2. **底色贴图名**像脸，而且只有这一个材质用它
    3. **头部几何**（兜底）：用 MMD 标准骨 ``頭``/``首`` 划出头部区域，
       取"整个材质都在颈部以上、且名字没被排除"的材质里**面积最大**的那个 ——
       这是**猜**，所以依据里会写明，面板也会显示出来让人改
    4. 只有一个材质带肤色关键词（``肌``/``skin``）时才用它（身体材质风险最高，放最后）

    都认不出来就返回空列表 + 说明（调用方报警并列出材质名，绝不"干脆全加"）。
    """
    pool = [mat for mat in materials if mat is not None]
    if not pool:
        return [], "没有材质"

    by_name = [mat for mat in pool
               if _hit(mat.name, FACE_HINTS) and not _hit(mat.name, NOT_FACE_HINTS)]
    if by_name:
        return by_name, "材质名里有脸部关键词（%s）" % "、".join(m.name for m in by_name)

    users = {}
    for obj in objects or ():
        for slot in getattr(obj, "material_slots", ()):
            if slot.material is not None:
                users.setdefault(slot.material.name, []).append(obj.name)
    by_mesh = [mat for mat in pool
               if _hit(" ".join(users.get(mat.name, ())), FACE_HINTS)
               and not _hit(mat.name, NOT_FACE_HINTS)]
    if by_mesh:
        return by_mesh, "用它的网格名里有脸部关键词（%s）" % "、".join(
            m.name for m in by_mesh)

    by_texture = [mat for mat in pool
                  if _hit(getattr(util.base_image(mat), "name", ""), FACE_TEXTURE_HINTS)
                  and not _hit(mat.name, NOT_FACE_HINTS)]
    if len(by_texture) == 1:
        return by_texture, "底色贴图 %s 像脸，且只有它用" % getattr(
            util.base_image(by_texture[0]), "name", "?")

    zone, why = _face_zone_scores(pool, objects)
    if zone:
        note = "猜的：%s，那里面积最大的是「%s」（不对就用面板上的「脸=当前材质」指定）" \
            % (why, zone[0].name)
        # 头部区域里"整块都在脖子上"的候选都很小的时候（实测 鏡音リン：最大的一块只有 58 面
        # —— 那是眼睛/嘴之类），老实说清楚：这时候别硬猜，让人自己指。
        if _polygon_count(zone[0], objects) < 128:
            note += "；⚠ 这块只有 %d 个面，很可能是眼睛/嘴之类的零件 —— 请选中真正的脸材质后点「脸=当前材质」" \
                % _polygon_count(zone[0], objects)
        return [zone[0]], note

    by_skin = [mat for mat in pool if _hit(mat.name, SKIN_HINTS)]
    if len(by_skin) == 1:
        return by_skin, "唯一的肤色材质（%s）" % by_skin[0].name

    return [], ("认不出哪个材质是脸（材质名 / 网格名 / 底色贴图 / 头部几何 / 肤色关键词都试过）；"
                "现有材质：%s" % "、".join(mat.name for mat in pool[:12]))


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


def _neck_z():
    """颈部骨（认不出就用头部骨）的世界 z；没有骨架就 None。"""
    armature = None
    for obj in bpy.data.objects:
        if obj.type == "ARMATURE" and getattr(obj, "mmd_type", "NONE") in ("ARMATURE", None):
            armature = obj
            break
    if armature is None:
        for obj in bpy.data.objects:
            if obj.type == "ARMATURE":
                armature = obj
                break
    if armature is None:
        return None
    for names in (NECK_BONES, HEAD_BONES):
        for name in names:
            bone = armature.data.bones.get(name)
            if bone is not None:
                return (armature.matrix_world @ bone.head_local).z
    return None


def blush_region(mat, objects=()):
    """算这块脸材质的左右脸颊中心 + 半径，返回 ``(左, 右, 半径, 说明)``。

    **全是物体局部坐标**（配卡渲组里的 ``TexCoord.Object``），所以：
    模型多大、导入比例是多少、物体有没有旋转缩放，都不影响这几个数。

    量法（只用"这块材质自己画在哪"，不猜模型朝向）：

    1. 取用这块材质的那些面的顶点，只留**颈部以上**（有的模型"脸"材质顺手包了脖子）
    2. 中心 = 这些点的平均；**前** = 这些面的法线按面积加权（脸是朝前的，权重自然最大）
    3. **上** = 世界 Z 换算到物体局部；**右** = 前 × 上（左右对称，符号无所谓）
    4. 脸颊 = 中心 ± 右 × 45% 半宽 + 前 × 55% 凸出 − 上 × 10% 半高，半径 = 34% 半宽

    认不出来就 ``(None, None, 0.0, 原因)`` —— 卡渲组这时退回"整张脸"，照样只加在
    这块脸材质上（不会糊到身体）。
    """
    owners = [obj for obj in (objects or ())
              if obj.type == "MESH" and obj.data is not None
              and any(slot.material is mat for slot in obj.material_slots)]
    if not owners:
        owners = [obj for obj in bpy.data.objects
                  if obj.type == "MESH" and obj.data is not None
                  and any(slot.material is mat for slot in obj.material_slots)]
    if not owners:
        return None, None, 0.0, "没有网格用这块材质"
    obj = max(owners, key=lambda item: len(item.data.polygons))
    slots = {index for index, slot in enumerate(obj.material_slots)
             if slot.material is mat}
    if not slots:
        return None, None, 0.0, "网格里没有这块材质的槽"

    mesh = obj.data
    indices, normals = set(), []
    for poly in mesh.polygons:
        if poly.material_index in slots:
            indices.update(poly.vertices)
            normals.append((poly.normal.copy(), poly.area))
    if len(indices) < 8:
        return None, None, 0.0, "这块材质的几何太少（%d 个点）" % len(indices)
    coords = [mesh.vertices[index].co.copy() for index in indices]

    floor_z = _neck_z()
    if floor_z is not None:
        matrix = obj.matrix_world
        above = [co for co in coords if (matrix @ co).z >= floor_z]
        if len(above) >= 8:                       # 全在脖子以下就别筛（宁可不动）
            coords = above

    centre = Vector((0.0, 0.0, 0.0))
    for co in coords:
        centre += co
    centre /= len(coords)

    world_to_local = obj.matrix_world.inverted().to_3x3()
    up = world_to_local @ Vector((0.0, 0.0, 1.0))
    if up.length < 1e-9:
        return None, None, 0.0, "物体的朝上方向退化"
    up.normalize()
    forward = Vector((0.0, 0.0, 0.0))
    for normal, area in normals:
        forward += normal * area
    if forward.length < 1e-9:
        forward = world_to_local @ Vector((0.0, -1.0, 0.0))   # MMD 惯例：脸朝 -Y
    forward = (forward - up * forward.dot(up)).normalized()
    right = forward.cross(up)
    if right.length < 1e-9:
        return None, None, 0.0, "脸的正前/朝上方向共线"
    right.normalize()

    half_w = max(abs((co - centre).dot(right)) for co in coords)
    half_h = max(abs((co - centre).dot(up)) for co in coords)
    radius = half_w * CHEEK_RADIUS
    if radius <= 1e-6:
        return None, None, 0.0, "脸材质的包围盒是扁的（半宽 %.5f）" % half_w
    # 脸颊球心两步定：
    #   ① 在"左右/上下"这个平面里挑出离目标点**最近的一颗真实顶点** —— 它在颊面上，
    #      所以球一定切得到脸颊（早先按"中心往前推 55% 凸出"算，球心落在头里面，
    #      球面只是擦着颊面过去，实测遮罩几乎全是 0）
    #   ② 再沿 -前 压进去一点，让球和颊面交出一个**圆盘**而不是一个小点
    cheeks = []
    for sign in (1.0, -1.0):
        target_x, target_z = sign * half_w * CHEEK_SIDE, -half_h * CHEEK_DROP
        nearest = min(coords, key=lambda co: ((co - centre).dot(right) - target_x) ** 2
                      + ((co - centre).dot(up) - target_z) ** 2)
        cheeks.append(nearest - forward * (radius * CHEEK_SINK))
    return cheeks[0], cheeks[1], radius, \
        "脸材质 %s 的颊面（半宽 %.4f／半高 %.4f），脸颊球半径 %.4f" \
        % (obj.name, half_w, half_h, radius)


def place_blush(mat, objects=()):
    """把脸颊圈写进卡渲组；认不出脸颊就把半径清零（= 退回整脸）。返回 ``(是否, 说明)``。"""
    node = find_group_node(mat)
    if node is None:
        return False, "这块材质还没卡渲过"
    if node.inputs.get("腮红半径") is None:
        return False, "卡渲组是旧资产（没有脸颊圈输入）—— 重新点一次「一键卡渲」"
    left, right, radius, why = blush_region(mat, objects)
    if left is None:
        node.inputs["腮红半径"].default_value = 0.0
        return False, why
    for name, value in (("腮红左", tuple(left)), ("腮红右", tuple(right)),
                        ("腮红半径", float(radius)), ("腮红软边", CHEEK_SOFT)):
        knob = node.inputs.get(name)
        if knob is not None:
            knob.default_value = value
    return True, why


def set_blush(mat, amount=BLUSH_STRENGTH):
    """把腮红写进卡渲组（``amount=0`` 就是关掉）。没卡渲过返回 False。"""
    node = find_group_node(mat)
    if node is None:
        return False
    socket = node.inputs.get("腮红浓淡")
    if socket is None:
        return False
    socket.default_value = amount
    if amount:
        for name, value in (("腮红色", BLUSH_COLOR), ("腮红保底", BLUSH_FLOOR)):
            knob = node.inputs.get(name)
            if knob is not None:
                knob.default_value = value
    return True


def add_blush(mat):
    """旧接口：给一个材质打开腮红（现在只会被脸部材质调到）。"""
    return set_blush(mat)


def blush_texture(materials):
    """找出模型自带的腮红贴图（照れ 之类），返回 ``(图片, 说明)``；没有就 ``(None, 原因)``。

    认法：材质名或它的底色贴图名命中 ：data:`BLUSH_TEXTURE_HINTS`。
    这是**作者自己画的腮红形状**，比我们猜的阈值准得多。
    """
    for mat in materials:
        if mat is None:
            continue
        image = util.base_image(mat)
        name = getattr(image, "name", "") or ""
        if _hit(mat.name, BLUSH_TEXTURE_HINTS):
            if image is not None:
                return image, "模型自带腮红材质「%s」的贴图 %s" % (mat.name, name)
        if name and _hit(name, BLUSH_TEXTURE_HINTS):
            return image, "模型自带腮红贴图 %s（材质「%s」）" % (name, mat.name)
    return None, "模型里没有找到腮红贴图（照れ / blush / チーク …）"


def wire_blush_mask(mat, image):
    """把腮红贴图的 **alpha** 接进卡渲组的「腮红贴图」输入（遮罩）。

    贴图外面套一个我们自己建的节点（``bv_`` 前缀），UV 跟着底色贴图走 ——
    不然 MMD 的自建 UV 组不会生效，图案会跑到别的地方去。
    """
    node = find_group_node(mat)
    if node is None or image is None:
        return False
    socket = node.inputs.get("腮红贴图")
    if socket is None:
        print("[BV-Toon] 卡渲组里没有「腮红贴图」输入（资产是旧版？）"
              "—— 这次只能用着色器腮红")
        return False
    tree = mat.node_tree
    texture = tree.nodes.get(BLUSH_TEX_NODE)
    if texture is None or texture.type != "TEX_IMAGE":
        texture = tree.nodes.new("ShaderNodeTexImage")
        texture.name = BLUSH_TEX_NODE
        texture.label = "腮红贴图（遮罩）"
        texture.location = (node.location.x - 320, node.location.y - 620)
    texture.image = image
    try:
        texture.image.colorspace_settings.name = "Non-Color"
    except Exception as error:
        print("[BV-Toon] 腮红贴图色彩空间没设上：%s" % error)
    # UV 跟底色贴图一致（MMD 自建 UV 组）
    base = tree.nodes.get(util.BASE_TEX)
    for link in list(texture.inputs["Vector"].links):
        tree.links.remove(link)
    source = None
    if base is not None and base.type == "TEX_IMAGE":
        source = base.inputs["Vector"].links[0].from_socket \
            if base.inputs["Vector"].is_linked else None
    if source is not None:
        tree.links.new(source, texture.inputs["Vector"])
    # 用 alpha 当遮罩（RGB 是均匀浅粉，亮度没有信息）。照れ 这类贴图的 alpha 整体很淡
    # （实测：均值 0.02、>0.5 的只占 1.8%），直接乘会把腮红抹没 —— 先映射一次：
    # alpha 0.15 以下当没有（免得整脸一层雾），0.50 以上当满遮罩。
    mask = tree.nodes.get(BLUSH_MASK_NODE)
    if mask is None or mask.type != "MAP_RANGE":
        mask = tree.nodes.new("ShaderNodeMapRange")
        mask.name = BLUSH_MASK_NODE
        mask.label = "腮红遮罩（alpha 规整）"
        mask.location = (node.location.x - 320, node.location.y - 760)
    mask.clamp = True
    for socket_name, value in (("From Min", BLUSH_ALPHA_FLOOR),
                               ("From Max", BLUSH_ALPHA_CEIL),
                               ("To Min", 0.0), ("To Max", 1.0)):
        # ⚠️ 别把上面的组输入变量 socket 覆盖掉（我第一版就是这么写的：
        # 结果遮罩接到了 Map Range 自己的插槽上，组的输入根本没接）
        knob = mask.inputs.get(socket_name)
        if knob is None:
            print("[BV-Toon] 腮红遮罩节点缺少 %s 输入，遮罩可能不准" % socket_name)
            continue
        knob.default_value = value
    for link in list(mask.inputs["Value"].links):
        tree.links.remove(link)
    tree.links.new(texture.outputs["Alpha"], mask.inputs["Value"])
    for link in list(socket.links):
        tree.links.remove(link)
    tree.links.new(mask.outputs["Result"], socket)
    # **告诉组"用贴图当遮罩"**（组里是"替换内置遮罩"，不是相乘）
    use = node.inputs.get("腮红用贴图")
    if use is None:
        print("[BV-Toon] 卡渲组里没有「腮红用贴图」输入（.blend 资产是旧版？）"
              "—— 贴图遮罩会跟内置遮罩相乘，腮红会明显变淡")
        return False
    use.default_value = 1.0
    return True


def clear_blush_mask(mat):
    """把「腮红贴图」输入还原成 1.0、并关掉「用贴图」，摘掉我们插的节点。"""
    node = find_group_node(mat)
    if node is None or mat.node_tree is None:
        return False
    socket = node.inputs.get("腮红贴图")
    if socket is None:
        return False
    tree = mat.node_tree
    for link in list(socket.links):
        tree.links.remove(link)
    socket.default_value = 1.0
    use = node.inputs.get("腮红用贴图")
    if use is not None:
        use.default_value = 0.0
    for name in (BLUSH_TEX_NODE, BLUSH_MASK_NODE):
        stale = tree.nodes.get(name)
        if stale is not None:
            tree.nodes.remove(stale)
    return True


def blush_mask_source(mat):
    """当前腮红遮罩接的是什么（给体检/日志用）：贴图名 / None。"""
    node = find_group_node(mat)
    if node is None or mat.node_tree is None:
        return None
    socket = node.inputs.get("腮红贴图")
    if socket is None or not socket.is_linked:
        return None
    source = socket.links[0].from_node
    image = getattr(source, "image", None)
    return getattr(image, "name", None) or source.name


def blush_amount(mat):
    """当前腮红浓淡（没卡渲过就是 None）。"""
    node = find_group_node(mat)
    if node is None or node.inputs.get("腮红浓淡") is None:
        return None
    return node.inputs["腮红浓淡"].default_value


# 目影
# ---------------------------------------------------------------------------

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