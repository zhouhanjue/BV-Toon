# -*- coding: utf-8 -*-
"""BVToon -- 给 MMD 模型用的 Blender 卡渲插件。

从零写的：卡渲节点组、泛光、腮红、目影全部由本插件自己生成（Python 建节点），
**不加载、不依赖任何第三方插件的节点组或资源文件**；只读 mmd_tools 暴露的
``mmd_material`` 属性（贴图相对路径、球面模式、透明度、描边参数）来了解模型，
所以原作者的材质数据一个字节都不会被删掉。

面板（3D 视图 → N → 卡渲）：

    模式          替换【模型】材质 / 替换单个【材质】
    卡渲预设      普通偏暖 / 冷调 / 夜色暖
    MMD 设置      MMD 边缘预览（+清空）/ MMD 设置目影
    其他设置      添加泛光（+移除）/ 添加腮红 / 还原成基本材质

© 2025 BVan / DEEPSEEK
"""

bl_info = {
    "name": "BV-Toon",
    "author": "BVan / DEEPSEEK",
    "version": (1, 1, 7),
    "blender": (3, 6, 0),
    "location": "3D视图 > N 面部 > Toon",
    "description": "MMD 模型一键卡渲：原生读取材质、一键套用、边缘预览、目影、腮红、泛光、还原。",
    "category": "Material",
    "support": "COMMUNITY",
}

import bpy

from . import bv_glow
from . import bv_materials
from . import bv_shading
from . import bv_util


# ---------------------------------------------------------------------------
# 面板
# ---------------------------------------------------------------------------

class BVTOON_PT_panel(bpy.types.Panel):
    bl_label = "BV-Toon 卡渲"
    bl_idname = "BVTOON_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Toon'

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box.label(text="BV-Toon 一键卡渲", icon='SHADERFX')
        box.prop(context.scene, "bv_mode", text="")
        row = box.row(align=True)
        row.scale_y = 1.5
        row.operator("bvtoon.one_click", text="一键卡渲", icon="PLAY")
        box.row(align=True).label(text="卡渲 + 边缘预览，一次点完",
                                  icon="INFO")

        layout.label(text="其他设置")
        box2 = layout.box()
        row = box2.row(align=True)
        row.operator("bvtoon.add_glow", text="添加泛光", icon="LIGHT")
        row.operator("bvtoon.remove_glow", text="", icon='TRASH')
        row = box2.row(align=True)
        row.operator("bvtoon.set_eye_shadow", text="设置目影", icon="HIDE_OFF")
        row = box2.row(align=True)
        row.operator("bvtoon.add_blush", text="添加腮红", icon="OVERLAY")
        row = box2.row(align=True)
        row.operator("bvtoon.restore_mat", text="还原成基本材质")
        row = box2.row(align=True)
        row.prop(context.scene, '["bv_edge_scale"]', text="描边粗细")
        row.operator("bvtoon.set_edge_width", text="应用", icon="CHECKMARK")
        layout.label(text="维护：BVan / DEEPSEEK · BVToon %s"
                     % ".".join(str(part) for part in bl_info["version"]))


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def target_objects(context):
    mode = getattr(context.scene, "bv_mode", "REPLACE_MODEL")
    if mode == "REPLACE_MODEL":
        return [obj for obj in context.selected_objects
                if obj.type == "MESH" and obj.data is not None]
    obj = context.object
    if obj is not None and obj.type == "MESH" and obj.data is not None:
        return [obj]
    return []


def target_materials(context):
    materials, seen = [], set()
    for obj in target_objects(context):
        for slot in obj.material_slots:
            mat = slot.material
            if mat is None or mat in seen or mat.node_tree is None:
                continue
            seen.add(mat)
            if bv_util.is_mmd(mat):
                materials.append(mat)
    return materials


# ---------------------------------------------------------------------------
# 操作符
# ---------------------------------------------------------------------------

class BVTOON_OT_apply_preset(bpy.types.Operator):
    """把卡渲预设套到 MMD 材质上（原生读 mmd_material，不做破坏性转换）"""
    bl_idname = "bvtoon.apply_preset"
    bl_label = "应用卡渲预设"
    bl_options = {"REGISTER", "UNDO"}

    preset_index: bpy.props.IntProperty(default=0)

    def execute(self, context):
        materials = target_materials(context)
        if not materials:
            self.report({"ERROR"}, "先选中 MMD 模型（物体模式），或者把模式切到单个材质")
            return {"CANCELLED"}
        report = []
        done = sum(1 for mat in materials
                   if bv_materials.apply_preset(mat, self.preset_index,
                                                report=report))
        name = bv_shading.preset_names()[self.preset_index] \
            if 0 <= self.preset_index < len(bv_shading.preset_names()) else "?"
        self.report({"INFO"}, "已套用「%s」：%d 个材质" % (name, done))
        for line in report:
            print("[BVToon]", line)
        return {"FINISHED"}


class BVTOON_OT_one_click(bpy.types.Operator):
    """一键卡渲：套卡渲预设 → MMD 边缘预览 → MMD 设置目影"""
    bl_idname = "bvtoon.one_click"
    bl_label = "一键卡渲"
    bl_description = ("一次点完：读 MMD 原生材质套卡渲预设、生成 MMD 边缘预览。"
                      "失败的一步会单独提示，不影响其它步骤")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if not target_objects(context):
            self.report({"ERROR"}, "先选中 MMD 模型（物体模式），或者把模式切到单个材质")
            return {"CANCELLED"}
        steps = (
            ("卡渲", lambda: bpy.ops.bvtoon.apply_preset(preset_index=0)),
            ("边缘预览", lambda: bpy.ops.bvtoon.edge_preview_create()),
            
        )
        done, skipped = [], []
        for label, call in steps:
            try:
                result = call()
            except Exception as error:
                skipped.append("%s(%s)" % (label, error))
                continue
            (done if "FINISHED" in result else skipped).append(label)
        if "卡渲" not in done:
            self.report({"ERROR"}, "卡渲没成功：%s" % "、".join(skipped))
            return {"CANCELLED"}
        # 材质自带的描边色 / 粗细（MMD 的 edge_color / edge_weight）
        edge_mats = target_materials(context) or [
            slot.material for obj in target_objects(context)
            for slot in obj.material_slots if slot.material is not None]
        scene = context.scene
        if "bv_edge_scale" not in scene:
            scene["bv_edge_scale"] = 0.08
        bv_materials.apply_edge_preview(edge_mats, thickness=float(scene["bv_edge_scale"]))
        # 色彩管理：视图变换改成「标准」—— AgX/Filmic 会把卡渲的颜色洗淡、明暗压平
        try:
            scene = context.scene
            scene.view_settings.view_transform = "Standard"
            scene.view_settings.look = "None"
            print("[BV-Toon] 视图变换 -> 标准")
        except Exception as error:
            print("[BV-Toon] 视图变换设置失败：%s" % error)
        message = "已一键卡渲：%s" % "、".join(done)
        if skipped:
            message += "；跳过 %s" % "、".join(skipped)
        self.report({"INFO"}, message)
        print("[BV-Toon] %s" % message)
        return {"FINISHED"}


class BVTOON_OT_restore(bpy.types.Operator):
    """还原成基本材质（拿回基础贴图 + Principled）"""
    bl_idname = "bvtoon.restore_mat"
    bl_label = "还原成基本材质"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        materials = target_materials(context) or \
            [slot.material for obj in target_objects(context)
             for slot in obj.material_slots if slot.material is not None]
        done = sum(1 for mat in materials if bv_materials.restore(mat))
        self.report({"INFO"}, "已还原 %d 个材质" % done)
        return {"FINISHED"}


class BVTOON_OT_add_blush(bpy.types.Operator):
    """在暗部加一层腮红"""
    bl_idname = "bvtoon.add_blush"
    bl_label = "添加腮红"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        materials = target_materials(context)
        if not materials:
            self.report({"ERROR"}, "先选中已经卡渲过的 MMD 模型")
            return {"CANCELLED"}
        done = sum(1 for mat in materials if bv_materials.add_blush(mat))
        self.report({"INFO"}, "腮红已加到 %d 个材质（参数在 BVToon_Blush 组上）" % done)
        return {"FINISHED"}


class BVTOON_OT_set_eye_shadow(bpy.types.Operator):
    """把「目影」材质设成纯黑半透明"""
    bl_idname = "bvtoon.set_eye_shadow"
    bl_label = "MMD 设置目影"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        targets = [slot.material for obj in target_objects(context)
                   for slot in obj.material_slots
                   if slot.material is not None
                   and bv_materials.is_eye_shadow(slot.material)]
        if not targets:
            self.report({"WARNING"}, "没找到名字里带「目影」的材质")
            return {"CANCELLED"}
        for mat in targets:
            bv_materials.set_eye_shadow(mat)
        self.report({"INFO"}, "目影材质已设置：%d 个" % len(targets))
        return {"FINISHED"}


class BVTOON_OT_edge_preview_create(bpy.types.Operator):
    """MMD 边缘预览（转给 mmd_tools）"""
    bl_idname = "bvtoon.edge_preview_create"
    bl_label = "MMD 边缘预览"

    def execute(self, context):
        try:
            bpy.ops.mmd_tools.edge_preview_setup(action='CREATE')
        except Exception:
            self.report({"ERROR"}, "需要物体模式、选中 MMD 模型，并启用 MMD Tools")
            return {"CANCELLED"}
        return {"FINISHED"}


class BVTOON_OT_edge_preview_clean(bpy.types.Operator):
    """删除边缘预览"""
    bl_idname = "bvtoon.edge_preview_clean"
    bl_label = "删除边缘预览"

    def execute(self, context):
        try:
            bpy.ops.mmd_tools.edge_preview_setup(action='CLEAN')
        except Exception:
            self.report({"ERROR"}, "需要物体模式、选中 MMD 模型，并启用 MMD Tools")
            return {"CANCELLED"}
        return {"FINISHED"}


class BVTOON_OT_add_glow(bpy.types.Operator):
    """给场景加一层自发光驱动的朦胧泛光（合成器，可随时移除）"""
    bl_idname = "bvtoon.add_glow"
    bl_label = "添加泛光"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if not bv_glow.insert_glow(context.scene):
            self.report({"ERROR"}, "无法建立合成器节点树")
            return {"CANCELLED"}
        self.report({"INFO"},
                    "泛光已添加：合成器里的 %s 节点可调 强度/阈值/大小/外发光"
                    % bv_glow.GLOW_GROUP)
        return {"FINISHED"}


class BVTOON_OT_remove_glow(bpy.types.Operator):
    """移除泛光，其余合成器节点保持不动"""
    bl_idname = "bvtoon.remove_glow"
    bl_label = "移除泛光"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if not bv_glow.remove_glow(context.scene):
            self.report({"WARNING"}, "场景里没有泛光节点")
            return {"CANCELLED"}
        return {"FINISHED"}



class BVTOON_OT_set_edge_width(bpy.types.Operator):
    """按面板上的「描边粗细」重新套一次描边（不用重跑一键卡渲）"""
    bl_idname = "bvtoon.set_edge_width"
    bl_label = "应用描边粗细"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        scale = float(scene.get("bv_edge_scale", 2.0))
        materials = target_materials(context) or [
            slot.material for obj in target_objects(context)
            for slot in obj.material_slots if slot.material is not None]
        if not materials:
            self.report({"ERROR"}, "先选中模型")
            return {"CANCELLED"}
        bv_materials.apply_edge_preview(materials, thickness=scale)
        self.report({"INFO"}, "描边粗细已按 %.2f 重套" % scale)
        return {"FINISHED"}
CLASSES = (
    BVTOON_OT_set_edge_width,
    BVTOON_PT_panel,
    BVTOON_OT_one_click,
    BVTOON_OT_apply_preset,
    BVTOON_OT_restore,
    BVTOON_OT_add_blush,
    BVTOON_OT_set_eye_shadow,
    BVTOON_OT_edge_preview_create,
    BVTOON_OT_edge_preview_clean,
    BVTOON_OT_add_glow,
    BVTOON_OT_remove_glow,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.bv_mode = bpy.props.EnumProperty(
        name="模式",
        items=[("REPLACE_MODEL", "替换【模型】材质", ""),
               ("REPLACE_SINGLE", "替换单个【材质】", "")],
        default="REPLACE_MODEL")
    print("[BVToon] v%s 已启用：面板在 3D 视图 N → 卡渲"
          % ".".join(str(part) for part in bl_info["version"]))


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.bv_mode


if __name__ == "__main__":
    register()
