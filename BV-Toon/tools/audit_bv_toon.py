import bpy, addon_utils, sys, os, traceback
FAIL=[]
def chk(name, ok, detail=""):
    print("  [%s] %s%s" % ("ok  " if ok else "FAIL", name, ("  (%s)" % detail) if detail else ""))
    if not ok: FAIL.append(name)
bpy.ops.wm.read_factory_settings(use_empty=True)
for k in ("bl_ext.blender_org.mmd_tools","mmd_tools"):
    try:
        addon_utils.enable(k, default_set=True, persistent=True); break
    except Exception: pass
addon_utils.enable("BV-Toon", default_set=True, persistent=True)
m=sys.modules["BV-Toon"]
print("AUDIT_START version=%s" % (m.bl_info.get("version"),))
sc=bpy.context.scene
chk("bl_info 版本 >= 1.3.1", tuple(m.bl_info.get("version")) >= (1,3,1), str(m.bl_info.get("version")))
chk("场景属性 bv_mode 存在", hasattr(sc,"bv_mode"))
chk("面板在 Toon 标签", getattr(m.BVTOON_PT_panel,"bl_category",None)=="Toon", str(getattr(m.BVTOON_PT_panel,"bl_category",None)))
for op in ("one_click","apply_preset","add_glow","remove_glow","add_blush","set_eye_shadow","edge_preview_create","edge_preview_clean","set_edge_width"):
    chk("操作符 %s 已注册" % op, hasattr(bpy.types,"BVTOON_OT_"+op))
chk("还原操作符已注销", not hasattr(bpy.types,"BVTOON_OT_restore"))
bpy.ops.mmd_tools.import_model(filepath=r"C:\Users\zhouh\Desktop\新建文件夹\奥黛塔 原模型.pmx", scale=0.08, clean_model=True)
objs=[o for o in sc.objects if o.type=="MESH" and getattr(o,"mmd_type","NONE")=="NONE"]
bpy.ops.object.select_all(action='DESELECT')
for o in objs: o.select_set(True)
bpy.context.view_layer.objects.active=objs[0]
sc.bv_mode="REPLACE_MODEL"
print("AUDIT one_click=%s" % (bpy.ops.bvtoon.one_click(),))
chk("一键卡渲后视图变换=Standard", sc.view_settings.view_transform=="Standard", sc.view_settings.view_transform)
stray=[]
for mat in bpy.data.materials:
    if mat.node_tree is None or mat.node_tree.nodes.get("bv_shading") is None: continue
    for n in mat.node_tree.nodes:
        if not n.name.startswith("bv_") and n.bl_idname!="ShaderNodeOutputMaterial":
            stray.append("%s/%s" % (mat.name,n.name))
chk("材质树无非卡渲节点", not stray, str(stray[:4]))
missing=[]
for mat in bpy.data.materials:
    d=getattr(mat,"mmd_material",None)
    if d is None or mat.node_tree is None or mat.node_tree.nodes.get("bv_shading") is None: continue
    if getattr(d,"toon_texture","") or getattr(d,"is_shared_toon_texture",False):
        if mat.node_tree.nodes.get("bv_toon_mask") is None: missing.append(mat.name)
chk("有渐变贴图的材质都建了查表链", not missing, str(missing[:4]))
# 每个操作符各点一次，抓异常
for op, kw in (("add_glow",{}),("add_glow",{}),("remove_glow",{}),("remove_glow",{}),
               ("add_blush",{}),("set_eye_shadow",{}),("set_edge_width",{}),
               ("edge_preview_create",{}),("one_click",{})):
    try:
        r=getattr(bpy.ops.bvtoon,op)(**kw)
        chk("调用 %s -> %s" % (op, tuple(r)), "FINISHED" in r)
    except Exception as e:
        chk("调用 %s" % op, False, repr(e)[:90])
edges=sum(1 for o in bpy.data.objects for mm in o.modifiers if "edge" in mm.name.lower())
print("AUDIT 描边修改器=%d 描边材质=%d" % (edges, len([x for x in bpy.data.materials if x.name.startswith("mmd_edge")])))
try:
    print("AUDIT edge_preview_clean=%s" % (bpy.ops.bvtoon.edge_preview_clean(),))
except Exception as e:
    chk("edge_preview_clean", False, repr(e)[:80])
glow=[g for g in bpy.data.node_groups if g.name=="BVToon_Glow"]
chk("泛光组不重复(<=1)", len(glow)<=1, "%d 个" % len(glow))
print("AUDIT_SUMMARY failures=%d" % len(FAIL))
for f in FAIL: print("FAILED:", f)