# -*- coding: utf-8 -*-
"""第 4 轮：遮罩探针。把 `band` / `mask` / `blended` 直接画出来，看它到底是什么值。

    blender -b --python tools/probe_mask.py -- [--pmx <model.pmx>]

做法：把组里「阴影分界」那个节点的输出**改接到组的 `颜色` 输出**，
再把每个材质的 Material Output 换成 Emission(颜色)，于是渲出来的就是遮罩本身。
同时把像素统计打出来（min/max/mean）—— 如果是常数，一眼就能看出是 0 还是 1。
"""

import os
import sys

import bpy

WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(WORKSPACE, "docs")
ODETTE = os.path.join(os.path.expanduser("~"), "Desktop",
                      "\u65b0\u5efa\u6587\u4ef6\u5939",
                      "\u5965\u9edb\u5854 \u539f\u6a21\u578b.pmx")
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
PMX = argv[argv.index("--pmx") + 1] if "--pmx" in argv else ODETTE


def setup():
    import addon_utils
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for key in ("bl_ext.blender_org.mmd_tools", "mmd_tools"):
        try:
            addon_utils.enable(key, default_set=True, persistent=True)
            break
        except Exception:
            continue
    addon_utils.enable("BV-Toon", default_set=True, persistent=True)
    scene = bpy.context.scene
    for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            scene.render.engine = engine
            break
        except Exception:
            continue
    scene.render.resolution_x = 480
    scene.render.resolution_y = 600
    scene.render.image_settings.file_format = "PNG"
    world = bpy.data.worlds[0] if bpy.data.worlds else bpy.data.worlds.new("w")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg is not None:
        bg.inputs[0].default_value = (0.0, 0.0, 0.0, 1.0)
        bg.inputs[1].default_value = 0.0
    return scene


def camera(scene, objects):
    from mathutils import Vector
    pts = [o.matrix_world @ Vector(c) for o in objects for c in o.bound_box]
    low = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    high = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    centre = (low + high) / 2.0
    size = max(high.z - low.z, high.x - low.x) * 1.15
    data = bpy.data.cameras.new("probe")
    data.type = "ORTHO"
    data.ortho_scale = size
    cam = bpy.data.objects.new("probe", data)
    scene.collection.objects.link(cam)
    cam.location = centre + Vector((0.0, -(high.y - low.y) * 2.0 - size, 0.0))
    cam.rotation_euler = (1.5707963, 0.0, 0.0)
    scene.camera = cam


def shading_nodes():
    for mat in bpy.data.materials:
        if mat.node_tree is None:
            continue
        node = mat.node_tree.nodes.get("bv_shading")
        if node is not None and node.node_tree is not None:
            yield mat, node


def retarget(label):
    """把组里某个中间节点的输出改接到 `颜色` 输出，并返回找到的节点名。"""
    found = None
    for _mat, node in shading_nodes():
        group = node.node_tree
        sink = next((n for n in group.nodes if n.bl_idname == "NodeGroupOutput"), None)
        source = next((n for n in group.nodes if n.label == label), None)
        if sink is None:
            continue
        if source is None:
            continue
        found = source.name
        socket = sink.inputs.get("颜色")
        if socket is not None:
            for link in list(socket.links):
                group.links.remove(link)
            out = source.outputs[0]
            group.links.new(out, socket)
    return found


def to_emission():
    """把每个材质的输出换成 Emission(组的颜色输出)，这样渲的就是遮罩。"""
    changed = 0
    for mat, node in shading_nodes():
        tree = mat.node_tree
        sink = next((n for n in tree.nodes if n.bl_idname == "ShaderNodeOutputMaterial"), None)
        if sink is None:
            continue
        emit = tree.nodes.get("bv_probe_emit")
        if emit is None:
            emit = tree.nodes.new("ShaderNodeEmission")
            emit.name = "bv_probe_emit"
            emit.label = "探针"
            emit.location = (node.location.x + 300, node.location.y + 300)
        colour = node.outputs.get("颜色")
        if colour is None:
            continue
        for link in list(emit.inputs["Color"].links):
            tree.links.remove(link)
        tree.links.new(colour, emit.inputs["Color"])
        for link in list(sink.inputs["Surface"].links):
            tree.links.remove(link)
        tree.links.new(emit.outputs["Emission"], sink.inputs["Surface"])
        changed += 1
    return changed


def stats(path):
    image = bpy.data.images.load(path, check_existing=False)
    pixels = image.pixels[:]
    values = [pixels[i] for i in range(0, len(pixels), 4)]
    bpy.data.images.remove(image)
    values.sort()
    return (values[0], values[len(values) // 2], values[-1],
            sum(values) / len(values))


def shoot(scene, name):
    scene.render.filepath = os.path.join(OUT, name)
    bpy.ops.render.render(write_still=True)
    return scene.render.filepath


def main():
    print("PROBE_START model=%s" % PMX)
    if not os.path.isfile(PMX):
        print("PROBE_SKIP")
        return
    scene = setup()
    bpy.ops.mmd_tools.import_model(filepath=PMX, scale=0.08, clean_model=True)
    model = [o for o in scene.objects if o.type == "MESH" and o.data is not None
             and getattr(o, "mmd_type", "NONE") == "NONE"]
    bpy.ops.object.select_all(action='DESELECT')
    for o in model:
        o.select_set(True)
    bpy.context.view_layer.objects.active = model[0]
    if hasattr(scene, "bv_mode"):
        scene.bv_mode = "REPLACE_MODEL"
    print("PROBE one_click=%s" % (bpy.ops.bvtoon.one_click(),))
    camera(scene, model)
    print("PROBE materials=%d" % len(list(shading_nodes())))

    # 组里所有节点的标签，先看有哪些可探
    first = next(iter(shading_nodes()), None)
    if first is not None:
        labels = [n.label or n.name for n in first[1].node_tree.nodes]
        print("PROBE labels=%s" % [x for x in labels if x][:40])

    for label, tag in (("阴影分界", "band"), ("条带 / 渐变贴图", "blend"),
                       ("× Fresnel", "mask"), ("× 暗部深浅", "strength")):
        found = retarget(label)
        if found is None:
            print("PROBE_%s NOT_FOUND (label=%s)" % (tag.upper(), label))
            continue
        count = to_emission()
        scene.render.filepath = os.path.join(OUT, "probe_%s.png" % tag)
        bpy.ops.render.render(write_still=True)
        low, mid, high, mean = stats(scene.render.filepath)
        print("PROBE_%s node=%s materials=%d min=%.4f p50=%.4f max=%.4f mean=%.4f"
              % (tag.upper(), found, count, low, mid, high, mean))
    print("PROBE_END")


main()
