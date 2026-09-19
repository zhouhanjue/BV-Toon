import bpy, addon_utils, sys, os, shutil, tempfile, traceback
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
chk("bl_info 版本 >= 1.6.0", tuple(m.bl_info.get("version")) >= (1,6,0), str(m.bl_info.get("version")))
chk("场景属性 bv_mode 存在", hasattr(sc,"bv_mode"))
chk("面板在 Toon 标签", getattr(m.BVTOON_PT_panel,"bl_category",None)=="Toon", str(getattr(m.BVTOON_PT_panel,"bl_category",None)))

# --- 完整性校验（哈希防盗）：三态 + 水印 + 面板告警 ------------------------
integ=getattr(m,"bv_integrity",None)
chk("完整性校验模块已随插件加载", integ is not None)
if integ is not None:
    addon_dir=os.path.dirname(os.path.abspath(m.__file__))
    rep=integ.verify(addon_dir)
    chk("已装副本：清单核对通过", rep["state"]==integ.STATE_OK, "%s / %s" % (rep["state"], rep["reason"]))
    chk("已装副本：清单在 BVToonData 下", os.path.isfile(integ.manifest_path(addon_dir)), integ.MANIFEST_REL)
    chk("清单覆盖 = 顶层 .py + 卡渲资产",
        rep["checked"]==len(integ.tracked(addon_dir)),
        "%d/%d" % (rep["checked"], len(integ.tracked(addon_dir))))
    scratch=tempfile.mkdtemp(prefix="bvtoon_audit_")
    copy=os.path.join(scratch,"BV-Toon")
    try:
        shutil.copytree(addon_dir, copy, ignore=shutil.ignore_patterns("__pycache__"))
        integ.write_manifest(copy, ".".join(str(p) for p in m.bl_info["version"]))
        chk("临时副本：写好清单即 ok", integ.verify(copy)["state"]==integ.STATE_OK)
        with open(os.path.join(copy,"bv_util.py"),"a",encoding="utf-8") as fh:
            fh.write("\n# audit tamper\n")
        rep=integ.verify(copy)
        chk("改一个字节 -> modified", rep["state"]==integ.STATE_MODIFIED, rep["reason"][:70])
        chk("被改时水印 = 未授权修改版",
            integ.credit_text(rep,"x")==integ.CREDIT_MODIFIED, integ.credit_text(rep,"x"))
        os.remove(integ.manifest_path(copy))
        rep=integ.verify(copy)
        chk("删掉清单 -> unverified", rep["state"]==integ.STATE_UNVERIFIED, rep["reason"][:70])
        chk("无清单时水印 = 未验证副本",
            integ.credit_text(rep,"x")==integ.CREDIT_UNVERIFIED, integ.credit_text(rep,"x"))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    m.force_watermark(sc)
    chk("渲染前水印 = 默认署名", sc.render.stamp_note_text=="渲染 BVToon / @BVan", sc.render.stamp_note_text)
    chk("正常态水印 85% 透明 + 无底框",
        abs(sc.render.stamp_foreground[3]-0.15)<1e-6 and sc.render.stamp_background[3]==0.0,
        str(tuple(sc.render.stamp_foreground)))
    chk("render_pre 挂着 force_watermark",
        any(getattr(h,"__name__","")=="force_watermark" for h in bpy.app.handlers.render_pre))
    # 面板绘制（正常态不该报警；这段也顺带证明 draw() 里的完整性查询不会崩）
    class _Rec(object):
        def __init__(self):
            object.__setattr__(self,"alert",False); object.__setattr__(self,"labels",[]); object.__setattr__(self,"ops",[])
        def __setattr__(self,n,v):
            if n=="alert" and v: object.__setattr__(self,"alert",True)
            else: object.__setattr__(self,n,v)
        def box(self,**k): return self
        def row(self,**k): return self
        def column(self,**k): return self
        def label(self,**k): self.labels.append(k.get("text","")); return None
        def prop(self,*a,**k): return None
        def operator(self,i,**k): self.ops.append(i); return type("Op",(),{})()
    rec=_Rec()
    try:
        m.BVTOON_PT_panel.draw(type("Panel",(),{"layout":rec})(), bpy.context)
        # 面板上的按钮数：腮红那组已经按要求删掉（作者：去除腮红功能），
        # 所以门槛从 9 降到 8 —— 不是"少画了一个"，是那个功能不存在了。
        chk("面板能画出来且正常态不报警", (not rec.alert) and len(rec.ops)>=8,
            "alert=%s ops=%d" % (rec.alert, len(rec.ops)))
    except Exception as error:
        chk("面板能画出来且正常态不报警", False, repr(error)[:80])

# --- 「损毁画面」（校验不过时把画面弄坏）----------------------------------
dmg=getattr(m,"bv_damage",None)
chk("损毁模块已随插件加载", dmg is not None)
if dmg is not None:
    def _dmg_factor():
        node=dmg.find_node(sc)
        if node is None: return None
        for s in node.inputs:
            if s.type=="VALUE": return round(float(s.default_value),3)
        return None
    chk("损毁：面板档位属性已删除（没有可选项）",
        not hasattr(sc,"bv_damage_mode"),
        str([n for n in dir(sc) if "damage" in n]))
    chk("损毁：正常态不接损毁节点", dmg.find_node(sc) is None)
    chk("损毁：损毁强度表（被改/未验证 → 1，通过 → 0）",
        (dmg.factor_for("modified")==1.0 and dmg.factor_for("unverified")==1.0
         and dmg.factor_for("ok")==0.0),
        "modified=%s unverified=%s ok=%s" % (dmg.factor_for("modified"),
                                             dmg.factor_for("unverified"),
                                             dmg.factor_for("ok")))
    chk("损毁：模块里没有可选档位（ITEMS/MODE_OFF/effective_mode 都没了）",
        (not hasattr(dmg,"ITEMS") and not hasattr(dmg,"MODE_OFF")
         and not hasattr(dmg,"effective_mode") and getattr(dmg,"MODE",None)=="ALL"),
        "MODE=%s" % getattr(dmg,"MODE","?"))
    try:
        dmg.enforce(sc, {"state":"modified"})
        chk("损毁：被改 → 接上损毁节点且强度=1", _dmg_factor()==1.0, str(_dmg_factor()))
        dmg.enforce(sc, {"state":"ok"})
        chk("损毁：恢复正常 → 损毁节点被摘掉（接线还原）",
            dmg.find_node(sc) is None, str(_dmg_factor()))
        chk("损毁：摘得掉", dmg.remove(sc) is False)
    except Exception as error:
        chk("损毁：接进合成器", False, repr(error)[:80])
    # 说清楚：档位那套（DEFAULT_MODE 之类）1.7.0 已经整项删除，别再按老接口调

for op in ("one_click","apply_preset","add_glow","remove_glow","set_eye_shadow","edge_preview_create","edge_preview_clean","set_edge_width"):
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
# 每个操作符各点一次，抓异常。两点说明（2026-09-20 修）：
# * 重复调用（第二次 add_glow / remove_glow）本来就该返回 CANCELLED —— 没东西可摘；
# * 「目影」要模型里真有名字带「目影」的材质才 FINISHED，奥黛塔没有，CANCELLED 是对的。
# 所以只对**首次**调用要求 FINISHED，其余只要求"不抛异常、结果别是空的"。
SOFT_OPS={"set_eye_shadow"}
seen=set()
for op, kw in (("add_glow",{}),("add_glow",{}),("remove_glow",{}),("remove_glow",{}),
               ("set_eye_shadow",{}),("set_edge_width",{}),
               ("edge_preview_create",{}),("one_click",{})):
    try:
        r=getattr(bpy.ops.bvtoon,op)(**kw)
        first = op not in seen
        seen.add(op)
        if first and op not in SOFT_OPS:
            ok = "FINISHED" in r
        else:
            ok = ("FINISHED" in r) or ("CANCELLED" in r)
        chk("调用 %s -> %s" % (op, tuple(r)), ok)
    except Exception as e:
        chk("调用 %s" % op, False, repr(e)[:90])
edges=sum(1 for o in bpy.data.objects for mm in o.modifiers if "edge" in mm.name.lower())
print("AUDIT 描边修改器=%d 描边材质=%d" % (edges, len([x for x in bpy.data.materials if x.name.startswith("mmd_edge")])))
# 腮红功能已按要求移除（作者：去除腮红功能），相关断言一并删除。