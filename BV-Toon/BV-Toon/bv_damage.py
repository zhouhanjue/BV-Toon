# -*- coding: utf-8 -*-
"""BVToon -- 校验不过就把画面弄坏（合成器）。

三态里的两种异常状态，除了把水印换成警告文字，还可以**把渲染出来的画面本身损毁**：
像素化（马赛克）→ 压色阶 → 去饱和并压暗。出图一眼就是"这图废了"，比一行红字狠得多。

面板「校验不过时」三档（默认第二档）：

* ``OFF``       只标记水印 —— 画面照常，只把水印换成警告文字
* ``MODIFIED``  被改就损毁画面（默认）
* ``ALL``       被改或未验证都损毁 —— 更狠：没有清单的副本（比如从源码目录直接拷贝安装的）也一起损毁

**为什么走合成器**：它是渲染管线的一部分，对静帧、动画、视口渲染都生效，而且是
"画面出来之前"动手 —— 不用去猜输出文件名再改文件（那种做法在 GUI 里连 Render Result 都改不到）。

**诚实边界**：开关本身是场景属性，懂行的人可以关掉它，也可以直接停用插件；
真正拦不住的是愿意改代码的人（那时他早就能把整个校验删掉）。它拦的是"拿改过的副本
出图冒充原版"—— 让那些图自己废掉。GPL v3 允许修改与再分发，这里动的只是**这个副本
自己渲染出来的画面**，不限制任何人改代码或再分发。

节点名/插座名是探测过的，不猜（Glare 的参数就搬过家）：
``CompositorNodePixelate`` 是 ``Color``/``Size``，``CompositorNodePosterize`` 是
``Image``/``Steps``，``CompositorNodeHueSat`` 是 ``Image``/``Saturation``/``Value``，
而图像混合在 4.5 是 ``CompositorNodeMixRGB``、5.2 起只有 ``ShaderNodeMix``
（两边都由 ``bv_glow._mix`` 兜住）。

© 2025 BVan / DEEPSEEK
"""

import bpy

from . import bv_glow
from . import bv_integrity      # 状态常量只定义一份（"ok/modified/unverified"）

#: 节点组与组节点名（组节点用 bv_ 前缀，跟材质树的白名单一个规矩）
DAMAGE_GROUP = "BVToon_Integrity_Damage"
DAMAGE_NODE = "bv_integrity_damage"

SOCKET_IMAGE = "图像"
SOCKET_FACTOR = "损毁"

#: **唯一档位**：被改或未验证都损毁。
#: 这里**没有**用户可选的档位、没有"改成只标记水印"这条路 —— 早先版本有过
#: OFF/MODIFIED/ALL 三档 + 面板下拉框，现在整个删掉了（用户明确要求：永远最严格）。
MODE = "ALL"
MODE_LABEL = "被改或未验证都损毁"

#: 损毁参数：马赛克块越大、色阶越少、越暗，越明显
PIXEL_SIZE = 64
STEPS = 3
SATURATION = 0.12
VALUE = 0.45

#: 借用的 bv_glow 助手（4.5 与 5.x 的合成器 API 不一样，这套 plumbing 只留一份实现）
BORROWED = ("scene_tree", "existing_tree", "_sink", "_sink_input", "_source",
            "_mix", "_set")


def missing_helpers():
    """bv_glow 里少了的助手名字（空表示都在）。名字对不上要大声说，别静默降级。"""
    return [name for name in BORROWED if not hasattr(bv_glow, name)]


def _knob(node, names, value, label):
    """按属性名/插座名设一个参数；全都设不上就打印出来（静默失败是这项目最大的坑）。"""
    for name in names:
        if bv_glow._set(node, name, value):
            return True
    print("[BV-Toon] 损毁节点 %s 的「%s」没设上（试过 %s），这一层可能不起作用"
          % (node.bl_idname, label, "/".join(names)))
    return False


def _plug(node, names, kind="RGBA"):
    """找一个插座：先按名字，再按类型兜底。"""
    for name in names:
        socket = node.inputs.get(name) if hasattr(node, "inputs") else None
        if socket is not None and (kind is None or socket.type == kind):
            return socket
    for socket in getattr(node, "inputs", ()):
        if kind is None or socket.type == kind:
            return socket
    return None


def _out(node, names, kind="RGBA"):
    for name in names:
        socket = node.outputs.get(name) if hasattr(node, "outputs") else None
        if socket is not None and (kind is None or socket.type == kind):
            return socket
    for socket in getattr(node, "outputs", ()):
        if kind is None or socket.type == kind:
            return socket
    return None


def damage_group():
    """损毁节点组：``损毁=0`` 原样通过，``损毁=1`` 把图弄坏。没有就现建。"""
    missing = missing_helpers()
    if missing:
        print("[BV-Toon] bv_glow 里找不到合成器助手 %s，损毁功能不可用" % missing)
        return None
    group = bpy.data.node_groups.get(DAMAGE_GROUP)
    if group is not None:
        return group

    group = bpy.data.node_groups.new(DAMAGE_GROUP, "CompositorNodeTree")
    group.interface.new_socket(SOCKET_IMAGE, in_out="INPUT",
                               socket_type="NodeSocketColor")
    group.interface.new_socket(SOCKET_FACTOR, in_out="INPUT",
                               socket_type="NodeSocketFloat")
    group.interface.new_socket(SOCKET_IMAGE, in_out="OUTPUT",
                               socket_type="NodeSocketColor")

    source = group.nodes.new("NodeGroupInput")
    source.location = (-400, 0)
    sink = group.nodes.new("NodeGroupOutput")
    sink.location = (400, 0)

    pixelate = bv_glow._new_node(group.nodes, "CompositorNodePixelate")
    pixelate.name = "bv_damage_pixelate"
    pixelate.location = (-180, 120)
    _knob(pixelate, ("pixel_size", "Size", "size", "大小"), PIXEL_SIZE, "马赛克块大小")

    posterize = bv_glow._new_node(group.nodes, "CompositorNodePosterize")
    posterize.name = "bv_damage_posterize"
    posterize.location = (0, 120)
    _knob(posterize, ("levels", "Steps", "色阶", "级数"), STEPS, "色阶数")

    hue = bv_glow._new_node(group.nodes, "CompositorNodeHueSat")
    hue.name = "bv_damage_hue"
    hue.location = (180, 120)
    _knob(hue, ("color_saturation", "Saturation", "饱和度"), SATURATION, "饱和度")
    _knob(hue, ("color_value", "Value", "明度"), VALUE, "明度")

    mix, slot_a, slot_b, mix_out = bv_glow._mix(group, "MIX", 0.0)
    mix.name = "bv_damage_mix"
    mix.location = (0, -120)

    image_in = source.outputs[SOCKET_IMAGE]
    factor_in = source.outputs[SOCKET_FACTOR]
    image_out = sink.inputs[SOCKET_IMAGE]

    # 原图 -> mix.A（fac=0 时就是这个），原图 -> 损毁链 -> mix.B（fac=1 时是这个）
    group.links.new(image_in, slot_a)
    group.links.new(image_in, _plug(pixelate, ("Color", "Image", "图像")))
    group.links.new(_out(pixelate, ("Color", "Image", "图像")),
                    _plug(posterize, ("Image", "图像")))
    group.links.new(_out(posterize, ("Image", "图像")),
                    _plug(hue, ("Image", "图像")))
    group.links.new(_out(hue, ("Image", "图像")), slot_b)
    group.links.new(mix_out, image_out)

    factor = bv_glow._factor_socket(mix)
    if factor is None:
        print("[BV-Toon] 损毁节点组：混合节点没有 fac 插座，损毁会一直生效"
              "（好在只在校验不过时才接进来）")
    else:
        group.links.new(factor_in, factor)
    return group


def find_node(scene):
    """场景里那个损毁组节点（没有就 None）。只在场景已经有合成器树时找。"""
    if not hasattr(bv_glow, "existing_tree"):
        return None
    tree = bv_glow.existing_tree(scene)
    if tree is None:
        return None
    return next((node for node in tree.nodes if node.name == DAMAGE_NODE), None)


def factor_for(state):
    """损毁强度（0 或 1）：**被改和未验证都算 1**（唯一档位，没有别的可能）。"""
    return 1.0 if state in (bv_integrity.STATE_MODIFIED,
                            bv_integrity.STATE_UNVERIFIED) else 0.0


def set_factor(scene, factor):
    """把已有的损毁节点设成 factor（不动合成器结构）。返回设到了没有。"""
    node = find_node(scene)
    if node is None:
        return factor <= 0.0              # 没有节点、又不需要损毁 = 已经是想要的状态
    socket = _plug(node, (SOCKET_FACTOR, "Factor", "Fac"), "VALUE")
    if socket is None:
        print("[BV-Toon] 损毁组节点上没有「%s」输入，设法调整" % SOCKET_FACTOR)
        return False
    try:
        socket.default_value = float(factor)
        return True
    except Exception as error:
        print("[BV-Toon] 损毁强度设置失败：%s" % error)
        return False


def enforce(scene, report):
    """渲染前调用：校验不过就损毁画面（唯一档位），通过就把上一次的损毁摘掉。

    **没有档位可选**：被改和未验证都损毁（:data:`MODE`）。返回一句说明（打日志用），
    失败也返回一句（绝不静默）。
    """
    state = report.get("state")
    factor = factor_for(state)

    if factor <= 0.0:
        if find_node(scene) is None:
            return "不损毁（%s）" % state
        # 校验恢复通过就把节点摘掉、把接线还原
        if remove(scene):
            return "不损毁（%s），已把上次的损毁节点摘掉并还原接线" % state
        return "不损毁（%s），但摘除损毁节点失败（看上面的报错）" % state

    if missing_helpers():
        return "损毁失败：bv_glow 的合成器助手不在"

    group = damage_group()
    if group is None:
        return "损毁失败：节点组建不起来"

    try:
        tree, api = bv_glow.scene_tree(scene)      # 需要时会把合成器打开
    except Exception as error:
        return "损毁失败：拿不到合成器树（%s）" % error
    sink = bv_glow._sink(tree, api)
    sink_in = bv_glow._sink_input(sink)
    if sink_in is None:
        return "损毁失败：合成器没有输出插槽"

    node = next((item for item in tree.nodes if item.name == DAMAGE_NODE), None)
    if node is None:
        node = tree.nodes.new("CompositorNodeGroup")
        node.name = DAMAGE_NODE
        node.label = "BVToon 完整性损毁"
        node.location = (200, -300)
    if getattr(node, "node_tree", None) is None:
        node.node_tree = group
    image_in = _plug(node, (SOCKET_IMAGE, "Image"), "RGBA")
    image_out = _out(node, (SOCKET_IMAGE, "Image"), "RGBA")
    if image_in is None or image_out is None:
        return "损毁失败：组节点上没有图像插槽"

    # 接线：现在喂给 Composite 的那一路 -> 损毁节点 -> Composite（原本的上游保留）
    # 注意 bv_glow._source() 返回的是 **(插槽, 渲染层节点)** 这个二元组，不是单个插槽
    try:
        source, _layers = bv_glow._source(tree, sink)
        wired = any(link.from_socket == image_out for link in sink_in.links)
        if not wired:
            for link in list(sink_in.links):
                tree.links.remove(link)
            if source is not None:
                tree.links.new(source, image_in)
            tree.links.new(image_out, sink_in)
    except Exception as error:
        import traceback
        traceback.print_exc()
        return "损毁失败：接不进合成器（%s）" % error
    set_factor(scene, 1.0)
    return "已损毁画面（%s / %s，合成器 %s）" % (state, MODE_LABEL, api)


def remove(scene):
    """把损毁节点连同它的接线摘掉（还原成"损毁之前"的样子）。体检/收尾用。"""
    tree = bv_glow.existing_tree(scene) if hasattr(bv_glow, "existing_tree") else None
    if tree is None:
        return False
    node = next((item for item in tree.nodes if item.name == DAMAGE_NODE), None)
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
        print("[BV-Toon] 摘除损毁节点失败：%s" % error)
        return False
    if upstream is not None and hasattr(bv_glow, "_sink") and hasattr(bv_glow, "_sink_input"):
        try:
            api = "compositing_node_group" if hasattr(scene, "compositing_node_group") \
                else "use_nodes"
            sink = bv_glow._sink(tree, api)
            sink_in = bv_glow._sink_input(sink)
            if sink_in is not None:
                for link in list(sink_in.links):
                    tree.links.remove(link)
                tree.links.new(upstream, sink_in)
        except Exception as error:
            print("[BV-Toon] 恢复接线失败：%s" % error)
    return True
