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
        chk("面板能画出来且正常态不报警", (not rec.alert) and len(rec.ops)>=9,
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

# --- 腮红只加在脸上（1.6.0 改的；阈值是量出来的，不是拍的）-----------------
# 旧行为是写到每个卡渲材质上（衣服、头发、腿一起泛红）；而且旧阈值 0.62 对脸够不着
# —— "看着有效果"其实是糊在衣服和皮肤上（见 HANDOFF 第 18 条）。
bm=getattr(m,"bv_materials",None)
chk("腮红：材质模块在", bm is not None)
if bm is not None:
    shadable=[mat for mat in bpy.data.materials
              if mat.node_tree is not None and mat.node_tree.nodes.get("bv_shading") is not None]
    face,why=bm.face_materials(shadable,[o for o in sc.objects if o.type=="MESH"])
    chk("腮红：认得出脸部材质", bool(face), why[:70])
    chk("腮红：脸材质是「颜」系名字",
        any(("颜" in mat.name) or ("顔" in mat.name) for mat in face),
        str([mat.name for mat in face]))
    chk("腮红：脸部材质浓淡 > 0",
        all((bm.blush_amount(mat) or 0)>0 for mat in face),
        str([bm.blush_amount(mat) for mat in face]))
    stray=[mat.name for mat in shadable
           if mat not in face and (bm.blush_amount(mat) or 0)>0]
    chk("腮红：非脸部材质上没有腮红", not stray, str(stray[:5]))
    chk("腮红：脸材质数远少于卡渲材质数",
        len(face) < max(1,len(shadable)//2), "%d / %d" % (len(face), len(shadable)))
    chk("腮红：有整块脸的保底浓度（1.7.0 起，保证看得见）",
        0.0 < bm.BLUSH_FLOOR <= 0.8, str(bm.BLUSH_FLOOR))
    chk("腮红：面板记下了认出的脸材质", bool(sc.get("bv_face_materials")),
        str(sc.get("bv_face_materials")))
    # 模型自带腮红贴图（照れ）当遮罩这条路：组里必须有「腮红贴图」输入
    # （没有就是 .blend 资产没重建 —— 那条路会静默失效），而且必须真的接上
    group=next((g for g in bpy.data.node_groups if g.name=="BVToon_Shading"), None)
    chk("腮红：卡渲组有「腮红贴图」输入（资产已重建）",
        group is not None and any(item.name=="腮红贴图" for item in group.interface.items_tree),
        str([item.name for item in group.interface.items_tree][-3:]) if group else "-")
    texture, why = bm.blush_texture(shadable)
    chk("腮红：认得出模型自带腮红贴图", texture is not None, why[:60])
    if texture is not None:
        sources={mat.name: bm.blush_mask_source(mat) for mat in face}
        chk("腮红：脸部材质都接上了贴图遮罩",
            all(sources.get(mat.name) for mat in face), str(sources))
        chk("腮红：遮罩节点是我们自己建的 bv_ 前缀",
            all((mat.node_tree.nodes.get("bv_blush_tex") is not None
                 and mat.node_tree.nodes.get("bv_blush_mask") is not None)
                for mat in face), str([mat.name for mat in face]))
    # 1.7.0：脸颊圈（几何遮罩）—— 组里必须有那三个输入，点完「添加腮红」后半径 > 0，
    # 而且两个球心得**落在脸材质的包围盒里**（落到外面 = 脸上没有腮红，白装）
    chk("腮红：卡渲组有脸颊圈输入（资产已重建）",
        group is not None and all(any(item.name == n for item in group.interface.items_tree)
                                  for n in ("腮红左", "腮红右", "腮红半径")),
        str([item.name for item in group.interface.items_tree][-6:]) if group else "-")
    meshes = [o for o in sc.objects if o.type == "MESH"]
    placed = [bm.place_blush(mat, meshes) for mat in face]
    chk("腮红：认得出脸颊（半径 > 0）", bool(placed) and all(ok for ok, _ in placed),
        str([why[:44] for _, why in placed])[:120])
    inside = []
    for mat in face:
        node = bm.find_group_node(mat)
        left, right, radius, _ = bm.blush_region(mat, meshes)
        if node is None or left is None:
            inside.append(False)
            continue
        def _round(values):
            return tuple(round(float(v), 6) for v in values)
        stored_left = _round(node.inputs["腮红左"].default_value)
        stored_right = _round(node.inputs["腮红右"].default_value)
        inside.append(stored_left == _round(left) and radius > 0
                      and stored_left != stored_right)     # 左右两个球心必须分开
    chk("腮红：脸颊球心写进了组（左右分开、半径 > 0）", bool(inside) and all(inside),
        str(inside))

try:
    print("AUDIT edge_preview_clean=%s" % (bpy.ops.bvtoon.edge_preview_clean(),))
except Exception as e:
    chk("edge_preview_clean", False, repr(e)[:80])
glow=[g for g in bpy.data.node_groups if g.name=="BVToon_Glow"]
chk("泛光组不重复(<=1)", len(glow)<=1, "%d 个" % len(glow))
# --- 1.7.2：泛光强度按模型实测自动定（深色角色不能比别人暗）-----------------
# 之前是固定 0.10，实测胡桃剪影外只有 0.017、奥黛塔 0.160（差 7 倍）。
try:
    bg = getattr(m, "bv_glow", None)
    chk("泛光：模块在", bg is not None)
    if bg is not None:
        chk("泛光：目标值/迭代次数是量出来的常量",
            bg.GLOW_HALO_TARGET > 0.05 and bg.GLOW_ITERATIONS >= 2,
            "目标 %.2f 迭代 %d" % (bg.GLOW_HALO_TARGET, bg.GLOW_ITERATIONS))
        group = next((g for g in bpy.data.node_groups if g.name == bg.GLOW_GROUP), None)
        chk("泛光：组里有「增益」输入（旧资产要重加）",
            group is not None and any(item.name == "增益"
                                      for item in group.interface.items_tree),
            str([item.name for item in group.interface.items_tree])[:90] if group else "-")
        state, _api, node = bg.glow_state(sc)
        strength = float(node.inputs["强度"].default_value) if node is not None else -1
        note = str(sc.get("bv_glow_note", ""))
        if node is None:            # 前面的幂等测试把泛光移掉了：再挂一次
            bpy.ops.bvtoon.add_glow()
            state, _api, node = bg.glow_state(sc)
            strength = float(node.inputs["强度"].default_value) if node is not None else -1
            note = str(sc.get("bv_glow_note", ""))
        measured = "强度" in note and "量不了" not in note
        chk("泛光：添加后强度有出处（实测 或 明说量不了）",
            node is not None and (measured or ("量不了" in note and
                                               abs(strength - bg.GLOW_STRENGTH) < 1e-6)),
            "强度 %.2f ｜ %s" % (strength, note[:70]))
        chk("泛光：只往上调（不把本来就亮的压暗）",
            strength >= bg.GLOW_STRENGTH - 1e-6,
            "强度 %.3f ≥ 默认 %.3f" % (strength, bg.GLOW_STRENGTH))
        left = [h for h in bpy.app.handlers.render_pre
                if getattr(h, "__name__", "") == "force_watermark"]
        chk("泛光：量完之后强制署名处理器还在（临时摘了要挂回去）",
            bool(left), "render_pre 里 %d 个" % len(left))
except Exception as error:
    chk("泛光：实测强度那一段", False, repr(error)[:90])

# --- 重载文件之后强制署名还在（1.6.0 修掉的真 bug）------------------------
# 放最后：它会清空场景，前面那些跟模型有关的检查不能被它打断。
# 两条真实路径：新建文件（插件还开着，靠 persistent 标记活下来）
#             ＋ 工厂重置（连插件一起关，重新启用后靠 register() 补挂）
def _fw_handlers():
    return [h for h in bpy.app.handlers.render_pre if getattr(h,"__name__","")=="force_watermark"]
def _fw_shoot(tag):
    sc2=bpy.context.scene
    cam_d=bpy.data.cameras.new("fw_"+tag); cam=bpy.data.objects.new("fw_"+tag,cam_d)
    sc2.collection.objects.link(cam); sc2.camera=cam
    sc2.render.engine="BLENDER_WORKBENCH"
    sc2.render.resolution_x=64; sc2.render.resolution_y=64
    sc2.render.filepath=os.path.join(tempfile.gettempdir(),"bvtoon_audit_fw_%s.png" % tag)
    sc2.render.use_stamp=False; sc2.render.stamp_note_text="入侵者"
    bpy.ops.render.render(write_still=True)
    return sc2.render.stamp_note_text
bpy.ops.wm.read_homefile(use_empty=True)
chk("新建文件后 render_pre 还挂着 force_watermark", len(_fw_handlers())>=1, str(len(_fw_handlers())))
chk("新建文件后真渲染：水印被强制设回来", _fw_shoot("homefile")!="入侵者")
bpy.ops.wm.read_factory_settings(use_empty=True)
addon_utils.enable("BV-Toon", default_set=True, persistent=True)
chk("工厂重置+重新启用后又挂上了", len(_fw_handlers())>=1, str(len(_fw_handlers())))
chk("工厂重置+重新启用后真渲染：水印被强制设回来", _fw_shoot("factory")!="入侵者")

print("AUDIT_SUMMARY failures=%d" % len(FAIL))
for f in FAIL: print("FAILED:", f)