# -*- coding: utf-8 -*-
"""MikuMikuToon -- 基础工具层：读 MMD 材质数据、把贴图找回来、建自己的一套 UV 节点。

不碰 mmd_tools 的节点，也不调用它的材质转换：只读材质上的 ``mmd_material`` 属性组
（贴图相对路径、球面/副纹理模式、透明度、描边参数），节点和 UV 都自己建。

© 2025 BVan / DEEPSEEK
"""

import os

import bpy

from . import mmt_compat

#: 本插件自己建的节点名（和 mmd_tools 的 mmd_* 节点互不干扰）
BASE_TEX = "mmt_base_tex"
SPHERE_TEX = "mmt_sphere_tex"
TOON_TEX = "mmt_toon_tex"
#: 「底色贴图 × 材质底色」那一步的节点名（MMD 最终颜色是两者相乘）
BASE_TINT = "mmt_base_tint"
#: 「加算球面强度」>1 时的乘算节点（默认不建）
SPHERE_GAIN = "mmt_sphere_gain"
SPHERE_LEVEL = "mmt_sphere_level"
UV_NODE = "mmt_uv"
UV_GROUP = "MikuMikuToon_MMDUV"

#: MMD 球面贴图模式
SPHERE_OFF, SPHERE_MULT, SPHERE_ADD, SPHERE_SUBTEX = 0, 1, 2, 3

#: 描边材质/预览材质不参与卡渲替换
EDGE_HINTS = ("mmt_edge", "mmd_edge")


# 物件 / 材质筛选（面板与操作符共用）

def target_objects(context):
    """当前该处理哪些网格：整体替换模式下取选中的，单材质模式取激活物体。"""
    mode = getattr(context.scene, "mmt_mode", "REPLACE_MODEL")
    if mode == "REPLACE_MODEL":
        return [obj for obj in context.selected_objects
                if obj.type == "MESH" and obj.data is not None]
    obj = context.object
    if obj is not None and obj.type == "MESH" and obj.data is not None:
        return [obj]
    return []


def target_materials(context):
    """上面那些物件上的 MMD 材质（去重，跳过描边材质）。"""
    materials, seen = [], set()
    for obj in target_objects(context):
        for slot in obj.material_slots:
            mat = slot.material
            if mat is None or mat in seen or mat.node_tree is None:
                continue
            seen.add(mat)
            if is_mmd(mat):
                materials.append(mat)
    return materials


def edge_colour(scene):
    """面板上的「统一描边颜色」：勾了给颜色，没勾给 None（= 用模型自带的 edge_color）。"""
    if not getattr(scene, "mmt_edge_use_color", False):
        return None
    value = scene.mmt_edge_color
    try:
        colour = tuple(float(v) for v in value)[:3]
    except Exception:
        return None
    return colour if len(colour) == 3 else None


def mmd(mat):
    """材质的 MMD 数据组，没有就返回 None（说明不是 MMD 材质）。"""
    return getattr(mat, "mmd_material", None)


def is_mmd(mat):
    if mat is None or mmd(mat) is None:
        return False
    name = mat.name or ""
    return not any(hint in name for hint in EDGE_HINTS)


def norm(path):
    return (path or "").replace("\\", "/")


def base_image(mat):
    """材质当前的底色贴图：先看我建的节点，再退回任意一张贴图。"""
    tree = mat.node_tree if mat.use_nodes else None
    if tree is None:
        return None
    node = tree.nodes.get(BASE_TEX)
    if node is not None and node.type == "TEX_IMAGE" and node.image is not None:
        return node.image
    for candidate in tree.nodes:
        if candidate.type == "TEX_IMAGE" and candidate.image is not None:
            return candidate.image
    return None


def model_root(mat):
    """模型目录：用 pmx 里的相对路径 + 幸存的底色贴图反推。"""
    data = mmd(mat)
    if data is None:
        return None
    rel = norm(getattr(data, "texture_rel_path", ""))
    image = base_image(mat)
    if image is not None and image.filepath:
        absolute = norm(os.path.normpath(bpy.path.abspath(image.filepath)))
        if rel and absolute.endswith(rel):
            return absolute[: len(absolute) - len(rel)].rstrip("/")
        return os.path.dirname(absolute)
    return None


def resolve(mat, rel):
    """把 pmx 里的相对路径解析成真实文件路径。"""
    rel = norm(rel)
    if not rel:
        return None
    if os.path.isabs(rel) and os.path.isfile(rel):
        return rel
    root = model_root(mat)
    candidates = []
    if root:
        candidates.append(os.path.join(root, *rel.split("/")))
        candidates.append(os.path.join(root, os.path.basename(rel)))
    image = base_image(mat)
    if image is not None and image.filepath:
        candidates.append(os.path.join(
            os.path.dirname(bpy.path.abspath(image.filepath)),
            os.path.basename(rel)))
    for path in candidates:
        if path and os.path.isfile(path):
            return os.path.normpath(path)
    return None


def shared_toon(mat):
    """MMD 内置的共享渐变（toon01..toon10）。"""
    data = mmd(mat)
    if data is None or not data.is_shared_toon_texture:
        return None
    index = int(data.shared_toon_texture)
    if not 0 <= index <= 9:
        return None
    name = "toon%02d.bmp" % (index + 1)
    folders = []
    for key in ("bl_ext.blender_org.mmd_tools", "mmd_tools"):
        entry = bpy.context.preferences.addons.get(key)
        if entry is not None:
            folder = getattr(entry.preferences, "shared_toon_folder", "")
            if folder:
                folders.append(folder)
    try:
        import addon_utils
        for module in addon_utils.modules():
            if module.__name__.endswith("mmd_tools") and module.__file__:
                folders.append(os.path.join(os.path.dirname(module.__file__),
                                            "externals", "MikuMikuDance"))
    except Exception:
        pass   # 有意忽略
    for folder in folders:
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            return path
    return None


def toon_path(mat):
    data = mmd(mat)
    if data is None:
        return None
    if data.is_shared_toon_texture:
        return shared_toon(mat)
    if data.toon_texture:
        path = os.path.normpath(bpy.path.abspath(data.toon_texture))
        if os.path.isfile(path):
            return path
    rel = getattr(data, "toon_texture_rel_path", "")
    return resolve(mat, rel) if rel else None


def sphere_path(mat):
    data = mmd(mat)
    if data is None or int(data.sphere_texture_type) == SPHERE_OFF:
        return None
    rel = getattr(data, "sphere_texture_rel_path", "")
    if rel:
        found = resolve(mat, rel)
        if found:
            return found
    root = model_root(mat)
    name = os.path.basename(norm(rel)) if rel else ""
    if root and name:
        for sub in ("", "sph", "spa", "sphere", "Sphere", "textures", "tex"):
            path = os.path.join(root, sub, name)
            if os.path.isfile(path):
                return os.path.normpath(path)
    return None


def load_image(path, add_mode):
    """载入贴图，并按 mmd_tools 的规矩给色彩空间（加算球面用线性）。"""
    if not path or not os.path.isfile(path):
        return None
    target = os.path.normpath(path)
    for existing in bpy.data.images:
        if existing.filepath and os.path.normpath(
                bpy.path.abspath(existing.filepath)) == target:
            return existing
    try:
        image = bpy.data.images.load(path, check_existing=True)
    except Exception:
        return None
    try:
        image.colorspace_settings.name = ("Linear Rec.709" if add_mode
                                          else "sRGB")
    except Exception:
        try:
            image.colorspace_settings.name = "Non-Color" if add_mode else "sRGB"
        except Exception:
            pass   # 有意忽略
    return image


# 自己的一套 UV（底色 / 相机空间法线 / 副纹理）

#: UV 组版本。改了下面这套算法就 +1，旧场景里那份会被重建。
UV_VERSION = 2


def uv_group():
    group = bpy.data.node_groups.get(UV_GROUP)
    if group is not None and len(group.nodes):
        if group.get("mmt_uv_version") == UV_VERSION:
            return group
        # 旧版：整组重建（组节点指向同一个 NodeTree，会自动跟着更新）
        for node in list(group.nodes):
            group.nodes.remove(node)
        print("[MikuMikuToon] 重建 UV 组（旧版球面 UV 算法是错的）")
    if group is None:
        group = bpy.data.node_groups.new(UV_GROUP, "ShaderNodeTree")
    for name in ("底色 UV", "渐变 UV", "球面 UV", "副纹理 UV"):
        group.interface.new_socket(name, in_out="OUTPUT",
                                   socket_type="NodeSocketVector")
    out = group.nodes.new("NodeGroupOutput")
    out.location = (600, 0)
    coords = group.nodes.new("ShaderNodeTexCoord")
    coords.location = (-200, 0)
    xform = group.nodes.new("ShaderNodeVectorTransform")
    xform.location = (60, -180)
    xform.vector_type = "NORMAL"
    xform.convert_from = "OBJECT"
    xform.convert_to = "CAMERA"
    mapping = group.nodes.new("ShaderNodeMapping")
    mapping.location = (300, -180)
    mapping.vector_type = "POINT"
    mapping.inputs["Location"].default_value = (0.5, 0.5, 0.0)
    mapping.inputs["Scale"].default_value = (0.5, 0.5, 1.0)
    subtex = group.nodes.new("ShaderNodeUVMap")
    subtex.location = (300, -380)
    subtex.uv_map = "UV1"
    links = group.links
    links.new(coords.outputs["Normal"], xform.inputs["Vector"])
    links.new(xform.outputs["Vector"], mapping.inputs["Vector"])
    links.new(coords.outputs["UV"], out.inputs["底色 UV"])
    links.new(mapping.outputs["Vector"], out.inputs["渐变 UV"])
    links.new(mapping.outputs["Vector"], out.inputs["球面 UV"])
    links.new(subtex.outputs["UV"], out.inputs["副纹理 UV"])
    # 记下算法版本，供下次判断是否重建
    group["mmt_uv_version"] = UV_VERSION
    return group


def uv_node(tree):
    """材质树里的 UV 组节点（按需创建）。"""
    node = tree.nodes.get(UV_NODE)
    if node is None or node.type != "GROUP" or node.node_tree is None:
        if node is not None:
            tree.nodes.remove(node)
        node = tree.nodes.new("ShaderNodeGroup")
        node.name = UV_NODE
        node.label = "MikuMikuToon MMD UV"
        node.node_tree = uv_group()
        node.location = (-1700, -300)
    return node


def tex_node(tree, name, label, location):
    node = tree.nodes.get(name)
    if node is None or node.type != "TEX_IMAGE":
        if node is not None:
            tree.nodes.remove(node)
        node = tree.nodes.new("ShaderNodeTexImage")
    node.name = name
    node.label = label
    node.location = location
    node.extension = "REPEAT"
    return node


def texture_nodes(mat, report=None):
    """建/修好这个材质的贴图节点，返回 (底色, 球面, 渐变) 三个节点。

    球面/副纹理按 MMD 的模式走：加算用加、乘算用乘、副纹理用 UV1；渐变只保留备用。
    """
    tree = mat.node_tree
    uv = uv_node(tree)
    data = mmd(mat)
    result = {"base": None, "sphere": None, "toon": None}

    # 底色
    path = resolve(mat, getattr(data, "texture_rel_path", ""))
    node = tree.nodes.get(BASE_TEX)
    image = node.image if (node is not None and node.type == "TEX_IMAGE") else None
    if image is None and path:
        image = load_image(path, add_mode=False)
        if image is None and report is not None:
            report.append("%s: 底色贴图读不到 %s" % (mat.name, path))
    if image is not None:
        node = tex_node(tree, BASE_TEX, "MikuMikuToon 底色", (-1700, 120))
        node.image = image
        if not node.inputs["Vector"].is_linked:
            tree.links.new(uv.outputs["底色 UV"], node.inputs["Vector"])
        result["base"] = node

    # 球面 / 副纹理
    mode = int(data.sphere_texture_type)
    sphere = tree.nodes.get(SPHERE_TEX)
    if mode == SPHERE_OFF:
        if sphere is not None:
            tree.nodes.remove(sphere)
    else:
        path = sphere_path(mat)
        image = sphere.image if (sphere is not None
                                and sphere.type == "TEX_IMAGE") else None
        if image is None and path:
            image = load_image(path, add_mode=mode == SPHERE_ADD)
            if image is None and report is not None:
                report.append("%s: 球面贴图读不到 %s" % (mat.name, path))
        if image is None:
            if report is not None:
                report.append("%s: 找不到球面贴图（模式 %d）" % (mat.name, mode))
        else:
            node = tex_node(tree, SPHERE_TEX, "MikuMikuToon 球面", (-1700, -60))
            node.image = image
            want = "副纹理 UV" if mode == SPHERE_SUBTEX else "球面 UV"
            socket = uv.outputs.get(want) or uv.outputs.get("球面 UV")
            if socket is not None and not node.inputs["Vector"].is_linked:
                tree.links.new(socket, node.inputs["Vector"])
            result["sphere"] = node

    # 渐变（保留）
    path = toon_path(mat)
    toon = tree.nodes.get(TOON_TEX)
    if path is None:
        if toon is not None and toon.image is None:
            tree.nodes.remove(toon)
    else:
        image = toon.image if (toon is not None
                              and toon.type == "TEX_IMAGE") else None
        if image is None or not image.has_data:
            image = load_image(path, add_mode=False)
        if image is not None:
            node = tex_node(tree, TOON_TEX, "MikuMikuToon 渐变", (-1700, -240))
            node.image = image
            if not node.inputs["Vector"].is_linked:
                tree.links.new(uv.outputs["渐变 UV"], node.inputs["Vector"])
            result["toon"] = node
    return result


#: 球面层相关节点的名字前缀（去掉旧的、查找真正生效的都靠它）
SPHERE_STAGE = "mmt_sphere_stage"


def clear_sphere_stage(tree):
    """删掉材质树里所有的球面层节点（含 Blender 加过 .001 后缀的）。返回删了几个。"""
    stale = [node for node in tree.nodes if node.name.startswith(SPHERE_STAGE)]
    for node in stale:
        tree.nodes.remove(node)
    return len(stale)


def live_sphere_stage(mat):
    """找真正生效的那个球面层节点：它必须接着卡渲组。

    ``nodes.get("mmt_sphere_stage")`` 只按名字取第一个，可能是上次遗留、已不接输出的
    废弃节点，改它等于没改。
    """
    tree = mat.node_tree if mat is not None else None
    if tree is None:
        return None
    marker = mat.node_tree.nodes.get("mmt_shading")
    if marker is None:
        marker = next((node for node in tree.nodes
                       if node.bl_idname == "ShaderNodeGroup"
                       and node.node_tree is not None
                       and "Shading" in node.node_tree.name), None)
    for node in tree.nodes:
        if not node.name.startswith(SPHERE_STAGE):
            continue
        for socket in node.outputs:
            if any(link.to_node == marker for link in socket.links):
                return node
    return None


def sphere_stage(mat, base_socket, strength=1.0):
    """把球面层按 MMD 的算法混进底色：加算 = 相加、乘算 = 相乘。

    MMD 是在反照率上做这一步的（打光之前），所以接在卡渲组的底色入口；``strength``
    是手动余量（默认 1.0 = 与 MMD 同强度）。
    """
    tree = mat.node_tree
    data = mmd(mat)
    node = tree.nodes.get(SPHERE_TEX)
    mode = int(data.sphere_texture_type)
    if node is None or node.image is None or mode == SPHERE_OFF or strength <= 0:
        return base_socket

    # 先清掉上次留下的球面层节点：撞名时 Blender 会加 .001 后缀，而 nodes.get()
    # 永远返回第一个（可能已不接输出），改它等于没改。
    clear_sphere_stage(tree)

    blend = "ADD" if mode == SPHERE_ADD else "MULTIPLY"
    mix = tree.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.blend_type = blend
    mix.name = "mmt_sphere_stage"
    mix.label = "球面层（%s）" % ("加算" if mode == SPHERE_ADD else "乘算")
    mix.location = (-1200, 260)
    factor = mmt_compat.factor_socket(mix)
    if factor is not None:
        factor.default_value = max(0.0, min(1.0, float(strength)))
    a, b = mmt_compat.color_sockets(mix)
    if base_socket is not None:
        tree.links.new(base_socket, a)
    else:
        a.default_value = (1.0, 1.0, 1.0, 1.0)
    # Factor 只有 0..1，>1 的加强要另外乘一次（见 set_sphere_strength）
    if strength > 1.0:
        gain = tree.nodes.new("ShaderNodeMix")
        gain.data_type = "RGBA"
        gain.blend_type = "MULTIPLY"
        gain.name = SPHERE_GAIN
        gain.label = "球面强度 ×%.2f" % float(strength)
        gain.location = (-1350, 200)
        gain_factor = mmt_compat.factor_socket(gain)
        if gain_factor is not None:
            gain_factor.default_value = 1.0
        gain_a, gain_b = mmt_compat.color_sockets(gain)
        tree.links.new(node.outputs["Color"], gain_a)
        level = tree.nodes.new("ShaderNodeCombineXYZ")
        level.name = SPHERE_LEVEL
        level.location = (-1450, 140)
        for channel in ("X", "Y", "Z"):
            level.inputs[channel].default_value = float(strength)
        tree.links.new(level.outputs["Vector"], gain_b)
        tree.links.new(mmt_compat.socket_out(gain), b)
    else:
        tree.links.new(node.outputs["Color"], b)
    return mmt_compat.socket_out(mix)


def set_sphere_strength(mat, strength):
    """改「加算球面」的强度（不用重跑一键卡渲）。返回 True 表示动过。

    1.0 = 与 MMD 同强度；>1 = 球面层再乘一个系数。只动球面层那两个节点。
    """
    if not is_mmd(mat) or mat.node_tree is None:
        return False
    tree = mat.node_tree
    # 必须找接着卡渲组的那一个，不能按名字取第一个
    mix = live_sphere_stage(mat)
    node = tree.nodes.get(SPHERE_TEX)
    if mix is None or node is None or node.image is None:
        return False
    value = max(0.0, float(strength))
    factor = mmt_compat.factor_socket(mix)
    if factor is not None:
        factor.default_value = max(0.0, min(1.0, value))
    gain = tree.nodes.get(SPHERE_GAIN)
    level = tree.nodes.get(SPHERE_LEVEL)
    if value > 1.0:
        # 需要加强：没有乘算节点就现建一对
        if gain is None or gain.type != "MIX":
            gain = tree.nodes.new("ShaderNodeMix")
            gain.data_type = "RGBA"
            gain.blend_type = "MULTIPLY"
            gain.name = SPHERE_GAIN
            gain.location = (-1350, 200)
            gain_factor = mmt_compat.factor_socket(gain)
            if gain_factor is not None:
                gain_factor.default_value = 1.0
        if level is None or level.type != "COMBINE_XYZ":
            level = tree.nodes.new("ShaderNodeCombineXYZ")
            level.name = SPHERE_LEVEL
            level.location = (-1450, 140)
            tree.links.new(level.outputs["Vector"], mmt_compat.color_sockets(gain)[1])
        gain_a, gain_b = mmt_compat.color_sockets(gain)
        a, b = mmt_compat.color_sockets(mix)
        for link in list(b.links):
            tree.links.remove(link)
        tree.links.new(node.outputs["Color"], gain_a)
        tree.links.new(mmt_compat.socket_out(gain), b)
        for channel in ("X", "Y", "Z"):
            level.inputs[channel].default_value = value
        gain.label = "球面强度 ×%.2f" % value
    else:
        a, b = mmt_compat.color_sockets(mix)
        if gain is not None:
            for link in list(mmt_compat.socket_out(gain).links):
                tree.links.remove(link)
            tree.nodes.remove(gain)
        if level is not None:
            tree.nodes.remove(level)
        for link in list(b.links):
            tree.links.remove(link)
        tree.links.new(node.outputs["Color"], b)
    return True


def tint_from_diffuse(colour):
    """MMD 的材质底色该不该当作"染色"？返回要乘进去的颜色（``None`` = 不乘）。

    MMD 里纯灰的底色不是颜色，是"受光程度"（默认 0.8 灰代表全亮）：有色偏（差 > 0.05）
    就当染色原样用；纯灰且亮度 ≥ 0.6 返回 None；纯灰但亮度 < 0.6 是故意做暗件，保留。
    """
    colour = tuple(float(value) for value in (colour or ()))[:3]
    if len(colour) < 3:
        return None
    if all(abs(value - 1.0) <= 0.002 for value in colour):
        return None                                  # 本来就是白
    high, low = max(colour), min(colour)
    if (high - low) <= 0.05 and (high + low) * 0.5 >= 0.6:
        return None                                  # MMD 的默认灰 = 受光程度，不是颜色
    return colour


def base_tint(mat, base_socket, colour):
    """把 MMD 的材质底色（diffuse）算进卡渲的「底色」入口。

    MMD 的最终颜色是 ``底色贴图 × 材质底色``，没有底色贴图时就是材质底色本身；只乘
    贴图的话，纯色材质会变白、有贴图的会偏亮。算不算染色交给 :func:`tint_from_diffuse`
    判断；``base_socket`` 为 None 时返回 None，由调用方把材质底色填进插座。
    """
    colour = tint_from_diffuse(colour)
    if not colour:
        return base_socket
    if base_socket is None:
        return None
    tree = mat.node_tree
    mix = tree.nodes.get(BASE_TINT)
    if mix is None:
        mix = tree.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.blend_type = "MULTIPLY"
        mix.name = BASE_TINT
        mix.label = "底色 × 材质底色"
        mix.location = (-1500, 120)
    factor = mmt_compat.factor_socket(mix)
    if factor is not None:
        factor.default_value = 1.0
    first, second = mmt_compat.color_sockets(mix)
    if first is None or second is None:
        return base_socket
    for link in list(first.links):
        tree.links.remove(link)
    tree.links.new(base_socket, first)
    second.default_value = (colour[0], colour[1], colour[2], 1.0)
    return mmt_compat.socket_out(mix)

