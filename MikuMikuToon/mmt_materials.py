# -*- coding: utf-8 -*-
"""MikuMikuToon -- 材质层：把卡渲套到 MMD 材质上、还原、目影。

只为底色和球面建自己的节点，着色交给自己的节点组；不删除、不改写别家插件的节点。
© 2025 BVan / DEEPSEEK
"""

import bpy
from mathutils import Vector

from . import mmt_shading as shading
from . import mmt_util as util

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


def auto_exposure(scene, trigger=None, stop=None, step=None, floor=None,
                  rounds=None):
    """按模型自适应曝光：爆白超过阈值就按步长下调卡渲组的「亮度」。返回 ``(亮度, 说明)``。"""
    from . import mmt_glow
    trigger = mmt_glow.EXPOSURE_TRIGGER if trigger is None else trigger
    stop = mmt_glow.EXPOSURE_STOP if stop is None else stop
    step = mmt_glow.EXPOSURE_STEP if step is None else step
    floor = mmt_glow.EXPOSURE_FLOOR if floor is None else floor
    rounds = mmt_glow.EXPOSURE_ROUNDS if rounds is None else rounds
    sockets = []
    for mat in bpy.data.materials:
        node = find_group_node(mat)
        if node is None:
            continue
        socket = node.inputs.get("亮度")
        if socket is not None and not socket.links:
            sockets.append(socket)
    if not sockets:
        return None, "没有可调的卡渲组（先一键卡渲）"
    current = float(sockets[0].default_value)
    # 用整个模型量（临时全身取景相机），别用用户的相机 —— 否则取景一变结论就变
    targets = set()
    for mat in bpy.data.materials:
        if find_group_node(mat) is None:
            continue
        for obj in bpy.data.objects:
            if obj.type != "MESH":
                continue
            if any(slot.material is mat for slot in obj.material_slots):
                targets.add(obj)
    blown, why = mmt_glow.measure_blown(scene, objects=sorted(targets, key=lambda o: o.name))
    if blown is None:
        return current, "没量成曝光（%s），亮度保持 %.2f" % (why, current)
    if blown <= trigger:
        return current, "爆白 %.1f%%（不超过 %.0f%%），亮度不用动" % (blown * 100,
                                                             trigger * 100)
    start = current
    for _ in range(max(1, int(rounds))):
        if blown is None or blown <= stop or current <= floor + 1e-6:
            break
        current = max(floor, round(current - step, 3))
        for socket in sockets:
            socket.default_value = current
        blown, why = mmt_glow.measure_blown(scene, objects=sorted(targets, key=lambda o: o.name))
    print("[MikuMikuToon] 自适应曝光：亮度 %.2f -> %.2f（爆白 %s）"
          % (start, current, "%.1f%%" % (blown * 100) if blown is not None else "没量成"))
    return current, "爆白 %.1f%% → 亮度 %.2f → %.2f（%s）" % (
        blown * 100 if blown is not None else -1.0, start, current,
        ("已压到 %.0f%% 以下" % (stop * 100)) if (blown is not None and blown <= stop)
        else "已到下限 %.2f" % floor)


def apply_preset(mat, preset_index=0, sphere_strength=1.0, report=None):
    """把一个预设套到这个材质上。返回 True 表示材质被处理过。"""
    # mmd_edge.* 是 mmd_tools 的描边材质，绝对不能套卡渲，否则描边会被改掉。
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
    # MMD 的最终颜色 = 底色贴图 × 材质底色；没有底色贴图时就是材质底色本身，
    # 少这一步这类材质会拿到卡渲组的默认白，整个模型变白。
    diffuse = tuple(float(value) for value in
                    (getattr(data, "diffuse_color", ()) or ()))[:3]
    base_socket = util.base_tint(mat, base_socket, diffuse)
    if base_socket is not None:
        # 球面强度按 MMD 模式分开：加算(2) 是闪片/宝石，压低就不闪，所以不压；乘算(1) 用预设值
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
        node.name = "mmt_shading"
        node.label = "MikuMikuToon 卡渲"
        node.location = (400, 200)
        node.node_tree = shading.shading_group()

    shading.apply_preset(node, values)

    # 渐变贴图（MMD toon ramp）：在这边查表再把暗部遮罩送进组，组的接口不支持图片插座。
    # 查表方式照 MMD：U=0.5、V=受光程度。
    toon = textures.get("toon")
    mask_socket = node.inputs.get("渐变遮罩")
    ambient = tuple(getattr(data, "ambient_color", ()) or ())
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
        mask = tree.nodes.get("mmt_toon_mask")
        if mask is None:
            geometry = tree.nodes.new("ShaderNodeNewGeometry"); geometry.name = "mmt_toon_geo"
            geometry.location = (node.location.x - 900, node.location.y - 600)
            geometry.label = "渐变查表（受光程度）"
            turn = tree.nodes.new("ShaderNodeVectorRotate"); turn.name = "mmt_toon_turn"
            turn.location = (geometry.location.x + 180, geometry.location.y)
            turn.rotation_type = "AXIS_ANGLE"
            turn.inputs["Axis"].default_value = (0.0, 0.0, 1.0)
            tree.links.new(geometry.outputs["Normal"], turn.inputs["Vector"])
            degrees = None
            turn_socket = node.inputs.get("受光方向")
            if turn_socket is not None:
                degrees = tree.nodes.new("ShaderNodeMath"); degrees.name = "mmt_toon_angle"
                degrees.location = (geometry.location.x, geometry.location.y - 220)
                degrees.operation = "MULTIPLY"
                degrees.inputs[1].default_value = 6.283185
                degrees.inputs[0].default_value = float(turn_socket.default_value)
                tree.links.new(degrees.outputs[0],
                               turn.inputs["Angle"])
            split = tree.nodes.new("ShaderNodeSeparateXYZ"); split.name = "mmt_toon_split"
            split.location = (turn.location.x + 180, geometry.location.y)
            tree.links.new(turn.outputs["Vector"], split.inputs["Vector"])
            to_v = tree.nodes.new("ShaderNodeMath"); to_v.name = "mmt_toon_v"
            to_v.location = (split.location.x + 160, geometry.location.y)
            to_v.operation = "MULTIPLY_ADD"
            to_v.inputs[1].default_value = 0.25
            to_v.inputs[2].default_value = 0.25
            tree.links.new(split.outputs["X"], to_v.inputs[0])
            uv = tree.nodes.new("ShaderNodeCombineXYZ"); uv.name = "mmt_toon_uv"
            uv.location = (to_v.location.x + 160, geometry.location.y)
            uv.inputs["X"].default_value = 0.5
            tree.links.new(to_v.outputs[0], uv.inputs["Y"])
            sample = tree.nodes.new("ShaderNodeTexImage")
            sample.location = (uv.location.x + 180, geometry.location.y)
            sample.name = "mmt_toon_sample"
            sample.label = "渐变贴图（MMD toon）"
            sample.extension = "EXTEND"
            sample.image = toon.image
            tree.links.new(uv.outputs["Vector"], sample.inputs["Vector"])
            grey = tree.nodes.new("ShaderNodeRGBToBW"); grey.name = "mmt_toon_grey"
            grey.location = (sample.location.x + 180, geometry.location.y)
            tree.links.new(sample.outputs["Color"], grey.inputs["Color"])
            mask = tree.nodes.new("ShaderNodeMath")
            mask.location = (grey.location.x + 160, geometry.location.y)
            mask.name = "mmt_toon_mask"
            mask.label = "渐变 → 暗部遮罩"
            mask.operation = "MULTIPLY_ADD"   # K×(1−灰度)
            mask.use_clamp = True
            mask.inputs[1].default_value = -7.0
            mask.inputs[2].default_value = 7.0
            tree.links.new(grey.outputs["Val"], mask.inputs[0])
        else:
            sample = tree.nodes.get("mmt_toon_sample")
            if sample is not None:
                sample.image = toon.image
        for link in list(mask_socket.links):
            tree.links.remove(link)
        tree.links.new(mask.outputs[0], mask_socket)
    # MMD 的环境色就是"暗部色调"，掺进 暗部色。统一灰的环境色代表"暗部亮度"而不是颜色，
    # 拿它染暗部只会均匀压暗，所以只在三通道不等时才动。
    ambient = tuple(getattr(data, "ambient_color", ()) or ())
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
    elif len(diffuse) >= 3:
        # 连底色贴图都没有：直接把材质底色填进「底色」，别留默认白
        socket = node.inputs.get("底色")
        if socket is not None and not socket.links:
            socket.default_value = (diffuse[0], diffuse[1], diffuse[2], 1.0)

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

    贴图 alpha 也要参与判断：pmx 里 alpha=1.0 的材质（头发闪片、目光叠加等）靠贴图自己的
    alpha 抠形状，只按 pmx alpha 判断会设成 OPAQUE，脸上盖一块黑面具。有 alpha 的用 BLEND
    而不是 HASHED（抖动 + 双面会把头发糊成一团黑）。不做背面剔除：MMD 的"单面"标志按它自己的
    正面约定写，照搬到 Blender 会把正面剔掉。
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
        # 材质属性在本版本被移除，渲染照样走
        pass   # 有意忽略


def restore(mat):
    """还原成基本材质：只搭一个 Principled + 底色贴图，不给别家节点动刀。"""
    if mat is None or mat.node_tree is None:
        return False
    tree = mat.node_tree
    for node in list(tree.nodes):
        if node.bl_idname == "ShaderNodeGroup" and node.node_tree is not None \
                and node.node_tree.name == shading.SHADING_GROUP:
            tree.nodes.remove(node)
    stage = tree.nodes.get("mmt_sphere_stage")
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
#: 脸部底色贴图关键词（材质名认不出时看贴图名）
FACE_TEXTURE_HINTS = ("颜", "顔", "顏", "face", "kao", "かお")
#: 肤色关键词：弱证据（多半是身体，不是脸），别的证据都没有时才用
SKIN_HINTS = ("肌", "はだ", "皮肤", "肌色", "skin")
NOT_FACE_HINTS = ("髪", "发", "髮", "hair", "目", "眼", "eye", "瞳", "白目", "睫", "lash",
                  "眉", "brow", "口", "mouth", "齿", "歯", "teeth", "舌", "tongue",
                  "耳", "ear", "爪", "nail", "衣", "服", "裙", "裤", "鞋", "靴", "袜",
                  "帽", "饰", "飾", "アクセ", "宝石", "金属", "武器", "剑", "剣", "刀",
                  "rigid", "physics")
#: 头骨的名字（MMD 标准骨名）—— 认不出名字时按它定"头部区域"
HEAD_BONES = ("頭", "头", "head", "Head")
NECK_BONES = ("首", "neck", "Neck", "上半身2", "上半身")


def _hit(text, hints):
    low = (text or "").lower()
    return any(hint in low for hint in hints)


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
        # 该材质在本版本没有这个属性
        pass   # 有意忽略
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


#: 名字里带这三个字任意一个的材质一律不画描边 —— 眼与眉，只认这三个字：
#: 像「神之眼AL」那种带"眼"的配饰不算。
NO_EDGE_NAME_HINTS = ("瞳", "目", "眉")


def _edge_flag_map(obj):
    """每个材质槽：这个材质画不画描边。

    MMD 标了 ``edge_flag = 0`` 的不画；名字命中 :data:`NO_EDGE_NAME_HINTS` 的也不画，
    哪怕模型把它标成"画"。没有 mmd 数据的材质按"画"算。
    """
    flags = []
    for slot in obj.material_slots:
        if slot.material is None:
            flags.append(True)
            continue
        name = slot.material.name or ""
        if _hit(name, NO_EDGE_NAME_HINTS):
            flags.append(False)
            continue
        data = util.mmd(slot.material)
        flags.append(bool(getattr(data, "enabled_toon_edge", True))
                     if data is not None else True)
    return flags


def drop_disabled_edges(objects=()):
    """把 MMD 标了「不画描边」（edge_flag = 0）的材质的边壳权重清零。

    必须我们自己来：mmd_tools 建边壳时只读 ``edge_weight``（多粗）、不读 edge_flag（画不画），
    对"描边关"的材质只是把壳的面换成共享的透明材质盖住，壳照样全长出来。这里从几何上解决：
    壳厚 = 全局粗细 × 顶点组权重，清零权重就行；只清零所有相邻面都是「描边关」材质的顶点，
    跨材质的边界顶点保持原样，免得啃掉相邻材质的描边。只动 mmd_tools 那个
    ``mmd_edge_preview`` 修改器与其同名顶点组，别人挂的 SOLIDIFY 一概不碰。
    """
    dropped = 0
    for obj in (objects or list(bpy.data.objects)):
        if getattr(obj, "type", "") != "MESH" or obj.data is None:
            continue
        modifier = obj.modifiers.get("mmd_edge_preview")
        if modifier is None or modifier.type != "SOLIDIFY":
            continue
        group = obj.vertex_groups.get("mmd_edge_preview")
        if group is None or group.index < 0:
            continue
        flags = _edge_flag_map(obj)
        if all(flags):
            continue
        keep = {}
        for poly in obj.data.polygons:
            index = poly.material_index
            wanted = flags[index] if 0 <= index < len(flags) else True
            for vertex in poly.vertices:
                keep[vertex] = keep.get(vertex, False) or wanted
        victims = [vertex for vertex, wanted in keep.items() if not wanted]
        if not victims:
            continue
        group.add(victims, 0.0, "REPLACE")
        dropped += len(victims)
    if dropped:
        print("[MikuMikuToon] 描边：按 MMD 的「不画描边」标记清掉 %d 个顶点的壳"
              % dropped)
    return dropped


def _edge_objects(materials, objects=()):
    """本插件允许改描边的对象：带 ``mmd_edge_preview`` 修改器的网格。

    不能扫 ``bpy.data.objects``：scene 里别的模型、别的插件也可能挂着 SOLIDIFY，
    动它们的粗细是破坏别人的文件。
    """
    wanted = {mat.name for mat in materials if mat is not None}
    found = []
    for obj in (objects or list(bpy.data.objects)):
        if getattr(obj, "type", "") != "MESH":
            continue
        modifier = obj.modifiers.get("mmd_edge_preview")
        if modifier is None or modifier.type != "SOLIDIFY":
            continue
        if not wanted:
            found.append(obj)
            continue
        # 材质是共享数据：同一个材质可能被多个对象用到
        if any(slot.material is not None and slot.material.name in wanted
               for slot in obj.material_slots):
            found.append(obj)
    return found


def apply_edge_preview(materials, thickness=0.08, colour=None, objects=()):
    """按材质自带的描边参数（edge_color / edge_weight）设置 mmd_tools 的描边。

    mmd_tools 的描边 = 每网格一个 ``mmd_edge_preview`` SOLIDIFY 修改器（粗细全局）加每材质一个
    mmd_edge.<材质名> 描边材质（颜色各自不同）；``colour`` 给了就统一描边色，没给就用材质自己的
    MMD ``edge_color``，``objects`` 限定要动的对象。
    """
    touched = 0
    for mat in materials:
        data = util.mmd(mat)
        if data is None:
            continue
        own = tuple(float(x) for x in getattr(data, "edge_color", (0.0, 0.0, 0.0)))[:3]
        use = own if colour is None else tuple(colour)[:3]
        # 写进 MMDEdgePreview 组的「Color」插座。那个组里后面跟着一个 Gamma 2.2
        # （`out = color ** (1/2.2)`），所以统一颜色时先做一次反向补偿，
        # 让面板上选什么、渲出来就是什么；用模型自带颜色时保持 mmd_tools 的原样写法。
        write = use if colour is None else tuple(
            min(1.0, max(0.0, value)) ** 2.2 for value in use)
        for name in ("mmd_edge." + mat.name, "mmd_edge." + mat.name.split(".")[0]):
            edge = bpy.data.materials.get(name)
            if edge is None or not edge.use_nodes or edge.node_tree is None:
                continue
            edge.diffuse_color = (use[0], use[1], use[2], 1.0)
            for node in edge.node_tree.nodes:
                if node.bl_idname == "ShaderNodeGroup" and node.node_tree is not None:
                    for socket in node.inputs:
                        if socket.type == "RGBA" and not socket.links:
                            socket.default_value = (write[0], write[1], write[2], 1.0)
            touched += 1
    thickness = max(0.001, float(thickness))   # 绝对值：面板上的「描边粗细」就是它
    targets = _edge_objects(materials, objects)
    for obj in targets:
        obj.modifiers["mmd_edge_preview"].thickness = thickness
        touched += 1
    # MMD 说"不画描边"的材质不能靠透明材质盖，直接把壳去掉
    drop_disabled_edges(targets)
    print("[MikuMikuToon] 描边：套到 %d 处（%d 个对象），粗细 %.3f（MMD 原始 0.08）｜颜色 %s"
          % (touched, len(targets), thickness,
             "统一 %s" % (tuple(round(float(v), 3) for v in colour),)
             if colour is not None else "用模型自带的"))
    return touched


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
        print("[MikuMikuToon] edge_preview CLEAN 失败：%s" % error)
    for obj in list(bpy.data.objects):
        for modifier in list(getattr(obj, "modifiers", [])):
            if "edge" in (modifier.name or "").lower():
                try:
                    obj.modifiers.remove(modifier)
                    removed += 1
                except Exception as error:
                    print("[MikuMikuToon] 删描边修改器失败：%s" % error)
    for mat in list(bpy.data.materials):
        if (mat.name or "").startswith("mmd_edge"):
            try:
                bpy.data.materials.remove(mat)
                removed += 1
            except Exception as error:
                print("[MikuMikuToon] 删描边材质失败：%s" % error)
    return removed


def drop_other_nodes(mat):
    """白名单清理：只留卡渲自己的节点（mmt_*）和 Material Output，其余全删。

    比按名字猜原来的节点可靠 —— mmd_tools 每个版本命名的花样都不一样。
    """
    if not mat.use_nodes or mat.node_tree is None:
        return 0
    tree = mat.node_tree
    if tree.nodes.get("mmt_shading") is None:
        return 0                      # 没被卡渲接管过的材质不动
    removed = 0
    for node in list(tree.nodes):
        if node.name.startswith("mmt_"):
            continue
        if node.bl_idname == "ShaderNodeOutputMaterial":
            continue
        tree.nodes.remove(node)
        removed += 1
    return removed