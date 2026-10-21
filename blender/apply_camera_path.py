"""
Blender 헤드리스 전용 스크립트 (bpy). Colab에서:

    blender -b -P blender/apply_camera_path.py -- \\
        --path control/presets/demo_bullet_time.json \\
        --mesh /content/dummy_subject.glb \\
        --out-dir /content/render/demo_bullet_time

control/schema.py의 CameraPath JSON을 읽어 카메라를 키프레임하고,
각 프레임의 depth + normal pass를 PNG로 렌더한다. 이 결과가
③생성 엔진(ComfyUI ControlNet)의 조건 입력이 된다.

주의: bpy 안에서는 control/schema.py의 pydantic import를 쓰지 않고
표준 json 모듈로 직접 파싱한다 — Blender의 번들 파이썬에 pydantic이
없을 수 있어 의존성을 최소화.
"""
import argparse
import json
import sys
import os

try:
    import bpy
except ImportError:
    print("이 스크립트는 Blender 내부에서만 실행됩니다: blender -b -P apply_camera_path.py")
    sys.exit(1)


def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--path", required=True, help="CameraPath JSON 경로")
    p.add_argument("--mesh", required=True, help="generate_dummy_mesh.py가 만든 glb")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--res-x", type=int, default=768)
    p.add_argument("--res-y", type=int, default=1024)
    return p.parse_args(argv)


def setup_compositor_for_depth_normal(out_dir: str):
    """Depth + Normal 두 패스를 각각 PNG 시퀀스로 뽑도록 컴포지터 노드 구성."""
    scene = bpy.context.scene
    scene.use_nodes = True
    scene.view_layers["ViewLayer"].use_pass_z = True
    scene.view_layers["ViewLayer"].use_pass_normal = True

    tree = scene.node_tree
    tree.nodes.clear()
    rl = tree.nodes.new("CompositorNodeRLayers")

    depth_out = tree.nodes.new("CompositorNodeOutputFile")
    depth_out.base_path = os.path.join(out_dir, "depth")
    depth_out.file_slots[0].path = "depth_"
    depth_out.format.file_format = "PNG"
    depth_out.format.color_depth = "16"
    normalize = tree.nodes.new("CompositorNodeNormalize")
    tree.links.new(rl.outputs["Depth"], normalize.inputs[0])
    tree.links.new(normalize.outputs[0], depth_out.inputs[0])

    normal_out = tree.nodes.new("CompositorNodeOutputFile")
    normal_out.base_path = os.path.join(out_dir, "normal")
    normal_out.file_slots[0].path = "normal_"
    normal_out.format.file_format = "PNG"
    tree.links.new(rl.outputs["Normal"], normal_out.inputs[0])


def main():
    args = parse_args()

    with open(args.path, "r", encoding="utf-8") as f:
        camera_path = json.load(f)

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)

    bpy.ops.import_scene.gltf(filepath=args.mesh)

    cam_data = bpy.data.cameras.new("morph_camera")
    cam_obj = bpy.data.objects.new("morph_camera", cam_data)
    bpy.context.scene.collection.objects.link(cam_obj)
    bpy.context.scene.camera = cam_obj

    scene = bpy.context.scene
    scene.render.resolution_x = args.res_x
    scene.render.resolution_y = args.res_y
    scene.render.fps = camera_path["fps"]
    scene.frame_start = 0
    scene.frame_end = len(camera_path["frames"]) - 1

    for fr in camera_path["frames"]:
        frame_idx = fr["frame"]
        pos = fr["position"]
        look = fr["look_at"]

        cam_obj.location = (pos["x"], pos["y"], pos["z"])

        import mathutils
        direction = mathutils.Vector(
            (look["x"] - pos["x"], look["y"] - pos["y"], look["z"] - pos["z"])
        )
        rot_quat = direction.to_track_quat("-Z", "Y")
        cam_obj.rotation_euler = rot_quat.to_euler()
        cam_data.angle = fr["fov_deg"] * 3.14159265 / 180.0

        cam_obj.keyframe_insert(data_path="location", frame=frame_idx)
        cam_obj.keyframe_insert(data_path="rotation_euler", frame=frame_idx)
        cam_data.keyframe_insert(data_path="lens", frame=frame_idx)

    os.makedirs(args.out_dir, exist_ok=True)
    setup_compositor_for_depth_normal(args.out_dir)

    bpy.ops.render.render(animation=True)
    print(f"렌더 완료: {args.out_dir} ({len(camera_path['frames'])} 프레임)")


if __name__ == "__main__":
    main()
