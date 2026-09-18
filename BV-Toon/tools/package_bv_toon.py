# -*- coding: utf-8 -*-
"""把 clean-room 的 BV-Toon 打成 Blender 能直接「从磁盘安装」的 zip。

    python tools/package_bv_toon.py                      # -> dist\\BV-Toon-<版本>.zip
    python tools/package_bv_toon.py --verify             # 顺便在每个 Blender 里真装一遍验证
    python tools/package_bv_toon.py --check              # 只检查已经打好的 zip
    python tools/package_bv_toon.py --tag 1.6.0          # 显式指定 tag（与 bl_info 不一致会拒绝）

这个脚本**只**打 ``clean-room\\BV-Toon``。工作区根目录那个 ``BV-Toon`` 是私有的
MBTs 改版（本机自用、不可上架），它有自己的旧脚本 ``tools\\package_private_mbts.py``。

BV-Toon 是经典 ``bl_info`` 插件（不是 2.8+ 的 extension），所以 zip 必须**正好**
有一个顶层目录 ``BV-Toon`` —— Blender 的「从磁盘安装」就是拿那个目录名当模块名的。

打包流程里做的检查（都是"对不上就拒绝"，绝不打一个坏 zip 出去）：

* 该有的文件都在（6 个 ``.py`` + 卡渲资产 + LICENSE / README / MMD-NOTICE）
* 全部 ``.py`` 能 ``ast.parse``
* ``bl_info`` 版本 == tag（== zip 名里的版本），且插件里没有再硬编码版本号
* ``LICENSE`` 是 GPL v3 全文 + §7 附加条款；插件 README 里写了当前版本
* 仓库文档里有三语 ``RELEASE-<版本>.md``（找不到文档目录时跳过并说明）
* ``__init__.py`` 里确实接了完整性校验（``bv_integrity.verify()``）—— 漏接就等于白做
* 打包时**生成** ``BVToonData/integrity.json``（顶层 .py + 卡渲资产的 SHA-256）写进 zip
* 打完把 zip 再拆开核对：清单里的每个哈希都必须等于 zip 里那个文件的哈希

``--verify`` 会拿一个**一次性 Blender 配置**真装一次，然后实测五种情形：正常 /
改一个字节（modified）/ 多一个 ``.py``（modified）/ 删掉清单（unverified）/
重算清单（恢复 ok），逐个检查水印文字与面板告警。
"""

import argparse
import ast
import glob
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(WORKSPACE, "dist")
FOLDER = "BV-Toon"

#: 源码目录的候选（工具被复制到 github 副本里跑时布局不一样）
SOURCE_CANDIDATES = (
    os.path.join(WORKSPACE, "clean-room", "BV-Toon"),
    os.path.join(WORKSPACE, "BV-Toon"),
)

#: 仓库级文档目录的候选（github\\BV-Toon）；找不到就跳过发布说明检查
DOCS_CANDIDATES = (
    os.path.join(WORKSPACE, "github", "BV-Toon"),
    WORKSPACE,
)

SKIP_DIRS = {"__pycache__", ".git", ".svn", ".idea", ".vscode"}
SKIP_SUFFIX = (".pyc", ".pyo", ".bvtoonorig", ".blend1", ".blend2", ".orig", ".bak")
SKIP_NAMES = {"Thumbs.db", "desktop.ini", ".DS_Store"}

#: 清单每次打包现算，源码目录里那份（如果有）不作为内容打包
MANIFEST_REL = "BVToonData/integrity.json"

REQUIRED = (
    "__init__.py",
    "bv_integrity.py",
    "bv_damage.py",
    "bv_glow.py",
    "bv_materials.py",
    "bv_shading.py",
    "bv_util.py",
    "BVToonData/BVToonShading.blend",
    "LICENSE",
    "MMD-NOTICE.md",
    "README.md",
)

#: 插件里不该再出现的硬编码版本号（版本只写 bl_info 一处）
HARDCODED_VERSION = re.compile(r"BV-Toon\s+\d+\.\d+\.\d+")


def default_source():
    for candidate in SOURCE_CANDIDATES:
        if os.path.isfile(os.path.join(candidate, "__init__.py")):
            return candidate
    return SOURCE_CANDIDATES[0]


def docs_dir():
    for candidate in DOCS_CANDIDATES:
        if os.path.isfile(os.path.join(candidate, "CHANGELOG.md")):
            return candidate
    return None


def load_integrity_module(source):
    """把插件自己的 bv_integrity.py 装进来 —— 生成端与校验端共用同一套规则。

    ``bv_integrity`` 刻意不导入 bpy，所以这里在 Blender 之外也能直接跑。
    """
    path = os.path.join(source, "bv_integrity.py")
    if not os.path.isfile(path):
        return None
    spec = importlib.util.spec_from_file_location("bv_integrity_packaged", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_text(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def addon_version(source):
    text = read_text(os.path.join(source, "__init__.py"))
    found = re.search(r'"version"\s*:\s*\(([^)]*)\)', text)
    if not found:
        return None
    parts = [part.strip() for part in found.group(1).split(",") if part.strip()]
    return ".".join(parts)


def check_source(source, tag):
    """打包之前必须成立的事情。返回问题列表（空表示可以打）。"""
    problems = []
    if not os.path.isfile(os.path.join(source, "__init__.py")):
        return ["源码目录不像 BV-Toon：%s（用 --source 指路）" % source]

    for relative in REQUIRED:
        if not os.path.isfile(os.path.join(source, relative.replace("/", os.sep))):
            problems.append("缺文件 %s" % relative)

    for name in sorted(os.listdir(source)):
        if not name.endswith(".py"):
            continue
        path = os.path.join(source, name)
        try:
            ast.parse(read_text(path), path)
        except SyntaxError as error:
            problems.append("%s 语法错误：%s" % (name, error))

    version = addon_version(source)
    if version is None:
        problems.append("__init__.py 里读不到 bl_info version")
    elif version != tag:
        problems.append("版本对不上：bl_info=%s，tag/zip 名=%s" % (version, tag))

    init = os.path.join(source, "__init__.py")
    if os.path.isfile(init):
        text = read_text(init)
        if "bv_integrity.verify()" not in text:
            problems.append("__init__.py 没接完整性校验（找不到 bv_integrity.verify()）"
                            "—— 这么发出去就等于白做")
        found = HARDCODED_VERSION.search(text)
        if found:
            problems.append("插件里又出现硬编码版本号 %r；版本只写 bl_info 一处"
                            % found.group(0))

    license_path = os.path.join(source, "LICENSE")
    if os.path.isfile(license_path):
        license_text = read_text(license_path)
        for needle, what in (("GNU GENERAL PUBLIC LICENSE", "GPL 全文"),
                             ("Version 3, 29 June 2007", "GPL v3 版本行"),
                             ("BVToon / @BVan", "§7 署名附加条款")):
            if needle not in license_text:
                problems.append("LICENSE 里找不到%s（%r）" % (what, needle))

    readme = os.path.join(source, "README.md")
    if os.path.isfile(readme) and tag and tag not in read_text(readme):
        problems.append("插件 README.md 里没写当前版本 %s（版本号要四处一致）" % tag)

    docs = docs_dir()
    if docs:
        for suffix in ("", ".en", ".ja"):
            name = "RELEASE-%s%s.md" % (tag, suffix)
            if not os.path.isfile(os.path.join(docs, name)):
                problems.append("仓库文档里没有 %s（三语版本说明要齐）" % name)
    else:
        print("  note: 没找到仓库文档目录，跳过发布说明检查")
    return problems


def iter_files(source):
    """要打进 zip 的文件（跳过垃圾，以及本脚本会重新生成的清单）。"""
    for root, dirs, files in os.walk(source):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(files):
            if name in SKIP_NAMES or name.endswith(SKIP_SUFFIX):
                continue
            full = os.path.join(root, name)
            relative = os.path.relpath(full, source).replace("\\", "/")
            if relative == MANIFEST_REL:
                continue
            yield full, relative


def _write(archive, member, path):
    info = zipfile.ZipInfo(member, date_time=time.localtime(os.path.getmtime(path))[:6])
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    with open(path, "rb") as handle:
        archive.writestr(info, handle.read())


def _write_bytes(archive, member, payload, date_time):
    info = zipfile.ZipInfo(member, date_time=date_time)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    archive.writestr(info, payload)


def build(source=None, out_dir=DIST, tag=None, quiet=False):
    """打 zip。返回 (zip 路径, 版本, 问题列表)；有问题时 zip 路径是 None。

    **可复现**：清单那条 zip 记录的时间戳取"源码里最新的一个 mtime"，不是"现在"——
    否则同样的源码每打一次 sha 都不同，HANDOFF 里记的 sha256 就变成假的了（踩过）。
    """
    source = source or default_source()
    tag = tag or addon_version(source) or "unknown"
    problems = check_source(source, tag)
    if problems:
        if not quiet:
            for problem in problems:
                print("  REFUSING: %s" % problem)
        return None, tag, problems

    integrity = load_integrity_module(source)
    if integrity is None:
        return None, tag, ["bv_integrity.py 装不进来，没法生成清单"]

    version = addon_version(source)
    manifest = integrity.build_manifest(source, version)
    manifest_bytes = integrity.dumps(manifest).encode("utf-8")

    os.makedirs(out_dir, exist_ok=True)
    target = os.path.join(out_dir, "%s-%s.zip" % (FOLDER, tag))
    files = list(iter_files(source))
    stamp = time.localtime(max(os.path.getmtime(full) for full, _ in files))[:6]

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for full, relative in files:
            _write(archive, "%s/%s" % (FOLDER, relative), full)
        _write_bytes(archive, "%s/%s" % (FOLDER, MANIFEST_REL), manifest_bytes, stamp)

    if not quiet:
        print("built %s" % target)
        print("  bl_info version : %s" % version)
        print("  top level folder: %s/  （Blender 就是拿这个目录名当模块名）" % FOLDER)
        print("  %d files + 1 清单, %.2f MB packed"
              % (len(files), os.path.getsize(target) / 1e6))
        print("  清单覆盖        : %s" % ", ".join(sorted(manifest["files"])))
    return target, tag, []


def check_zip(path, source=None):
    """把打好的 zip 拆开核对：结构、垃圾、清单与文件是否逐字节对得上。"""
    source = source or default_source()
    problems = []
    if not os.path.isfile(path):
        return ["没有这个文件：%s" % path]
    integrity = load_integrity_module(source)
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        tops = {name.split("/", 1)[0] for name in names}
        if tops != {FOLDER}:
            problems.append("顶层必须只有一个目录 %r，实际是 %s"
                            % (FOLDER, sorted(tops)))
        for name in names:
            base = name.rstrip("/").split("/")[-1]
            if base in SKIP_NAMES or base.endswith(SKIP_SUFFIX) or "__pycache__" in name:
                problems.append("zip 里有垃圾文件：%s" % name)
        for relative in REQUIRED:
            member = "%s/%s" % (FOLDER, relative)
            if member not in names:
                problems.append("zip 里缺 %s" % relative)
        corrupt = archive.testzip()
        if corrupt:
            problems.append("压缩包损坏：%s" % corrupt)

        member = "%s/%s" % (FOLDER, MANIFEST_REL)
        if member not in names:
            problems.append("zip 里没有完整性清单 %s" % MANIFEST_REL)
            return problems
        try:
            manifest = json.loads(archive.read(member).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as error:
            problems.append("清单不是合法 JSON：%s" % error)
            return problems
        if integrity is not None and manifest.get("format") != integrity.FORMAT:
            problems.append("清单格式是 %r，插件认的是 %r"
                            % (manifest.get("format"), integrity.FORMAT))
        files = manifest.get("files") or {}
        if not files:
            problems.append("清单里没有文件表")
            return problems

        for relative in sorted(files):
            packed = "%s/%s" % (FOLDER, relative)
            if packed not in names:
                problems.append("清单里列了 %s，zip 里却没有" % relative)
                continue
            digest = hashlib.sha256(archive.read(packed)).hexdigest()
            if digest != files[relative]:
                problems.append("清单说的 %s 哈希对不上 zip 里的内容" % relative)

        # 清单覆盖面必须等于 zip 里真正的顶层 .py（多一个少一个都是漏洞）
        packed_py = {name[len(FOLDER) + 1:] for name in names
                     if name.startswith(FOLDER + "/") and name.endswith(".py")
                     and "/" not in name[len(FOLDER) + 1:]}
        listed_py = {name for name in files if name.endswith(".py") and "/" not in name}
        if packed_py != listed_py:
            problems.append("清单的 .py 覆盖面不对：zip 里 %s，清单里 %s"
                            % (sorted(packed_py), sorted(listed_py)))
    return problems


# ---------------------------------------------------------------------------
# --verify：在每个 Blender 里真装一遍，实测五种情形
# ---------------------------------------------------------------------------

VERIFY_SCRIPT = r'''
import os, sys
import bpy

zip_path = sys.argv[sys.argv.index("--") + 1]
EXPECT_VERSION = "__VERSION__"
EXPECT_OK_CREDIT = "__CREDIT_OK__"
EXPECT_MODIFIED = "__CREDIT_MODIFIED__"
EXPECT_UNVERIFIED = "__CREDIT_UNVERIFIED__"

print("INSTALL_START", bpy.app.version_string, os.path.basename(zip_path))
print("INSTALL scripts dir:", bpy.utils.user_resource("SCRIPTS"))
print("INSTALL addon_install ->", bpy.ops.preferences.addon_install(filepath=zip_path,
                                                                    overwrite=True))
print("INSTALL addon_enable  ->", bpy.ops.preferences.addon_enable(module="BV-Toon"))
module = sys.modules.get("BV-Toon")
addon_dir = os.path.dirname(getattr(module, "__file__", "") or "")
print("INSTALL module:", addon_dir)

FAIL = []


def chk(name, ok, detail=""):
    print("INSTALL [%s] %s%s" % ("ok  " if ok else "FAIL", name,
                                 ("  (%s)" % detail) if detail else ""))
    if not ok:
        FAIL.append(name)


version = ".".join(str(p) for p in module.bl_info["version"])
chk("版本 = %s" % EXPECT_VERSION, version == EXPECT_VERSION, version)
integrity = module.bv_integrity
print("INSTALL 清单:", integrity.manifest_path(addon_dir),
      os.path.isfile(integrity.manifest_path(addon_dir)))


class Recorder:
    """把面板 draw() 画的东西记下来（画了哪些属性行 / alert / enabled / label）。"""

    def __init__(self):
        object.__setattr__(self, "labels", [])
        object.__setattr__(self, "ops", [])
        object.__setattr__(self, "props", [])
        object.__setattr__(self, "alert", False)
        object.__setattr__(self, "disabled", False)

    def __setattr__(self, name, value):
        if name == "alert" and value:
            object.__setattr__(self, "alert", True)
        elif name == "enabled" and value is False:
            object.__setattr__(self, "disabled", True)      # 有行被禁用了
        else:
            object.__setattr__(self, name, value)

    def box(self, **kw): return self
    def row(self, **kw): return self
    def column(self, **kw): return self

    def label(self, **kw):
        self.labels.append(kw.get("text", ""))
        return None

    def prop(self, data, name, **kw):
        self.props.append(name)                # 记下"画了哪个属性行"
        return None

    def operator(self, idname, **kw):
        self.ops.append(idname)
        return type("Op", (), {})()


def draw_panel():
    recorder = Recorder()
    module.BVTOON_PT_panel.draw(type("Panel", (), {"layout": recorder})(), bpy.context)
    return recorder


# --- 1) 正常状态 ---------------------------------------------------------
report = integrity.verify(addon_dir)
chk("正常：清单核对通过", report["state"] == integrity.STATE_OK, report["reason"])
chk("正常：清单覆盖顶层 .py + 卡渲资产",
    report["checked"] == len(integrity.tracked(addon_dir)),
    "%d/%d" % (report["checked"], len(integrity.tracked(addon_dir))))
sc = bpy.context.scene
module.force_watermark(sc)
chk("正常：水印 = 默认署名", sc.render.stamp_note_text == EXPECT_OK_CREDIT,
    sc.render.stamp_note_text)
chk("正常：水印是 85% 透明白字、无底框",
    abs(sc.render.stamp_foreground[3] - 0.15) < 1e-6
    and tuple(sc.render.stamp_foreground[:3]) == (1.0, 1.0, 1.0)
    and sc.render.stamp_background[3] == 0.0,
    "%s / %s" % (tuple(sc.render.stamp_foreground),
                 tuple(sc.render.stamp_background)))
ok_panel = draw_panel()
chk("正常：面板不报警", not ok_panel.alert, str(ok_panel.labels[:2]))
chk("正常：面板按钮齐全", len(ok_panel.ops) >= 9, str(len(ok_panel.ops)))
# 损毁**没有设置项**：任何状态下都不该画出这个属性行
chk("正常：面板没有损毁档位选项（属性行不画）",
    "bv_damage_mode" not in ok_panel.props, str(ok_panel.props))
chk("正常：面板写明损毁是唯一档位、无选项",
    any("唯一档位" in text or "无选项" in text for text in ok_panel.labels),
    str([t for t in ok_panel.labels if "损毁" in t][:1]))

# --- 2) 改一个字节（modified）-------------------------------------------
target = os.path.join(addon_dir, "bv_util.py")
with open(target, "a", encoding="utf-8") as handle:
    handle.write("\n# tampered by package_bv_toon.py --verify\n")
report = integrity.verify(addon_dir)
chk("被改：状态 = modified", report["state"] == integrity.STATE_MODIFIED,
    report["state"])
chk("被改：认得出是哪个文件", "bv_util.py" in report["details"], str(report["details"]))
module.force_watermark(sc)
chk("被改：水印 = 未授权修改版", sc.render.stamp_note_text == EXPECT_MODIFIED,
    sc.render.stamp_note_text)
chk("被改：水印不透明 + 有黑底",
    sc.render.stamp_foreground[3] == 1.0 and sc.render.stamp_background[3] > 0.0,
    "%s / %s" % (tuple(sc.render.stamp_foreground),
                 tuple(sc.render.stamp_background)))
bad_panel = draw_panel()
chk("被改：面板报警", bad_panel.alert and EXPECT_MODIFIED in bad_panel.labels,
    str(bad_panel.labels[:2]))
chk("被改：面板同样没有损毁档位选项",
    "bv_damage_mode" not in bad_panel.props, str(bad_panel.props))

# --- 3) 多出一个 .py 也算改动 -------------------------------------------
extra = os.path.join(addon_dir, "bv_sneaky.py")
with open(extra, "w", encoding="utf-8") as handle:
    handle.write("# not in the manifest\n")
report = integrity.verify(addon_dir)
chk("多出文件：状态 = modified", report["state"] == integrity.STATE_MODIFIED,
    report["state"])
os.remove(extra)
os.remove(target)          # 把篡改复原（不影响下面的 unverified 检查）

# --- 4) 清单缺失（unverified）-------------------------------------------
manifest = integrity.manifest_path(addon_dir)
os.remove(manifest)
report = integrity.verify(addon_dir)
chk("没清单：状态 = unverified", report["state"] == integrity.STATE_UNVERIFIED,
    report["state"])
module.force_watermark(sc)
chk("没清单：水印 = 未验证副本", sc.render.stamp_note_text == EXPECT_UNVERIFIED,
    sc.render.stamp_note_text)
meh_panel = draw_panel()
chk("没清单：面板报警", meh_panel.alert and EXPECT_UNVERIFIED in meh_panel.labels,
    str(meh_panel.labels[:2]))

# --- 5) 清单写回去就恢复正常 --------------------------------------------
integrity.write_manifest(addon_dir, version)
report = integrity.verify(addon_dir)
chk("重算清单后：状态 = ok", report["state"] == integrity.STATE_OK, report["reason"])
module.force_watermark(sc)
chk("重算清单后：水印 = 默认署名", sc.render.stamp_note_text == EXPECT_OK_CREDIT,
    sc.render.stamp_note_text)

# --- 6) 重新加载文件之后，强制署名还在（1.6.0 修掉的真 bug）-------------
# 两条真实路径都得测：
#   a) 文件 > 新建（wm.read_homefile）：插件还开着，处理器**必须**活下来
#      —— 靠 @bpy.app.handlers.persistent；没有它 render_pre 就成了空列表，
#         而"面板绘制时补挂"在后台渲染里根本不会发生 ⇒ 强制署名静默失效
#   b) 工厂重置（wm.read_factory_settings）：它连插件一起关了，重新启用后
#      处理器**必须**重新挂上 —— 靠 register() 里调 mount_watermark_handler()
#      （Blender 重新启用插件不会再跑模块顶层代码，只靠文件末尾那一句会挂空）


def watermark_handlers():
    return [h for h in bpy.app.handlers.render_pre
            if getattr(h, "__name__", "") == "force_watermark"]


def shoot_small(scene, tag):
    """真渲一张 64x64：先把水印破坏掉，看处理器有没有把它设回来。"""
    camera_data = bpy.data.cameras.new("fw_%s" % tag)
    camera = bpy.data.objects.new("fw_%s" % tag, camera_data)
    scene.collection.objects.link(camera)
    scene.camera = camera
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 64
    scene.render.resolution_y = 64
    scene.render.resolution_percentage = 100
    scene.render.filepath = os.path.join(bpy.app.tempdir, "bvtoon_fw_%s.png" % tag)
    scene.render.use_stamp = False
    scene.render.stamp_note_text = "入侵者"
    bpy.ops.render.render(write_still=True)
    return scene.render.stamp_note_text


chk("重载前：render_pre 挂着 force_watermark", len(watermark_handlers()) >= 1,
    str(len(watermark_handlers())))
bpy.ops.wm.read_homefile(use_empty=True)
chk("新建文件后：插件还开着", "BV-Toon" in bpy.context.preferences.addons)
chk("新建文件后：render_pre 还挂着 force_watermark",
    len(watermark_handlers()) >= 1, str(len(watermark_handlers())))
note = shoot_small(bpy.context.scene, "homefile")
chk("新建文件后真渲染：水印被强制设回来", note != "入侵者", note)

bpy.ops.wm.read_factory_settings(use_empty=True)
print("INSTALL 工厂重置后：插件还启用着 =", "BV-Toon" in bpy.context.preferences.addons)
bpy.ops.preferences.addon_enable(module="BV-Toon")
chk("工厂重置后重新启用：render_pre 又挂上了",
    len(watermark_handlers()) >= 1, str(len(watermark_handlers())))
note = shoot_small(bpy.context.scene, "factory")
chk("工厂重置+重新启用后真渲染：水印被强制设回来", note != "入侵者", note)

# --- 7) 「损毁画面」真的会把图弄坏（像素级）------------------------------
# 只看"节点接上了/factor 设对了"是不够的（这项目的 Glare 就吃过这个亏：设置对、画面错），
# 所以这里渲一张有花纹的图，正常态与损毁态必须明显不同。
damage = module.bv_damage
chk("损毁：损毁强度表（被改/未验证 → 1，通过 → 0）",
    (damage.factor_for("modified") == 1.0
     and damage.factor_for("unverified") == 1.0
     and damage.factor_for("ok") == 0.0),
    "modified=%s unverified=%s ok=%s"
    % (damage.factor_for("modified"), damage.factor_for("unverified"),
       damage.factor_for("ok")))
# **没有档位可选**：整个设置项被删掉了（属性不存在、模块里也没有档位常量）
chk("损毁：场景上**没有**损毁档位属性（设置项已删除）",
    not hasattr(bpy.context.scene, "bv_damage_mode"),
    str([name for name in dir(bpy.context.scene) if "damage" in name]))
chk("损毁：模块里也没有可选的档位常量",
    not hasattr(damage, "ITEMS") and not hasattr(damage, "MODE_OFF")
    and not hasattr(damage, "DEFAULT_MODE") and not hasattr(damage, "effective_mode")
    and damage.MODE == "ALL",
    "MODE=%s" % getattr(damage, "MODE", "?"))
chk("损毁：没有「强制/还原档位」那套函数了",
    not hasattr(damage, "force_if_failing"),
    "force_if_failing 还在" if hasattr(damage, "force_if_failing") else "已删除")


def checker_scene():
    """一张有花纹的自发光平面铺满画面：任何"损毁"都必然改变像素。"""
    scene = bpy.context.scene
    for obj in list(bpy.data.objects):
        if obj.type == "MESH":
            bpy.data.objects.remove(obj, do_unlink=True)
    mesh = bpy.data.meshes.new("fw_plane")
    # 平面立在 XZ 面上（法线朝 -Y），相机在 -Y 看 +Y —— 上一版把平面放在 XY 面上，
    # 相机是"侧着看"它，整幅图几乎全黑，像素检查于是变成了一次假通过。
    mesh.from_pydata([(-2, 0, -2), (2, 0, -2), (2, 0, 2), (-2, 0, 2)], [],
                     [(0, 1, 2, 3)])
    mesh.update()
    plane = bpy.data.objects.new("fw_plane", mesh)
    scene.collection.objects.link(plane)
    material = bpy.data.materials.new("fw_checker")
    material.use_nodes = True
    tree = material.node_tree
    tree.nodes.clear()
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    emit = tree.nodes.new("ShaderNodeEmission")
    checker = tree.nodes.new("ShaderNodeTexChecker")
    try:
        checker.inputs["Scale"].default_value = 8.0
    except Exception as error:
        print("INSTALL note: 棋盘 Scale 没设上：%s" % error)
    tree.links.new(checker.outputs["Color"], emit.inputs["Color"])
    tree.links.new(emit.outputs["Emission"], output.inputs["Surface"])
    plane.data.materials.append(material)
    camera_data = bpy.data.cameras.new("fw_dmg_cam")
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = 4.0
    camera = bpy.data.objects.new("fw_dmg_cam", camera_data)
    scene.collection.objects.link(camera)
    camera.location = (0.0, -5.0, 0.0)
    camera.rotation_euler = (1.5707963, 0.0, 0.0)
    scene.camera = camera
    for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            scene.render.engine = engine
            break
        except Exception:
            continue
    scene.render.resolution_x = 160
    scene.render.resolution_y = 160
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    try:
        scene.view_settings.view_transform = "Standard"
    except Exception:
        pass
    return scene


def shoot_pixels(scene, tag):
    path = os.path.join(bpy.app.tempdir, "bvtoon_dmg_%s.png" % tag)
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    image = bpy.data.images.load(path, check_existing=False)
    buffer = list(image.pixels)
    bpy.data.images.remove(image)
    return buffer


def bright_fraction(pixels):
    """画面里"有内容"的像素比例（平均亮度 > 0.05）。用来分辨"损毁"和"黑屏"。"""
    bright = 0
    for index in range(0, len(pixels), 4):
        if (pixels[index] + pixels[index + 1] + pixels[index + 2]) / 3.0 > 0.05:
            bright += 1
    return bright / max(1, len(pixels) // 4)


def sink_fed_by(scene):
    """合成器的输出插槽现在吃的是哪个节点的输出（名字）。"""
    tree = module.bv_glow.existing_tree(scene)
    if tree is None:
        return None
    api = "compositing_node_group" if hasattr(scene, "compositing_node_group") \
        else "use_nodes"
    socket = module.bv_glow._sink_input(module.bv_glow._sink(tree, api))
    if socket is None or not socket.is_linked:
        return "<没有连线>"
    return socket.links[0].from_node.name


dmg_scene = checker_scene()
ok_pixels = shoot_pixels(dmg_scene, "ok")
chk("损毁：正常态没接损毁节点（画面照常）", damage.find_node(dmg_scene) is None)
chk("损毁：正常态画面有内容（不是黑屏）", bright_fraction(ok_pixels) > 0.05,
    "%.1f%% 的像素有内容" % (100.0 * bright_fraction(ok_pixels)))
chk("损毁：正常态合成器输出没走损毁节点",
    sink_fed_by(dmg_scene) in (None, "<没有连线>", "Render Layers"),
    str(sink_fed_by(dmg_scene)))

with open(os.path.join(addon_dir, "bv_glow.py"), "a", encoding="utf-8") as handle:
    handle.write("\n# damage pixel test\n")
bad_pixels = shoot_pixels(dmg_scene, "modified")
node = damage.find_node(dmg_scene)
chk("损毁：被改后合成器里接上了损毁节点", node is not None)
# 关键两条：光"节点存在"或"图变了"都不够 —— 合成器被弄坏（空输入=黑屏）也会让图变。
# 上一版就是这样假通过的（图变了 21.7%，其实画面是空的），所以这里必须查接线。
chk("损毁：合成器的输出改由损毁节点供图",
    sink_fed_by(dmg_scene) == "bv_integrity_damage", str(sink_fed_by(dmg_scene)))
wired_in = 0
if node is not None:
    RGBA_IN = [s for s in node.inputs if s.type == "RGBA"]
    wired_in = len(RGBA_IN[0].links) if RGBA_IN else 0
chk("损毁：损毁节点自己的输入也接着（上游没丢）", wired_in >= 1, str(wired_in))
chk("损毁：损毁态还有画面（是马赛克，不是黑屏/空合成）",
    bright_fraction(bad_pixels) > 0.02,
    "%.1f%% 的像素有内容" % (100.0 * bright_fraction(bad_pixels)))
changed = 0
for index in range(0, len(ok_pixels), 4):
    if max(abs(ok_pixels[index + channel] - bad_pixels[index + channel])
           for channel in range(3)) > 0.05:
        changed += 1
ratio = changed / max(1, len(ok_pixels) // 4)
chk("损毁：被改后画面被毁（像素级，没有档位可调）", ratio > 0.05,
    "%.1f%% 的像素变了" % (100.0 * ratio))

integrity.write_manifest(addon_dir, version)          # 复原
module.force_watermark(dmg_scene)
chk("损毁：恢复清单后不再损毁", damage.factor_for("ok") == 0.0)
chk("损毁：恢复后合成器输出不再由损毁节点供图",
    sink_fed_by(dmg_scene) != "bv_integrity_damage", str(sink_fed_by(dmg_scene)))

print("INSTALL_SUMMARY failures=%d" % len(FAIL))
for item in FAIL:
    print("INSTALL_FAIL", item)
print("INSTALL_END")
sys.exit(1 if FAIL else 0)
'''


def find_blenders():
    """机器上所有 Blender（两个版本都要测：API 差异是这项目的老坑）。"""
    roots = [os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                          "Blender Foundation"),
             os.environ.get("ProgramFiles", r"C:\Program Files")]
    found = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for pattern in ("Blender */blender.exe", "XF Blender*/blender.exe"):
            found.extend(glob.glob(os.path.join(root, pattern)))
    seen, unique = set(), []
    for path in sorted(found):
        real = os.path.realpath(path).lower()
        if real not in seen:
            seen.add(real)
            unique.append(path)
    return unique


def verify(zip_path, blender, source):
    """在一次性配置里真装一遍，跑完整的三态实测。"""
    integrity = load_integrity_module(source)
    scratch = tempfile.mkdtemp(prefix="bvtoon_pkg_")
    script = os.path.join(scratch, "verify_zip.py")
    with open(script, "w", encoding="utf-8") as handle:
        handle.write(VERIFY_SCRIPT
                     .replace("__VERSION__", addon_version(source) or "")
                     .replace("__CREDIT_OK__", "渲染 BVToon / @BVan")
                     .replace("__CREDIT_MODIFIED__", integrity.CREDIT_MODIFIED)
                     .replace("__CREDIT_UNVERIFIED__", integrity.CREDIT_UNVERIFIED))
    env = dict(os.environ,
               BLENDER_USER_CONFIG=os.path.join(scratch, "config"),
               BLENDER_USER_SCRIPTS=os.path.join(scratch, "scripts"),
               BLENDER_USER_EXTENSIONS=os.path.join(scratch, "extensions"))
    for folder in ("config", "scripts", "extensions"):
        os.makedirs(os.path.join(scratch, folder), exist_ok=True)
    print("  verifying with %s（一次性配置）" % blender)
    process = subprocess.run([blender, "-b", "--factory-startup",
                              "--python", script, "--", zip_path],
                             env=env, capture_output=True, text=True,
                             encoding="utf-8", errors="replace")
    for line in (process.stdout or "").splitlines():
        if line.startswith("INSTALL"):
            print("    " + line)
    for line in (process.stderr or "").splitlines():
        if "Error" in line or "Traceback" in line:
            print("    stderr:", line)
    shutil.rmtree(scratch, ignore_errors=True)
    if process.returncode != 0:
        tail = "\n".join((process.stdout or "").splitlines()[-6:])
        print("    verify FAILED (%s)\n%s" % (blender, tail))
    return process.returncode == 0


def main():
    # Windows 控制台常常是 GBK：打印不进去的字符（✓ ⚠ 之类）会直接抛
    # UnicodeEncodeError 把整个脚本打断 —— 本工具就被这个坑过一次（复现性自检明明过了，
    # 却倒在"打印结果"那一行）。宁可打成 ?，也别崩。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=None,
                        help="插件源码目录（默认 clean-room\\BV-Toon）")
    parser.add_argument("--out", default=DIST)
    parser.add_argument("--tag", default=None,
                        help="版本 tag，默认取 bl_info；与 bl_info 不一致会拒绝")
    parser.add_argument("--check", action="store_true",
                        help="只检查已打好的 zip（不给路径时取 dist 里最新的一个）")
    parser.add_argument("--zip", default=None, help="--check 要检查的 zip")
    parser.add_argument("--verify", action="store_true",
                        help="在每个 Blender 里真装一遍并实测几种状态")
    parser.add_argument("--blender", default=None,
                        help="只用一个 Blender 验证（默认全都用）")
    args = parser.parse_args()

    source = args.source or default_source()
    print("source:", source)

    if args.check:
        if args.zip:
            candidates = [args.zip]
        else:
            candidates = sorted(glob.glob(os.path.join(args.out, "*.zip")),
                                key=os.path.getmtime)
        if not candidates:
            print("no zip in %s" % args.out)
            return 1
        path = candidates[-1]
        print("checking %s" % path)
        problems = check_zip(path, source)
        for problem in problems:
            print("  BAD:", problem)
        print("check: %s" % ("ok" if not problems else "%d 个问题" % len(problems)))
        return 1 if problems else 0

    zip_path, tag, problems = build(source, args.out, args.tag)
    if zip_path is None:
        return 1
    problems = check_zip(zip_path, source)
    for problem in problems:
        print("  BAD:", problem)
    if problems:
        return 1

    with open(zip_path, "rb") as handle:
        digest = hashlib.sha256(handle.read()).hexdigest()
    print("  sha256          : %s" % digest)
    print("  安装            : Blender > 编辑 > 偏好设置 > 附加组件 > 右上角 v > 从磁盘安装")

    # 可复现性：同样的源码必须打出同样的 sha（否则记在文档里的 sha256 就是假的）
    with tempfile.TemporaryDirectory(prefix="bvtoon_repro_") as scratch:
        again, _again_tag, _again_problems = build(source, scratch, tag, quiet=True)
        if again is None:
            print("  REFUSING: 复现性自检时第二次打包失败")
            return 1
        with open(again, "rb") as handle:
            second = hashlib.sha256(handle.read()).hexdigest()
    if second != digest:
        print("  REFUSING: 同样的源码打出了不同的 zip（%s != %s）—— "
              "可复现性坏了，别在文档里写这个 sha" % (digest[:12], second[:12]))
        return 1
    print("  可复现          : 两次打包 sha 一致 ok")

    if not args.verify:
        return 0
    blenders = [args.blender] if args.blender else find_blenders()
    if not blenders:
        print("  没找到 Blender，跳过真装验证（--blender 可以指定）")
        return 0
    failed = [path for path in blenders if not verify(zip_path, path, source)]
    if failed:
        print("install test FAILED: %s" % failed)
        return 1
    print("  真装验证通过：%d 个 Blender" % len(blenders))
    return 0


if __name__ == "__main__":
    sys.exit(main())
