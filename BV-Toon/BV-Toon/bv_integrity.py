# -*- coding: utf-8 -*-
"""BVToon 完整性校验（哈希防盗）。

打包时（``tools/package_bv_toon.py``）把插件里真正决定行为的文件做成一份
SHA-256 清单 ``BVToonData/integrity.json``，随 zip 一起发出去；插件**加载时**
与**每次渲染前**都拿清单核对一遍，水印按结果分三种：

============  ==================================================================
状态           水印
============  ==================================================================
``ok``         正常署名（面板里那行文字，默认「渲染 BVToon / @BVan」，85% 透明）
``modified``   清单在、但文件对不上 →「未授权修改版 / UNAUTHORIZED MODIFIED COPY」
``unverified`` 清单缺失或读不懂     →「未验证副本 / UNVERIFIED COPY」
============  ==================================================================

为什么要分三态：从 GitHub 源码目录直接拷进 ``addons`` 的人（或者自己改代码的
人）不该被当成盗版 —— 清单是打包产物，源码目录里本来就没有。所以「对不上」才
是修改版，「没有清单」只是未验证。两种都不会再印出「渲染 BVToon / @BVan」。

**这不是加密，也不打算是**：懂行的人能把清单一起重算。它挡的是"随手改个名就说是
自己写的"，以及让改过的副本自己带着标记出门。GPL v3 §7 附加条款第 2 条本来就
要求「修改版必须以合理方式标明与原始版本不同」，这份水印就是那条要求的技术实现：
**只标记、只大声警告，从不阻止渲染**。自己改了代码想让水印恢复正常，重新生成
清单即可（跑一次 ``tools/install_bv_toon.py``，或重新打包）。

清单覆盖：插件根目录下全部顶层 ``.py``（多出一个 ``.py`` 也算改动）
＋ ``BVToonData/BVToonShading.blend``。文档与 ``LICENSE`` 不在范围内。

本模块**不导入 bpy**，所以打包/安装脚本（在 Blender 之外跑）能直接复用同一套
规则 —— 生成端与校验端共用一份 ``tracked()``，不会各写一套然后悄悄对不上。
"""

import hashlib
import json
import os

#: 清单位置（相对插件目录）
MANIFEST_REL = "BVToonData/integrity.json"
#: 卡渲节点组资产，跟 .py 一起受保护
ASSET_REL = "BVToonData/BVToonShading.blend"
#: 清单格式；换规则时改这个字符串，旧清单会被判成"读不懂"（= 未验证）
FORMAT = "bvtoon-integrity/1"
ALGORITHM = "sha256"

STATE_OK = "ok"
STATE_MODIFIED = "modified"
STATE_UNVERIFIED = "unverified"

#: 被改过的副本用的水印（不透明红字，见 __init__.py 的 force_watermark）
CREDIT_MODIFIED = "未授权修改版 / UNAUTHORIZED MODIFIED COPY"
#: 没有清单 / 清单读不懂时用的水印
CREDIT_UNVERIFIED = "未验证副本 / UNVERIFIED COPY"

_CHUNK = 1 << 20
#: (路径, 大小, mtime_ns) -> 摘要。渲染前每次都要校验，不该每次重读 700KB；
#: 文件一改 mtime 就变，缓存自然失效，所以缓存不会掩盖改动。
_CACHE = {}


def package_root():
    """插件目录：本文件所在目录。"""
    return os.path.dirname(os.path.abspath(__file__))


def tracked(root):
    """清单覆盖哪些文件：顶层 ``*.py``（按名字排序）+ 卡渲资产。

    生成端与校验端**都**走这里，所以"什么算插件的一部分"只有一处定义。
    """
    names = []
    try:
        entries = sorted(os.listdir(root))
    except OSError:
        entries = []
    for name in entries:
        if name.endswith(".py") and os.path.isfile(os.path.join(root, name)):
            names.append(name)
    if os.path.isfile(os.path.join(root, ASSET_REL.replace("/", os.sep))):
        names.append(ASSET_REL)
    return names


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def sha256_cached(path):
    """带 (大小, mtime) 缓存的摘要；读不了返回 None。"""
    try:
        info = os.stat(path)
    except OSError:
        return None
    key = (os.path.abspath(path), info.st_size, info.st_mtime_ns)
    digest = _CACHE.get(key)
    if digest is not None:
        return digest
    try:
        digest = sha256_file(path)
    except OSError:
        return None
    if len(_CACHE) > 64:            # 只留最近的一小把，别让它无限长
        _CACHE.clear()
    _CACHE[key] = digest
    return digest


def build_manifest(root, version=None):
    """算出清单。``version`` 只写进去给人看，不参与校验。"""
    files = {}
    for relative in tracked(root):
        path = os.path.join(root, relative.replace("/", os.sep))
        files[relative] = sha256_file(path)
    return {
        "format": FORMAT,
        "algorithm": ALGORITHM,
        "addon_version": version or "",
        "note": ("BVToon 完整性清单：顶层 .py + 卡渲资产的 SHA-256。"
                 "由 tools/package_bv_toon.py 或 tools/install_bv_toon.py 生成。"),
        "files": files,
    }


def dumps(manifest):
    return json.dumps(manifest, ensure_ascii=False, indent=2,
                      sort_keys=True) + "\n"


def manifest_path(root):
    return os.path.join(root, MANIFEST_REL.replace("/", os.sep))


def write_manifest(root, version=None):
    """把清单写进插件目录（安装脚本用；打包脚本直接写进 zip）。"""
    path = manifest_path(root)
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(dumps(build_manifest(root, version)))
    return path


def load_manifest(root):
    """(清单, 读不出来的原因)。成功时原因是 None。"""
    path = manifest_path(root)
    if not os.path.isfile(path):
        return None, "找不到 %s" % MANIFEST_REL
    try:
        with open(path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, ValueError) as error:
        return None, "%s 读不出来：%s" % (MANIFEST_REL, error)
    if not isinstance(manifest, dict):
        return None, "%s 的内容不是一份清单" % MANIFEST_REL
    if manifest.get("format") != FORMAT:
        return None, "%s 的格式是 %r，本版只认 %r" % (
            MANIFEST_REL, manifest.get("format"), FORMAT)
    if not isinstance(manifest.get("files"), dict) or not manifest["files"]:
        return None, "%s 里没有文件表" % MANIFEST_REL
    return manifest, None


def verify(root=None):
    """核对一遍，返回报告。**绝不抛异常**（渲染前要用它，崩了就真渲染不了）。

    报告字段：

    ``state``    ``ok`` / ``modified`` / ``unverified``
    ``credit``   该用的水印文字；``ok`` 时是 None —— 表示"用场景里那行正常署名"
    ``reason``   一句话原因（面板和渲染日志直接显示）
    ``details``  对不上的文件名列表
    ``checked``  核对了几个文件
    ``root``     核对的是哪个目录
    """
    root = root or package_root()
    report = {"state": STATE_UNVERIFIED, "credit": CREDIT_UNVERIFIED,
              "reason": "", "details": [], "checked": 0,
              "version": None, "root": root}
    manifest, error = load_manifest(root)
    if manifest is None:
        report["reason"] = error
        return report
    report["version"] = manifest.get("addon_version") or None
    files = manifest["files"]

    changed, gone, unreadable = [], [], []
    for relative in sorted(files):
        path = os.path.join(root, relative.replace("/", os.sep))
        if not os.path.isfile(path):
            gone.append(relative)
            continue
        digest = sha256_cached(path)
        if digest is None:
            unreadable.append(relative)
        elif digest != files[relative]:
            changed.append(relative)
    # 清单之外多出来的顶层 .py 也算改动（不然"加一个文件"就绕过去了）
    added = sorted(set(tracked(root)) - set(files))
    report["checked"] = len(files)

    if changed or gone or unreadable or added:
        parts = []
        if changed:
            parts.append("被改：%s" % "、".join(changed))
        if gone:
            parts.append("丢失：%s" % "、".join(gone))
        if unreadable:
            parts.append("读不了：%s" % "、".join(unreadable))
        if added:
            parts.append("多出：%s" % "、".join(added))
        report["state"] = STATE_MODIFIED
        report["credit"] = CREDIT_MODIFIED
        report["details"] = changed + gone + unreadable + added
        report["reason"] = "；".join(parts)
        return report

    report["state"] = STATE_OK
    report["credit"] = None
    report["reason"] = "清单核对通过（%d 个文件）" % len(files)
    return report


def state_of(root=None):
    """只要状态字符串（给体检脚本用）。"""
    return verify(root)["state"]


def credit_text(report, fallback):
    """水印文字：正常状态用面板那行署名，异常状态一律用警告文字。

    注意异常状态**不读场景里的自定义署名** —— 否则改一下面板文字就洗白了。
    """
    return report.get("credit") or fallback
