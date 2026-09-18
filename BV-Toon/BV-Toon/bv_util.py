# -*- coding: utf-8 -*-
"""BVToon -- 基础工具层：读 MMD 材质数据、把贴图找回来、建自己的一套 UV 节点。

这一层**不碰 mmd_tools 的节点**，也不调用它的材质转换：只读 ``mmd_material``
这个挂在材质上的属性组（贴图相对路径、球面/副纹理模式、透明度、描边参数），
然后自己建节点、自己接 UV。好处是模型哪怕被别的插件转换过、贴图节点被删过，
这里照样能把作者画的球面层、渐变层找回来重建。

© 2025 BVan / DEEPSEEK
"""

import os

import bpy

#: 本插件自己建的节点名（和 mmd_tools 的 mmd_* 节点互不干扰）
BASE_TEX = "bv_base_tex"
SPHERE_TEX = "bv_sphere_tex"
TOON_TEX = "bv_toon_tex"
UV_NODE = "bv_uv"
UV_GROUP = "BVToon_MMDUV"

#: MMD 球面贴图模式
SPHERE_OFF, SPHERE_MULT, SPHERE_ADD, SPHERE_SUBTEX = 0, 1, 2, 3

#: 描边材质/预览材质不参与卡渲替换
EDGE_HINTS = ("bv_edge", "mmd_edge")


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
        pass
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
            pass
    return image


# ---------------------------------------------------------------------------
# 自己的一套 UV：底色 UV、相机空间法线（渐变/球面用）、UV1（副纹理用）
# ---------------------------------------------------------------------------

def uv_group():
    group = bpy.data.node_groups.get(UV_GROUP)
    if group is not None and len(group.nodes):
        return group
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
    return group


def uv_node(tree):
    """材质树里的 UV 组节点（按需创建）。"""
    node = tree.nodes.get(UV_NODE)
    if node is None or node.type != "GROUP" or node.node_tree is None:
        if node is not None:
            tree.nodes.remove(node)
        node = tree.nodes.new("ShaderNodeGroup")
        node.name = UV_NODE
        node.label = "BVToon MMD UV"
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

    球面/副纹理按 MMD 的模式走：加算用加、乘算用乘、副纹理用 UV1；
    渐变（toon）只做保留与备用，卡渲本身用自己的阴影分界。
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
        node = tex_node(tree, BASE_TEX, "BVToon 底色", (-1700, 120))
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
            node = tex_node(tree, SPHERE_TEX, "BVToon 球面", (-1700, -60))
            node.image = image
            want = "副纹理 UV" if mode == SPHERE_SUBTEX else "球面 UV"
            socket = uv.outputs.get(want) or uv.outputs.get("球面 UV")
            if socket is not None and not node.inputs["Vector"].is_linked:
                tree.links.new(socket, node.inputs["Vector"])
            result["sphere"] = node

    # 渐变（保留，可选叠加）
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
            node = tex_node(tree, TOON_TEX, "BVToon 渐变", (-1700, -240))
            node.image = image
            if not node.inputs["Vector"].is_linked:
                tree.links.new(uv.outputs["渐变 UV"], node.inputs["Vector"])
            result["toon"] = node
    return result


def sphere_stage(mat, base_socket, strength=1.0):
    """把球面层按 MMD 的算法混进底色：加算 = 相加、乘算 = 相乘。

    MMD 是在**反照率**上做这一步的（打光之前），所以这里接在卡渲组的底色入口。
    """
    tree = mat.node_tree
    data = mmd(mat)
    node = tree.nodes.get(SPHERE_TEX)
    mode = int(data.sphere_texture_type)
    if node is None or node.image is None or mode == SPHERE_OFF or strength <= 0:
        return base_socket

    blend = "ADD" if mode == SPHERE_ADD else "MULTIPLY"
    mix = tree.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.blend_type = blend
    mix.name = "bv_sphere_stage"
    mix.label = "球面层（%s）" % ("加算" if mode == SPHERE_ADD else "乘算")
    mix.location = (-1200, 260)
    factor = _mix_factor(mix)
    if factor is not None:
        factor.default_value = max(0.0, min(1.0, float(strength)))
    a, b = _mix_colors(mix)
    if base_socket is not None:
        tree.links.new(base_socket, a)
    else:
        a.default_value = (1.0, 1.0, 1.0, 1.0)
    tree.links.new(node.outputs["Color"], b)
    return mix.outputs[_color_output_index(mix)]


def _mix_factor(node):
    for socket in node.inputs:
        if socket.name in {"Factor", "Fac"} and socket.type == "VALUE":
            return socket
    return None


def _mix_colors(node):
    colors = [s for s in node.inputs if s.type == "RGBA"]
    return (colors[0], colors[1]) if len(colors) >= 2 else (None, None)


def _color_output_index(node):
    for index, socket in enumerate(node.outputs):
        if socket.type == "RGBA":
            return index
    return 0
