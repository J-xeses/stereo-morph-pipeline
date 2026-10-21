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
    """캡슐(동체+다리) + 구(머리)로 된 휴먼 프록시. 바닥(z=0)에 발이 닿도록 배치."""
    leg_h = height * 0.5
    torso_h = height * 0.35
    head_r = height * 0.065

    bpy.ops.mesh.primitive_cylinder_add(
        radius=height * 0.08, depth=leg_h, location=(0, 0, leg_h / 2)
    )
    legs = bpy.context.active_object
    legs.name = "dummy_legs"

    bpy.ops.mesh.primitive_cylinder_add(
        radius=height * 0.14, depth=torso_h, location=(0, 0, leg_h + torso_h / 2)
    )
    torso = bpy.context.active_object
    torso.name = "dummy_torso"

    bpy.ops.mesh.primitive_uv_sphere_add(
        radius=head_r, location=(0, 0, leg_h + torso_h + head_r)
    )
    head = bpy.context.active_object
    head.name = "dummy_head"

    bpy.ops.object.select_all(action="DESELECT")
    for obj in (legs, torso, head):
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
