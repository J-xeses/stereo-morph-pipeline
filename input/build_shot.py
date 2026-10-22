"""
① 입력 레이어 CLI — 샷 매니페스트(YAML) 한 장으로 ②③ 레이어 아티팩트를
한번에 만든다. 이게 없으면 매번 camera_paths.py 함수를 손으로 호출하고
workflow_builder.py 파라미터를 따로 맞춰야 했음 — 이 스크립트가 그 둘을 묶는다.

    python input/build_shot.py input/cinematography_briefs/demo_bullet_time.yaml

출력:
    control/presets/<shot_id>.json       (카메라 궤적 — ②제어 레이어 산출물)
    comfyui/workflows/<shot_id>.json     (ComfyUI 워크플로우 — ③생성 엔진 입력)

control/schema.py 와 input/schema.py 가 둘 다 "schema.py"라는 이름이라, 그냥
sys.path에 두 폴더를 동시에 얹으면 import가 충돌한다. 그래서 각 디렉터리를
한 번에 하나씩만 sys.path 맨 앞에 넣고 즉시 되돌리는 방식으로 로드한다.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _load_module_from_dir(dir_path: Path, module_filename: str, module_name: str):
    original_path = list(sys.path)
    sys.path.insert(0, str(dir_path))
    try:
        spec = importlib.util.spec_from_file_location(module_name, dir_path / module_filename)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path = original_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", help="input/cinematography_briefs/<shot_id>.yaml 경로")
    args = parser.parse_args()

    with open(args.manifest, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    input_schema = _load_module_from_dir(ROOT / "input", "schema.py", "_cmp_input_schema")
    manifest = input_schema.ShotManifest(**raw)

    camera_paths = _load_module_from_dir(ROOT / "control", "camera_paths.py", "_cmp_camera_paths")
    technique_fn = getattr(camera_paths, manifest.technique, None)
    if technique_fn is None:
        available = [n for n in dir(camera_paths) if not n.startswith("_") and callable(getattr(camera_paths, n))]
        raise SystemExit(
            f"'{manifest.technique}' 함수가 control/camera_paths.py에 없음. "
            f"manifest.technique 오타 확인. 가능한 이름: {available}"
        )

    path = technique_fn(shot_id=manifest.shot_id, **manifest.params)
    preset_path = ROOT / "control" / "presets" / f"{manifest.shot_id}.json"
    preset_path.parent.mkdir(parents=True, exist_ok=True)
    path.to_json_file(str(preset_path))
    print(f"[1/3] 카메라 궤적: {preset_path} ({path.frame_count} frames, {manifest.technique})")

    try:
        preview = _load_module_from_dir(
            ROOT / "control", "preview_camera_path.py", "_cmp_preview_camera_path"
        )
        preview_path = preview.preview(str(preset_path))
        print(f"[2/3] CP1 궤적 프리뷰: {preview_path}  <- 열어서 의도대로인지 확인 후 진행할 것")
    except ImportError:
        print("[2/3] CP1 프리뷰 생략 — matplotlib 미설치 (pip install matplotlib)")

    workflow_builder = _load_module_from_dir(
        ROOT / "comfyui", "workflow_builder.py", "_cmp_workflow_builder"
    )
    workflow_path = ROOT / "comfyui" / "workflows" / f"{manifest.shot_id}.json"
    workflow_builder.write_workflow_json(
        str(workflow_path),
        shot_id=manifest.shot_id,
        depth_pass_dir=f"/content/render/{manifest.shot_id}/depth",
        subject_image_path=manifest.subject_image_path,
        positive_prompt=manifest.positive_prompt,
        negative_prompt=manifest.negative_prompt,
        frame_count=path.frame_count,
        fps=path.fps,
    )
    print(f"[3/3] ComfyUI 워크플로우: {workflow_path}")
    print(
        f"\n다음: git add control/presets/{manifest.shot_id}.json "
        f"comfyui/workflows/{manifest.shot_id}.json && git commit && git push"
        f"\nColab에서는 SHOT_ID = \"{manifest.shot_id}\" 로 설정 후 노트북 실행"
    )


if __name__ == "__main__":
    main()
