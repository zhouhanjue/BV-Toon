# -*- coding: utf-8 -*-
"""BV-Toon patch: keep the model's native MMD material detail alive.

THE PROBLEM
-----------
``bvtoon.convert_materials`` forwards to ``bpy.ops.mmd_tools.convert_materials()``
with its defaults, and that default is ``clean_nodes=True``.  The conversion

1. builds a Principled BSDF out of the MMD shader and then **deletes the MMD
   shader node**, and
2. removes every node that is no longer reachable from the material output.

So a model loses exactly the things that only an MMD material has:

===================================  ==========================================
``mmd_toon_tex``                     the author's hand painted toon ramp
``mmd_sphere_tex``                   the sphere / sub-texture layer -- the
                                     sparkles, the jewel sheen, the metal
                                     glint.  Nothing else in the material
                                     carries them.
``mmd_tex_uv``                       the MMD UV set: base UV, camera space
                                     normal for the sphere layer, UV1 for the
                                     sub-texture
===================================  ==========================================

The texture *images* survive the deletion only until the file is saved: with
the nodes gone their user count is zero and Blender drops them on reload.  That
is why the sparkles never come back once a model has been through the
conversion.

WHAT THIS PATCH DOES
--------------------
1. **Preserve** -- the conversion runs with ``clean_nodes=False``, and the
   addon's own ``cleanup`` is taught that MMD nodes are not clutter, so nothing
   is deleted in the first place.

2. **Repair** -- materials that were already destroyed (converted before this
   patch existed, or stripped by ``bvtoon.restore_mat``) get their toon ramp,
   sphere map and MMD UV group rebuilt from ``mmd_material``.  That property
   group lives on the Material, not on a node, so the conversion cannot touch
   it, and it still knows the sphere mode and both relative texture paths.

3. **Consume** -- BVToon' shader has no sphere input, so a restored node on its
   own changes nothing on screen.  One blend node is spliced into the
   *material's own* tree between whatever feeds the group's ``MColor`` and that
   socket, so the sphere layer lands on the albedo -- where MMD puts it --
   before the addon's shading runs.

   The blend is the one mmd_tools itself uses in ``MMDShaderDev``:

   ===========  =========================================================
   sphere mode  albedo
   ===========  =========================================================
   1 multiply   ``base * (Fac * sphere + (1 - Fac))``  -> MixRGB MULTIPLY
   2 add        ``base + Fac * sphere``                -> MixRGB ADD
   3 sub-texture same as 1, sampled through the SubTex UV set
   ===========  =========================================================

   with ``Fac = Sphere Tex Fac``, which mmd_tools sets to 1 for every active
   sphere mode.  Leaving Fac at Blender's MixRGB default of 0.5 (what an
   earlier revision of this file did) multiplies the albedo by roughly a half
   everywhere the texture is black -- the sparkles then read as *dark* spots
   instead of highlights, which is worse than dropping them.

   The addon's node group itself is never modified: adding sockets to a node
   group interface makes Blender 4.5 die with an access violation, and the
   material side can express this blend on its own.

4. **Trim the sidebar** -- ``BVTOON_FIX_PANEL`` below lists the buttons that are
   drawn.  Everything else (the other 13 presets, the conversion button, the
   lighting import, the geometry stroke, the two alpha modes) keeps working and
   stays reachable from the operator search (F3), it is just no longer in the
   N panel.  Set ``BVTOON_FIX_SKIP=panel`` to get the author's panel back.

Nothing here is distributed with the addon.  This is a local modification of a
copy the user owns; re-installing an official update overwrites it, and
``tools/install_bvtoon_fix.py`` puts it back.
"""

import os

import bpy

PATCH_VERSION = "2.7"
PATCH_KEY = "bvtoon_mmd_fix"

BASE_TEX = "mmd_base_tex"
TOON_TEX = "mmd_toon_tex"
SPHERE_TEX = "mmd_sphere_tex"
LEGACY_UV = "mmd_tex_uv"
UV_GROUP = "BVToon_MMDUV"

# every node this patch creates carries this prefix, so re-applying is
# idempotent and the stage can be stripped back off cleanly
STAGE_PREFIX = "GMR_MMD"

SPHERE_OFF, SPHERE_MULT, SPHERE_ADD, SPHERE_SUBTEX = 0, 1, 2, 3

#: how much of the sphere layer reaches the albedo.  1.0 is what MMD does;
#: the constant is here so a user can dial it without touching the maths below.
SPHERE_STRENGTH = 1.0


# ---------------------------------------------------------------------------
# The sidebar
# ---------------------------------------------------------------------------
#
# Which buttons the N panel draws.  Everything the addon registers keeps
# working -- this only decides what is on screen.
#
# Editing these two tuples is all it takes to change the panel:
#   * rename a preset in BVToonJson/data.json and the name here to match, or
#   * put more names in BVTOON_FIX_PANEL to get more preset buttons back.

#: preset buttons, by the names in BVToonJson/data.json, in the order given here
BVTOON_FIX_PRESETS = ("一键卡渲",)

#: 那个按钮上显示的字（和 data.json 里的预设名可以不一样）
BVTOON_FIX_PRESET_LABEL = "一键卡渲"

#: 自己的侧栏标签页与标题：不再和原插件的面板挤在同一个「卡渲」标签里
PANEL_CATEGORY = "BV-Toon"
PANEL_TITLE = "BV-Toon 卡渲"

#: 那个大按钮调用的操作符：转换材质 + 预设 + 边缘预览 + 目影，一次点完
BVTOON_FIX_MAIN_BUTTON = "bvtoon.one_click"

#: the panel body: (section label, rows of buttons), each button being
#: (operator id, text, icon).  Buttons in one row share a row.
BVTOON_FIX_SECTIONS = (
    ("其他设置", (
        (("bvtoon.add_glow", "添加泛光", "LIGHT"),
         ("bvtoon.remove_glow", "", "TRASH")),
        (("bvtoon.add_blush", "添加腮红", "OVERLAY"),),
        (("bvtoon.restore_mat", "还原成基本材质", None),),
    )),
)

#: the sections whose buttons are gone from the panel
BVTOON_FIX_HIDDEN = (
    "bvtoon.convert_materials",      # MMD 转换给Blender
    "bvtoon.import_lighting",        # 导入灯光环境(场景)
    "bvtoon.add_geom_stroke",        # 添加几何描边
    "bvtoon.remove_geom_stroke",
    "bvtoon.set_alpha_blend_one",    # Alpha 混合
    "bvtoon.set_alpha_hashed_one",   # Alpha 抖动
)


# ---------------------------------------------------------------------------
# Genshin style glow -- 朦胧眩光 / 泛光
# ---------------------------------------------------------------------------
#
# EEVEE Next has no bloom of its own (the legacy EEVEE checkbox is gone), so the
# glow is a compositor effect.  Two glare passes at different radii are summed
# and then *added* to the image:
#
#     image ─┬─► Glare wide ─┐
#            ├─► Glare core ─┴─► sum ─► bleach ─► ×strength
#            └────────────────────────────────► + ──► out
#
# Adding is the point.  The Glare node can blend the glow into the image itself,
# but it does so by *lerping* towards the glare-only image, which lifts the
# blacks and dims everything that does not glow.  Bright areas gaining a halo
# while the rest of the frame stays where it is -- that is what makes it read as
# a haze rather than as a washed out picture.
#
# The two radii are what turn a hard "bloom" into 朦胧: the wide pass is the veil
# over the whole frame, the core pass is the tighter halo right around the
# highlight.  A little desaturation keeps it from turning into coloured fog,
# because Genshin's bloom leans white.

#: node group holding the effect; its sockets are exposed in the compositor
GLOW_GROUP = "BVToon_Glow"
#: everything this patch puts in the scene's compositor tree carries this prefix
GLOW_PREFIX = "GMR_GLOW"
#: marks a compositor tree this patch had to create (5.x scenes start without one)
SCENE_TREE_FLAG = "bvtoon_glow_tree"

GLOW_STRENGTH = 0.35      # how much glow is added on top of the image
#: The glow is fed by the render's **Emit pass** -- the character's own emission
#: -- plus whatever in the combined image is brighter than this.  Emission alone
#: is enough, which is the point: a card-shaded model lights itself, so the
#: effect has to work with no scene lights at all.  Measured on a real model
#: with the world switched off, an BVToon preset puts the character at a median
#: luminance of 0.80, so a threshold meant to catch "emission" would have missed
#: two thirds of it -- the emit pass has no such problem.
GLOW_THRESHOLD = 0.95
GLOW_WIDE_SIZE = 8        # veil radius, glare size is 1..9
GLOW_CORE_SIZE = 4        # halo radius
#: the outward aura: the character's silhouette (from the emit pass) blurred by
#: this percentage of the frame, tinted, and added to the glow.  This is the
#: part that spreads past the silhouette on every side instead of hugging the
#: highlights.
GLOW_AURA_SPREAD = 12.0
GLOW_AURA_WEIGHT = 0.9
#: how much emission a pixel needs before it counts as "the character"
GLOW_AURA_FLOOR = 0.02
GLOW_AURA_TINT = (1.0, 0.96, 0.92, 1.0)   # a touch warm, like the reference
GLOW_SATURATION = 0.85    # 1.0 keeps the glow colourful, lower bleaches it
GLOW_TINT = (1.0, 0.98, 0.94, 1.0)   # a touch warm, like sunlight through haze
#: glare quality: HIGH looks best, MEDIUM renders an 8K frame noticeably faster
GLOW_QUALITY = "HIGH"

#: the glare mode used for both passes; BLOOM is the lighting glare added in 4.4
GLOW_MODE = "BLOOM"


def _has(node, name):
    return node.bl_rna.properties.get(name) is not None


def _set(node, name, value):
    """Set a property or a socket, whichever this Blender has.

    Sockets are only touched when their type matches the value: assigning a
    float to the glare node's Clamp socket makes Blender print an RNA warning
    even though the exception is swallowed.
    """
    if _has(node, name):
        try:
            setattr(node, name, value)
            return True
        except Exception:
            pass
    socket = node.inputs.get(name)
    if socket is None:
        return False
    fits = ((socket.type == "VALUE" and isinstance(value, (int, float))
             and not isinstance(value, bool))
            or (socket.type == "BOOLEAN" and isinstance(value, bool))
            or (socket.type == "INT" and isinstance(value, int)
                and not isinstance(value, bool))
            or (socket.type == "RGBA" and isinstance(value, (tuple, list))))
    if not fits:
        return False
    try:
        socket.default_value = value
        return True
    except Exception:
        return False


def _socket(node, name, kind=None):
    for candidate in node.inputs:
        if candidate.name == name and (kind is None or candidate.type == kind):
            return candidate
    return None


def _output(node, name=None, kind="RGBA"):
    for candidate in node.outputs:
        if (name is None or candidate.name == name) and candidate.type == kind:
            return candidate
    return None


def _glare_node(nodes, label, size, location):
    """One glare pass.

    Its own threshold stays at **0**: everything it is handed goes into the
    glow, including dim emission.  Gating the *image* by 阈值 happens once, in
    the source chain, where it cannot touch the emit path -- feeding 阈值 into
    this socket instead silently suppresses exactly the self-emission the
    effect exists for (measured: a 0.35 emissive patch then glows 13x less).
    """
    node = nodes.new("CompositorNodeGlare")
    node.name = "%s_%s" % (GLOW_PREFIX, label)
    node.label = label
    node.location = location
    _set(node, "glare_type", GLOW_MODE)          # 4.5 and older
    _set(node, "quality", GLOW_QUALITY)
    _set(node, "mix", 0.0)                       # the glow is taken from the
    _set(node, "threshold", 0.0)                 # Glare output and added by us
    _set(node, "size", int(size))
    _set(node, "Type", GLOW_MODE)                # 5.x exposes these as sockets
    _set(node, "Quality", GLOW_QUALITY)
    for name, value in (("Threshold", 0.0), ("Smoothness", 0.0),
                        ("Clamp", False), ("Maximum", 10.0),
                        ("Saturation", 1.0), ("Strength", 1.0), ("Fade", 1.0),
                        ("Color Modulation", 1.0)):
        _set(node, name, value)
    tint = _socket(node, "Tint", "RGBA")
    if tint is not None:
        tint.default_value = GLOW_TINT
    return node


def _factor_socket(node):
    """The float that drives a mix node, whichever node class it is."""
    for socket in node.inputs:
        if socket.name in {"Fac", "Factor"} and socket.type == "VALUE":
            return socket
    return None


def _new_node(nodes, *names):
    """Create the first of these node types that this Blender actually has.

    5.x moved several compositor nodes onto the shared shader node classes --
    ``CompositorNodeMath`` is gone and ``ShaderNodeMath`` lives in a compositor
    tree instead -- so the names get tried rather than assumed.
    """
    for name in names:
        try:
            return nodes.new(name)
        except Exception:
            continue
    raise RuntimeError("none of these node types exist here: %s"
                       % ", ".join(names))


def _mix(tree, blend_type, factor=1.0, label=""):
    """An image mix node, on either compositor API.  Returns (node, a, b, out).

    4.5 has the classic ``CompositorNodeMixRGB``; 5.x dropped it and lets the
    shader Mix node live in a compositor tree instead.
    """
    if hasattr(bpy.types, "CompositorNodeMixRGB"):
        node = tree.nodes.new("CompositorNodeMixRGB")
        node.blend_type = blend_type
        node.inputs[0].default_value = factor
        return node, node.inputs[1], node.inputs[2], node.outputs[0]
    node = tree.nodes.new("ShaderNodeMix")
    node.data_type = "RGBA"
    node.blend_type = blend_type
    factor_socket = next(s for s in node.inputs
                         if s.name == "Factor" and s.type == "VALUE")
    factor_socket.default_value = factor
    a = next(s for s in node.inputs if s.name == "A" and s.type == "RGBA")
    b = next(s for s in node.inputs if s.name == "B" and s.type == "RGBA")
    return node, a, b, _output(node)


def glow_group():
    """Build (once) the node group that turns an image into a glowing image.

    Its inputs are exposed on the group node, so the strength, threshold and
    size stay adjustable in the compositor without a single line of UI code.

    What actually glows is the sum of

    * ``自发光`` -- the render's Emit pass, i.e. the character's own emission.
      This is the part that makes the effect work in an unlit scene, and it is
      why the glow is not simply a threshold on the image.
    * ``图像`` above ``阈值`` -- so highlights of a lit frame still bloom, with
      the threshold available to keep a bright sky out of it.
    """
    group = bpy.data.node_groups.get(GLOW_GROUP)
    if group is not None and len(group.nodes):
        return group
    if group is None:
        group = bpy.data.node_groups.new(GLOW_GROUP, "CompositorNodeTree")
    for name, kind in (("图像", "NodeSocketColor"), ("自发光", "NodeSocketColor"),
                       ("强度", "NodeSocketFloat"), ("阈值", "NodeSocketFloat"),
                       ("大小", "NodeSocketFloat")):
        group.interface.new_socket(name, in_out="INPUT", socket_type=kind)
    # the output cannot reuse the input's name: Blender then hands back the
    # wrong socket from inputs[]/outputs[] and links.new() fails on direction
    group.interface.new_socket("泛光", in_out="OUTPUT",
                              socket_type="NodeSocketColor")
    # and every socket needs its real default: a fresh float socket is 0, which
    # would make 强度 = 0 and quietly add nothing at all
    defaults = {"强度": GLOW_STRENGTH, "阈值": GLOW_THRESHOLD,
                "大小": float(GLOW_WIDE_SIZE)}
    for socket in group.interface.items_tree:
        if socket.name in defaults and hasattr(socket, "default_value"):
            socket.default_value = defaults[socket.name]

    nodes, links = group.nodes, group.links
    source = nodes.new("NodeGroupInput")
    source.location = (-900, 0)
    sink = nodes.new("NodeGroupOutput")
    sink.location = (700, 0)

    # --- what glows: emission + the image's own highlights ---------------
    # SUBTRACT weights the second colour by Fac, so handing Fac the 阈值 input
    # and a white colour gives 图像 - 阈值 per channel: the knob really drives
    # the node, and it is a float into a float socket (no colour juggling).
    # LIGHTEN against black then floors the negatives at zero.
    over_node, over_a, over_b, over_out = _mix(group, "SUBTRACT", 1.0)
    over_node.name = "%s_over" % GLOW_PREFIX
    over_node.label = "图像 - 阈值"
    over_node.location = (-620, -300)
    links.new(source.outputs["图像"], over_a)
    over_b.default_value = (1.0, 1.0, 1.0, 1.0)
    threshold_factor = _factor_socket(over_node)
    if threshold_factor is not None:
        links.new(source.outputs["阈值"], threshold_factor)

    floor_node, floor_a, floor_b, floor_out = _mix(group, "LIGHTEN", 1.0)
    floor_node.name = "%s_floor" % GLOW_PREFIX
    floor_node.label = "clamp to black"
    floor_node.location = (-440, -300)
    links.new(over_out, floor_a)
    floor_b.default_value = (0.0, 0.0, 0.0, 1.0)

    source_node, source_a, source_b, source_out = _mix(group, "ADD", 1.0)
    source_node.name = "%s_source" % GLOW_PREFIX
    source_node.label = "emission + highlights"
    source_node.location = (-260, -180)
    links.new(floor_out, source_a)
    links.new(source.outputs["自发光"], source_b)

    wide = _glare_node(nodes, "wide", GLOW_WIDE_SIZE, (-560, 220))
    core = _glare_node(nodes, "core", GLOW_CORE_SIZE, (-560, -60))

    # 大小 is 1..9 like Blender's own glare size, but the socket the new glare
    # node exposes is a 0..1 fraction -- feeding 2..8 straight in gets clamped to
    # 1 and the knob does nothing at all.  Scale it instead.
    scale = _new_node(nodes, "CompositorNodeMath", "ShaderNodeMath")
    scale.name = "%s_size" % GLOW_PREFIX
    scale.label = "大小 ÷ 9"
    scale.operation = "MULTIPLY"
    scale.location = (-760, 220)
    scale.inputs[1].default_value = 1.0 / 9.0
    links.new(source.outputs["大小"], scale.inputs[0])

    for node in (wide, core):
        links.new(source_out, node.inputs["Image"])
        size = _socket(node, "Size", "VALUE")
        if size is not None:
            links.new(scale.outputs[0], size)

    sum_node, sum_a, sum_b, sum_out = _mix(group, "ADD", 1.0)
    sum_node.name = "%s_sum" % GLOW_PREFIX
    sum_node.label = "two radii"
    sum_node.location = (-260, 120)
    links.new(_output(wide, "Glare"), sum_a)
    links.new(_output(core, "Glare"), sum_b)

    # --- the part that spreads outward in every direction ----------------
    # A glare radius tops out at 1.0 (a fraction of the frame) and still hugs
    # the bright edges.  What this look needs is an aura around the *whole*
    # silhouette -- including the dark parts of a costume -- so the character is
    # turned into a mask (anything the Emit pass has something in), that mask is
    # tinted and blurred wide, and the result is added to the glow.  Because the
    # mask comes from the emit pass, a lit background never enters it.
    separator = _new_node(nodes, "CompositorNodeSeparateColor")
    separator.name = "%s_aura_sep" % GLOW_PREFIX
    separator.label = "emit rgb"
    separator.location = (-760, 620)
    if _has(separator, "mode"):
        separator.mode = "RGB"
    links.new(source.outputs["自发光"], separator.inputs["Image"])

    def _math(label, operation, value_b=None, location=(-600, 620)):
        node = _new_node(nodes, "CompositorNodeMath", "ShaderNodeMath")
        node.name = "%s_%s" % (GLOW_PREFIX, label)
        node.label = label
        node.operation = operation
        node.location = location
        if value_b is not None and len(node.inputs) > 1:
            node.inputs[1].default_value = value_b
        return node

    peak = _math("aura_max1", "MAXIMUM", location=(-600, 620))
    links.new(separator.outputs["Red"], peak.inputs[0])
    links.new(separator.outputs["Green"], peak.inputs[1])
    peak2 = _math("aura_max2", "MAXIMUM", location=(-460, 620))
    links.new(peak.outputs[0], peak2.inputs[0])
    links.new(separator.outputs["Blue"], peak2.inputs[1])
    gate = _math("aura_gate", "GREATER_THAN", GLOW_AURA_FLOOR, (-320, 620))
    links.new(peak2.outputs[0], gate.inputs[0])

    tinted, tint_a, tint_b, tint_out = _mix(group, "MIX", 1.0)
    tinted.name = "%s_aura_tint" % GLOW_PREFIX
    tinted.label = "aura colour"
    tinted.location = (-160, 620)
    tint_a.default_value = (0.0, 0.0, 0.0, 1.0)
    tint_b.default_value = GLOW_AURA_TINT
    gate_factor = _factor_socket(tinted)
    if gate_factor is not None:
        links.new(gate.outputs[0], gate_factor)
    else:                                       # 5.x names it Factor
        links.new(gate.outputs[0], tinted.inputs[0])

    aura = _new_node(nodes, "CompositorNodeBlur")
    aura.name = "%s_aura" % GLOW_PREFIX
    aura.label = "aura"
    aura.location = (20, 620)
    # the blur's size is a property (or a vector socket), not a float a knob can
    # drive, so the aura keeps a fixed spread -- a wide one, which is the point
    if _has(aura, "filter_type"):
        for filter_name in ("GAUSS", "GAUSSIAN", "FAST_GAUSS"):
            try:
                aura.filter_type = filter_name
                break
            except Exception:
                continue
    if _has(aura, "use_relative"):
        aura.use_relative = True
    for name in ("size_x", "size_y"):
        if _has(aura, name):
            try:
                setattr(aura, name, int(GLOW_AURA_SPREAD))
            except Exception:
                pass
    links.new(tint_out, aura.inputs["Image"])

    aura_mix, aura_a, aura_b, aura_out = _mix(group, "ADD", GLOW_AURA_WEIGHT)
    aura_mix.name = "%s_aura_mix" % GLOW_PREFIX
    aura_mix.label = "aura onto glow"
    aura_mix.location = (200, 260)
    links.new(sum_out, aura_a)
    links.new(aura.outputs["Image"], aura_b)

    bleach = nodes.new("CompositorNodeHueSat")
    bleach.name = "%s_bleach" % GLOW_PREFIX
    bleach.label = "haze"
    bleach.location = (200, 120)
    bleach.inputs["Saturation"].default_value = GLOW_SATURATION
    bleach.inputs["Fac"].default_value = 1.0
    links.new(aura_out, bleach.inputs["Image"])

    add_node, add_a, add_b, add_out = _mix(group, "ADD", GLOW_STRENGTH)
    add_node.name = "%s_add" % GLOW_PREFIX
    add_node.label = "glow onto image"
    add_node.location = (240, 0)
    links.new(source.outputs["图像"], add_a)
    links.new(bleach.outputs["Image"], add_b)
    strength = add_node.inputs[0]
    links.new(source.outputs["强度"], strength)
    links.new(add_out, sink.inputs["泛光"])
    return group

# ---------------------------------------------------------------------------
# Wiring the glow into the scene's compositor
# ---------------------------------------------------------------------------

def scene_tree(scene):
    """(compositor tree, api) -- the API moved in 5.0.

    4.5 and older: ``scene.use_nodes`` plus ``scene.node_tree``, ending in a
    Composite node.  5.x: the scene owns a compositor *node group* through
    ``compositing_node_group``, and the tree's own group output is the sink.

    Either way, note on the scene whether *we* had to switch compositing on, so
    removing the glow can hand the scene back the way it was found.
    """
    if hasattr(scene, "compositing_node_group"):
        tree = scene.compositing_node_group
        if tree is None:
            tree = bpy.data.node_groups.new("Compositor", "CompositorNodeTree")
            scene[SCENE_TREE_FLAG] = 1
            scene.compositing_node_group = tree
        return tree, "compositing_node_group"
    if not scene.use_nodes:
        scene[SCENE_TREE_FLAG] = 1
    scene.use_nodes = True
    return scene.node_tree, "use_nodes"


#: node types a compositor tree may contain for the glow to consider it "still
#: untouched" when it is removed again
STRUCTURAL_NODES = {"CompositorNodeRLayers", "CompositorNodeComposite",
                    "NodeGroupOutput", "NodeGroupInput", "NodeReroute",
                    "CompositorNodeViewer", "CompositorNodeOutputFile"}


def _sink(tree, api):
    """The node the final image has to reach.

    On 5.x the compositor tree is a node group and the scene reads its *group
    outputs*, so the interface needs an output socket -- without one the tree
    renders nothing no matter how well the nodes inside are wired.
    """
    if api == "compositing_node_group":
        outputs = [item for item in tree.interface.items_tree
                   if item.in_out == "OUTPUT"]
        if not outputs:
            tree.interface.new_socket("Image", in_out="OUTPUT",
                                      socket_type="NodeSocketColor")
        node = next((n for n in tree.nodes
                     if n.bl_idname == "NodeGroupOutput"), None)
        if node is None:
            node = tree.nodes.new("NodeGroupOutput")
            node.location = (400, 0)
        return node

    node = next((n for n in tree.nodes
                 if n.bl_idname == "CompositorNodeComposite"), None)
    if node is None:
        node = tree.nodes.new("CompositorNodeComposite")
        node.location = (400, 0)
    return node


def _sink_input(sink):
    for name in ("Image", "图像"):
        socket = sink.inputs.get(name)
        if socket is not None:
            return socket
    return sink.inputs[0] if len(sink.inputs) else None


def _render_layers(tree):
    """The Render Layers node of this tree, created if there is none."""
    node = next((n for n in tree.nodes
                 if n.bl_idname == "CompositorNodeRLayers"), None)
    if node is None:
        node = tree.nodes.new("CompositorNodeRLayers")
        node.location = (-200, 0)
    return node


def _source(tree, sink):
    """(image socket that feeds the sink, render layers node)."""
    socket = _sink_input(sink)
    if socket is not None and socket.is_linked:
        upstream = socket.links[0].from_socket
        layers = upstream.node if upstream.node.bl_idname == "CompositorNodeRLayers" \
            else _render_layers(tree)
        return upstream, layers
    layers = next((n for n in tree.nodes
                   if n.bl_idname == "CompositorNodeRLayers"
                   and not any(out.is_linked for out in n.outputs)), None)
    if layers is None:
        layers = _render_layers(tree)
    return _output(layers, "Image"), layers


def _emit_socket(layers):
    """The render layer's emission output: ``Emit`` in 4.5, ``Emission`` in 5.x.

    It only exists once ``use_pass_emit`` is on, so this has to be asked for
    *after* switching the pass on.
    """
    for name in ("Emit", "Emission"):
        socket = _output(layers, name)
        if socket is not None:
            return socket
    return None


def _glow_nodes(tree):
    return [node for node in tree.nodes if node.name.startswith(GLOW_PREFIX)]


def glow_state(scene):
    """What the glow looks like right now: (added, tree api, group node)."""
    tree = existing_tree(scene)
    api = ("compositing_node_group" if hasattr(scene, "compositing_node_group")
           else "use_nodes")
    if tree is None:
        return False, api, None
    node = next((n for n in _glow_nodes(tree)
                 if n.bl_idname == "CompositorNodeGroup"), None)
    return node is not None, api, node


def insert_glow(scene):
    """Put the glow between whatever renders and the composite.

    Idempotent, and it does not care what else the compositor tree does: the
    glow is spliced into the existing link instead of replacing the tree.
    """
    tree, api = scene_tree(scene)
    sink = _sink(tree, api)
    target = _sink_input(sink)
    if target is None:
        return False
    # drop an older glow first: reading the source before that would hand back
    # the old glow's *output*, which is about to be deleted
    remove_glow(scene, keep_tree=True)
    source, layers = _source(tree, sink)

    # the character's own emission is the glow source, so the view layer has to
    # render its Emit pass
    view_layer = bpy.context.view_layer
    if hasattr(view_layer, "use_pass_emit"):
        view_layer.use_pass_emit = True

    node = tree.nodes.new("CompositorNodeGroup")
    node.name = "%s_group" % GLOW_PREFIX
    node.label = "Genshin 泛光"
    node.node_tree = glow_group()
    node.location = (60, 0)
    for link in list(target.links):
        tree.links.remove(link)
    tree.links.new(source, node.inputs["图像"])
    emit = _emit_socket(layers)
    if emit is not None:
        tree.links.new(emit, node.inputs["自发光"])
    tree.links.new(node.outputs["泛光"], target)
    return True


def existing_tree(scene):
    """The compositor tree only if the scene already has one -- creating a tree
    is a side effect that a "there is nothing to remove" answer must not have.
    """
    if hasattr(scene, "compositing_node_group"):
        return scene.compositing_node_group
    if scene.use_nodes and scene.node_tree is not None:
        return scene.node_tree
    return None


def remove_glow(scene, keep_tree=False):
    """Take the glow back out, leaving the rest of the compositor alone.

    Nothing is created on the way: what the glow was fed by has to be read out
    of the glow's *input* before it is deleted -- the node's own output is what
    the composite is consuming, and reconnecting that would leave the frame
    dangling (and black).
    """
    tree = existing_tree(scene)
    if tree is None:
        return False
    api = ("compositing_node_group" if hasattr(scene, "compositing_node_group")
           else "use_nodes")
    nodes = _glow_nodes(tree)
    if not nodes:
        return False

    group = next((node for node in nodes
                  if node.bl_idname == "CompositorNodeGroup"), None)
    source = None
    if group is not None:
        for socket in group.inputs:
            if socket.is_linked:
                source = socket.links[0].from_socket
                break

    sink = _sink(tree, api)
    target = _sink_input(sink)
    if target is not None:
        for link in list(target.links):
            tree.links.remove(link)
        if source is not None:
            tree.links.new(source, target)
        else:
            # nothing upstream to restore: keep the render connected
            layers = tree.nodes.new("CompositorNodeRLayers")
            layers.location = (-200, 0)
            tree.links.new(_output(layers, "Image"), target)

    for node in nodes:
        tree.nodes.remove(node)

    # if this patch had to switch compositing on and nothing else was ever
    # added, switch it back off instead of leaving a tree behind
    untouched = all(node.bl_idname in STRUCTURAL_NODES for node in tree.nodes)
    if not keep_tree and untouched and scene.get(SCENE_TREE_FLAG):
        if api == "compositing_node_group":
            scene.compositing_node_group = None
            if tree.users == 0:
                bpy.data.node_groups.remove(tree)
        else:
            scene.use_nodes = False
        del scene[SCENE_TREE_FLAG]
    return True


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class BVTOON_AddGlow(bpy.types.Operator):
    """给场景加一层原神式的朦胧泛光（合成器，可随时删掉）"""
    bl_idname = "bvtoon.add_glow"
    bl_label = "添加泛光"
    bl_description = ("在合成器里加一层朦胧泛光：亮部晕开，暗部不动。"
                      "参数在合成器那个 BVToon_Glow 节点上，随时可调")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if not insert_glow(context.scene):
            self.report({"ERROR"}, "无法建立合成器节点树")
            return {"CANCELLED"}
        self.report({"INFO"}, "泛光已添加：合成器里的 BVToon_Glow 节点可调强度/阈值/大小")
        return {"FINISHED"}


class BVTOON_RemoveGlow(bpy.types.Operator):
    """删掉泛光，其余合成器节点保持不动"""
    bl_idname = "bvtoon.remove_glow"
    bl_label = "删除泛光"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if not remove_glow(context.scene):
            self.report({"WARNING"}, "场景里没有泛光节点")
            return {"CANCELLED"}
        return {"FINISHED"}


GLOW_CLASSES = (BVTOON_AddGlow, BVTOON_RemoveGlow)


class BVTOON_OneClick(bpy.types.Operator):
    """一键卡渲：转换材质 → 套卡渲预设 → MMD 边缘预览 → MMD 设置目影"""

    bl_idname = "bvtoon.one_click"
    bl_label = "一键卡渲"
    bl_description = ("把 MMD 模型一次处理到位：转换材质（球面层不丢）、套卡渲预设、"
                      "生成 MMD 边缘预览、设置目影。失败的一步会单独提示，不影响其它步骤")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        objects = [obj for obj in context.selected_objects
                   if obj.type == "MESH" and obj.data is not None]
        if not objects and context.object is not None \
                and context.object.type == "MESH":
            objects = [context.object]
        if not objects:
            self.report({"ERROR"}, "先选中 MMD 模型（物体模式）")
            return {"CANCELLED"}
        bpy.ops.object.select_all(action='DESELECT')
        for obj in objects:
            obj.select_set(True)
        context.view_layer.objects.active = objects[0]

        # 转换用模型模式（和面板上的模式一致）
        if hasattr(scene, "bvtoon_mode"):
            scene.bvtoon_mode = "REPLACE_MODEL"

        steps = (
            ("转换材质", lambda: bpy.ops.bvtoon.convert_materials()),
            ("卡渲预设", lambda: bpy.ops.bvtoon.apply_preset(preset_index=0)),
            ("MMD 边缘预览", lambda: bpy.ops.bvtoon.edge_preview_create()),
            ("MMD 设置目影", lambda: bpy.ops.bvtoon.set_eye_shadow()),
        )
        done, skipped = [], []
        for label, call in steps:
            try:
                result = call()
            except Exception as error:
                skipped.append("%s(%s)" % (label, error))
                continue
            if "FINISHED" in result:
                done.append(label)
            else:
                skipped.append(label)
        if "卡渲预设" not in done:
            self.report({"ERROR"}, "卡渲预设没成功：%s" % "、".join(skipped))
            return {"CANCELLED"}
        message = "已一键卡渲：%s" % "、".join(done)
        if skipped:
            message += "；跳过 %s" % "、".join(skipped)
        self.report({"INFO"}, message)
        print("[BV-Toon] %s" % message)
        return {"FINISHED"}


ONE_CLICK_CLASSES = (BVTOON_OneClick,)


def trim_panel(module):
    """Draw only the buttons in ``BVTOON_FIX_SECTIONS``, under our own tab.

    The addon's own ``draw`` is kept as ``_bvtoon_mmd_original`` so the panel can
    be put back, and every operator stays registered -- the hidden buttons are
    still reachable from Blender's operator search (F3).

    The panel also moves to its **own sidebar tab** with its own title, so the
    trimmed menu never sits on top of the plugin it was built from: two panels
    with near-identical buttons in one tab is exactly the confusion to avoid.
    """
    panel = getattr(module, "BVTOONPresetPanel", None)
    original_draw = getattr(panel, "draw", None)
    if panel is None or original_draw is None:
        return False
    if getattr(original_draw, "_bvtoon_mmd_patched", False):
        return False

    panel.bl_category = PANEL_CATEGORY
    panel.bl_label = PANEL_TITLE

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box.label(text="BV-Toon 一键卡渲", icon="SHADERFX")
        box.prop(context.scene, "bvtoon_mode", text="")

        # 一个大按钮把整条链路走完：转换材质 → 卡渲预设 → MMD 边缘预览 → 目影
        row = box.row(align=True)
        row.scale_y = 1.5
        row.operator(BVTOON_FIX_MAIN_BUTTON, icon="PLAY",
                     text=BVTOON_FIX_PRESET_LABEL)
        hint = box.row(align=True)
        hint.label(text="转换材质 + 卡渲预设 + 边缘预览 + 目影", icon="INFO")

        for title, rows in BVTOON_FIX_SECTIONS:
            layout.label(text=title, icon="DOT")
            section = layout.box()
            for row in rows:
                line = section.row(align=True)
                for idname, text, icon in row:
                    if icon:
                        line.operator(idname, text=text, icon=icon)
                    else:
                        line.operator(idname, text=text)

        footer = layout.row(align=True)
        footer.alignment = "CENTER"
        footer.label(text="BV-Toon · 维护：BVan / DEEPSEEK · 补丁 %s"
                     % PATCH_VERSION, icon="INFO")

    draw._bvtoon_mmd_patched = True
    draw._bvtoon_mmd_original = original_draw
    panel.draw = draw
    return True


# ---------------------------------------------------------------------------
# MMD data access
# ---------------------------------------------------------------------------

def _norm(path):
    return (path or "").replace("\\", "/")


def _mm(mat):
    return getattr(mat, "mmd_material", None)


def _base_image(mat):
    tree = mat.node_tree
    if tree is None:
        return None
    node = tree.nodes.get(BASE_TEX)
    if node is not None and node.type == "TEX_IMAGE":
        return node.image
    for node in tree.nodes:
        if node.type == "TEX_IMAGE" and node.image is not None:
            return node.image
    return None


def model_root(mat):
    """Directory the PMX came from, derived from the surviving base texture."""
    mm = _mm(mat)
    if mm is None:
        return None
    rel = _norm(getattr(mm, "texture_rel_path", ""))
    image = _base_image(mat)
    if image is not None and image.filepath:
        absolute = _norm(os.path.normpath(bpy.path.abspath(image.filepath)))
        if rel and absolute.endswith(rel):
            return absolute[: len(absolute) - len(rel)].rstrip("/")
        return os.path.dirname(absolute)
    return None


def _resolve(mat, rel):
    rel = _norm(rel)
    if not rel:
        return None
    if os.path.isabs(rel) and os.path.isfile(rel):
        return rel
    root = model_root(mat)
    candidates = []
    if root:
        candidates.append(os.path.join(root, *rel.split("/")))
        candidates.append(os.path.join(root, os.path.basename(rel)))
    image = _base_image(mat)
    if image is not None and image.filepath:
        candidates.append(os.path.join(
            os.path.dirname(bpy.path.abspath(image.filepath)),
            os.path.basename(rel)))
    for path in candidates:
        if path and os.path.isfile(path):
            return os.path.normpath(path)
    return None


def _shared_toon(mat):
    mm = _mm(mat)
    if mm is None or not mm.is_shared_toon_texture:
        return None
    index = int(mm.shared_toon_texture)
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
    mm = _mm(mat)
    if mm is None:
        return None
    if mm.is_shared_toon_texture:
        return _shared_toon(mat)
    if mm.toon_texture:
        path = os.path.normpath(bpy.path.abspath(mm.toon_texture))
        if os.path.isfile(path):
            return path
    rel = getattr(mm, "toon_texture_rel_path", "")
    return _resolve(mat, rel) if rel else None


def sphere_path(mat):
    mm = _mm(mat)
    if mm is None or int(mm.sphere_texture_type) == SPHERE_OFF:
        return None
    rel = getattr(mm, "sphere_texture_rel_path", "")
    if rel:
        found = _resolve(mat, rel)
        if found:
            return found
    root = model_root(mat)
    name = os.path.basename(_norm(rel)) if rel else ""
    if root and name:
        folders = ("", "sph", "spa", "sphere", "Sphere", "textures", "tex")
        for sub in folders:
            path = os.path.join(root, sub, name)
            if os.path.isfile(path):
                return os.path.normpath(path)
    return None


# ---------------------------------------------------------------------------
# Node construction
# ---------------------------------------------------------------------------

def _load(path, add_mode):
    """Load one MMD texture, with the colour space mmd_tools would give it.

    ``MMDShaderDev`` reads the sphere map of an "add" material as linear data
    (mmd_tools sets ``Linear Rec.709`` there) and every other sphere map as
    sRGB.  Loading it the other way round shifts the sparkle colours.
    """
    if not path or not os.path.isfile(path):
        return None
    image = None
    for existing in bpy.data.images:
        if existing.filepath and os.path.normpath(
                bpy.path.abspath(existing.filepath)) == os.path.normpath(path):
            image = existing
            break
    if image is None:
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


def uv_group():
    """The MMD UV set, built the way mmd_tools' ``MMDTexUV`` builds it.

    Only used when mmd_tools' own group is not in the file any more.
    """
    group = bpy.data.node_groups.get(UV_GROUP)
    if group is not None and len(group.nodes):
        return group
    if group is None:
        group = bpy.data.node_groups.new(UV_GROUP, "ShaderNodeTree")
        for name in ("Base UV", "Toon UV", "Sphere UV", "SubTex UV"):
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
        group.links.new(coords.outputs["Normal"], xform.inputs["Vector"])
        group.links.new(xform.outputs["Vector"], mapping.inputs["Vector"])
        group.links.new(coords.outputs["UV"], out.inputs["Base UV"])
        group.links.new(mapping.outputs["Vector"], out.inputs["Toon UV"])
        group.links.new(mapping.outputs["Vector"], out.inputs["Sphere UV"])
        group.links.new(subtex.outputs["UV"], out.inputs["SubTex UV"])
    return group


def _mmd_uv_node(tree):
    node = tree.nodes.get(LEGACY_UV)
    if node is None or node.type != "GROUP" or node.node_tree is None:
        if node is not None:
            tree.nodes.remove(node)
        node = tree.nodes.new("ShaderNodeGroup")
        node.name = LEGACY_UV
        node.label = "MMD UV"
        node.node_tree = bpy.data.node_groups.get("MMDTexUV") or uv_group()
        node.location = (-1500, -260)
    return node


def _tex_node(tree, name, label, location):
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


def repair_material(mat, report=None):
    """Rebuild whatever a destructive conversion deleted.  Idempotent."""
    result = {"toon": False, "sphere": False, "uv": False}
    mm = _mm(mat)
    if mm is None or not mat.use_nodes or mat.node_tree is None:
        return result
    tree = mat.node_tree
    uv_node = _mmd_uv_node(tree)
    result["uv"] = True

    def uv_out(name):
        return uv_node.outputs.get(name)

    # ---- toon ramp -----------------------------------------------------
    path = toon_path(mat)
    existing = tree.nodes.get(TOON_TEX)
    if path is None:
        if existing is not None and existing.image is None:
            tree.nodes.remove(existing)
    else:
        image = existing.image if (existing is not None
                                  and existing.type == "TEX_IMAGE") else None
        if image is None or not image.has_data:
            image = _load(path, add_mode=False)
        if image is None:
            if report is not None:
                report.append("%s: toon unreadable %s" % (mat.name, path))
        else:
            node = _tex_node(tree, TOON_TEX, "MMD Toon Tex", (-1500, -80))
            node.image = image
            if not node.inputs["Vector"].is_linked and uv_out("Toon UV"):
                tree.links.new(uv_out("Toon UV"), node.inputs["Vector"])
            result["toon"] = True

    # ---- sphere / sub-texture layer ------------------------------------
    mode = int(mm.sphere_texture_type)
    path = sphere_path(mat)
    existing = tree.nodes.get(SPHERE_TEX)
    if mode == SPHERE_OFF:
        if existing is not None:
            tree.nodes.remove(existing)
        return result
    if path is None:
        if report is not None:
            report.append("%s: sphere not found (mode %d)" % (mat.name, mode))
        return result
    is_add = mode == SPHERE_ADD
    image = existing.image if (existing is not None
                              and existing.type == "TEX_IMAGE") else None
    if image is None or not image.has_data:
        image = _load(path, add_mode=is_add)
    if image is None:
        if report is not None:
            report.append("%s: sphere unreadable %s" % (mat.name, path))
        return result
    node = _tex_node(tree, SPHERE_TEX, "MMD Sphere Tex", (-1500, 120))
    node.image = image
    # mmd_tools samples the sub-texture through the second UV set and every
    # other sphere map through the camera space normal
    want = "SubTex UV" if mode == SPHERE_SUBTEX else "Sphere UV"
    source = uv_out(want) or uv_out("Sphere UV")
    if source is not None and not node.inputs["Vector"].is_linked:
        tree.links.new(source, node.inputs["Vector"])
    result["sphere"] = True
    return result


def repair_materials(materials, report=None):
    toon = sphere = 0
    for mat in materials:
        res = repair_material(mat, report=report)
        toon += 1 if res["toon"] else 0
        sphere += 1 if res["sphere"] else 0
    return toon, sphere


# ---------------------------------------------------------------------------
# Wiring one material -- entirely inside the material node tree
# ---------------------------------------------------------------------------

def _stage_nodes(tree):
    return [n for n in tree.nodes if n.name.startswith(STAGE_PREFIX)]


def find_group_node(mat):
    """The BVToon preset group node in this material, if there is one."""
    tree = mat.node_tree
    if tree is None:
        return None
    fallback = None
    for node in tree.nodes:
        if node.bl_idname != "ShaderNodeGroup" or node.node_tree is None:
            continue
        if node.node_tree.name.startswith("BVToon-"):
            return node
        if fallback is None and "MColor" in node.inputs:
            fallback = node
    return fallback


def base_source(socket):
    """The albedo source feeding ``socket``, seeing through this patch's stage.

    Re-wiring a material that already carries a stage would otherwise lose the
    base texture -- the stage is what ``MColor`` points at, so the raw source
    has to be read out of the stage's own first input.
    """
    if socket is None or not socket.is_linked:
        return None
    node = socket.links[0].from_node
    if not node.name.startswith(STAGE_PREFIX):
        return socket.links[0].from_socket
    for inp in node.inputs:
        if inp.name in {"Color1", "A"} and inp.is_linked:
            return inp.links[0].from_socket
    return None


def strip_stage(mat):
    """Remove a previously inserted stage, reconnecting the raw source."""
    tree = mat.node_tree
    if tree is None:
        return
    group_node = find_group_node(mat)
    base = None
    if group_node is not None:
        base = base_source(group_node.inputs.get("MColor"))
    for node in _stage_nodes(tree):
        if base is not None and node.outputs and node.outputs[0].is_linked:
            for link in list(node.outputs[0].links):
                to_socket = link.to_socket
                tree.links.remove(link)
                tree.links.new(base, to_socket)
        tree.nodes.remove(node)


def wire_material(mat, strength=SPHERE_STRENGTH):
    """Blend this material's MMD sphere layer into what feeds the BVToon group.

    MMD applies the sphere map to the albedo before lighting, which is exactly
    where this lands: between the base texture and the group's ``MColor``.

    One MixRGB node carries the whole thing, because Blender's own blend maths
    is the maths mmd_tools uses inside ``MMDShaderDev``:

        MULTIPLY   Color1 * (Fac * Color2 + (1 - Fac))
        ADD        Color1 + Fac * Color2

    with ``Fac = Sphere Tex Fac`` = 1 for every active sphere mode.  For an
    "add" sphere map -- the usual sparkle / jewel / metal layer, painted black
    outside the highlights -- the black background then adds nothing, and the
    highlights add their own colour.  A multiply map behaves like a modulated
    multiply, again weighted by the same factor.
    """
    mm = _mm(mat)
    group_node = find_group_node(mat)
    if mm is None or group_node is None or mat.node_tree is None:
        return False
    tree = mat.node_tree
    socket = group_node.inputs.get("MColor")
    if socket is None:
        return False

    # where the raw base comes from, before our stage is dropped
    source = base_source(socket)
    strip_stage(mat)
    if source is None and socket.is_linked:
        source = base_source(socket)

    sphere = tree.nodes.get(SPHERE_TEX)
    mode = int(mm.sphere_texture_type)
    if sphere is None or sphere.image is None or mode == SPHERE_OFF \
            or strength <= 0.0:
        return False

    node = tree.nodes.new("ShaderNodeMixRGB")
    node.name = "%s_Sphere" % STAGE_PREFIX
    node.blend_type = "ADD" if mode == SPHERE_ADD else "MULTIPLY"
    node.label = ("MMD Sphere ADD" if mode == SPHERE_ADD
                  else "MMD Sphere MULT")
    node.inputs[0].default_value = max(0.0, min(1.0, float(strength)))
    anchor = source.node.location if source is not None else None
    node.location = ((anchor.x + 260) if anchor else 260,
                     (anchor.y - 260) if anchor else -260)

    for link in list(socket.links):
        tree.links.remove(link)
    if source is not None:
        tree.links.new(source, node.inputs[1])
    else:
        node.inputs[1].default_value = (1.0, 1.0, 1.0, 1.0)
    tree.links.new(sphere.outputs["Color"], node.inputs[2])
    tree.links.new(node.outputs[0], socket)
    return True


# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------

def protected_nodes(nt):
    """Native MMD nodes the addon's own cleanup must not delete.

    Deleting them is what loses the data: with no consumer their image drops to
    zero users and is gone on the next save.  The name prefixes are mmd_tools'
    own convention -- ``mmd_base_tex``, ``mmd_toon_tex``, ``mmd_sphere_tex``,
    ``mmd_tex_uv``, ``mmd_shader``, ``mmd_bind*``, ``mmd_edge_preview``.
    """
    keep = set()
    for node in nt.nodes:
        if node.name.startswith("mmd_"):
            keep.add(node)
            continue
        if node.bl_idname == "ShaderNodeGroup" and node.node_tree is not None \
                and node.node_tree.name.startswith(("MMD", "BVToon_MMD")):
            keep.add(node)
    return keep


def base_texture_node(mat):
    tree = mat.node_tree
    if tree is None:
        return None
    node = tree.nodes.get(BASE_TEX)
    if node is not None and node.type == "TEX_IMAGE" and node.image is not None:
        return node
    return None


def prefer_base_texture(mat):
    """Point a freshly restored Principled BSDF at the author's base texture.

    ``bvtoon.restore_mat`` rebuilds a Principled and links *every* texture node
    into Base Color, so the last one in the node list wins.  That is harmless
    while the conversion has deleted the toon and sphere nodes, but this patch
    exists precisely to keep them, and then the material can come back wearing
    its sphere map as the base colour.  Re-pointing the link at ``mmd_base_tex``
    keeps the addon's "restore" honest.
    """
    node = base_texture_node(mat)
    if node is None:
        return False
    tree = mat.node_tree
    changed = False
    for candidate in tree.nodes:
        if candidate.type != "BSDF_PRINCIPLED":
            continue
        for socket in candidate.inputs:
            if socket.name == "Base Color":
                for link in list(socket.links):
                    tree.links.remove(link)
                tree.links.new(node.outputs["Color"], socket)
                changed = True
            elif socket.name == "Alpha" and node.outputs["Alpha"].is_linked is False:
                for link in list(socket.links):
                    tree.links.remove(link)
                tree.links.new(node.outputs["Alpha"], socket)
    return changed


def install(module):
    """Monkey-patch the host addon.  Safe to call once at register time.

    ``BVTOON_FIX_SKIP`` (comma separated: cleanup, convert, wire, restore, panel,
    glow) turns individual hooks off, which is both the escape hatch if one of
    them misbehaves on some model and how the hooks get bisected.
    """
    skip = {part.strip() for part in os.environ.get("BVTOON_FIX_SKIP", "").split(",")
            if part.strip()}
    module._bvtoon_mmd_fix_skipped = sorted(skip)

    # 0. 自己的操作符每次都要注册。install() 在"补丁已装"时会提前返回，而
    #    read_factory_settings / 重新启用会把所有类注销掉 —— 那样按钮就会以
    #    "could not be found" 失败（实测踩过）。这里放在最早，且可重复执行。
    if "glow" not in skip:
        for cls in GLOW_CLASSES + ONE_CLICK_CLASSES:
            try:
                bpy.utils.register_class(cls)
            except Exception as error:
                print("[BV-Toon] 无法注册 %s：%s" % (cls.__name__, error))

    if getattr(module, "_bvtoon_mmd_fix_installed", None) == PATCH_VERSION:
        return False

    # 1. their cleanup deletes anything with no linked outputs -- the MMD
    #    texture nodes lose their consumer the moment mmd_shader is parked, so
    #    they would be removed right after being restored.
    #
    #    It is also the right place to wire the layers back up: it is the last
    #    thing replace_material does, so by then the tree has been rebuilt and
    #    the group node exists.  Wrapping BVTOONPresetOperator.execute instead
    #    makes Blender 4.5 die with an access violation -- even a pass-through
    #    wrapper crashes -- so that approach is avoided entirely.
    original_cleanup = getattr(module, "cleanup", None)
    if original_cleanup is not None and "cleanup" not in skip and not getattr(
            original_cleanup, "_bvtoon_mmd_patched", False):
        def cleanup(nt, keep, _original=original_cleanup):
            result = _original(nt, set(keep) | protected_nodes(nt))
            if "wire" not in skip:
                try:
                    finish_tree(nt)
                except Exception:
                    import traceback
                    traceback.print_exc()
            return result
        cleanup._bvtoon_mmd_patched = True
        module.cleanup = cleanup

    # 2. stop the destructive conversion at the source
    convert = getattr(module, "BVTOON_convert_materials", None)
    if convert is not None and "convert" not in skip and not getattr(
            convert.execute, "_bvtoon_mmd_patched", False):
        def execute(self, context):
            enabled = (bpy.context.preferences.addons.get(
                           "bl_ext.blender_org.mmd_tools") is not None
                       or bpy.context.preferences.addons.get("mmd_tools")
                       is not None)
            if not enabled:
                self.report({"ERROR"},
                            "Select the model in Object Mode with MMD Tools "
                            "enabled")
                return {"FINISHED"}
            # clean_nodes=False keeps the toon / sphere / UV nodes alive; the
            # default True is exactly what destroys them.
            bpy.ops.mmd_tools.convert_materials(use_principled=True,
                                                clean_nodes=False)
            repaired = (0, 0)
            if "wire" not in skip:
                try:
                    repaired = finish_materials(context)
                except Exception:
                    import traceback
                    traceback.print_exc()
            if repaired[0] or repaired[1]:
                self.report({"INFO"},
                            "MMD 细节已保留：%d 个渐变贴图, %d 个球面/副纹理贴图"
                            % repaired)
            return {"FINISHED"}
        execute._bvtoon_mmd_patched = True
        convert.execute = execute

    # 3. the sidebar: draw only the buttons the user asked to keep
    if "panel" not in skip:
        try:
            trim_panel(module)
        except Exception:
            import traceback
            traceback.print_exc()

    # 4. "restore basic material" links every texture node into Base Color, and
    #    this patch is what keeps extra texture nodes alive -- so make sure the
    #    author's base texture is the one that ends up connected.
    operator = getattr(module, "BVTOONMaterialOperator", None)
    original_restore = getattr(operator, "restore_single_material", None)
    if original_restore is not None and "restore" not in skip and not getattr(
            original_restore, "_bvtoon_mmd_patched", False):
        def restore_single_material(self, mat, _original=original_restore):
            result = _original(self, mat)
            try:
                prefer_base_texture(mat)
            except Exception:
                import traceback
                traceback.print_exc()
            return result
        restore_single_material._bvtoon_mmd_patched = True
        operator.restore_single_material = restore_single_material

    # 5. the glow buttons are ours, so they get registered (and unregistered)
    #    here; the addon has no idea they exist.  The one-click button is ours
    #    too (it chains the addon's own operators).
    if "glow" not in skip:
        for cls in GLOW_CLASSES + ONE_CLICK_CLASSES:
            try:
                bpy.utils.register_class(cls)
            except Exception as error:
                # 别静默吞掉：注册失败时按钮会以 "could not be found" 出现，
                # 那种报错很难查（实测踩过），这里直接把原因打出来
                print("[BV-Toon] 无法注册 %s：%s" % (cls.__name__, error))
        original_unregister = getattr(module, "unregister", None)
        if original_unregister is not None and not getattr(
                original_unregister, "_bvtoon_mmd_patched", False):
            def unregister(_original=original_unregister):
                for cls in GLOW_CLASSES + ONE_CLICK_CLASSES:
                    try:
                        bpy.utils.unregister_class(cls)
                    except Exception:
                        pass
                return _original()
            unregister._bvtoon_mmd_patched = True
            module.unregister = unregister

    module._bvtoon_mmd_fix_installed = PATCH_VERSION
    # say so in the system console: a silent patch is indistinguishable from a
    # patch that never loaded, which is exactly the confusion this line ends
    print("[BV-Toon] patch v%s active: trimmed sidebar + glow buttons "
          "(BVTOON_FIX_SKIP=%s)"
          % (PATCH_VERSION, ",".join(sorted(skip)) or "none"))
    return True


def target_materials(context):
    """MMD materials of whatever the user is about to convert."""
    mode = getattr(context.scene, "bvtoon_mode", None)
    objects = []
    if mode == "REPLACE_MODEL":
        objects = [obj for obj in context.selected_objects
                   if obj.type == "MESH" and obj.data is not None]
    else:
        obj = context.object
        if obj is not None and obj.type == "MESH" and obj.data is not None:
            objects = [obj]
    materials = []
    seen = set()
    for obj in objects:
        for slot in obj.material_slots:
            mat = slot.material
            if mat is None or mat in seen or not mat.use_nodes \
                    or mat.node_tree is None:
                continue
            seen.add(mat)
            if _mm(mat) is None or "mmd_edge" in mat.name:
                continue
            materials.append(mat)
    return materials


def finish_materials(context, report=None, strength=SPHERE_STRENGTH):
    """Repair + wire every MMD material of the current selection."""
    materials = target_materials(context)
    if not materials:
        return 0, 0
    return repair_materials(materials, report=report)


def material_for_tree(tree):
    """The Material that owns this node tree, or None.

    ``tree.id_data`` is no use here: a ShaderNodeTree is itself an ID, so
    id_data comes back as the tree.  Scanning the material list is O(n) in
    materials, which are counted in tens.
    """
    for mat in bpy.data.materials:
        if mat.use_nodes and mat.node_tree is tree:
            return mat
    return None


def finish_tree(tree, strength=SPHERE_STRENGTH):
    """Repair + wire the material that owns ``tree``, if it is an MMD one.

    Called from the cleanup hook, which is handed a ShaderNodeTree.  That hook
    is the last thing ``replace_material`` does, so by the time it runs the tree
    has been rebuilt and the preset group node exists.
    """
    mat = material_for_tree(tree)
    if mat is None or _mm(mat) is None:
        return False
    repair_material(mat)
    return wire_material(mat, strength=strength)
