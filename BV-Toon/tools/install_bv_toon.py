# -*- coding: utf-8 -*-
"""把 clean-room 的 BV-Toon 装进本机每个 Blender（幂等）。

    python tools/install_bv_toon.py                 # 装进找到的每个 BV-Toon 副本
    python tools/install_bv_toon.py --check         # 只报告会改什么，不写盘
    python tools/install_bv_toon.py --target <dir>  # 只装一个指定目录（不存在就建）
    python tools/install_bv_toon.py --selftest      # 在临时目录里证明这个脚本本身可信

用任意 Python 3 跑，不需要 Blender。

装的时候做三件事：

1. 把 ``clean-room\\BV-Toon`` 的文件同步过去（内容相同就不动，保持幂等）
2. **删掉目标目录里多出来的顶层 ``.py``**（旧版本的残留会跟着被加载，实测踩过）
3. **在目标目录重新生成** ``BVToonData/integrity.json``

第 3 步是要紧的：清单必须描述**装上去的那些字节**。少了它，装完的副本会被自己的
完整性校验判成「未验证副本」，水印就不对了。（生成与校验共用插件里的
``bv_integrity``，规则只有一份。）
"""

import argparse
import ast
import importlib.util
import os
import re
import shutil
import sys

WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SOURCE_CANDIDATES = (
    os.path.join(WORKSPACE, "clean-room", "BV-Toon"),
    os.path.join(WORKSPACE, "BV-Toon"),
)

SKIP_DIRS = {"__pycache__", ".git", ".svn", ".idea", ".vscode"}
SKIP_SUFFIX = (".pyc", ".pyo", ".bvtoonorig", ".blend1", ".blend2", ".orig", ".bak")
SKIP_NAMES = {"Thumbs.db", "desktop.ini", ".DS_Store"}

#: 目标目录里不该留的顶层文件（旧版本换模块名时留下的）
STALE_CHECK_SUFFIX = ".py"


def default_source():
    for candidate in SOURCE_CANDIDATES:
        if os.path.isfile(os.path.join(candidate, "__init__.py")):
            return candidate
    return SOURCE_CANDIDATES[0]


def load_integrity_module(source):
    path = os.path.join(source, "bv_integrity.py")
    if not os.path.isfile(path):
        return None
    spec = importlib.util.spec_from_file_location("bv_integrity_installed", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_bytes(path):
    with open(path, "rb") as handle:
        return handle.read()


def addon_version(root):
    """从某个副本的 __init__.py 读出 bl_info 版本。"""
    init = os.path.join(root, "__init__.py")
    if not os.path.isfile(init):
        return None
    with open(init, "r", encoding="utf-8") as handle:
        found = re.search(r'"version"\s*:\s*\(([^)]*)\)', handle.read())
    if not found:
        return None
    parts = [part.strip() for part in found.group(1).split(",") if part.strip()]
    return ".".join(parts)


def payload(source):
    """要同步的文件：{相对路径: 绝对路径}（清单不在里面 —— 它由目标目录现算）。"""
    files = {}
    for root, dirs, names in os.walk(source):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(names):
            if name in SKIP_NAMES or name.endswith(SKIP_SUFFIX):
                continue
            full = os.path.join(root, name)
            relative = os.path.relpath(full, source).replace("\\", "/")
            if relative == "BVToonData/integrity.json":
                continue
            files[relative] = full
    return files


def addon_dirs():
    """本机每个 Blender 配置里的 BV-Toon 副本。"""
    roaming = os.path.join(os.path.expanduser("~"), "AppData", "Roaming",
                           "Blender Foundation")
    found = []
    if not os.path.isdir(roaming):
        return found
    for product in sorted(os.listdir(roaming)):
        versions = os.path.join(roaming, product)
        if not os.path.isdir(versions):
            continue
        for version in sorted(os.listdir(versions)):
            candidate = os.path.join(versions, version, "scripts", "addons", "BV-Toon")
            if os.path.isfile(os.path.join(candidate, "__init__.py")):
                found.append(candidate)
    return found


def stale_top_level(target, files):
    """目标目录里多出来的顶层 .py（不在这次要装的清单里）。"""
    if not os.path.isdir(target):
        return []
    known = set(files)
    found = []
    for name in sorted(os.listdir(target)):
        path = os.path.join(target, name)
        if name.endswith(STALE_CHECK_SUFFIX) and os.path.isfile(path) \
                and name not in known:
            found.append(name)
    return found


def plan(target, source):
    """(要复制的文件, 要删的残留)；不写盘。"""
    files = payload(source)
    todo = []
    for relative in sorted(files):
        dst = os.path.join(target, relative.replace("/", os.sep))
        if not os.path.isfile(dst) or read_bytes(files[relative]) != read_bytes(dst):
            todo.append(relative)
    return todo, stale_top_level(target, files)


def manifest_state(target, source):
    """目标目录里清单现在对不对（只读，不写盘）。返回 "ok" 或一句原因。"""
    integrity = load_integrity_module(source)
    if integrity is None:
        return "源码里没有 bv_integrity.py"
    if not os.path.isdir(target):
        return "目标目录不存在"
    manifest, error = integrity.load_manifest(target)
    if error:
        return error
    report = integrity.verify(target)
    if report["state"] != integrity.STATE_OK:
        return "清单与实际文件对不上：%s" % report["reason"]
    version = addon_version(target)
    listed = manifest.get("addon_version")
    if listed not in (None, "", version):
        return "清单版本 %s 与插件 %s 不一致" % (listed, version)
    return "ok"


def install(target, source, check=False, quiet=False):
    """把一个副本装成当前 clean-room 版本。返回 (结果, 明细)。"""
    files = payload(source)
    todo, stale = plan(target, source)
    if check:
        return ("would-install" if (todo or stale) else "ok"), (todo, stale)
    os.makedirs(target, exist_ok=True)
    for name in stale:
        os.remove(os.path.join(target, name))
        if not quiet:
            print("  removed   %s/%s（旧版本残留）" % (target, name))
    for relative in todo:
        dst = os.path.join(target, relative.replace("/", os.sep))
        folder = os.path.dirname(dst)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)
        shutil.copy2(files[relative], dst)
    cache = os.path.join(target, "__pycache__")
    if os.path.isdir(cache):
        shutil.rmtree(cache, ignore_errors=True)
    integrity = load_integrity_module(source)
    version = None
    if integrity is not None:
        version = integrity.build_manifest(source).get("addon_version")
        integrity.write_manifest(target, version)
    # 装完必须自证：清单写得对不对，用同一套规则查一遍
    state = manifest_state(target, source)
    if not quiet:
        print("  %-9s %s（复制 %d 个文件，删残留 %d 个，清单=%s）"
              % ("installed" if todo or stale else "ok", target, len(todo),
                 len(stale), state))
    return ("installed" if todo or stale else "ok"), (todo, stale)


def selftest(source):
    """在临时目录里证明这个脚本可信（装 / 幂等 / 删残留 / 清单自证）。"""
    import tempfile
    scratch = tempfile.mkdtemp(prefix="bvtoon_install_")
    target = os.path.join(scratch, "BV-Toon")
    checks = []

    def check(name, ok, detail=""):
        checks.append((name, bool(ok)))
        print("  [%s] %s%s" % ("ok  " if ok else "FAIL", name,
                               ("  (%s)" % detail) if detail else ""))

    integrity = load_integrity_module(source)
    state, (todo, stale) = install(target, source, quiet=True)
    check("第一次装：文件都过去了", state == "installed" and len(todo) >= 10,
          "%d 个" % len(todo))
    check("第一次装：清单写好了", os.path.isfile(integrity.manifest_path(target)))
    check("第一次装：校验通过", integrity.verify(target)["state"] == integrity.STATE_OK)
    check("第一次装：__init__.py 能解析",
          ast.parse(open(os.path.join(target, "__init__.py"),
                         encoding="utf-8").read()) is not None)

    state, (todo, stale) = install(target, source, quiet=True)
    check("第二次装：什么都不用改（幂等）", state == "ok" and not todo and not stale,
          "todo=%d stale=%d" % (len(todo), len(stale)))

    state, (todo, stale) = install(target, source, check=True, quiet=True)
    check("--check：对得上就报告 ok", state == "ok" and not todo)

    # 篡改：清单要立刻发现
    victim = os.path.join(target, "bv_shading.py")
    with open(victim, "a", encoding="utf-8") as handle:
        handle.write("\n# tampered\n")
    report = integrity.verify(target)
    check("改一个字节 → modified", report["state"] == integrity.STATE_MODIFIED,
          report["state"])
    detail = manifest_state(target, source)
    check("--check 能说清清单对不上", detail != "ok", detail[:60])

    # 旧版本残留的顶层 .py 会被删掉，删完清单重新自证
    leftover = os.path.join(target, "bv_old_module.py")
    with open(leftover, "w", encoding="utf-8") as handle:
        handle.write("# stale module from an older version\n")
    check("残留能被认出来", stale_top_level(target, payload(source)) == ["bv_old_module.py"])
    install(target, source, quiet=True)
    check("残留被删掉", not os.path.isfile(leftover))
    check("重装后校验通过", integrity.verify(target)["state"] == integrity.STATE_OK)

    # 清单缺失 → unverified（这就是"忘了写清单"的后果，所以安装必须写）
    os.remove(integrity.manifest_path(target))
    check("删掉清单 → unverified",
          integrity.verify(target)["state"] == integrity.STATE_UNVERIFIED)
    install(target, source, quiet=True)
    check("重装又把清单补回来", integrity.verify(target)["state"] == integrity.STATE_OK)

    shutil.rmtree(scratch, ignore_errors=True)
    failures = [name for name, ok in checks if not ok]
    print("selftest: %d/%d" % (len(checks) - len(failures), len(checks)))
    return 1 if failures else 0


def main():
    # Windows 控制台常常是 GBK：打印不进去的字符会抛 UnicodeEncodeError 打断脚本。
    # 宁可打成 ?，也别崩（package_bv_toon.py 被这个坑过一次）。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=None,
                        help="插件源码目录（默认 clean-room\\BV-Toon）")
    parser.add_argument("--target", action="append", default=[],
                        help="要装的 addon 目录（可重复；不存在就建）")
    parser.add_argument("--check", action="store_true",
                        help="只报告会改什么，不写盘")
    parser.add_argument("--selftest", action="store_true",
                        help="在临时目录里验证这个脚本本身")
    args = parser.parse_args()

    source = args.source or default_source()
    if args.selftest:
        return selftest(source)

    targets = args.target or addon_dirs()
    print("source :", source)
    if not targets:
        print("没找到 BV-Toon 副本；用 --target 指定一个目录")
        return 1
    results = {}
    for target in targets:
        result, _ = install(target, source, check=args.check)
        results[result] = results.get(result, 0) + 1
    # 装完再逐个自证一遍（清单是不是真的描述了装上去的那些字节）
    for target in targets:
        detail = manifest_state(target, source)
        print("  verify    %s -> %s" % (target, detail))
        if not args.check and detail != "ok":
            print("  FAIL      %s 的完整性自证没通过：%s" % (target, detail))
            return 1
    print("summary:", ", ".join("%s=%d" % item for item in sorted(results.items())))
    if args.check and results.get("would-install"):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
