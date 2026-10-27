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


def setup_compositor_for_depth_normal(out_dir: str, depth_near: float, depth_far: float):
    """Depth + Normal 두 패스를 각각 PNG 시퀀스로 뽑도록 컴포지터 노드 구성.

    2026-10-27 발견: CompositorNodeNormalize는 프레임 안에 찍힌 모든 픽셀의
    min~max를 0~1로 늘린다. 배경(지오메트리가 없는 픽셀)의 Z값은 카메라
    clip_end(기본 1000m)로 찍히는데, 이게 프레임 min~max에 그대로 섞여
    들어가 "피사체 표면 0.2~0.3m 범위"가 "0~1000m 범위" 안의 먼지 수준으로
    눌려버림 — 코 돌기를 head_r*1.1로 과장해뒀어도(generate_dummy_mesh.py
    v2) 깊이맵에는 거의 안 드러나고 밋밋한 구 하나만 보이던 원인이었음
    (demo_bullet_time 생성 결과가 "사람"이 아니라 "매끈한 둥근 물체"로
    나오던 버그와 직결). CompositorNodeMapRange로 교체해 카메라 궤적상
    실제 피사체 표면이 있을 수 있는 고정 거리 구간(depth_near~depth_far,
    main()에서 궤적 전체의 camera-to-look_at 거리로 계산)만 0~1에 매핑하고
    그 밖은 clamp. 배경은 여전히 1(흰색)로 클램프되어 기존 흰 배경 관례는
    유지됨.
    """
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
    map_range = tree.nodes.new("CompositorNodeMapRange")
    map_range.inputs["From Min"].default_value = depth_near
    map_range.inputs["From Max"].default_value = depth_far
    map_range.inputs["To Min"].default_value = 0.0
    map_range.inputs["To Max"].default_value = 1.0
    map_range.use_clamp = True
    tree.links.new(rl.outputs["Depth"], map_range.inputs["Value"])
    tree.links.new(map_range.outputs[0], depth_out.inputs[0])

    normal_out = tree.nodes.new("CompositorNodeOutputFile")
    normal_out.base_path = os.path.join(out_dir, "normal")
    normal_out.file_slots[0].path = "normal_"
    normal_out.format.file_format = "PNG"
    tree.links.new(rl.outputs["Normal"], normal_out.inputs[0])

    # 디버그/CP용 컬러 렌더 — depth/normal과 달리 사람이 직접 보고 "카메라가
    # 의도대로 도는지, 더미가 어떻게 생겼는지"를 확인하기 위한 패스.
    beauty_out = tree.nodes.new("CompositorNodeOutputFile")
    beauty_out.base_path = os.path.join(out_dir, "beauty")
    beauty_out.file_slots[0].path = "beauty_"
    beauty_out.format.file_format = "PNG"
    tree.links.new(rl.outputs["Image"], beauty_out.inputs[0])


def main():
    args = parse_args()

    with open(args.path, "r", encoding="utf-8") as f:
        camera_path = json.load(f)

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)

    bpy.ops.import_scene.gltf(filepath=args.mesh)

    # depth/normal 패스는 조명이 필요 없지만, 사람이 카메라 궤적을 "눈으로"
    # 확인하려면(CP1 다음의 비주얼 확인 단계) 실제 더미 실루엣이 찍힌 컬러
    # 렌더가 있어야 한다 — 조명 없으면 완전 검은 화면만 나옴.
    sun_data = bpy.data.lights.new(name="morph_sun", type="SUN")
    sun_data.energy = 3.0
    sun_obj = bpy.data.objects.new(name="morph_sun", object_data=sun_data)
    bpy.context.scene.collection.objects.link(sun_obj)
    sun_obj.rotation_euler = (0.9, 0.3, 0.8)

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

    # EEVEE는 헤드리스 Colab에서 GPU 디스플레이 컨텍스트를 못 잡아
    # (EGL_BAD_MATCH) 조용히 CPU 소프트웨어 렌더로 폴백 — 프레임당 60초+로 느림.
    # Cycles+CUDA는 디스플레이 컨텍스트 없이도 GPU 연산기를 직접 쓸 수 있어
    # 헤드리스 환경에 적합. depth/normal pass는 조명 품질이 필요 없으므로
    # 샘플 수를 최소로 낮춰 추가로 가속한다.
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 4
    scene.cycles.use_denoising = False
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        prefs.compute_device_type = "CUDA"
        prefs.get_devices()
        for device in prefs.devices:
            device.use = device.type in ("CUDA", "CPU")
        scene.cycles.device = "GPU"
        print("Cycles GPU devices:", [(d.name, d.type, d.use) for d in prefs.devices])
    except Exception as e:
        print(f"GPU 설정 실패, CPU로 진행: {e}")
        scene.cycles.device = "CPU"

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

    # 궤적 전체에서 카메라-피사체(look_at) 거리의 최소/최대를 구해, 그 구간에
    # 여유(±0.3m)를 둔 걸 depth 정규화 구간으로 쓴다 — 표면 굴곡(코 등)이
    # 배경 깊이에 묻히지 않게 하기 위함(위 setup_compositor_for_depth_normal
    # 설명 참고).
    cam_dists = [
        ((fr["position"]["x"] - fr["look_at"]["x"]) ** 2
         + (fr["position"]["y"] - fr["look_at"]["y"]) ** 2
         + (fr["position"]["z"] - fr["look_at"]["z"]) ** 2) ** 0.5
        for fr in camera_path["frames"]
    ]
    depth_near = max(min(cam_dists) - 0.3, 0.05)
    depth_far = max(cam_dists) + 0.3

    os.makedirs(args.out_dir, exist_ok=True)
    setup_compositor_for_depth_normal(args.out_dir, depth_near, depth_far)

    bpy.ops.render.render(animation=True)
    print(f"렌더 완료: {args.out_dir} ({len(camera_path['frames'])} 프레임)")


if __name__ == "__main__":
    main()
