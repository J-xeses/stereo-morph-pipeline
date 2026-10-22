"""
Blender 헤드리스 전용 스크립트 (bpy). 로컬에서는 import조차 안 됨 — Colab에서만:

    blender -b -P blender/generate_dummy_mesh.py -- --out /content/dummy.glb

더미 휴먼 프록시 메시를 만든다. 목적은 포토리얼이 아니라 "depth/normal pass를
뽑기 위한 대략적 실루엣" — 캡슐(동체) + 구(머리) 조합. 나중에 실제 캐릭터
리그(characters.json 기반)로 교체 가능하도록 함수 분리.
"""
import argparse
import sys

try:
    import bpy
except ImportError:
    print("이 스크립트는 Blender 내부에서만 실행됩니다: blender -b -P generate_dummy_mesh.py")
    sys.exit(1)


def parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="/content/dummy_subject.glb")
    p.add_argument("--height", type=float, default=1.6, help="피사체 전체 높이(m)")
    return p.parse_args(argv)


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def build_dummy_human(height: float):
    """캡슐(동체+다리) + 구(머리)로 된 휴먼 프록시. 바닥(z=0)에 발이 닿도록 배치.

    원통+구는 회전축(Z) 기준으로 완벽히 대칭이라, 카메라가 주위를 돌아도
    depth pass가 각도와 무관하게 거의 동일하게 나온다(CP3 실측으로 발견 —
    불릿타임/회전 롱테이크에서 카메라가 도는데도 결과물이 정지해 보이는
    원인이었음). 앞뒤 방향으로 납작하게 눌러 타원형으로 만들고 코/눈두덩이/턱
    랜드마크를 추가해 각도마다 실루엣이 실제로 달라지도록 비대칭을 준다.

    v1(코 돌기 head_r*0.35 크기)은 측면(90도)에서 거의 안 보였다 — depth
    컴포지터가 프레임마다 0~255로 정규화하는데, 머리 전체 깊이 범위에 비해
    돌기가 너무 작아 신호가 묻혔기 때문(CP3 "순수 depth" 진단 테스트로 확인,
    2026-10-22). v2는 코를 머리 반지름에 준하는 크기로 과장하고, 눈두덩이를
    boolean difference로 파서 추가 랜드마크를 준다.
    """
    leg_h = height * 0.5
    torso_h = height * 0.35
    head_r = height * 0.065
    head_center_z = leg_h + torso_h + head_r

    def flatten_front_back(obj, y_scale):
        obj.scale = (1.0, y_scale, 1.0)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

    def boolean_diff(target, cutter):
        mod = target.modifiers.new(name="bool_tmp", type="BOOLEAN")
        mod.operation = "DIFFERENCE"
        mod.object = cutter
        bpy.context.view_layer.objects.active = target
        bpy.ops.object.modifier_apply(modifier=mod.name)
        bpy.data.objects.remove(cutter, do_unlink=True)

    bpy.ops.mesh.primitive_cylinder_add(
        radius=height * 0.08, depth=leg_h, location=(0, 0, leg_h / 2)
    )
    legs = bpy.context.active_object
    legs.name = "dummy_legs"
    flatten_front_back(legs, 0.6)

    bpy.ops.mesh.primitive_cylinder_add(
        radius=height * 0.14, depth=torso_h, location=(0, 0, leg_h + torso_h / 2)
    )
    torso = bpy.context.active_object
    torso.name = "dummy_torso"
    flatten_front_back(torso, 0.6)

    bpy.ops.mesh.primitive_uv_sphere_add(radius=head_r, location=(0, 0, head_center_z))
    head = bpy.context.active_object
    head.name = "dummy_head"
    flatten_front_back(head, 0.75)

    # 눈두덩이 — 정면/3쿼터 각도 구분을 돕는 보조 랜드마크. 머리 표면에서
    # 살짝 파낸 형태(boolean difference).
    eye_z = head_center_z + head_r * 0.15
    for side in (-1, 1):
        bpy.ops.mesh.primitive_uv_sphere_add(
            radius=head_r * 0.22,
            location=(side * head_r * 0.4, -head_r * 0.65, eye_z),
        )
        eye_cutter = bpy.context.active_object
        boolean_diff(head, eye_cutter)

    # 코 — 실루엣에서 가장 중요한 비대칭 랜드마크. v1보다 3배 이상 키워
    # depth 정규화에 묻히지 않게 함(실제 인체 비율보다 과장된 크기 — 의도적).
    nose_depth = head_r * 1.1
    bpy.ops.mesh.primitive_cone_add(
        radius1=head_r * 0.32,
        radius2=head_r * 0.08,
        depth=nose_depth,
        location=(0, -(head_r * 0.75 + nose_depth * 0.5), head_center_z - head_r * 0.05),
        rotation=(1.5708, 0, 0),
    )
    nose = bpy.context.active_object
    nose.name = "dummy_nose"

    # 턱 — 아래쪽 비대칭 보강
    bpy.ops.mesh.primitive_uv_sphere_add(
        radius=head_r * 0.3,
        location=(0, -head_r * 0.55, head_center_z - head_r * 0.85),
    )
    chin = bpy.context.active_object
    chin.name = "dummy_chin"

    bpy.ops.object.select_all(action="DESELECT")
    for obj in (legs, torso, head, nose, chin):
        obj.select_set(True)
    bpy.context.view_layer.objects.active = torso
    bpy.ops.object.join()
    torso.name = "dummy_subject"
    return torso


def main():
    args = parse_args()
    clear_scene()
    subject = build_dummy_human(args.height)

    bpy.ops.export_scene.gltf(filepath=args.out, export_format="GLB")
    print(f"더미 메시 생성 완료: {args.out} (height={args.height}m)")


if __name__ == "__main__":
    main()
