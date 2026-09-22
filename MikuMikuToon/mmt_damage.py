# -*- coding: utf-8 -*-
"""MikuMikuToon -- 校验不通过时损毁画面（合成器）。

只在副本被改过或没有清单时生效：像素化 → 压色阶 → 去饱和压暗。

没有档位可选：被改和未验证都损毁，只有"损毁 / 不损毁"两种结果。
拦不住愿意改代码的人，拦的是"拿改过的副本出图冒充原版"。

© 2025 BVan / DEEPSEEK
"""

import bpy

from . import mmt_compat
from . import mmt_integrity

#: 节点组与场景里那个组节点的名字（组节点用 mmt_ 前缀，跟材质树白名单一个规矩）
DAMAGE_GROUP = "MikuMikuToon_Integrity_Damage"
DAMAGE_NODE = "mmt_integrity_damage"

SOCKET_IMAGE = "图像"
SOCKET_FACTOR = "损毁"

#: 唯一档位：被改或未验证都损毁，没有用户可选档位。
#: 常量留着是因为 ``tools/audit_mmt_toon.py`` 会检查它等于 ``"ALL"``。
MODE = "ALL"

#: 损毁参数：块越大、色阶越少、越暗，越明显
PIXEL_SIZE = 64
STEPS = 3
SATURATION = 0.12
VALUE = 0.45

#: 校验不通过的两个状态都损毁
BAD_STATES = (mmt_integrity.STATE_MODIFIED, mmt_integrity.STATE_UNVERIFIED)


def should_damage(report):
    """这份完整性报告该不该损毁画面。"""
    return (report or {}).get("state") in BAD_STATES


def factor_for(state):
    """损毁强度：被改和未验证都算 1，正常算 0（唯一档位）。

    公开 API —— ``tools/audit_mmt_toon.py`` 与 ``tools/package_mmt_toon.py``
    用它做"损毁强度表"的检查，名字与语义都不能改。
    """
    return 1.0 if state in BAD_STATES else 0.0


# ---------------------------------------------------------------------------
# 节点组
# ---------------------------------------------------------------------------

def _knob(node, candidates, value, label):
    """按候选名设参数；一个都设不上就报出来（静默失败最难查）。"""
    for name in candidates:
        if mmt_compat.set_value(node, name, value):
            return True
    print("[MikuMikuToon] 损毁节点 %s 的「%s」没设上（试过 %s），这一层可能不起作用"
          % (node.bl_idname, label, "/".join(candidates)))
    return False


def damage_group():
    """损毁节点组：损毁=0 原样通过，损毁=1 把图弄坏。已在就复用。"""
    group = bpy.data.node_groups.get(DAMAGE_GROUP)
    if group is not None:
        return group

    group = bpy.data.node_groups.new(DAMAGE_GROUP, "CompositorNodeTree")
    mmt_compat.tree_socket(group, SOCKET_IMAGE, "INPUT", "NodeSocketColor")
    mmt_compat.tree_socket(group, SOCKET_FACTOR, "INPUT", "NodeSocketFloat")
    mmt_compat.tree_socket(group, SOCKET_IMAGE, "OUTPUT", "NodeSocketColor")

    source = group.nodes.new("NodeGroupInput")
    source.location = (-400, 0)
    sink = group.nodes.new("NodeGroupOutput")
    sink.location = (400, 0)

    # 三连击：马赛克 → 压色阶 → 去饱和压暗
    pixelate = mmt_compat.new_node(group.nodes, "CompositorNodePixelate")
    pixelate.name = "mmt_damage_pixelate"
    pixelate.location = (-180, 120)
    _knob(pixelate, ("pixel_size", "Size", "size", "大小"), PIXEL_SIZE, "马赛克块大小")

    posterize = mmt_compat.new_node(group.nodes, "CompositorNodePosterize")
    posterize.name = "mmt_damage_posterize"
    posterize.location = (0, 120)
    _knob(posterize, ("levels", "Steps", "色阶", "级数"), STEPS, "色阶数")

    hue = mmt_compat.new_node(group.nodes, "CompositorNodeHueSat")
    hue.name = "mmt_damage_hue"
    hue.location = (180, 120)
    _knob(hue, ("color_saturation", "Saturation", "饱和度"), SATURATION, "饱和度")
    _knob(hue, ("color_value", "Value", "明度"), VALUE, "明度")

    mix, slot_a, slot_b, mix_out = mmt_compat.mix_node(group, "MIX", 0.0)
    mix.name = "mmt_damage_mix"
    mix.location = (0, -120)

    image_in = source.outputs[SOCKET_IMAGE]
    factor_in = source.outputs[SOCKET_FACTOR]
    image_out = sink.inputs[SOCKET_IMAGE]

    # 原图 → mix.A（系数 0 时走这条），原图 → 损毁链 → mix.B（系数 1 时走这条）
    group.links.new(image_in, slot_a)
    group.links.new(image_in, mmt_compat.socket_like(
        pixelate, ("Color", "Image", "图像"), "RGBA"))
    group.links.new(
        mmt_compat.socket_like(pixelate, ("Color", "Image", "图像"), "RGBA", False),
        mmt_compat.socket_like(posterize, ("Image", "图像"), "RGBA"))
    group.links.new(
        mmt_compat.socket_like(posterize, ("Image", "图像"), "RGBA", False),
        mmt_compat.socket_like(hue, ("Image", "图像"), "RGBA"))
    group.links.new(
        mmt_compat.socket_like(hue, ("Image", "图像"), "RGBA", False), slot_b)
    group.links.new(mix_out, image_out)

    factor = mmt_compat.factor_socket(mix)
    if factor is None:
        print("[MikuMikuToon] 损毁节点组：混合节点没有系数插座，损毁会一直生效"
              "（好在只在校验不过时才接进来）")
    else:
        group.links.new(factor_in, factor)
    return group


# ---------------------------------------------------------------------------
# 场景里那个组节点
# ---------------------------------------------------------------------------

def find_node(scene):
    """场景里的损毁组节点（没有就 None）。只找，不建。"""
    tree = mmt_compat.existing_tree(scene)
    if tree is None:
        return None
    return next((node for node in tree.nodes if node.name == DAMAGE_NODE), None)


def set_factor(scene, factor):
    """把已有的损毁节点设成 factor（不动合成器结构）。返回设到了没有。"""
    node = find_node(scene)
    if node is None:
        return factor <= 0.0          # 没节点又不需要损毁 = 已经是想要的状态
    socket = mmt_compat.socket_like(node, (SOCKET_FACTOR, "Factor", "Fac"), "VALUE")
    if socket is None:
        print("[MikuMikuToon] 损毁组节点上没有「%s」输入，没法调整" % SOCKET_FACTOR)
        return False
    # 只有数值插座能写数值：往别的类型写，Blender 会刷
    # "RNA_float_set: NodeSocket.default_value not found."
    if getattr(socket, "type", "") not in ("VALUE", "INT"):
        print("[MikuMikuToon] 损毁强度插座是 %s 类型，写不了数值" % getattr(socket, "type", "?"))
        return False
    try:
        socket.default_value = float(factor)
        return True
    except Exception as error:
        print("[MikuMikuToon] 损毁强度设置失败：%s" % error)
        return False


def _attach(scene, tree):
    """把损毁组节点接到"上游 → Composite"这条线上。返回 (节点, 说明或 None)。"""
    sink = mmt_compat.find_sink(tree)
    target = mmt_compat.sink_input(sink) if sink is not None else None
    if target is None:
        return None, "合成器没有输出插槽"

    node = find_node(scene)
    if node is None:
        node = tree.nodes.new("CompositorNodeGroup")
        node.name = DAMAGE_NODE
        node.label = "MikuMikuToon 完整性损毁"
        node.location = (200, -300)
    if getattr(node, "node_tree", None) is None:
        node.node_tree = damage_group()

    image_in = mmt_compat.socket_like(node, (SOCKET_IMAGE, "Image"), "RGBA")
    image_out = mmt_compat.socket_like(node, (SOCKET_IMAGE, "Image"), "RGBA", False)
    if image_in is None or image_out is None:
        return None, "组节点上没有图像插槽"

    # 已经接好就别动（重复调用安全）
    if any(link.from_socket == image_out for link in target.links):
        return node, None

    # 上游：现在喂给输出的那一路（可能是 Reroute，得穿透）
    upstream = None
    if target.is_linked:
        upstream = mmt_compat.resolve_reroutes(target.links[0].from_socket)
    if upstream is None:
        upstream, _layers = mmt_compat.find_source(tree, sink)

    for link in list(target.links):
        tree.links.remove(link)
    if upstream is not None:
        tree.links.new(upstream, image_in)
    tree.links.new(image_out, target)
    return node, None


def enforce(scene, report):
    """渲染前调用：校验不过就损毁，通过了就把上次的损毁摘掉。返回一句说明。"""
    if not should_damage(report):
        state = (report or {}).get("state")
        if find_node(scene) is None:
            return "不损毁（%s）" % state
        if remove(scene):
            return "不损毁（%s），已把上次的损毁节点摘掉并还原接线" % state
        return "不损毁（%s），但摘除损毁节点失败（看上面的报错）" % state

    group = damage_group()
    if group is None:
        return "损毁失败：节点组建不起来"
    try:
        tree, api = mmt_compat.scene_tree(scene)
    except Exception as error:
        return "损毁失败：拿不到合成器树（%s）" % error
    if tree is None:
        return "损毁失败：拿不到合成器树"

    node, problem = _attach(scene, tree)
    if problem:
        return "损毁失败：%s" % problem
    set_factor(scene, 1.0)
    return "已损毁画面（%s，合成器 %s）" % ((report or {}).get("state"), api)


def remove(scene):
    """把损毁节点连同接线摘掉，还原成"损毁之前"的样子。返回动过没有。"""
    tree = mmt_compat.existing_tree(scene)
    if tree is None:
        return False
    node = find_node(scene)
    if node is None:
        return False
    upstream = None
    for link in tree.links:
        if link.to_node == node:
            upstream = link.from_socket
            break
    try:
        tree.nodes.remove(node)
    except Exception as error:
        print("[MikuMikuToon] 摘除损毁节点失败：%s" % error)
        return False
    if upstream is None:
        return True
    sink = mmt_compat.find_sink(tree)
    target = mmt_compat.sink_input(sink) if sink is not None else None
    if target is None:
        return True
    try:
        for link in list(target.links):
            tree.links.remove(link)
        tree.links.new(upstream, target)
    except Exception as error:
        print("[MikuMikuToon] 恢复接线失败：%s" % error)
    return True
