# # # # # # # # # # # # # # # # # # # # # # # #
#                                             #
#    © 2025 BVan / DEEPSEEK                     #
#                                             #
# # # # # # # # # # # # # # # # # # # # # # # #


bl_info = {
    "name": "BV-Toon",
    "author": "BVan / DEEPSEEK",
    "version": (1, 0, 0),
    "blender": (3, 6, 0),
    "location": "3D视图 > N 面部 > 卡渲",
    "description": "Blender 一键卡渲插件（MMD 模型）。",
    "category": "Material",
    "support": "COMMUNITY",
}


import bpy
import json
import os
import sys
import mathutils
from bpy.types import Operator

MIAO_FACE_FOLDER = os.path.join(os.path.dirname(__file__), "BVToonData")

class BVTOONPresetPanel(bpy.types.Panel):
    bl_label = "Blender一键卡渲插件"
    bl_idname = "BVTOON_PT_BVToonPreset"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = '卡渲'

    def draw(self, context):
        layout = self.layout
        
        box = layout.box()
        box.prop(context.scene, "bvtoon_mode", text="")
        box.label(text="卡渲预设", icon='FUND')

        preset_data = load_preset_data() 
        
        if preset_data:
            for i, preset in enumerate(preset_data.get("presets", [])):
                if i % 2 == 0:
                    row = box.row()  
                row.operator("bvtoon.apply_preset", text=preset["name"]).preset_index = i
        layout.label(text="MMD 设置")
        box1 = layout.box()
        row = box1.row(align=True)
        row.operator("bvtoon.edge_preview_create", text="MMD 边缘预览", icon='ANTIALIASED')
        row.operator("bvtoon.edge_preview_clean", text="",icon='TRASH')
        row = box1.row(align=True)
        row.operator("bvtoon.convert_materials", text="MMD 转换给Blender",icon='BLENDER')
        row = box1.row(align=True)
        row.operator("bvtoon.set_eye_shadow", text="MMD 设置目影",icon="HIDE_OFF")
        layout.label(text="其他设置")
        box2 = layout.box()
        row = box2.row(align=True)
        row.operator("bvtoon.import_lighting", text="导入灯光环境(场景)", icon="LIGHT")
        row = box2.row(align=True)
        row.operator("bvtoon.add_blush", text="添加腮红",icon="OVERLAY")
        row = box2.row(align=True)
        row.operator("bvtoon.add_geom_stroke", text="添加几何描边")
        row.operator("bvtoon.remove_geom_stroke", text="", icon="TRASH")
        row = box2.row(align=True)
        row.operator("bvtoon.restore_mat", text="还原成基本材质")
        row = box2.row(align=True)
        row.operator("bvtoon.set_alpha_blend_one", text="Alpha混合")
        row.operator("bvtoon.set_alpha_hashed_one", text="Alpha抖动")

        layout.label(text="© 2025 BVan / DEEPSEEK")

class BVTOON_edge_preview_create(bpy.types.Operator):
    """边缘预览"""
    bl_idname = "bvtoon.edge_preview_create"
    bl_label = "只适用MMD模型"
    
    def execute(self, context):
        try:
            bpy.ops.mmd_tools.edge_preview_setup(action='CREATE')
        except Exception as e:
            self.report({'ERROR'}, f"物体模式下，仅限 MMD 模型，并开启MMD Tools")
        return {'FINISHED'}

class BVTOON_edge_preview_clean(bpy.types.Operator):
    """删除边缘预览"""
    bl_idname = "bvtoon.edge_preview_clean"
    bl_label = "只适用MMD模型"
    
    def execute(self, context):
        try:
            bpy.ops.mmd_tools.edge_preview_setup(action='CLEAN')
        except Exception as e:
            self.report({'ERROR'}, f"物体模式下，仅限 MMD 模型，并开启MMD Tools")
        return {'FINISHED'}

class BVTOON_convert_materials(bpy.types.Operator):
    """转换给Blender"""
    bl_idname = "bvtoon.convert_materials"
    bl_label = "只适用MMD模型"
    
    def execute(self, context):
        try:
            bpy.ops.mmd_tools.convert_materials()
        except Exception as e:
            self.report({'ERROR'}, f"物体模式下，选中模型，并开启MMD Tools")
        return {'FINISHED'}

def clear_links(sock):
    
    if not sock or not hasattr(sock, "links"):
        return
    nt = sock.node.id_data
    for lk in list(sock.links):
        nt.links.remove(lk)

def link_safe(nt, out_socket, in_socket):
    if out_socket and in_socket:
        
        for lk in list(in_socket.links):
            nt.links.remove(lk)
        nt.links.new(out_socket, in_socket)

def assign_default(src_val, sock):
    try:
        if not hasattr(sock, "default_value"):
            return
        dv = sock.default_value
        
        dv_is_scalar = isinstance(dv, float)
        dv_len = 1 if dv_is_scalar else (len(dv) if hasattr(dv, "__len__") else 1)
        
        if isinstance(src_val, (tuple, list, mathutils.Vector)):
            src_list = list(src_val)
        else:
            try:
                src_list = [float(src_val)] * dv_len
            except Exception:
                sock.default_value = src_val
                return
        if dv_is_scalar:
            sock.default_value = float(src_list[0])
        else:
            
            if len(src_list) < dv_len:
                src_list += [1.0] * (dv_len - len(src_list))
            sock.default_value = src_list[:dv_len]
    except Exception:
        pass

def transfer(nt, src_input, dst_socket):
    if src_input.is_linked:
        fsock = src_input.links[0].from_socket
        for lk in list(src_input.links):
            nt.links.remove(lk)
        link_safe(nt, fsock, dst_socket)
    else:
        clear_links(dst_socket)
        assign_default(src_input.default_value, dst_socket)

def cleanup(nt, keep):
    for n in list(nt.nodes):
        if n in keep or n.type == 'OUTPUT_MATERIAL':
            continue
        if not any(s.is_linked for s in n.outputs):
            nt.nodes.remove(n)

def ensure_output(nt):
    outs = [n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL']
    active = next((n for n in outs if n.is_active_output), None)
    if not active:
        active = outs[0] if outs else nt.nodes.new("ShaderNodeOutputMaterial")
        active.is_active_output = True
    for n in outs:
        if n is not active:
            nt.nodes.remove(n)
    return active

def get_group(nt, ref, out_node=None):
    for n in nt.nodes:
        if n.bl_idname == "ShaderNodeGroup" and n.node_tree == ref:
            return n
    g = nt.nodes.new("ShaderNodeGroup")
    g.node_tree = ref
    if out_node:
        g.location.x = out_node.location.x - 500
        g.location.y = out_node.location.y
    else:
        g.location = (0, 0)
    return g

def safe_set_view_transform(scene, transform, operator):
    try:
        scene.view_settings.view_transform = transform
        return True
    except Exception:
        operator.report({'WARNING'}, f"当前环境不支持色彩空间: '{transform}'，已跳过")
        return False

def safe_set_look(scene, look, operator):
    try:
        scene.view_settings.look = look
        return True
    except Exception:
        operator.report({'WARNING'}, f"当前环境不支持 Look: '{look}'，已跳过")
        return False

COLOR_SOCKETS     = {"basetex", "base_tex", "basecolor", "base_color", "mcolor"}
ALPHA_SOCKETS     = {"alpha"}
BASEALPHA_SOCKETS = {"basealpha", "base_alpha"}

class BVTOONPresetOperator(Operator):
    bl_idname = "bvtoon.apply_preset"
    bl_label  = "应用预设"
    preset_index: bpy.props.IntProperty()  

    def execute(self, context):
        preset_data = load_preset_data()
        if not preset_data:
            self.report({'ERROR'}, "无法加载预设数据")
            return {'CANCELLED'}
        
        safe_set_view_transform(context.scene, 'Standard', self)
        safe_set_look(context.scene, 'None', self)
  
        preset      = preset_data["presets"][self.preset_index]
        blend_rel   = preset["blend_file"]
        group_name  = preset["node_group"]
        
        if group_name not in bpy.data.node_groups:
            blend_path = os.path.join(os.path.dirname(__file__), blend_rel)
            with bpy.data.libraries.load(blend_path) as (src, dst):
                if group_name in src.node_groups:
                    dst.node_groups = [group_name]

        self.ng_ref = bpy.data.node_groups.get(group_name)
        if self.ng_ref is None:
            self.report({'ERROR'}, f"找不到节点组: {group_name}")
            return {'CANCELLED'}

        mode = context.scene.bvtoon_mode
        if mode == "REPLACE_MODEL":
            for obj in context.selected_objects:
                self.apply_materials(obj)
        else:
            mat = context.object.active_material
            if mat:
                self.replace_material(mat)
        return {'FINISHED'}

    def apply_materials(self, obj):
        for mat in obj.data.materials:
            if mat and "mmd_edge" not in mat.name:
                self.replace_material(mat)

    def replace_material(self, mat):
        if not mat.use_nodes:
            mat.use_nodes = True
        nt = mat.node_tree
        if nt is None:
            return

        out_node = ensure_output(nt)
        g_node   = get_group(nt, self.ng_ref, out_node)
        mcolor   = g_node.inputs.get("MColor")
        alpha    = g_node.inputs.get("Alpha")

        for n in nt.nodes:
            if n.type == 'BSDF_PRINCIPLED' or (n.bl_idname == "ShaderNodeGroup" and ("MMDShaderDev" in n.node_tree.name or "BVToon" in n.node_tree.name)):
                for inp in n.inputs:
                    key = inp.name.replace(" ", "_").lower()
                    if key in COLOR_SOCKETS and mcolor:
                        transfer(nt, inp, mcolor)
                    elif key in ALPHA_SOCKETS and alpha:
                        transfer(nt, inp, alpha)
                    elif key in BASEALPHA_SOCKETS:
                        base_alpha = (g_node.inputs.get("Base Alpha")  
                                      or g_node.inputs.get("BaseAlpha")
                                      or alpha)
                        if base_alpha:
                            transfer(nt, inp, base_alpha)

        m_out = g_node.outputs.get("MOutput")
        if m_out and "Surface" in out_node.inputs:
            link_safe(nt, m_out, out_node.inputs["Surface"])
        cleanup(nt, {g_node})

EYE_SHADOW_KEYWORDS = ["目影","眼睛1","eye_shadow",]

def set_eye_shadow(material):
    node_tree = material.node_tree
    nodes = node_tree.nodes
    for node in nodes:
        nodes.remove(node)
    bsdf = nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf.location = (-300, 0)
    bsdf.inputs['Base Color'].default_value = (0, 0, 0, 1)
    bsdf.inputs['Alpha'].default_value = 0.5
    output_node = nodes.get('Material Output') or nodes.new(type="ShaderNodeOutputMaterial")
    output_node.location = (0, 0)
    node_tree.links.new(bsdf.outputs['BSDF'], output_node.inputs['Surface'])
    material.blend_method = 'BLEND'

class BVTOON_set_eye_shadowpro(bpy.types.Operator):
    bl_idname = "bvtoon.set_eye_shadow"
    bl_label = "Set Eye Shadow Material"
    bl_description = "对名称包含眼影关键词的材质球生效"
    def execute(self, context):
        for obj in context.selected_objects:
            if obj.type != 'MESH':
                continue
            for slot in obj.material_slots:
                mat = slot.material
                if not mat:
                    continue
                if any(kw in mat.name for kw in EYE_SHADOW_KEYWORDS):
                    set_eye_shadow(mat)
        return {'FINISHED'}

class BVTOONMaterialOperator(bpy.types.Operator):
    bl_idname = "bvtoon.restore_mat"
    bl_label = "还原成基本材质"
    def execute(self, context):
        mode = context.scene.bvtoon_mode
        if mode == "REPLACE_MODEL":
            for obj in context.selected_objects:
                self.restore_materials(obj)  
        else:
            mat = context.object.active_material
            if mat:
                self.restore_single_material(mat)
        return {'FINISHED'}
    def restore_materials(self, obj):
        for mat in obj.data.materials:
            if "mmd_edge" not in mat.name:
                self.restore_single_material(mat)
    def restore_single_material(self, mat):
        if mat.node_tree is None:
            return  
        nodes_to_remove = []
        for node in mat.node_tree.nodes:
            if node.type == "BSDF_PRINCIPLED" or (node.type == "GROUP" and node.node_tree and "BVToon" in node.node_tree.name):
                nodes_to_remove.append(node)
        for node in nodes_to_remove:
            mat.node_tree.nodes.remove(node)
        principled_node = mat.node_tree.nodes.new("ShaderNodeBsdfPrincipled")
        principled_node.location = (100, 1200)
        for node in mat.node_tree.nodes:
            if node.type == "TEX_IMAGE":
                mat.node_tree.links.new(node.outputs["Color"], principled_node.inputs["Base Color"])
                mat.node_tree.links.new(node.outputs["Alpha"], principled_node.inputs["Alpha"])  
        material_output = None
        for node in mat.node_tree.nodes:
            if node.type == 'OUTPUT_MATERIAL':
                material_output = node
                break
        
        if not material_output:
            material_output = nodes.new(type="ShaderNodeOutputMaterial")
            material_output.location = (400, 1200)
        mat.node_tree.links.new(principled_node.outputs["BSDF"],material_output.inputs["Surface"])
def set_material_properties(material, blend_method, backface_culling=None, show_transparent_back=None, screen_refraction=None):
    material.blend_method = blend_method
    if backface_culling is not None:
        material.use_backface_culling = backface_culling
    if show_transparent_back is not None:
        material.show_transparent_back = show_transparent_back
    if screen_refraction is not None:
        material.use_screen_refraction = screen_refraction
def apply_to_active_material(context, blend_method, backface_culling=None, show_transparent_back=None, screen_refraction=None):
    obj = context.object
    if obj and obj.type == 'MESH' and obj.active_material:  
        material = obj.active_material
        if material and "mmd_edge" not in material.name:  
            set_material_properties(material, blend_method, backface_culling, show_transparent_back, screen_refraction)

class BVTOON_set_alpha_blend_one(bpy.types.Operator):
    bl_label = "设置混合一"
    bl_idname = "bvtoon.set_alpha_blend_one"
    bl_description = "仅对选中的材质生效"

    def execute(self, context):
        apply_to_active_material(context, 'BLEND', backface_culling=False, show_transparent_back=False)
        return {'FINISHED'}

class BVTOON_set_alpha_hashed_one(bpy.types.Operator):
    bl_label = "设置抖动一"
    bl_idname = "bvtoon.set_alpha_hashed_one"
    bl_description = "仅对选中的材质生效"
    def execute(self, context):
        apply_to_active_material(context, 'HASHED', screen_refraction=False)
        return {'FINISHED'}

MIAO_Pro_FOLDER = os.path.join(os.path.dirname(__file__), "BVToonPro")
filepath = os.path.join(MIAO_Pro_FOLDER, "BVToonPro.blend")

class BVTOON_AddGeometryStroke(bpy.types.Operator):
    bl_idname = "bvtoon.add_geom_stroke"
    bl_label = "Add Geometry Stroke"
    bl_description = "Add geometry stroke to the selected object"

    def execute(self, context):
        obj = context.active_object
        if obj and obj.type == 'MESH':
            if "BVToon_Bian" not in obj.vertex_groups:
                vgroup = obj.vertex_groups.new(name="BVToon_Bian")
                vgroup.add(range(len(obj.data.vertices)), 1.0, 'ADD')
            
            with bpy.data.libraries.load(filepath, link=False) as (data_from, data_to):
                if "BVToon_edge" in data_from.node_groups:
                    data_to.node_groups = ["BVToon_edge"]

            if "BVToon_edge" in bpy.data.node_groups:
                modifier = obj.modifiers.new(name="BVToon_edge", type='NODES')
                modifier.node_group = bpy.data.node_groups["BVToon_edge"]
            else:
                self.report({'WARNING'}, "Failed to load BVToon_edge node group.")
        else:
            self.report({'WARNING'}, "请选择模型并执行")
        return {'FINISHED'}

class BVTOON_RemoveGeometryStroke(bpy.types.Operator):
    bl_idname = "bvtoon.remove_geom_stroke"
    bl_label = "Remove Geometry Stroke"
    bl_description = "Remove BVToon_edge from the selected object"
    def execute(self, context):
        obj = context.active_object
        if obj and obj.type == 'MESH':
            modifiers_to_remove = [mod for mod in obj.modifiers if mod.name.startswith("BVToon_edge")]

            if modifiers_to_remove:
                for modifier in modifiers_to_remove:
                    obj.modifiers.remove(modifier)
                self.report({'INFO'}, f"Removed {len(modifiers_to_remove)} BVToon_edge modifier(s) from the selected object.")
            else:
                self.report({'WARNING'}, "No BVToon_edge modifier found on the selected object.")
        else:
            self.report({'WARNING'}, "请选择模型并执行")
        return {'FINISHED'}


def full_remove_collection(col_name: str):
    """彻底删除指定集合及其内部对象。"""
    col = bpy.data.collections.get(col_name)
    if not col:
        return
    for obj in list(col.all_objects):
        
        for c in list(obj.users_collection):
            c.objects.unlink(obj)
        
        if len(obj.users_collection) == 0:
            bpy.data.objects.remove(obj, do_unlink=True)
    
    for scene in bpy.data.scenes:
        if col.name in scene.collection.children:
            scene.collection.children.unlink(col)
    
    for parent in bpy.data.collections:
        if col.name in parent.children:
            parent.children.unlink(col)
    
    bpy.data.collections.remove(col, do_unlink=True)

class BVTOON_ImportEnvironmentLighting(bpy.types.Operator):
    bl_idname = "bvtoon.import_lighting"
    bl_label = "Import Environment Lighting"
    bl_description = "Import BVToonWorld environment lighting and BVToonLight collection"

    def execute(self, context):
        
        world = bpy.data.worlds.get("BVToonWorld")
        if world:
            bpy.data.worlds.remove(world, do_unlink=True)
        
        full_remove_collection("BVToonLight")
        
        with bpy.data.libraries.load(filepath, link=False) as (data_from, data_to):
            if "BVToonWorld" in data_from.worlds:
                data_to.worlds = ["BVToonWorld"]
            if "BVToonLight" in data_from.collections:
                data_to.collections = ["BVToonLight"]
        
        if "BVToonWorld" in bpy.data.worlds:
            context.scene.world = bpy.data.worlds["BVToonWorld"]
        else:
            self.report({'WARNING'}, "Failed to load BVToonWorld.")
        
        if "BVToonLight" in bpy.data.collections:
            context.scene.collection.children.link(bpy.data.collections["BVToonLight"])
        else:
            self.report({'WARNING'}, "Failed to load BVToonLight collection.")

        return {'FINISHED'}

class BVTOON_AddBlush(bpy.types.Operator):
    """添加腮红"""
    bl_idname = "bvtoon.add_blush"
    bl_label = "添加腮红"
    bl_description = "选中脸部材质球，并且有UV才能用"
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        obj = context.active_object
        if not obj:
            self.report({'ERROR'}, "没有选中的对象")
            return {'CANCELLED'}
        if obj.type != 'MESH':
            self.report({'ERROR'}, "选中的对象不是网格类型")
            return {'CANCELLED'}
        mat = obj.active_material
        if not mat:
            self.report({'ERROR'}, "选中的对象没有材质")
            return {'CANCELLED'}
        if not mat.use_nodes:
            self.report({'ERROR'}, "材质没有使用节点")
            return {'CANCELLED'}
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        
        existing_mface_nodes = [node for node in nodes if node.type == 'GROUP' and node.node_tree and node.node_tree.name == "MFace"]
        for node in existing_mface_nodes:
            nodes.remove(node)
        
        if "MFace" in bpy.data.node_groups:
            bvtoon_face2 = nodes.new('ShaderNodeGroup')
            bvtoon_face2.node_tree = bpy.data.node_groups["MFace"]
            bvtoon_face2.location = (200, 1300)
        else:
            if not os.path.exists(filepath):
                self.report({'ERROR'}, f"节点组文件不存在: {filepath}")
                return {'CANCELLED'}
            with bpy.data.libraries.load(filepath, link=False) as (data_from, data_to):
                if "MFace" in data_from.node_groups:
                    data_to.node_groups = ["MFace"]
                else:
                    self.report({'ERROR'}, "MFace 节点组在 BVToonPro.blend 中未找到")
                    return {'CANCELLED'}

            if "MFace" in bpy.data.node_groups:
                bvtoon_face2 = nodes.new('ShaderNodeGroup')
                bvtoon_face2.node_tree = bpy.data.node_groups["MFace"]
                bvtoon_face2.location = (200, 1300)
            else:
                self.report({'ERROR'}, "加载 MFace 节点组失败")
                return {'CANCELLED'}
        
        material_output = None
        for node in nodes:
            if node.type == 'OUTPUT_MATERIAL':
                material_output = node
                break

        if not material_output:
            self.report({'ERROR'}, "未找到材质输出节点")
            return {'CANCELLED'}
        
        existing_links = list(material_output.inputs['Surface'].links)
        for link in existing_links:
            links.remove(link)
        
        if 'OF' in bvtoon_face2.outputs:
            links.new(bvtoon_face2.outputs['OF'], material_output.inputs['Surface'])
        else:
            self.report({'ERROR'}, "MFace 节点组缺少 'OF' 输出接口")
            return {'CANCELLED'}
        
        bvtoon_nodes = [node for node in nodes if node.type == 'GROUP' and "BVToon" in node.node_tree.name]

        if bvtoon_nodes:
            
            bvtoon_node = bvtoon_nodes[0]
            if 'IF' in bvtoon_face2.inputs and 'OF' in bvtoon_face2.outputs:
                links.new(bvtoon_node.outputs[0], bvtoon_face2.inputs['IF'])
            else:
                self.report({'WARNING'}, "MFace 节点组缺少 'IF' 输入接口或 'OF' 输出接口")
        else:
            
            bsdf_node = None
            for node in nodes:
                if node.type in {'BSDF_PRINCIPLED', 'BSDF_DIFFUSE', 'BSDF_GLOSSY'}:
                    bsdf_node = node
                    break

            if bsdf_node:
                
                if 'IF' in bvtoon_face2.inputs:
                    links.new(bsdf_node.outputs['BSDF'], bvtoon_face2.inputs['IF'])
                    print(f"连接 BSDF 节点 '{bsdf_node.name}' 的 'BSDF' 输出到 MFace 的 'IF' 输入")
                else:
                    self.report({'WARNING'}, "MFace 节点组缺少 'IF' 输入接口")
            else:
                self.report({'WARNING'}, "请手动连接材质节点")
                return {'CANCELLED'}

        self.report({'INFO'}, "腮红已添加，请到材质里面检查一下")
        return {'FINISHED'}

def load_preset_data():
    data_path = os.path.join(os.path.dirname(__file__), "BVToonJson", "data.json")
    if not os.path.exists(data_path):
        print("Error: data.json not found in BVToonJson folder.")
        return {}
    with open(data_path, "r", encoding="utf-8") as f:
        return json.load(f)


def register():
    classes = [
        BVTOONPresetPanel,
        BVTOONPresetOperator,
        BVTOONMaterialOperator,
        BVTOON_set_eye_shadowpro,
        BVTOON_set_alpha_blend_one,
        BVTOON_set_alpha_hashed_one,

        BVTOON_edge_preview_create,
        BVTOON_edge_preview_clean,
        BVTOON_convert_materials,
        BVTOON_AddGeometryStroke,
        BVTOON_RemoveGeometryStroke,
        BVTOON_ImportEnvironmentLighting,
        BVTOON_AddBlush,
    ]
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.bvtoon_mode = bpy.props.EnumProperty(
        name="模式",
        items=[("REPLACE_MODEL", "替换【模型】材质", ""), ("REPLACE_SINGLE", "替换单个【材质】", "")],
        default="REPLACE_MODEL"
    )

    # --- local patch: keep the model's native MMD material data -----------
    # See BV_Toon_Fix.py.  mmd_tools' conversion defaults to clean_nodes=True,
    # which deletes the author's toon ramp, the sphere / sub-texture layer (the
    # sparkles and the sheen) and the MMD UV set -- and with no node left the
    # texture images are dropped on the next save.  This hook keeps them,
    # rebuilds them on materials that already lost them, and feeds the sphere
    # layer into the shader's albedo when a preset is applied.
    try:
        from . import BV_Toon_Fix
        BV_Toon_Fix.install(sys.modules[__name__])
    except Exception:
        import traceback
        traceback.print_exc()

def unregister():
    classes = [
        BVTOONPresetPanel,
        BVTOONPresetOperator,
        BVTOONMaterialOperator,
        BVTOON_set_eye_shadowpro,
        BVTOON_set_alpha_blend_one,
        BVTOON_set_alpha_hashed_one,

        BVTOON_edge_preview_create,
        BVTOON_edge_preview_clean,
        BVTOON_convert_materials,
        BVTOON_AddGeometryStroke,
        BVTOON_RemoveGeometryStroke,
        BVTOON_ImportEnvironmentLighting,
        BVTOON_AddBlush,
    ]
    for cls in classes:
        bpy.utils.unregister_class(cls)

    del bpy.types.Scene.bvtoon_mode


if __name__ == "__main__":
    register()
