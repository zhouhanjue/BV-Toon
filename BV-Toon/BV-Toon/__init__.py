# -*- coding: utf-8 -*-
"""BVToon -- 给 MMD 模型用的 Blender 卡渲插件。

从零写的：卡渲节点组、泛光、目影全部由本插件自己生成（Python 建节点），
**不加载、不依赖任何第三方插件的节点组或资源文件**；只读 mmd_tools 暴露的
``mmd_material`` 属性（贴图相对路径、球面模式、透明度、描边参数）来了解模型，
所以原作者的材质数据一个字节都不会被删掉。

面板（3D 视图 → N → 卡渲）：

    模式          替换【模型】材质 / 替换单个【材质】
    一键卡渲      套卡渲预设 → 边缘预览，一次点完
    其他设置      添加泛光（+移除）/ 设置目影 / 烧录署名 / 使用条款

完整性（哈希防盗，见 ``bv_integrity.py``）：打包时生成一份 SHA-256 清单随 zip
发出，加载时与每次渲染前核对。副本被改过 ⇒ 水印换成「未授权修改版」；没有清单
⇒「未验证副本」。只标记、只警告，**不阻止渲染**（GPL v3 允许修改）。

© 2025 BVan / DEEPSEEK
"""

bl_info = {
    "name": "BV-Toon",
    "author": "BVan / DEEPSEEK",
    "version": (1, 8, 0),
    "blender": (3, 6, 0),
    "location": "3D视图 > N 面部 > Toon",
    "description": "MMD 模型一键卡渲：原生读取材质、一键套用、边缘预览、目影、泛光、强制署名水印。",
    "category": "Material",
    "support": "COMMUNITY",
}

import bpy

from . import bv_damage
from . import bv_glow
from . import bv_integrity
from . import bv_materials
from . import bv_shading
from . import bv_util

#: 面板版本号只在这里写一次，条款弹窗 / 面板底栏都从 bl_info 取，免得四处对不上
_VERSION = ".".join(str(part) for part in bl_info["version"])

#: 正常状态下的默认署名（panel 可改；被改过的副本一律不用这行）
DEFAULT_CREDIT = "渲染 BVToon / @BVan"

#: Blender 的 stamp 是一整块，这些子项必须逐个关掉，只留署名
_OTHER_STAMP_PROPS = ("use_stamp_date", "use_stamp_time", "use_stamp_render_time",
                      "use_stamp_frame", "use_stamp_frame_range", "use_stamp_scene",
                      "use_stamp_camera", "use_stamp_lens", "use_stamp_filename",
                      "use_stamp_marker", "use_stamp_memory", "use_stamp_hostname",
                      "use_stamp_sequencer_strip", "use_stamp_strip_meta",
                      "use_stamp_labels")


# ---------------------------------------------------------------------------
# 完整性校验（哈希防盗）
# ---------------------------------------------------------------------------

#: 模块加载时先查一次；渲染前由 force_watermark 每次再查（带 mtime 缓存，很便宜）
INTEGRITY = bv_integrity.verify()


def report_integrity(report):
    """把校验结果打到控制台：正常一行，异常一大块（要显眼，别静默）。"""
    if report["state"] == bv_integrity.STATE_OK:
        print("[BV-Toon] 完整性校验通过：%s" % report["reason"])
        return
    bar = "=" * 70
    print(bar)
    print("[BV-Toon] [!] 完整性校验未通过：%s" % report["credit"])
    print("[BV-Toon]     原因：%s" % report["reason"])
    print("[BV-Toon]     渲染水印会被强制改成上面那行字，"
          "「渲染 BVToon / @BVan」不再出现。")
    print("[BV-Toon]     而且校验不过时**画面本身也会被损毁**（像素化+压色）："
          "这是**唯一档位**，面板上没有可放宽的选项。")
    print("[BV-Toon]     正版 zip 里一定带 %s；这个副本没有或对不上。"
          % bv_integrity.MANIFEST_REL)
    print("[BV-Toon]     自己改了代码想恢复正常水印：重跑 tools/install_bv_toon.py，"
          "或用 tools/package_bv_toon.py 重新打包（都会重算清单）。")
    print("[BV-Toon]     GPL v3 允许修改与再分发；这里只做标记，不阻止渲染。")
    print(bar)


def apply_watermark_style(render, report, scene):
    """按完整性状态定水印样式。只在这里定义一次，一键卡渲与 render_pre 共用。

    * 正常：白字、字号 18、默认 85% 透明、无底框（面板上的不透明度可调）
    * 异常：红字、字号 24、**不透明** + 半透明黑底 —— 要让人一眼看到，不能糊掉
    """
    if report["state"] == bv_integrity.STATE_OK:
        render.stamp_font_size = 18
        render.stamp_foreground = (1.0, 1.0, 1.0,
                                   float(scene.get("bv_credit_alpha", 0.15)))
        render.stamp_background = (0.0, 0.0, 0.0, 0.0)
    else:
        render.stamp_font_size = 24
        render.stamp_foreground = (1.0, 0.30, 0.24, 1.0)
        render.stamp_background = (0.0, 0.0, 0.0, 0.62)


def integrity_warning(layout, context):
    """面板顶部的告警块（只在异常状态出现）。面板绘制不许抛异常。"""
    try:
        report = bv_integrity.verify()
        if report["state"] == bv_integrity.STATE_OK:
            return
        box = layout.box()
        try:
            box.alert = True
        except Exception as error:              # 老版本没有 alert 也不该挡住面板
            print("[BV-Toon] 面板告警配色失败：%s" % error)
        box.label(text=report["credit"], icon="ERROR")
        box.label(text=report["reason"][:110])
        box.label(text="损毁是唯一档位（被改或未验证都损毁），没有可放宽的选项")
        box.label(text="重装正版 zip，或重跑 tools/install_bv_toon.py 重算清单")
    except Exception as error:
        print("[BV-Toon] 完整性提示绘制失败：%s" % error)


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
        # 画面板时再补挂一次（工厂重置/重载之后，只要有人看过面板就恢复强制署名）
        mount_watermark_handler()
        # 完整性：只要不是正常状态就在最上面报警（这里重新查一次，代价只有几次 stat）
        integrity_warning(layout, context)
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
        row.prop(context.scene, '["bv_stamp_on"]', text="烧录署名")
        row.prop(context.scene, '["bv_credit_text"]', text="")
        row.prop(context.scene, '["bv_credit_alpha"]', text="不透明度")
        row = box2.row(align=True)
        row.label(text="使用条款", icon='INFO')
        row.operator("bvtoon.terms_zh", text="中文")
        row.operator("bvtoon.terms_en", text="EN")
        row.operator("bvtoon.terms_ja", text="日本語")
        row = box2.row(align=True)
        # 「还原成基本材质」已按要求去掉：原节点现在直接删除，不再保留
        # 损毁**没有档位可选**（永远最严格），所以这里只写一行说明，连下拉框都没有
        row.label(text="损毁：被改或未验证都损毁（唯一档位，无选项）", icon="LOCKED")
        row = box2.row(align=True)
        row.prop(context.scene, '["bv_edge_scale"]', text="描边粗细")
        row.operator("bvtoon.set_edge_width", text="应用", icon="CHECKMARK")
        layout.label(text="维护：BVan / DEEPSEEK · BVToon %s" % _VERSION)


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
        # 删掉 mmd_tools 原来那套节点，材质树只留卡渲自己的
        dropped = sum(bv_materials.drop_other_nodes(mat) for mat in edge_mats)
        print("[BV-Toon] 已删除非卡渲节点 %d 个（材质树只剩 bv_* 与输出）" % dropped)
        bv_materials.apply_edge_preview(edge_mats, thickness=float(scene["bv_edge_scale"]))
        # 色彩管理：视图变换改成「标准」—— AgX/Filmic 会把卡渲的颜色洗淡、明暗压平
        try:
            scene = context.scene
            scene.view_settings.view_transform = "Standard"
            scene.view_settings.look = "None"
            print("[BV-Toon] 视图变换 -> 标准")
        except Exception as error:
            print("[BV-Toon] 视图变换设置失败：%s" % error)

        # 署名：把「渲染 BVToon / @BVan」烧进图片（stamp note）+ 写进元数据 —— 别人裁掉水印，元数据还在
        try:
            if context.scene.get("bv_stamp_on", True):
                # 水印文字由完整性状态决定：正常用面板那行，被改过的副本一律换成警告文字
                report = bv_integrity.verify()
                note = bv_integrity.credit_text(
                    report, context.scene.get("bv_credit_text", DEFAULT_CREDIT))
                if note in ("渲染：BVan", "BVToon", "BVToon / @BVan"):   # 旧默认值迁移成新的
                    note = DEFAULT_CREDIT
                    context.scene["bv_credit_text"] = note
                if report["state"] != bv_integrity.STATE_OK:
                    print("[BV-Toon] [!] 完整性校验未通过（%s），署名强制为「%s」"
                          % (report["state"], note))
                context.scene.render.use_stamp = True
                context.scene.render.use_stamp_note = True
                # 只留署名：Blender 的 stamp 是一整块，file/date/render time/timecode/scene/
                # frame/camera… 这些子项各自还开着，必须逐个关掉（否则图上全是标签）
                for prop in _OTHER_STAMP_PROPS:
                    if not hasattr(context.scene.render, prop):
                        continue
                    try:
                        setattr(context.scene.render, prop, False)
                    except Exception as error:
                        print("[BV-Toon] 关闭 %s 失败：%s" % (prop, error))
                context.scene.render.stamp_note_text = note
                apply_watermark_style(context.scene.render, report, context.scene)
                print("[BV-Toon] 已烧录署名：%s" % note)
        except Exception as error:
            print("[BV-Toon] 署名设置失败：%s" % error)
        if not context.scene.get("bv_credit_notice_shown", False):
            context.scene["bv_credit_notice_shown"] = True
            self.report({"INFO"}, "发布作品请署名：模型：<作者>（<链接>）/ 渲染：BVan"
                                  "（面板「署名文字」可改）")
        message = "已一键卡渲：%s" % "、".join(done)
        if skipped:
            message += "；跳过 %s" % "、".join(skipped)
        self.report({"INFO"}, message)
        print("[BV-Toon] %s" % message)
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
        # 泛光是吃"绝对亮度"的：不按模型实测调强度的话，深色角色几乎不发光
        # （实测胡桃的泛光只有奥黛塔的 1/7）。这里渲两张 96×96 量一下再定强度。
        strength, why = bv_glow.apply_strength(context.scene)
        context.scene["bv_glow_strength"] = strength
        context.scene["bv_glow_note"] = why
        self.report({"INFO"},
                    "泛光已添加（强度 %.2f）：%s；合成器里的节点可调 强度/阈值/大小/外发光/增益"
                    % (strength, why))
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
    # 损毁**没有设置项**：唯一档位（被改或未验证都损毁），所以不注册任何属性
    print("[BVToon] v%s 已启用：面板在 3D 视图 N → 卡渲" % _VERSION)
    report_integrity(INTEGRITY)
    # 重新启用也要挂上：Blender 重启用插件时不会重跑模块顶层代码
    mount_watermark_handler()


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.bv_mode
    # 卸载时把处理器摘掉：它带 persistent 标记，插件关了还挂着就太脏了
    for handler in list(bpy.app.handlers.render_pre):
        if getattr(handler, "__name__", "") == "force_watermark":
            try:
                bpy.app.handlers.render_pre.remove(handler)
            except Exception as error:
                print("[BV-Toon] 摘除 render_pre 失败：%s" % error)


if __name__ == "__main__":
    register()


def mount_watermark_handler():
    """把强制署名挂到 render_pre（按名字去重，重复调用安全）。

    **每次 register() 都要调用**：Blender 重新启用插件时不会再跑一遍模块顶层代码
    （模块已经在 sys.modules 里了），所以只靠文件末尾那一句，重新启用后就挂不上了 ——
    实测就是这样静默丢掉强制署名的。
    """
    try:
        current = [handler for handler in bpy.app.handlers.render_pre
                   if getattr(handler, "__name__", "") == "force_watermark"]
        if len(current) == 1 and current[0] is force_watermark:
            return                          # 已经挂好了，别重复也别刷屏
        for handler in current:             # 重载脚本留下的旧函数对象，换掉
            try:
                bpy.app.handlers.render_pre.remove(handler)
            except Exception as error:
                print("[BV-Toon] 摘除旧的 render_pre 处理器失败：%s" % error)
        bpy.app.handlers.render_pre.append(force_watermark)
        print("[BV-Toon] 渲染前强制署名已挂上（render_pre，persistent）")
    except Exception as error:
        print("[BV-Toon] 挂载 render_pre 失败：%s" % error)


# ---------------------------------------------------------------------------
# 强制水印：按下渲染的一瞬间再设一次，谁也绕不过
# ---------------------------------------------------------------------------

def _persistent(function):
    """让处理器活过"工厂重置 / 重载启动文件"—— 那些操作会**清空** `bpy.app.handlers`。

    实测（2026-09-18）：一次 `bpy.ops.wm.read_factory_settings()` 之后
    `bpy.app.handlers.render_pre` 就是空列表了，而"面板绘制时补挂"只在**有人打开
    Toon 面板**时才发生 —— 后台渲染根本没有面板可画，强制署名于是静默失效。
    加上这个装饰器，处理器在文件加载后仍然在列表里。
    """
    persistent = getattr(bpy.app.handlers, "persistent", None)
    if persistent is None:                  # 老 Blender 没有这个 API：说清楚，别静默
        print("[BV-Toon] 这个 Blender 没有 bpy.app.handlers.persistent；"
              "强制署名处理器活不过工厂重置（打开 Toon 面板时会补挂）")
        return function
    return persistent(function)


@_persistent
def force_watermark(scene=None, *args, **kwargs):
    """渲染前强制打开署名水印（只留署名一项）。

    同时**重新校验一次完整性**：水印文字与样式都由校验结果决定 —— 被改过的副本
    想印「渲染 BVToon / @BVan」也印不出来。
    """
    try:
        if __name__ not in bpy.context.preferences.addons:
            return                      # 插件没启用就不管
        target = scene if scene is not None else bpy.context.scene
        if target is None or getattr(target, "render", None) is None:
            # 静默 return 是这项目最大的坑（HANDOFF 第 1 条）：拿不到场景就说出来
            print("[BV-Toon] 渲染前强制署名跳过：拿不到 scene（scene=%r）" % (target,))
            return
        render = target.render
        report = bv_integrity.verify()
        note = bv_integrity.credit_text(
            report, target.get("bv_credit_text", DEFAULT_CREDIT))
        render.use_stamp = True
        render.use_stamp_note = True
        render.stamp_note_text = note
        apply_watermark_style(render, report, target)
        for prop in _OTHER_STAMP_PROPS:
            if hasattr(render, prop):
                setattr(render, prop, False)
        print("[BV-Toon] 渲染前已强制署名：%s（完整性：%s）"
              % (render.stamp_note_text, report["state"]))
        # 校验不过就把画面本身弄坏（唯一档位：被改和未验证都损毁，没有可放宽的选项）
        try:
            print("[BV-Toon] 画面损毁：%s" % bv_damage.enforce(target, report))
        except Exception as error:
            print("[BV-Toon] 损毁处理失败：%s" % error)
        if report["state"] != bv_integrity.STATE_OK:
            print("[BV-Toon]     原因：%s" % report["reason"])
    except Exception as error:
        print("[BV-Toon] 强制署名失败：%s" % error)


# 注册（按名字去重，重载脚本也不会叠加）。注意：bpy.app.handlers 的列表不支持切片赋值 ✗
mount_watermark_handler()

# ---------------------------------------------------------------------------
# 使用条款（中 / 英 / 日）与面板上的语言切换按钮
# ---------------------------------------------------------------------------

TERMS = {
    "zh": ("使用条款（中文） —— BV-Toon %s" % _VERSION,
           "1. 本插件以 GNU GPL v3 发布：可自由使用、修改、再分发（含商用）。",
           "2. 前提：再分发或发布修改版时，必须同样以 GPL v3 开源。",
           "3. 附加条款（§7）：必须保留署名 BVToon / @BVan，不得歪曲来源。",
           "4. 发布作品时请注明「渲染 BVToon / @BVan」。",
           "5. 插件会核对自身文件的哈希：被改过的副本渲染时自动带「未授权修改版」水印，"
           "没有清单的副本带「未验证副本」（只做标记，不限制修改与再分发）。",
           "6. 无担保。",
           "完整条款见插件目录 LICENSE 文件。"),
    "en": ("Terms of Use (English) — BV-Toon %s" % _VERSION,
           "1. Released under GNU GPL v3: free to use, modify and redistribute (incl. commercial).",
           "2. Copyleft: redistributions and modified versions must stay GPL v3.",
           "3. Section 7 terms: keep the credit BVToon / @BVan and do not misrepresent origin.",
           "4. Credit produced works as \"渲染 BVToon / @BVan\".",
           "5. The add-on checks the hashes of its own files: a modified copy renders with an"
           " \"UNAUTHORIZED MODIFIED COPY\" watermark, a copy with no manifest with"
           " \"UNVERIFIED COPY\" (a marking only; modification and redistribution stay free).",
           "6. No warranty.",
           "Full text in the LICENSE file next to the add-on."),
    "ja": ("利用規約（日本語） — BV-Toon %s" % _VERSION,
           "1. GNU GPL v3 で公開：使用・改変・再配布は自由（商用含む）。",
           "2. コピーレフト：再配布・改変版の公開時も GPL v3 を維持してください。",
           "3. 第 7 条の追加条項：署名 BVToon / @BVan の保持、出所の偽装禁止。",
           "4. 制作物の公開時は「渲染 BVToon / @BVan」と明記してください。",
           "5. 本アドオンは自身のファイルをハッシュ照合します：改変された副本は"
           "「未授权修改版」、マニフェストが無い副本は「未验证副本」の透かしが入ります"
           "（表示のみで、改変・再配布は制限しません）。",
           "6. 無保証。",
           "全文はアドオン同梱の LICENSE ファイルをご覧ください。"),
}

TERMS_CLASSES = []


def _make_terms_operator(code, title):
    class _Terms(bpy.types.Operator):
        bl_idname = "bvtoon.terms_%s" % code
        bl_label = title
        bl_description = "使用条款 / Terms of use / 利用規約"

        def invoke(self, context, event):
            return context.window_manager.invoke_popup(self, width=620)

        def draw(self, context):
            for line in TERMS[code]:
                self.layout.label(text=line)

        def execute(self, context):
            return {"FINISHED"}

    _Terms.__name__ = "BVTOON_OT_terms_" + code
    return _Terms


for _code, _title in (("zh", "使用条款 中文"), ("en", "Terms English"),
                      ("ja", "利用規約 日本語")):
    TERMS_CLASSES.append(_make_terms_operator(_code, _title))

# 注册（按 idname 去重，重载脚本不会重复注册）
for _cls in TERMS_CLASSES:
    try:
        if not hasattr(bpy.types, _cls.__name__):
            bpy.utils.register_class(_cls)
    except Exception as _error:
        print("[BV-Toon] 注册条款按钮失败：%s" % _error)