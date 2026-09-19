# -*- coding: utf-8 -*-
"""生成 BV-Toon 的资产 .blend（卡渲节点组）。

    blender -b --python tools/build_assets.py -- [--out <插件目录>]

自研版现在和"逆向版"一个套路：着色节点组装在 `.blend` 里，套用时 append 进来。
这个脚本用插件自己的 `bv_shading.build_shading_group()` 现场搭出节点组，
存进 `<插件>/BVToonData/BVToonShading.blend`，并**打上假用户**（没有使用者的
节点组保存时会被 Blender 丢掉 —— 之前 MFace 就是这么丢的）。

生成后：重新打包 zip，插件就能从资产加载；资产缺失时会自动回退到现场建组。
"""

import argparse
import importlib.util
import os
import sys

import bpy

WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_module(package_dir):
    spec = importlib.util.spec_from_file_location(
        "BVToon_assets", os.path.join(package_dir, "__init__.py"),
        submodule_search_locations=[package_dir])
    module = importlib.util.module_from_spec(spec)
    sys.modules["BVToon_assets"] = module
    spec.loader.exec_module(module)
    return module


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", default=os.path.join(WORKSPACE, "clean-room",
                                                           "BV-Toon"))
    args = parser.parse_args(argv)

    module = load_module(args.package)
    shading = importlib.import_module("BVToon_assets.bv_shading")

    asset_dir = os.path.join(args.package, shading.ASSET_DIR)
    os.makedirs(asset_dir, exist_ok=True)
    asset = os.path.join(asset_dir, shading.ASSET_NAME)

    # 干净起步：只留我们自己的组
    for group in list(bpy.data.node_groups):
        bpy.data.node_groups.remove(group)
    group = shading.build_shading_group()
    group.use_fake_user = True
    sockets = [item for item in group.interface.items_tree
               if item.item_type == "SOCKET"]
    print("BUILD_ASSETS group=%s nodes=%d sockets=%d"
          % (group.name, len(group.nodes), len(sockets)))
    bpy.ops.wm.save_as_mainfile(filepath=asset)
    print("BUILD_ASSETS saved=%s  (%.1f KB)"
          % (asset, os.path.getsize(asset) / 1024.0))

    # 存完再读回来确认它真的在文件里（假用户那条就是为这个）。
    # 注意：存完之后这个路径就是"当前文件"，Blender 不允许从当前文件 append，
    # 所以先切到一个空文件再读。
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for group in list(bpy.data.node_groups):
        bpy.data.node_groups.remove(group)
    with bpy.data.libraries.load(asset, link=False) as (source, target):
        names = list(source.node_groups)
    print("BUILD_ASSETS contents=%s" % names)
    print("BUILD_ASSETS_END" if shading.SHADING_GROUP in names
          else "BUILD_ASSETS_FAILED")


main()
