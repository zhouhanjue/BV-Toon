# -*- coding: utf-8 -*-
r"""检查 github 文件夹里的文档：本地链接有没有断、版本号有没有前后不一致。

    python tools\check_github_docs.py            # 报告
    python tools\check_github_docs.py --strict    # 有问题就 exit 1

查三件事：

1. 每个 ``*.md`` 里指向本仓库文件的 Markdown 链接/图片，目标是否存在
2. 语言切换条：三语文档（README / PUBLISH / MMD-NOTICE / RELEASE-x）三份都要在
3. 版本一致性：当前版本（取插件 ``bl_info``）要出现在 README 三语、PUBLISH 三语、
   最新一份 RELEASE、CHANGELOG；而 README / PUBLISH 里**不能**再指向旧版本
"""
import glob
import os
import re
import sys

WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GITHUB = os.path.join(WORKSPACE, "github", "BV-Toon")
PLUGIN_INIT = os.path.join(WORKSPACE, "clean-room", "BV-Toon", "__init__.py")
LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")

PROBLEMS = []


def note(text):
    PROBLEMS.append(text)
    print("  [FAIL] %s" % text)


def version():
    text = open(PLUGIN_INIT, encoding="utf-8").read()
    found = re.search(r'"version":\s*\((\d+),\s*(\d+),\s*(\d+)\)', text)
    return ".".join(found.groups()) if found else "?"


def check_links():
    print("== 链接 ==")
    for path in sorted(glob.glob(os.path.join(GITHUB, "**", "*.md"), recursive=True)):
        text = open(path, encoding="utf-8").read()
        for target in LINK.findall(text):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            clean = target.split("#")[0].strip()
            if not clean:
                continue
            resolved = os.path.normpath(os.path.join(os.path.dirname(path), clean))
            if not os.path.exists(resolved):
                note("%s -> 链接指不到：%s"
                     % (os.path.relpath(path, GITHUB), target))
    print("  链接检查完成")


def check_trilingual():
    print("== 三语成对 ==")
    stems = set()
    for path in glob.glob(os.path.join(GITHUB, "*.md")):
        name = os.path.basename(path)
        for suffix in (".en.md", ".ja.md"):
            if name.endswith(suffix):
                stems.add(name[:-len(suffix)])
                break
    for stem in sorted(stems):
        for suffix in (".md", ".en.md", ".ja.md"):
            if not os.path.isfile(os.path.join(GITHUB, stem + suffix)):
                note("%s 缺 %s" % (stem, suffix))
    print("  找到 %d 组三语文档：%s" % (len(stems), "、".join(sorted(stems))))


def check_versions():
    print("== 版本号 ==")
    current = version()
    print("  插件里的版本：%s" % current)
    must_have = ["README.md", "README.en.md", "README.ja.md",
                 "PUBLISH.md", "PUBLISH.en.md", "PUBLISH.ja.md",
                 "CHANGELOG.md", "RELEASE-%s.md" % current]
    for name in must_have:
        path = os.path.join(GITHUB, name)
        if not os.path.isfile(path):
            note("缺文件：%s" % name)
            continue
        text = open(path, encoding="utf-8").read()
        if current not in text:
            note("%s 里没有当前版本 %s" % (name, current))
    # README / PUBLISH 不该再指向旧版
    stale = re.compile(r"1\.7\.(?:[01])\b")
    for name in ("README.md", "README.en.md", "README.ja.md",
                 "PUBLISH.md", "PUBLISH.en.md", "PUBLISH.ja.md"):
        path = os.path.join(GITHUB, name)
        if not os.path.isfile(path):
            continue
        text = open(path, encoding="utf-8").read()
        for hit in sorted(set(stale.findall(text))):
            where = [line.strip() for line in text.splitlines() if hit in line]
            note("%s 还提到旧版本 %s：%s" % (name, hit, where[0][:70] if where else ""))
    print("  版本检查完成")


def check_tools():
    print("== tools ==")
    src = os.path.join(WORKSPACE, "tools")
    dst = os.path.join(GITHUB, "tools")
    if not os.path.isdir(dst):
        note("github 里没有 tools\\")
        return
    missing = [name for name in ("install_bv_toon.py", "package_bv_toon.py",
                                 "audit_bv_toon.py", "build_assets.py",
                                 "check_blush_face.py", "check_glow_uniform.py")
               if not os.path.isfile(os.path.join(dst, name))]
    if missing:
        note("github\\tools 里缺：%s" % "、".join(missing))
    for name in sorted(os.listdir(dst)):
        if name.endswith(".py") and not os.path.isfile(os.path.join(src, name)):
            note("github\\tools\\%s 在 tools\\ 里已经没有对应（旧脚本？）" % name)
    print("  tools 里 %d 个脚本" % len([n for n in os.listdir(dst) if n.endswith(".py")]))


def main():
    print("检查 %s" % GITHUB)
    check_links()
    check_trilingual()
    check_versions()
    check_tools()
    print("=" * 60)
    print("CHECK_GITHUB problems=%d" % len(PROBLEMS))
    if PROBLEMS and "--strict" in sys.argv:
        sys.exit(1)


main()
