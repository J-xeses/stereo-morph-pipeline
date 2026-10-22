"""
Blender depth/normal pass + 피사체 참조 이미지를 받아 ComfyUI "API 포맷" 워크플로우
JSON을 조립한다. 이 JSON을 ComfyUI 서버(Colab에서 실행 중)의 `/prompt` 엔드포인트로
POST하면 생성이 큐에 들어간다.

⚠️ 노드 타입 이름(class_type)은 ComfyUI 코어 + 커스텀 노드팩(AnimateDiff-Evolved,
ComfyUI-VideoHelperSuite, ComfyUI_ControlNet_AUX) 버전에 따라 바뀐다. 이 파일은
"설계도"이며, Colab에서 실제 설치된 노드팩의 node_type을 `--list-nodes`로 확인해
맞춰야 한다 (colab/stereo_morph_pipeline.ipynb 의 검증 셀 참고).

필요 커스텀 노드팩 (Colab 셀에서 git clone):
  - ComfyUI-AnimateDiff-Evolved
  - ComfyUI-VideoHelperSuite    (이미지 시퀀스 로드/영상 합성)
  - ComfyUI-Advanced-ControlNet (AnimateDiff 컨텍스트 윈도우와 호환되는 ControlNet 노드.
                                  코어 ControlNetLoader/ControlNetApplyAdvanced는
                                  슬라이딩 윈도우 미지원이라 32프레임 넘어가면 런타임 에러남)
"""
from __future__ import annotations

import json
import os


def build_workflow(
    shot_id: str,
    depth_pass_dir: str,
    subject_image_path: str,
    positive_prompt: str,
    negative_prompt: str = "blurry, distorted anatomy, extra limbs, low quality",
    frame_count: int = 36,
    fps: int = 24,
    checkpoint_name: str = "v1-5-pruned-emaonly.safetensors",
    controlnet_name: str = "control_v11f1p_sd15_depth.pth",
    denoise: float = 0.75,
    steps: int = 20,
    cfg: float = 7.0,
    seed: int = 0,
) -> dict:
    """ComfyUI API 포맷(dict[node_id] = {class_type, inputs}) 워크플로우를 반환."""

    workflow = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": checkpoint_name},
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": positive_prompt, "clip": ["1", 1]},
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative_prompt, "clip": ["1", 1]},
        },
        "4": {
            # VideoHelperSuite: 지정 폴더의 PNG 시퀀스를 프레임 배치로 로드
            "class_type": "VHS_LoadImagesPath",
            "inputs": {
                "directory": depth_pass_dir,
                "image_load_cap": frame_count,
                "skip_first_images": 0,
            },
        },
        "5": {
            # 코어 ControlNetLoader는 AnimateDiff 컨텍스트 윈도우(슬라이딩)를
            # 지원 안 함 — Advanced-ControlNet(Kosinkadink)의 Advanced 로더/적용
            # 노드로 교체.
            "class_type": "ACN_ControlNetLoaderAdvanced",
            "inputs": {"cnet": controlnet_name},
        },
        "6": {
            "class_type": "ACN_AdvancedControlNetApply",
            "inputs": {
                "positive": ["2", 0],
                "negative": ["3", 0],
                "control_net": ["5", 0],
                "image": ["4", 0],
                "strength": 1.0,
                "start_percent": 0.0,
                "end_percent": 1.0,
            },
        },
        "7": {
            "class_type": "LoadImage",
            "inputs": {"image": subject_image_path},
        },
        "8": {
            "class_type": "VAEEncode",
            "inputs": {"pixels": ["7", 0], "vae": ["1", 2]},
        },
        "13": {
            # 피사체 이미지는 1장뿐이라 VAEEncode 출력도 배치 1 — AnimateDiff가
            # 36프레임 전체(=ControlNet depth 배치 크기)를 생성하려면 latent도
            # 같은 배치 크기로 복제해야 함. 이게 없으면 배치 크기 불일치로
            # 샘플링이 깨져 완전 노이즈가 나온다.
            "class_type": "RepeatLatentBatch",
            "inputs": {"samples": ["8", 0], "amount": frame_count},
        },
        "14": {
            # mm_sd_v15_v2 모션모듈은 컨텍스트 윈도우 없이 최대 32프레임까지만 처리
            # 가능 — 그 이상(긴 롱테이크 등)은 슬라이딩 윈도우로 잘라서 처리해야 함.
            "class_type": "ADE_AnimateDiffUniformContextOptions",
            "inputs": {
                "context_length": 16,
                "context_stride": 1,
                "context_overlap": 4,
                "context_schedule": "uniform",
                "closed_loop": False,
                "fuse_method": "pyramid",
            },
        },
        "9": {
            # AnimateDiff-Evolved 모션 모듈 — 배치 전체에 시간적 일관성 부여
            "class_type": "ADE_AnimateDiffLoaderGen1",
            "inputs": {
                "model": ["1", 0],
                "model_name": "mm_sd_v15_v2.ckpt",
                "beta_schedule": "sqrt_linear (AnimateDiff)",
                "context_options": ["14", 0],
            },
        },
        "10": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["9", 0],
                "positive": ["6", 0],
                "negative": ["6", 1],
                "latent_image": ["13", 0],
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": denoise,
            },
        },
        "11": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["10", 0], "vae": ["1", 2]},
        },
        "12": {
            "class_type": "VHS_VideoCombine",
            "inputs": {
                "images": ["11", 0],
                "frame_rate": fps,
                "filename_prefix": f"morph_{shot_id}",
                "format": "video/h264-mp4",
                "pingpong": False,
                "save_output": True,
                "loop_count": 0,
            },
        },
    }
    return workflow


def write_workflow_json(out_path: str, **kwargs) -> None:
    wf = build_workflow(**kwargs)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(wf, f, indent=2, ensure_ascii=False)
    print(f"워크플로우 저장: {out_path} ({len(wf)} nodes)")


if __name__ == "__main__":
    # 데모 1개 샷으로 템플릿 생성 — Colab에서 노드팩 설치 후 이 파일을 그대로
    # /prompt 로 POST해서 1차 동작 검증하는 용도.
    here = os.path.dirname(__file__)
    write_workflow_json(
        os.path.join(here, "workflows", "bullet_time_morph.json"),
        shot_id="demo_bullet_time",
        depth_pass_dir="/content/render/demo_bullet_time/depth",
        subject_image_path="/content/subject_ref.png",
        positive_prompt="cinematic photoreal subject, bullet time orbit shot, consistent identity",
    )
