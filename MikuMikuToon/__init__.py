# -*- coding: utf-8 -*-
"""MikuMikuToon -- 给 MMD 模型用的 Blender 卡渲插件。

从零写的：卡渲节点组、泛光、目影全部由本插件自己生成（Python 建节点），
**不加载、不依赖任何第三方插件的节点组或资源文件**；只读 mmd_tools 暴露的
``mmd_material`` 属性（贴图相对路径、球面模式、透明度、描边参数）来了解模型，
所以原作者的材质数据一个字节都不会被删掉。

面板（3D 视图 → N → Toon）：

    卡渲          模式 + 一键卡渲 + 按模型自适应曝光
    泛光          添加/移除 + 游戏预设（可折叠）
    其它设置      描边粗细/颜色、目影、加算球面强度

完整性（哈希防盗，见 ``mmt_integrity.py``）：打包时生成一份 SHA-256 清单随 zip
发出，加载时与每次渲染前核对。副本被改过 ⇒ 水印换成「未授权修改版」；没有清单
⇒「未验证副本」。只标记、只警告，**不阻止渲染**（GPL v3 允许修改）。

© 2025 BVan / DEEPSEEK
"""

bl_info = {
    "name": "MikuMikuToon",
    "author": "BVan / DEEPSEEK",
    "version": (1, 10, 1),
    # 最低 4.3：节点组接口走 ``tree.interface`` / ``interface.new_socket()``，更早没有
    "blender": (4, 3, 0),
    "location": "3D视图 > N 面板 > Toon",
    "description": "MMD 模型一键卡渲：原生读取材质、一键套用、边缘预览、目影、泛光、强制署名水印。",
    "category": "Material",
    "support": "COMMUNITY",
}

import bpy

from . import mmt_compat
from . import mmt_damage
from . import mmt_glow
from . import mmt_integrity
from . import mmt_materials
from . import mmt_shading
from . import mmt_util

#: 版本号只从 bl_info 取一次
_VERSION = ".".join(str(part) for part in bl_info["version"])

#: 正常副本的署名；异常副本一律换成警告文字
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

#: 加载时查一次；渲染前由 force_watermark 再查（带 mtime 缓存）
INTEGRITY = mmt_integrity.verify()


def report_integrity(report):
    """把校验结果打到控制台：正常一行，异常一大块。"""
    if report["state"] == mmt_integrity.STATE_OK:
        print("[MikuMikuToon] 完整性校验通过：%s" % report["reason"])
        return
    bar = "=" * 70
    print(bar)
    print("[MikuMikuToon] [!] 完整性校验未通过：%s" % report["credit"])
    print("[MikuMikuToon]     原因：%s" % report["reason"])
    print("[MikuMikuToon]     渲染水印会被强制改成上面那行字，"
          "「渲染 BVToon / @BVan」不再出现。")
    print("[MikuMikuToon]     校验不过时**画面本身也会被损毁**（像素化+压色）："
          "唯一档位，没有可放宽的选项。")
    print("[MikuMikuToon]     正版 zip 里一定带 %s；这个副本没有或对不上。"
          % mmt_integrity.MANIFEST_REL)
    print("[MikuMikuToon]     自己改了代码想恢复正常水印：重跑 tools/install_mmt_toon.py，"
          "或用 tools/package_mmt_toon.py 重新打包（都会重算清单）。")
    print("[MikuMikuToon]     GPL v3 允许修改与再分发；这里只做标记，不阻止渲染。")
    print(bar)


#: 正常态水印的不透明度（85% 透明），固定值
CREDIT_ALPHA = 0.15


# ---------------------------------------------------------------------------
# 注册辅助：可重复调用、逐项兜底、不许半途炸
# ---------------------------------------------------------------------------
# 逐项 try/except + 先查 `hasattr(bpy.types, ...)`：Blender 重新启用插件时不会再跑
# 模块顶层代码，而是直接再调一次 register()，重复注册同一个类会抛
# `ValueError: already registered as a subclass`。没有逐项兜底的话，排在出错项后面的
# 类（含面板）就再也注册不上 —— 偏好里显示"已启用"，侧栏里却没有面板。
# 面板 draw() 里只要有一个控件画不出来，整块面板就没了，所以每个控件都过 `_prop()`。

#: 当前 Blender 版本（元组）
BLENDER_VERSION = mmt_compat.BLENDER_VERSION


def _has(obj, name):
    """属性/方法存在吗（不给 Blender 抛异常的机会）。"""
    try:
        return hasattr(obj, name)
    except Exception:
        return False


def _set(obj, name, value):
    """安全写属性：写不了打日志就算了，绝不让调用方崩。"""
    try:
        setattr(obj, name, value)
        return True
    except Exception as error:
        print("[MikuMikuToon] 写 %s 失败（跳过）：%s" % (name, error))
        return False


def _prop(layout, holder, name, **kwargs):
    """安全画一个属性控件：属性不存在就跳过这一行，绝不让整个面板消失。"""
    if not _has(holder, name) and not (hasattr(holder, "get") and name in holder):
        return False
    try:
        layout.prop(holder, name, **kwargs)
        return True
    except Exception as error:
        print("[MikuMikuToon] 画控件 %s 失败（跳过这一行）：%s" % (name, error))
        return False


def apply_watermark_style(render, report, scene=None):
    """按完整性状态定水印样式（一键卡渲与 render_pre 共用）。

    正常：白字 18 号、固定 85% 透明、无底框；异常：红字 24 号、不透明 + 黑底。
    ``scene`` 只是兼容老调用，样式已不由场景属性决定。
    """
    if report["state"] == mmt_integrity.STATE_OK:
        render.stamp_font_size = 18
        render.stamp_foreground = (1.0, 1.0, 1.0, CREDIT_ALPHA)
        render.stamp_background = (0.0, 0.0, 0.0, 0.0)
    else:
        render.stamp_font_size = 24
        render.stamp_foreground = (1.0, 0.30, 0.24, 1.0)
        render.stamp_background = (0.0, 0.0, 0.0, 0.62)


def integrity_warning(layout, context):
    """面板顶部的告警块（只在异常状态出现）。绘制过程不许抛。"""
    try:
        report = mmt_integrity.verify()
        if report["state"] == mmt_integrity.STATE_OK:
            return
        box = layout.box()
        try:
            box.alert = True
        except Exception as error:              # 老版本没有 alert 也不该挡住面板
            print("[MikuMikuToon] 面板告警配色失败：%s" % error)
        box.label(text=report["credit"], icon="ERROR")
        box.label(text=report["reason"][:110])
        box.label(text="损毁是唯一档位（被改或未验证都损毁），没有可放宽的选项")
        box.label(text="重装正版 zip，或重跑 tools/install_mmt_toon.py 重算清单")
    except Exception as error:
        print("[MikuMikuToon] 完整性提示绘制失败：%s" % error)


# ---------------------------------------------------------------------------
# 面板
# ---------------------------------------------------------------------------

class MIKUMIKUTOON_PT_panel(bpy.types.Panel):
    bl_label = "MikuMikuToon 卡渲"
    bl_idname = "MIKUMIKUTOON_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Toon'

    def draw(self, context):
        # 兜底：面板宁可少画几个控件，也绝不能整块消失
        try:
            _panel_body(self, context)
        except Exception as error:
            import traceback
            print("[MikuMikuToon] 面板绘制出错（已兜住，面板不会消失）：%s" % error)
            traceback.print_exc()
            try:
                self.layout.label(text="MikuMikuToon：面板绘制出错，详见控制台", icon="ERROR")
            except Exception:
                pass   # 兜底失败也不能再抛，否则面板整块没了


def _panel_body(self, context):
    """面板正文。做成模块级函数，审计里用假对象也能直接调。"""
    layout = self.layout
    # 补挂一次：工厂重置/重载之后，只要有人看过面板就恢复强制署名
    try:
        mount_watermark_handler()
    except Exception as error:
        print("[MikuMikuToon] 面板里补挂署名处理器失败：%s" % error)
    integrity_warning(layout, context)
    box = layout.box()
    box.label(text="MikuMikuToon 一键卡渲", icon='SHADERFX')
    _prop(box, context.scene, "mmt_mode", text="")
    row = box.row(align=True)
    row.scale_y = 1.5
    row.operator("mikumikutoon.one_click", text="一键卡渲", icon="PLAY")
    box.row(align=True).label(text="卡渲 + 边缘预览，一次点完", icon="INFO")
    # 亮色材质在平涂下会被削成一片白，这里按模型自动压亮度
    _prop(box.row(align=True), context.scene, "mmt_auto_exposure",
          text="按模型自适应曝光（亮部不削顶）")

    glow_box = layout.box()
    glow_box.label(text="泛光", icon='LIGHT')
    row = glow_box.row(align=True)
    row.scale_y = 1.2
    row.operator("mikumikutoon.add_glow", text="添加泛光", icon="LIGHT")
    row.operator("mikumikutoon.remove_glow", text="", icon='TRASH')
    # glow_state 只查节点、不建树不写场景 —— draw 必须只读
    has_glow = False
    try:
        has_glow = bool(mmt_glow.glow_state(context.scene)[0])
    except Exception:
        has_glow = False        # 这里绝不能抛：一抛，下面的行就全画不出来
    if has_glow:
        opened = bool(context.scene.mmt_glow_presets_open)
        row = glow_box.row(align=True)
        _prop(row, context.scene, "mmt_glow_presets_open", text="游戏泛光预设",
                 icon="TRIA_DOWN" if opened else "TRIA_RIGHT", emboss=False)
        current = context.scene.get("mmt_glow_look")
        if current:
            row.label(text="当前：%s" % current, icon="CHECKMARK")
        if opened:
            inner = glow_box.box()      # 再套一层：底色深一档，表示这是展开部分
            row = inner.row(align=True)
            row.scale_y = 1.4
            for name in mmt_glow.look_names():
                row.operator("mikumikutoon.glow_look", text=name).look = name
            # 预设强度定在"有光照"的管线里，我们全自发光，照搬会把画面糊掉
            row = inner.row(align=True)
            _prop(row, context.scene, "mmt_glow_tame", text="按模型收力（推荐）")
            for name, values in mmt_glow.LOOKS:
                inner.label(text="%s：强度 %.2f ｜ 阈值 %.2f ｜ 大小 %.0f ｜ 外发光 %.2f ｜ 增益 %.0f"
                            % (name, values["强度"], values["阈值"], values["大小"],
                               values["外发光"], values["增益"]))
    else:
        glow_box.row(align=True).label(
            text="点「添加泛光」后，这里会出现各游戏的泛光预设", icon="INFO")

    # ---- 其它设置：描边 + 目影 ----
    layout.label(text="其它设置")
    box_settings = layout.box()
    row = box_settings.row(align=True)
    # ⚠️ draw() 里一个字节都不能写场景：受限上下文禁止写 ID，写了就抛，
    # 而一抛，这一行下面的控件就全画不出来
    _prop(row, context.scene, "mmt_edge_scale", text="描边粗细")
    row.operator("mikumikutoon.set_edge_width", text="应用", icon="CHECKMARK")
    row = box_settings.row(align=True)
    row.operator("mikumikutoon.set_eye_shadow", text="设置目影", icon="HIDE_OFF")
    row = box_settings.row(align=True)
    _prop(row, context.scene, "mmt_edge_use_color", text="统一描边颜色")
    sub = row.row(align=True)
    sub.enabled = bool(context.scene.mmt_edge_use_color)
    _prop(sub, context.scene, "mmt_edge_color", text="")
    # MMD 球面模式 2（闪粉/金属/水钻）那一层的强度，1.00 = 与 MMD 同强度
    row = box_settings.row(align=True)
    _prop(row, context.scene, "mmt_sphere_add", text="加算球面强度")
    row.operator("mikumikutoon.set_sphere_add", text="应用", icon="CHECKMARK")


# 选材质的工具（target_objects / target_materials / edge_colour）在 mmt_util 里


# ---------------------------------------------------------------------------
# 操作符
# ---------------------------------------------------------------------------

class MIKUMIKUTOON_OT_apply_preset(bpy.types.Operator):
    """把卡渲预设套到 MMD 材质上（原生读 mmd_material，不做破坏性转换）"""
    bl_idname = "mikumikutoon.apply_preset"
    bl_label = "应用卡渲预设"
    bl_options = {"REGISTER", "UNDO"}

    preset_index: bpy.props.IntProperty(default=0)

    def execute(self, context):
        materials = mmt_util.target_materials(context)
        if not materials:
            self.report({"ERROR"}, "先选中 MMD 模型（物体模式），或者把模式切到单个材质")
            return {"CANCELLED"}
        report = []
        done = sum(1 for mat in materials
                   if mmt_materials.apply_preset(mat, self.preset_index,
                                                report=report))
        name = mmt_shading.preset_names()[self.preset_index] \
            if 0 <= self.preset_index < len(mmt_shading.preset_names()) else "?"
        self.report({"INFO"}, "已套用「%s」：%d 个材质" % (name, done))
        for line in report:
            print("[MikuMikuToon]", line)
        return {"FINISHED"}


class MIKUMIKUTOON_OT_one_click(bpy.types.Operator):
    """一键卡渲：套卡渲预设 → MMD 边缘预览 → MMD 设置目影"""
    bl_idname = "mikumikutoon.one_click"
    bl_label = "一键卡渲"
    bl_description = ("一次点完：读 MMD 原生材质套卡渲预设、生成 MMD 边缘预览。"
                      "失败的一步会单独提示，不影响其它步骤")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if not mmt_util.target_objects(context):
            self.report({"ERROR"}, "先选中 MMD 模型（物体模式），或者把模式切到单个材质")
            return {"CANCELLED"}
        steps = (
            ("卡渲", lambda: bpy.ops.mikumikutoon.apply_preset(preset_index=0)),
            ("边缘预览", lambda: bpy.ops.mikumikutoon.edge_preview_create()),
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
        # 材质自带的描边色/粗细（MMD 的 edge_color / edge_weight）
        targets = mmt_util.target_objects(context)
        edge_mats = mmt_util.target_materials(context) or [
            slot.material for obj in targets
            for slot in obj.material_slots if slot.material is not None]
        scene = context.scene
        # 删掉 mmd_tools 原来那套节点，材质树只留卡渲自己的
        dropped = sum(mmt_materials.drop_other_nodes(mat) for mat in edge_mats)
        print("[MikuMikuToon] 已删除非卡渲节点 %d 个（材质树只剩 mmt_* 与输出）" % dropped)
        mmt_materials.apply_edge_preview(edge_mats, thickness=float(scene.mmt_edge_scale),
                                        colour=mmt_util.edge_colour(scene), objects=targets)
        # 视图变换改「标准」：AgX/Filmic 会把卡渲的颜色洗淡、明暗压平
        try:
            scene.view_settings.view_transform = "Standard"
            scene.view_settings.look = "None"
            print("[MikuMikuToon] 视图变换 -> 标准")
        except Exception as error:
            print("[MikuMikuToon] 视图变换设置失败：%s" % error)

        # 自适应曝光：严重削顶时压「亮度」，正常模型不动。
        # ⚠️ 必须在视图变换设成标准之后量：AgX/Filmic 会把高光压下来，
        # 在它下面量永远是"爆白 0%"
        if scene.mmt_auto_exposure:
            try:
                value, why = mmt_materials.auto_exposure(scene)
                if value is not None:
                    self.report({"INFO"}, "自适应曝光：%s" % why)
                    print("[MikuMikuToon] 自适应曝光：%s" % why)
            except Exception as error:
                print("[MikuMikuToon] 自适应曝光失败：%s" % error)

        # 署名强制执行：没有开关，也不能改文字
        try:
            # 水印文字由完整性状态决定，被改过的副本一律换成警告文字
            report = mmt_integrity.verify()
            note = mmt_integrity.credit_text(report, DEFAULT_CREDIT)
            if report["state"] != mmt_integrity.STATE_OK:
                print("[MikuMikuToon] [!] 完整性校验未通过（%s），署名强制为「%s」"
                      % (report["state"], note))
            render = context.scene.render
            render.use_stamp = True
            render.use_stamp_note = True
            # Blender 的 stamp 是一整块，别的子项得逐个关掉，否则图上全是标签
            for prop in _OTHER_STAMP_PROPS:
                if not hasattr(render, prop):
                    continue
                try:
                    setattr(render, prop, False)
                except Exception as error:
                    print("[MikuMikuToon] 关闭 %s 失败：%s" % (prop, error))
            render.stamp_note_text = note
            apply_watermark_style(render, report)
            print("[MikuMikuToon] 已烧录署名（强制）：%s" % note)
        except Exception as error:
            print("[MikuMikuToon] 署名设置失败：%s" % error)
        if not context.scene.mmt_credit_notice_shown:
            context.scene.mmt_credit_notice_shown = True
            self.report({"INFO"}, "作品上会强制烧录署名「%s」（不可关闭）"
                        % DEFAULT_CREDIT)
        message = "已一键卡渲：%s" % "、".join(done)
        if skipped:
            message += "；跳过 %s" % "、".join(skipped)
        self.report({"INFO"}, message)
        print("[MikuMikuToon] %s" % message)
        return {"FINISHED"}


class MIKUMIKUTOON_OT_set_eye_shadow(bpy.types.Operator):
    """把「目影」材质设成纯黑半透明"""
    bl_idname = "mikumikutoon.set_eye_shadow"
    bl_label = "MMD 设置目影"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        targets = [slot.material for obj in mmt_util.target_objects(context)
                   for slot in obj.material_slots
                   if slot.material is not None
                   and mmt_materials.is_eye_shadow(slot.material)]
        if not targets:
            self.report({"WARNING"}, "没找到名字里带「目影」的材质")
            return {"CANCELLED"}
        for mat in targets:
            mmt_materials.set_eye_shadow(mat)
        self.report({"INFO"}, "目影材质已设置：%d 个" % len(targets))
        return {"FINISHED"}


class MIKUMIKUTOON_OT_edge_preview_create(bpy.types.Operator):
    """MMD 边缘预览（转给 mmd_tools）"""
    bl_idname = "mikumikutoon.edge_preview_create"
    bl_label = "MMD 边缘预览"

    def execute(self, context):
        try:
            bpy.ops.mmd_tools.edge_preview_setup(action='CREATE')
        except Exception:
            self.report({"ERROR"}, "需要物体模式、选中 MMD 模型，并启用 MMD Tools")
            return {"CANCELLED"}
        return {"FINISHED"}


class MIKUMIKUTOON_OT_edge_preview_clean(bpy.types.Operator):
    """删除边缘预览"""
    bl_idname = "mikumikutoon.edge_preview_clean"
    bl_label = "删除边缘预览"

    def execute(self, context):
        try:
            bpy.ops.mmd_tools.edge_preview_setup(action='CLEAN')
        except Exception:
            self.report({"ERROR"}, "需要物体模式、选中 MMD 模型，并启用 MMD Tools")
            return {"CANCELLED"}
        return {"FINISHED"}


class MIKUMIKUTOON_OT_add_glow(bpy.types.Operator):
    """给场景加一层自发光驱动的朦胧泛光（合成器，可随时移除）"""
    bl_idname = "mikumikutoon.add_glow"
    bl_label = "添加泛光"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if not mmt_glow.insert_glow(context.scene):
            self.report({"ERROR"}, "无法建立合成器节点树")
            return {"CANCELLED"}
        # 泛光吃的是"绝对亮度"：不按模型调强度的话深色角色几乎不发光。
        # 这里渲两张小图量一下剪影外的光再定强度。
        strength, why = mmt_glow.apply_strength(context.scene)
        context.scene["mmt_glow_strength"] = strength
        context.scene["mmt_glow_note"] = why
        self.report({"INFO"},
                    "泛光已添加（强度 %.2f）：%s；合成器里的节点可调 强度/阈值/大小/外发光/增益"
                    % (strength, why))
        return {"FINISHED"}


class MIKUMIKUTOON_OT_glow_look(bpy.types.Operator):
    """把泛光调成某个游戏的看家参数（场景里还没有泛光就先加一层）"""
    bl_idname = "mikumikutoon.glow_look"
    bl_label = "套用泛光预设"
    bl_options = {"REGISTER", "UNDO"}

    look: bpy.props.StringProperty(default="")

    def execute(self, context):
        name = self.look or (mmt_glow.look_names() or [""])[0]
        tame = bool(context.scene.mmt_glow_tame)      # 「按模型收力」默认开
        ok, why = mmt_glow.apply_look(context.scene, name, tame=tame)
        if not ok:
            self.report({"ERROR"}, why)
            return {"CANCELLED"}
        self.report({"INFO"}, "泛光已套用 %s" % why)
        return {"FINISHED"}


class MIKUMIKUTOON_OT_remove_glow(bpy.types.Operator):
    """移除泛光，其余合成器节点保持不动"""
    bl_idname = "mikumikutoon.remove_glow"
    bl_label = "移除泛光"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if not mmt_glow.remove_glow(context.scene):
            self.report({"WARNING"}, "场景里没有泛光节点")
            return {"CANCELLED"}
        # 泛光没了，预设那一行会跟着隐藏；顺手清掉"当前预设"和展开状态，
        # 免得再加泛光时显示上一次的旧信息
        for name, value in (("mmt_glow_look", None),
                            ("mmt_glow_presets_open", False)):
            try:
                if name in context.scene:
                    del context.scene[name]
                elif hasattr(context.scene, name):
                    setattr(context.scene, name, value)
            except Exception as error:
                print("[MikuMikuToon] 清 %s 失败：%s" % (name, error))
        return {"FINISHED"}


class MIKUMIKUTOON_OT_set_edge_width(bpy.types.Operator):
    """按面板上的「描边粗细 / 统一描边颜色」重新套一次描边（不用重跑一键卡渲）"""
    bl_idname = "mikumikutoon.set_edge_width"
    bl_label = "应用描边设置"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        scale = float(scene.mmt_edge_scale)
        colour = mmt_util.edge_colour(scene)
        targets = mmt_util.target_objects(context)
        materials = mmt_util.target_materials(context) or [
            slot.material for obj in targets
            for slot in obj.material_slots if slot.material is not None]
        if not materials:
            self.report({"ERROR"}, "先选中模型")
            return {"CANCELLED"}
        mmt_materials.apply_edge_preview(materials, thickness=scale, colour=colour,
                                         objects=targets)
        self.report({"INFO"}, "描边已重套：粗细 %.2f ｜颜色 %s"
                    % (scale, "统一 %s" % (tuple(round(v, 3) for v in colour),)
                       if colour else "用模型自带的"))
        return {"FINISHED"}


class MIKUMIKUTOON_OT_set_sphere_add(bpy.types.Operator):
    """按面板上的「加算球面强度」重设 MMD 球面模式 2 那一层（不用重跑一键卡渲）"""
    bl_idname = "mikumikutoon.set_sphere_add"
    bl_label = "应用加算球面强度"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        value = float(context.scene.mmt_sphere_add)
        materials = mmt_util.target_materials(context) or [
            slot.material for obj in mmt_util.target_objects(context)
            for slot in obj.material_slots if slot.material is not None]
        if not materials:
            self.report({"ERROR"}, "先选中模型")
            return {"CANCELLED"}
        done = sum(1 for mat in materials
                   if mmt_util.set_sphere_strength(mat, value))
        self.report({"INFO"}, "加算球面强度已设为 ×%.2f：%d 个材质" % (value, done))
        print("[MikuMikuToon] 加算球面强度 ×%.2f 应用到 %d 个材质" % (value, done))
        return {"FINISHED"}


class MIKUMIKUTOON_OT_selfcheck(bpy.types.Operator):
    """把插件自检报告打到控制台。

    面板上没有按钮，需要时在 Python 控制台敲 ``bpy.ops.mikumikutoon.selfcheck()``。
    """
    bl_idname = "mikumikutoon.selfcheck"
    bl_label = "打印自检报告"
    bl_description = ("检查面板 / 操作符 / 场景属性 / 署名处理器是否都在，"
                      "并把完整报告打到系统控制台")
    bl_options = {"REGISTER"}

    def execute(self, context):
        ok = report_registration(force=True)      # 强制打完整块，不管正常与否
        if ok:
            self.report({"INFO"}, "自检全部正常；完整报告已打到系统控制台")
        else:
            self.report({"WARNING"},
                        "自检发现问题；完整报告已打到系统控制台（窗口 → 切换系统控制台）")
        return {"FINISHED"}


CLASSES = (
    MIKUMIKUTOON_OT_set_edge_width,
    MIKUMIKUTOON_OT_set_sphere_add,
    MIKUMIKUTOON_OT_selfcheck,
    MIKUMIKUTOON_PT_panel,
    MIKUMIKUTOON_OT_one_click,
    MIKUMIKUTOON_OT_apply_preset,
    MIKUMIKUTOON_OT_set_eye_shadow,
    MIKUMIKUTOON_OT_edge_preview_create,
    MIKUMIKUTOON_OT_edge_preview_clean,
    MIKUMIKUTOON_OT_add_glow,
    MIKUMIKUTOON_OT_glow_look,
    MIKUMIKUTOON_OT_remove_glow,
)


SCENE_PROPS = (
    ("mmt_edge_scale", "Float", dict(name="描边粗细", default=0.08,
                                    min=0.0005, max=1.0, precision=4,
                                    description="MMD 描边（内勾壳）的粗细")),
    ("mmt_edge_use_color", "Bool", dict(name="统一描边颜色", default=False,
                                       description="关 = 每个材质用模型自带的 edge_color；"
                                                   "开 = 全部用下面选的颜色")),
    ("mmt_edge_color", "FloatVector", dict(name="描边颜色", subtype="COLOR",
                                          size=3, min=0.0, max=1.0,
                                          default=(0.05, 0.05, 0.05))),
    # 署名相关（mmt_stamp_on / mmt_credit_text / mmt_credit_alpha）不再注册：
    # 署名强制执行，没有开关、也不能改文字与透明度
    ("mmt_credit_notice_shown", "Bool", dict(name="署名提示已弹过", default=False)),
    # 泛光预设的折叠开关（面板上那个三角）
    ("mmt_glow_presets_open", "Bool", dict(name="游戏泛光预设展开", default=False)),
    # 套用游戏预设时，强度按这个模型的自动值收力
    ("mmt_glow_tame", "Bool", dict(name="按模型收力", default=True)),
    # 严重削顶（亮色材质被削成一片白）时自动压「亮度」
    ("mmt_auto_exposure", "Bool", dict(name="按模型自适应曝光", default=True)),
    # MMD 球面模式 2（闪粉/金属/水钻）那一层的强度余量，1.00 = 与 mmd_tools 同强度
    ("mmt_sphere_add", "Float", dict(name="加算球面强度", default=1.0,
                                    min=0.0, max=4.0, precision=2,
                                    description="MMD 球面模式 2（加算：闪粉/金属/水钻）"
                                                "那一层的强度。1.00 = 与 MMD 同强度")),
)


#: 记住这次注册上去的类/属性，注销时只摘自己摘过的
_REGISTERED_CLASSES = []
_REGISTERED_PROPS = []


def _class_exists(name):
    """这个 bl_idname 对应的类是不是已经注册过了（重复注册是致命的）。"""
    return getattr(bpy.types, name, None) is not None


def _register_classes(classes, label, keep):
    """逐项注册：已存在的跳过，单项失败只警告，不影响后面（尤其是面板）。"""
    done = 0
    for cls in classes:
        name = getattr(cls, "__name__", repr(cls))
        if _class_exists(name):
            continue                      # 已经注册过：跳过，不是错误
        try:
            bpy.utils.register_class(cls)
        except Exception as error:
            print("[MikuMikuToon] 注册%s失败（跳过这一项，继续注册其余的）：%s -> %s"
                  % (label, name, error))
            continue
        keep.append(cls)
        done += 1
    return done


def _unregister_classes(classes, label):
    """逐项注销，没注册的跳过；出错只警告。"""
    for cls in reversed(list(classes)):
        name = getattr(cls, "__name__", repr(cls))
        if not _class_exists(name):
            continue
        try:
            bpy.utils.unregister_class(cls)
        except Exception as error:
            print("[MikuMikuToon] 注销%s失败：%s -> %s" % (label, name, error))


def _register_prop(holder, name, prop, keep):
    """注册一个属性；已经有同名属性就跳过。"""
    if hasattr(holder, name):
        return False
    try:
        setattr(holder, name, prop)
        keep.append((holder, name))
        return True
    except Exception as error:
        print("[MikuMikuToon] 注册属性 %s 失败：%s" % (name, error))
        return False


#: 自检要看的场景属性（面板控件直接依赖它们）
CHECK_PROPS = ("mmt_mode", "mmt_edge_scale", "mmt_auto_exposure")


def check_registration():
    """查"面板到底能不能出来"。返回 (缺的东西列表, 明细字典)。"""
    missing = []
    detail = {}

    panel = getattr(bpy.types, "MIKUMIKUTOON_PT_panel", None)
    detail["面板类"] = panel is not None
    if panel is None:
        missing.append("面板类 MIKUMIKUTOON_PT_panel 没注册上")
    else:
        detail["侧栏页签"] = getattr(panel, "bl_category", None)
        detail["空间/区域"] = "%s / %s" % (getattr(panel, "bl_space_type", "?"),
                                           getattr(panel, "bl_region_type", "?"))
        if not detail["侧栏页签"]:
            missing.append("面板没有 bl_category（不会出现在任何侧栏页签里）")
        if detail["空间/区域"] != "VIEW_3D / UI":
            missing.append("面板的位置不是 3D 视图的侧栏（现在是 %s）"
                           % detail["空间/区域"])

    # 操作符：面板上的按钮点不点得动
    wanted_ops = ("one_click", "apply_preset", "set_edge_width", "set_eye_shadow",
                  "add_glow", "remove_glow", "glow_look", "set_sphere_add")
    ops = [op for op in wanted_ops if _has(bpy.ops.mikumikutoon, op)]
    detail["操作符"] = ops
    detail["操作符全了"] = len(ops) == len(wanted_ops)
    if "one_click" not in ops:
        missing.append("操作符 mikumikutoon.one_click 没注册上（「一键卡渲」按钮会失效）")

    # 场景属性：面板上每个控件都要能读到值，读不到那一行就画不出来
    props = [name for name in CHECK_PROPS if _has(bpy.types.Scene, name)]
    detail["场景属性"] = props
    detail["场景属性全了"] = len(props) == len(CHECK_PROPS)
    for name in CHECK_PROPS:
        if name not in props:
            missing.append("场景属性 %s 没注册上（面板上对应那一行会消失）" % name)

    # 强制署名处理器
    mounted = any(getattr(handler, "__name__", "") == "force_watermark"
                  for handler in bpy.app.handlers.render_pre)
    detail["强制署名处理器"] = mounted
    if not mounted:
        missing.append("render_pre 上没有 force_watermark（水印不会强制烧录）")

    return missing, detail


def report_registration(force=False):
    """把自检结果打出来：正常一行带过，不正常打整块诊断。

    ``force=True`` 时无论正常与否都打完整块 —— 手动敲
    ``bpy.ops.mikumikutoon.selfcheck()`` 就是想要全过程。
    """
    missing, detail = check_registration()
    line = "[MikuMikuToon] 自检：%s" % ("全部正常" if not missing else
                                        "有 %d 项不对" % len(missing))
    if not missing and not force:
        print(line + "｜面板在 3D 视图 N → %s" % (detail.get("侧栏页签") or "?"))
        return True

    print("=" * 68)
    print("[MikuMikuToon] 自检报告（v%s）" % _VERSION)
    print("-" * 68)
    print("  Blender        : %s" % bpy.app.version_string)
    print("  插件模块       : %s" % __file__)
    print("  面板类         : %s" % ("在" if detail["面板类"] else "★不在"))
    if detail.get("侧栏页签"):
        print("  侧栏页签       : %r（3D 视图 → N → 这个页签）" % detail["侧栏页签"])
    print("  面板位置       : %s" % detail.get("空间/区域", "?"))
    print("  操作符         : %s（%s）"
          % ("、".join(detail["操作符"]) or "★一个都没有",
             "齐全" if detail["操作符全了"] else "★不齐"))
    print("  场景属性       : %s（%s）"
          % ("、".join(detail["场景属性"]) or "★一个都没有",
             "齐全" if detail["场景属性全了"] else "★不齐"))
    print("  强制署名处理器 : %s" % ("已挂上" if detail["强制署名处理器"] else "★没挂上"))
    if missing:
        print("-" * 68)
        print("  有问题的项：")
        for item in missing:
            print("    * %s" % item)
        print("-" * 68)
        print("  怎么办（按顺序试）：")
        print("    1) 偏好设置 → 附加组件 → 把 MikuMikuToon 关掉再打开；")
        print("    2) 还不行就重启 Blender（运行中的 Blender 不会重载插件代码）；")
        print("    3) 看这份报告**上面**有没有 '注册...失败' 的报错行 —— 那一行才是根因；")
        print("    4) 把从 [MikuMikuToon] 开头到这里的整段复制给作者。")
    else:
        print("-" * 68)
        print("  所有项都正常。如果你在界面上仍然看不到面板：")
        print("    * 面板在 **3D 视图**的侧栏：按 N，再看页签栏里有没有「%s」；"
              % (detail.get("侧栏页签") or "Toon"))
        print("    * 侧栏页签可以被折叠/隐藏，右键页签栏或看侧栏顶部的箭头；")
        print("    * 确认当前窗口是 3D 视图，不是着色器/合成器编辑器。")
    print("=" * 68)
    return not missing


#: 定时自检只安排一次（每次启用都安排会刷屏）
_SELFCHECK_SCHEDULED = False


def _selfcheck_timer():
    """启用后过一小会儿再查一次，抓"当时注册了、后来被别的插件挤掉"的情况。

    一次性定时器，返回 None 表示不再重复。
    """
    try:
        report_registration()
    except Exception as error:
        print("[MikuMikuToon] 自检本身出错了（不影响使用）：%s" % error)
    return None


def schedule_selfcheck(delay=1.0):
    """安排一次延迟自检；已经安排过就跳过。"""
    global _SELFCHECK_SCHEDULED
    if _SELFCHECK_SCHEDULED:
        return
    try:
        if bpy.app.timers.register(_selfcheck_timer, first_interval=delay,
                                   persistent=True):
            _SELFCHECK_SCHEDULED = True
    except Exception as error:
        # 定时器不可用（比如后台模式）也要当场查一次
        print("[MikuMikuToon] 排不了延迟自检（%s），改成立刻自检" % error)
        report_registration()


def register_scene_props():
    for name, kind, options in SCENE_PROPS:
        maker = {"Float": bpy.props.FloatProperty,
                 "Bool": bpy.props.BoolProperty,
                 "String": bpy.props.StringProperty,
                 "FloatVector": bpy.props.FloatVectorProperty}[kind]
        try:
            prop = maker(**options)
        except Exception as error:
            print("[MikuMikuToon] 构造属性 %s 失败：%s" % (name, error))
            continue
        _register_prop(bpy.types.Scene, name, prop, _REGISTERED_PROPS)


def unregister_scene_props():
    # 只清掉这次注册的；别人（或上一次）留下的不动
    for holder, name in reversed(list(_REGISTERED_PROPS)):
        try:
            delattr(holder, name)
        except Exception:
            pass   # 本来就不在
    del _REGISTERED_PROPS[:]
    # 兜底：万一 _REGISTERED_PROPS 丢了（模块重载），按名字再扫一遍
    for name, _kind, _options in SCENE_PROPS:
        if hasattr(bpy.types.Scene, name):
            try:
                delattr(bpy.types.Scene, name)
            except Exception:
                pass   # 本来就没注册上


def register():
    _register_classes(CLASSES, "类", _REGISTERED_CLASSES)
    _register_prop(bpy.types.Scene, "mmt_mode", bpy.props.EnumProperty(
        name="模式",
        items=[("REPLACE_MODEL", "替换【模型】材质", ""),
               ("REPLACE_SINGLE", "替换单个【材质】", "")],
        default="REPLACE_MODEL"), _REGISTERED_PROPS)
    register_scene_props()
    report_integrity(INTEGRITY)
    # 重新启用也要挂上：Blender 重新启用插件时不会重跑模块顶层代码
    mount_watermark_handler()
    # 当场自检：面板没出来就把原因打出来（正常只打一行）
    report_registration()
    # 再排一次延迟自检，抓"后来被别的插件挤掉"的情况
    schedule_selfcheck()


def unregister():
    unregister_scene_props()
    _unregister_classes(CLASSES, "类")
    del _REGISTERED_CLASSES[:]
    # 摘掉处理器：它带 persistent 标记，插件关了还挂着就太脏
    for handler in list(bpy.app.handlers.render_pre):
        if getattr(handler, "__name__", "") == "force_watermark":
            try:
                bpy.app.handlers.render_pre.remove(handler)
            except Exception as error:
                print("[MikuMikuToon] 摘除 render_pre 失败：%s" % error)


if __name__ == "__main__":
    register()


def mount_watermark_handler():
    """把强制署名挂到 render_pre（按名字去重，重复调用安全）。

    每次 register() 都要调：Blender 重新启用插件时不会再跑模块顶层代码，
    只靠文件末尾那一句的话，重新启用后就挂不上。
    """
    try:
        current = [handler for handler in bpy.app.handlers.render_pre
                   if getattr(handler, "__name__", "") == "force_watermark"]
        if len(current) == 1 and current[0] is force_watermark:
            return                          # 已经挂好，别重复也别刷屏
        for handler in current:             # 重载脚本留下的旧函数对象，换掉
            try:
                bpy.app.handlers.render_pre.remove(handler)
            except Exception as error:
                print("[MikuMikuToon] 摘除旧的 render_pre 处理器失败：%s" % error)
        bpy.app.handlers.render_pre.append(force_watermark)
        print("[MikuMikuToon] 渲染前强制署名已挂上（render_pre，persistent）")
    except Exception as error:
        print("[MikuMikuToon] 挂载 render_pre 失败：%s" % error)


# ---------------------------------------------------------------------------
# 强制水印：按下渲染的一瞬间再设一次
# ---------------------------------------------------------------------------

def _persistent(function):
    """让处理器活过"工厂重置 / 重载启动文件"，那些操作会清空 `bpy.app.handlers`。

    `read_factory_settings()` 之后 render_pre 就是空列表，而"画面板时补挂"只在有人
    打开 Toon 面板时才发生 —— 后台渲染没有面板可画，强制署名会静默失效。
    """
    persistent = getattr(bpy.app.handlers, "persistent", None)
    if persistent is None:                  # 老版本没有这个 API，说清楚别静默
        print("[MikuMikuToon] 这个 Blender 没有 bpy.app.handlers.persistent；"
              "强制署名处理器活不过工厂重置（打开 Toon 面板时会补挂）")
        return function
    return persistent(function)


@_persistent
def force_watermark(scene=None, *args, **kwargs):
    """渲染前强制打开署名水印，只留署名一项。

    水印文字与样式都由完整性校验结果决定，被改过的副本印不出
    「渲染 BVToon / @BVan」。
    """
    try:
        if __name__ not in bpy.context.preferences.addons:
            return                      # 插件没启用就不管
        target = scene if scene is not None else bpy.context.scene
        if target is None or getattr(target, "render", None) is None:
            print("[MikuMikuToon] 渲染前强制署名跳过：拿不到 scene（scene=%r）" % (target,))
            return
        render = target.render
        report = mmt_integrity.verify()
        note = mmt_integrity.credit_text(report, DEFAULT_CREDIT)
        render.use_stamp = True
        render.use_stamp_note = True
        render.stamp_note_text = note
        apply_watermark_style(render, report)
        for prop in _OTHER_STAMP_PROPS:
            if hasattr(render, prop):
                setattr(render, prop, False)
        print("[MikuMikuToon] 渲染前已强制署名：%s（完整性：%s）"
              % (render.stamp_note_text, report["state"]))
        # 校验不过就把画面本身弄坏（唯一档位，没有可放宽的选项）
        try:
            print("[MikuMikuToon] 画面损毁：%s" % mmt_damage.enforce(target, report))
        except Exception as error:
            print("[MikuMikuToon] 损毁处理失败：%s" % error)
        if report["state"] != mmt_integrity.STATE_OK:
            print("[MikuMikuToon]     原因：%s" % report["reason"])
    except Exception as error:
        print("[MikuMikuToon] 强制署名失败：%s" % error)


# 模块加载时挂一次（按名字去重，重载脚本也不会叠加）
mount_watermark_handler()
