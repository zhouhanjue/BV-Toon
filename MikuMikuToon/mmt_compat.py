# -*- coding: utf-8 -*-
"""MikuMikuToon -- Blender 版本兼容底座。

4.5 / 5.0 / 5.1 / 5.2 之间真正会变的只有几件事：节点类型名、参数从"属性"搬到"插座"、
合成器树挂在哪个属性上 —— 这些差异全部收在这个文件里，别的模块不许再判版本。
兼容代码要逐级兜底，``except Exception`` 集中在本文件；其余模块出错就报出来。
命名约定：``find_*`` 找不到返回 ``None``，``set_*`` 返回成没成（bool），永远不抛。
"""

import bpy

# 版本


def version():
    """Blender 版本三元组；拿不到就 (0, 0, 0)。"""
    try:
        return tuple(int(part) for part in bpy.app.version)
    except Exception:
        return (0, 0, 0)


#: 当前 Blender 版本（导入时算一次，整个进程不变）
BLENDER_VERSION = version()


def _has_rna_property(cls, attr):
    """RNA 属性表里有没有这个属性（``hasattr`` 对 RNA 类不可靠：类上是 False、实例上是 True，
    照它判会把 5.2 的合成器树挂在哪判反）；判断能力一律问 RNA 属性表或真实实例。"""
    try:
        return cls.bl_rna.properties.get(attr) is not None
    except Exception:
        return False


def _scene_supports(attr):
    """场景上有没有这个属性（优先问真实实例，其次问 RNA 属性表）。"""
    scene = getattr(bpy.context, "scene", None)
    if scene is not None:
        try:
            return hasattr(scene, attr)
        except Exception:
            pass
    return _has_rna_property(bpy.types.Scene, attr)


def _can_make_node(bl_idname):
    """某个节点类型在本版本能不能建（建在一个临时树上然后删掉）。"""
    try:
        tree = bpy.data.node_groups.new("mmt_probe_tmp", "CompositorNodeTree")
    except Exception:
        return False
    try:
        tree.nodes.new(bl_idname)
        return True
    except Exception:
        return False
    finally:
        try:
            bpy.data.node_groups.remove(tree)
        except Exception:
            pass


#: 5.2 起合成器树挂在 ``scene.compositing_node_group``；之前是 ``scene.node_tree``
HAS_COMPOSITING_GROUP = _scene_supports("compositing_node_group")

#: 上面那个判断的字符串形式（日志与分支判断用）—— 别处不许再自己判一遍
TREE_API = "compositing_node_group" if HAS_COMPOSITING_GROUP else "use_nodes"

#: 4.5 的合成器混合节点叫 CompositorNodeMixRGB；5.x 只有 ShaderNodeMix
HAS_LEGACY_MIX = _can_make_node("CompositorNodeMixRGB")

HAS_TREE_INTERFACE = _has_rna_property(bpy.types.CompositorNodeTree, "interface")


# 属性与插座

def has(obj, name):
    """``obj`` 上有没有这个名字的属性（RNA 属性表为准，比 hasattr 准）。"""
    properties = getattr(getattr(obj, "bl_rna", None), "properties", None)
    if properties is not None:
        try:
            return properties.get(name) is not None
        except Exception:
            pass
    try:
        return hasattr(obj, name)
    except Exception:
        return False


def set_value(node, name, value):
    """把 ``value`` 设到节点的 ``name`` 上 —— 属性优先，不行再当插座。

    4.5 把 Glare 的参数从属性搬到了插座，所以两种写法都要试；返回成没成。
    """
    if has(node, name):
        try:
            setattr(node, name, value)
            return True
        except Exception:
            pass
    socket = socket_in(node, name)
    return set_socket(node, name, value) if socket is not None else False


def set_socket(node, name, value):
    """按名字给输入插座赋值，类型不匹配就不写（避免 Blender 刷 RNA 噪音）。"""
    socket = socket_in(node, name)
    if socket is None:
        return False
    if not _fits(socket, value):
        return False
    try:
        socket.default_value = value
        return True
    except Exception:
        return False


def _fits(socket, value):
    kind = getattr(socket, "type", "")
    if kind == "VALUE":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "INT":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "BOOLEAN":
        return isinstance(value, bool)
    if kind in ("RGBA", "VECTOR"):
        return isinstance(value, (tuple, list))
    return False


def socket_in(node, name, kind=None):
    """按名字找输入插座（可选类型过滤）。"""
    for socket in getattr(node, "inputs", ()):
        if socket.name == name and (kind is None or socket.type == kind):
            return socket
    return None


def socket_out(node, name=None, kind="RGBA"):
    """按名字找输出插座；``name=None`` 表示"第一个该类型的"。"""
    for socket in getattr(node, "outputs", ()):
        if (name is None or socket.name == name) and (kind is None or socket.type == kind):
            return socket
    return None


def socket_like(node, names, kind=None, from_inputs=True):
    """先按名字列表找，找不到再退回"第一个该类型的插座"（节点改名/换类型时不断链）。"""
    group = getattr(node, "inputs" if from_inputs else "outputs", ())
    for name in names:
        for socket in group:
            if socket.name == name and (kind is None or socket.type == kind):
                return socket
    for socket in group:
        if kind is None or socket.type == kind:
            return socket
    return None


def color_sockets(node, outputs=False, count=2):
    """节点上前 ``count`` 个 RGBA 插座（Mix 类节点的 A/B 用）。"""
    group = getattr(node, "outputs" if outputs else "inputs", ())
    return [socket for socket in group if socket.type == "RGBA"][:count]


def factor_socket(node):
    """混合节点的系数插座（4.5 叫 Fac，5.x 叫 Factor）。"""
    for socket in getattr(node, "inputs", ()):
        if socket.name in ("Fac", "Factor") and socket.type == "VALUE":
            return socket
    return None


# 建节点

def new_node(nodes, *names):
    """按候选类型名依次试建节点；全都不存在就抛（这是真的没法继续）。"""
    for name in names:
        try:
            return nodes.new(name)
        except Exception:
            continue
    raise RuntimeError("这些节点类型在本版本都不存在：%s" % ", ".join(names))


def mix_node(tree, blend_type, factor=1.0):
    """图像混合节点：4.5 用 ``CompositorNodeMixRGB``，5.x 用 ``ShaderNodeMix``。

    返回 ``(节点, A 插座, B 插座, 输出插座)``。
    """
    if HAS_LEGACY_MIX:
        node = tree.nodes.new("CompositorNodeMixRGB")
        node.blend_type = blend_type
        try:
            node.inputs[0].default_value = factor
        except Exception:
            pass
        return node, node.inputs[1], node.inputs[2], node.outputs[0]
    node = tree.nodes.new("ShaderNodeMix")
    node.data_type = "RGBA"
    node.blend_type = blend_type
    fac = factor_socket(node)
    if fac is not None:
        try:
            fac.default_value = factor
        except Exception:
            pass
    colors = color_sockets(node)
    return node, colors[0], colors[1], socket_out(node)


# 合成器树（4.5/5.1 用 use_nodes，5.2 起用 compositing_node_group）

#: 场景上标记"这棵树是本插件建的"，摘泛光时好还原
TREE_FLAG = "mikumikutoon_compositor_tree"

#: 场景上标记"合成器设备是本插件改过的"
DEVICE_FLAG = "mikumikutoon_compositor_device"

STRUCTURAL_TYPES = {
    "CompositorNodeRLayers", "CompositorNodeComposite", "NodeGroupOutput",
    "NodeGroupInput", "NodeReroute", "CompositorNodeViewer",
    "CompositorNodeOutputFile",
}


def scene_tree(scene, create=True):
    """取（并按需建）场景的合成器树，返回 ``(树, 用的是哪个 API)``。

    ``create=False`` 时只找不建（探测用，绝不能有副作用）。
    """
    if HAS_COMPOSITING_GROUP:
        tree = scene.compositing_node_group
        if tree is None and create:
            tree = bpy.data.node_groups.new("Compositor", "CompositorNodeTree")
            scene[TREE_FLAG] = 1
            scene.compositing_node_group = tree
        return tree, "compositing_node_group"
    if not scene.use_nodes:
        if not create:
            return None, "use_nodes"
        scene[TREE_FLAG] = 1
    scene.use_nodes = True
    return scene.node_tree, "use_nodes"


def existing_tree(scene):
    """只在场景已经有合成器树时返回它（不建、不写场景）。"""
    if HAS_COMPOSITING_GROUP:
        return scene.compositing_node_group
    if scene.use_nodes and scene.node_tree is not None:
        return scene.node_tree
    return None


def forget_key(owner, key):
    """删掉自定义属性；本来不在就当成功（``del`` 对不存在的键抛 ``KeyError``）。"""
    try:
        del owner[key]
        return True
    except Exception:
        return False


def drop_tree(scene, tree):
    """把场景上的合成器树摘掉（只在本插件自己建的树上调用），顺手清掉标记位。"""
    if HAS_COMPOSITING_GROUP:
        scene.compositing_node_group = None
        if tree is not None and getattr(tree, "users", 0) == 0:
            bpy.data.node_groups.remove(tree)
    else:
        scene.use_nodes = False
    forget_key(scene, TREE_FLAG)
    return True


def tree_socket(tree, name, in_out, kind="NodeSocketColor"):
    """合成器组树的接口插座。

    ``tree.interface``（4.3+）与旧的 ``tree.inputs``/``tree.outputs`` 互斥：5.2 上
    ``tree.inputs`` 根本不存在，必须走到哪条分支才碰哪个属性。
    """
    if HAS_TREE_INTERFACE:
        return tree.interface.new_socket(name, in_out=in_out, socket_type=kind)
    collection = tree.inputs if in_out == "INPUT" else tree.outputs
    return collection.new(kind, name)


def find_sink(tree, create=True):
    """合成器的输出节点（结果往哪儿送）。

    5.2 起树是节点组，输出是 ``NodeGroupOutput``（接口上要有 OUTPUT 插座）；之前是
    ``CompositorNodeComposite``。没有就按需补。
    """
    if HAS_COMPOSITING_GROUP:
        node = next((item for item in tree.nodes
                     if item.bl_idname == "NodeGroupOutput"), None)
        if node is None and create:
            outputs = [item for item in tree.interface.items_tree
                       if item.in_out == "OUTPUT"]
            if not outputs:
                tree.interface.new_socket("Image", in_out="OUTPUT",
                                          socket_type="NodeSocketColor")
            node = tree.nodes.new("NodeGroupOutput")
            node.location = (400, 0)
        return node
    node = next((item for item in tree.nodes
                 if item.bl_idname == "CompositorNodeComposite"), None)
    if node is None and create:
        node = tree.nodes.new("CompositorNodeComposite")
        node.location = (400, 0)
    return node


def find_layers(tree, create=True):
    """渲染层节点（画面的源头）。按需补。"""
    node = next((item for item in tree.nodes
                 if item.bl_idname == "CompositorNodeRLayers"), None)
    if node is None and create:
        node = tree.nodes.new("CompositorNodeRLayers")
        node.location = (-200, 0)
    return node


def find_source(tree, sink=None, create=True):
    """喂给输出的那个上游插槽，外加渲染层节点。返回 ``(上游插座, 渲染层节点)``。

    必须穿透 Reroute：RLayers 后面常挂一个 Reroute，直接拿它的输出当源会连不上。
    总是返回上游的输出插座，否则第二次接会报 "Same input/output direction of sockets"。
    """
    sink = sink if sink is not None else find_sink(tree, create)
    target = sink_input(sink) if sink is not None else None
    if target is not None and target.is_linked:
        upstream = resolve_reroutes(target.links[0].from_socket)
        layers = (upstream.node if getattr(upstream, "node", None) is not None
                  and upstream.node.bl_idname == "CompositorNodeRLayers"
                  else find_layers(tree, create))
        return upstream, layers
    layers = next((item for item in tree.nodes
                   if item.bl_idname == "CompositorNodeRLayers"
                   and not any(out.is_linked for out in item.outputs)), None)
    if layers is None:
        layers = find_layers(tree, create)
    if layers is None:
        return None, None
    return socket_out(layers, "Image", "RGBA"), layers


def resolve_reroutes(socket):
    """穿透 Reroute，返回最上游那个输出插座。"""
    seen = 0
    while socket is not None and socket.is_linked and seen < 32:
        link = socket.links[0]
        upstream_node, upstream_socket = link.from_node, link.from_socket
        socket = upstream_socket
        if upstream_node.bl_idname != "NodeReroute":
            break
        seen += 1
    return socket


def sink_input(sink):
    """合成器输出节点上那个收画面的插座（4.5/5.x 名字不一样）。"""
    return socket_like(sink, ("Image", "图像", "Surface"), "RGBA")


def wire_source_to_sink(tree):
    """把渲染层直接接回合成器输出（重复调用安全）。返回 ``(上游插座, sink)``。"""
    sink = find_sink(tree)
    if sink is None:
        return None, None
    target = sink_input(sink)
    if target is None:
        return None, sink
    source, _layers = find_source(tree, sink)
    if source is None:
        return None, sink
    if any(link.from_socket == source for link in target.links):
        return source, sink
    for link in list(target.links):
        tree.links.remove(link)
    tree.links.new(source, target)
    return source, sink


def remove_node_tree(name):
    """按名字删掉节点组（不存在就当已经删了）。"""
    group = bpy.data.node_groups.get(name)
    if group is not None:
        bpy.data.node_groups.remove(group)
        return True
    return False
