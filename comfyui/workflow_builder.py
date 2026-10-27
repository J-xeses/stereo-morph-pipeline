"""
Blender depth/normal pass + 피사체 참조 이미지를 받아 ComfyUI "API 포맷" 워크플로우
JSON을 조립한다. 이 JSON을 ComfyUI 서버(Colab에서 실행 중)의 `/prompt` 엔드포인트로
POST하면 생성이 큐에 들어간다.

⚠️ 노드 타입 이름(class_type)은 ComfyUI 코어 + 커스텀 노드팩 버전에 따라 바뀐다.
이 파일은 "설계도"이며, Colab에서 실제 설치된 노드팩의 node_type을 `--list-nodes`로
확인해 맞춰야 한다 (colab/stereo_morph_pipeline.ipynb 의 검증 셀 참고).

2026-10-24 백엔드 교체 — SD1.5+AnimateDiff+수동IPAdapter 조합(아래 `build_workflow`,
레거시로 보존)은 베이스라인 자체가 depth 회전을 전혀 반영 못 해 FaceID 검증 전에
중단됨(project_periodic_direction_research 10/22~24 기록). 신규 기본 경로는
`build_workflow_vace` — Wan2.1-VACE-1.3B, **커스텀 노드팩 불필요**(ComfyUI 코어에
`WanVaceToVideo` 노드가 이미 포함돼 있음, comfy-core 0.3.34+ 확인됨 — 공식 템플릿
https://raw.githubusercontent.com/Comfy-Org/workflow_templates/main/templates/video_wan_vace_14B_v2v.json
및 ComfyUI 소스 comfy_extras/nodes_wan.py 의 WanVaceToVideo.define_schema 직접 확인,
입력 이름 positive/negative/vae/width/height/length/batch_size/strength/
control_video/control_masks/reference_image 전부 소스 코드로 재확인됨 — 추측 아님).
reference_image(피사체 참조) + control_video(Blender depth 시퀀스)를 한 노드에서
동시에 받고, `strength`(= 커뮤니티에서 "Reference Strength"라 부르는 값, 1.0~1.5
권장)로 정체성 고정 강도를 조절한다 — IP-Adapter처럼 별도 노드체인을 안 걸어도 됨.
VideoHelperSuite(VHS_LoadImagesPath/VHS_VideoCombine)는 그대로 재사용.

필요 커스텀 노드팩 (build_workflow_vace만 쓸 경우):
  - ComfyUI-VideoHelperSuite    (이미지 시퀀스 로드/영상 합성) — 이것만 있으면 됨

필요 커스텀 노드팩 (레거시 build_workflow, SD1.5 백엔드):
  - ComfyUI-AnimateDiff-Evolved
  - ComfyUI-VideoHelperSuite
  - ComfyUI-Advanced-ControlNet
  - ComfyUI_IPAdapter_plus      (use_ip_adapter_faceid=True일 때만 필요)
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
    use_ip_adapter_faceid: bool = False,
    ip_adapter_faceid_model: str = "ip-adapter-faceid_sd15.bin",
    ip_adapter_faceid_lora: str = "ip-adapter-faceid_sd15_lora.safetensors",
    ip_adapter_weight: float = 0.8,
    ip_adapter_clip_vision_name: str = "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors",
) -> dict:
    """ComfyUI API 포맷(dict[node_id] = {class_type, inputs}) 워크플로우를 반환.

    use_ip_adapter_faceid=True면 노드 15~19(LoraLoaderModelOnly → IPAdapterModelLoader
    → IPAdapterInsightFaceLoader → CLIPVisionLoader → IPAdapterFaceID)을 추가해 체크포인트
    모델을 패치하고,
    AnimateDiff 로더(노드 9)가 그 패치된 모델을 받도록 다시 연결한다. 참조 얼굴 이미지는
    subject_image_path와 동일한 이미지(노드 "7")를 그대로 재사용 — 피사체 사진 1장이면
    충분, 별도 얼굴 크롭 이미지를 또 준비할 필요 없음.
    """

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
            "inputs": {"image": os.path.basename(subject_image_path)},
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

    if use_ip_adapter_faceid:
        workflow["15"] = {
            # FaceID 전용 LoRA — 체크포인트 모델에 직접 적용(CLIP은 안 건드림)
            "class_type": "LoraLoaderModelOnly",
            "inputs": {
                "model": ["1", 0],
                "lora_name": ip_adapter_faceid_lora,
                "strength_model": 1.0,
            },
        }
        workflow["16"] = {
            "class_type": "IPAdapterModelLoader",
            "inputs": {"ipadapter_file": ip_adapter_faceid_model},
        }
        workflow["17"] = {
            # provider CPU — insightface 얼굴 임베딩 추출은 T4 VRAM을 안 먹음.
            # 2026-10-28: 클래스명이 "InsightFaceLoader"가 아니라 "IPAdapterInsightFaceLoader"임
            # (cubiq/ComfyUI_IPAdapter_plus의 IPAdapterPlus.py NODE_CLASS_MAPPINGS 직접 확인,
            # Colab (검증) 셀에서 "이름이 다름" 경고로 실측 발견) — model_name도 필수 입력이라
            # 빠지면 노드가 실패한다.
            "class_type": "IPAdapterInsightFaceLoader",
            "inputs": {"provider": "CPU", "model_name": "buffalo_l"},
        }
        workflow["19"] = {
            # 2026-10-28: IPAdapterFaceID가 "Missing CLIPVision model." 로 실패(Colab 실측) —
            # IPAdapterAdvanced.apply_ipadapter가 clip_vision을 무조건 요구함(FaceID도 예외
            # 아님, cubiq 소스 확인). ip-adapter-faceid_sd15.bin 자체엔 clip vision 가중치가
            # 안 들어있어서 IPAdapterModelLoader만으론 못 채움 — 별도 로더 필요.
            "class_type": "CLIPVisionLoader",
            "inputs": {"clip_name": ip_adapter_clip_vision_name},
        }
        workflow["18"] = {
            # 참조 얼굴 이미지는 피사체 사진(노드 7) 재사용 — 매 프레임 이 정체성을
            # 기억하도록 모델을 패치, 그 패치된 모델을 AnimateDiff 로더로 넘긴다.
            "class_type": "IPAdapterFaceID",
            "inputs": {
                "model": ["15", 0],
                "ipadapter": ["16", 0],
                "insightface": ["17", 0],
                "clip_vision": ["19", 0],
                "image": ["7", 0],
                "weight": ip_adapter_weight,
                "weight_faceidv2": 1.0,
                "weight_type": "linear",
                "combine_embeds": "concat",
                "start_at": 0.0,
                "end_at": 1.0,
                "embeds_scaling": "V only",
            },
        }
        workflow["9"]["inputs"]["model"] = ["18", 0]

    return workflow


def build_workflow_vace(
    shot_id: str,
    depth_pass_dir: str,
    subject_image_path: str,
    positive_prompt: str,
    negative_prompt: str = "blurry, distorted anatomy, extra limbs, low quality",
    frame_count: int = 36,
    fps: int = 24,
    width: int = 480,
    height: int = 640,
    reference_strength: float = 1.2,
    mask_pass_dir: str | None = None,
    diffusion_model_name: str = "wan2.1_vace_1.3B_fp16.safetensors",
    vae_name: str = "wan_2.1_vae.safetensors",
    clip_name: str = "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
    model_shift: float = 8.0,
    steps: int = 20,
    cfg: float = 6.0,
    sampler_name: str = "uni_pc",
    scheduler: str = "simple",
    seed: int = 0,
) -> dict:
    """Wan2.1-VACE 백엔드 ComfyUI API 포맷 워크플로우.

    width/height=480x640(3:4)은 blender/apply_camera_path.py의 기본 렌더 해상도
    768x1024(역시 3:4)과 종횡비를 맞춘 값 — WanVaceToVideo 내부에서
    control_video/reference_image를 "center" 크롭 후 리사이즈하므로, 종횡비가
    다르면 얼굴 프레이밍이 잘릴 수 있다(2026-10-24, nodes_wan.py 소스 확인).

    reference_strength가 바로 WanVaceToVideo의 "strength" 입력 — 커뮤니티 가이드
    (arca.live, 2026-10-24 확인)가 "낮은 유사도" 문제의 해법으로 꼽은 그 파라미터.
    **단, strength는 control/reference 전체에 걸리는 단일 값이라 이것만으로는
    "control이 reference를 압도" 문제를 못 고친다는 게 Comfy Cloud 진단(10/26)
    으로 확정됨 — control_masks(2026-10-27 추가, mask_pass_dir)로 피사체 실루엣
    영역의 control을 꺼서 그 영역만 reference가 지배하게 하는 쪽으로 보완.

    mask_pass_dir: apply_camera_path.py가 함께 렌더하는 control_masks 시퀀스
    경로(피사체=0/비활성, 배경=1/활성 — 공식 노드 소스 기준 의미). None이면
    기존처럼 control_masks를 안 넘김(= 전체 활성, 기존 동작과 동일).
    """
    workflow = {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": diffusion_model_name, "weight_dtype": "default"},
        },
        "2": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": clip_name, "type": "wan", "device": "default"},
        },
        "3": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": vae_name},
        },
        "4": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": positive_prompt, "clip": ["2", 0]},
        },
        "5": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative_prompt, "clip": ["2", 0]},
        },
        "6": {
            # Wan 계열은 flow-shift 샘플링 보정이 필요 — 14B/1.3B 공식 템플릿 기본값 그대로
            "class_type": "ModelSamplingSD3",
            "inputs": {"model": ["1", 0], "shift": model_shift},
        },
        "7": {
            # 피사체 참조 이미지 — rembg로 흰 배경 전처리된 버전을 넘기는 걸 전제.
            # ComfyUI의 LoadImage는 자기 input/ 폴더 기준 "파일명"만 받는다(절대경로
            # 주면 400 Invalid image file — 2026-10-24 demo_bullet_time 1차 실행에서
            # 실측, docs: 이 함수가 받는 subject_image_path는 /content/... 절대경로일
            # 수도 있으므로 항상 basename만 추출해서 넘긴다.
            "class_type": "LoadImage",
            "inputs": {"image": os.path.basename(subject_image_path)},
        },
        "8": {
            # Blender depth 시퀀스 — VHS_LoadImagesPath가 이미지 배치로 로드
            "class_type": "VHS_LoadImagesPath",
            "inputs": {
                "directory": depth_pass_dir,
                "image_load_cap": frame_count,
                "skip_first_images": 0,
            },
        },
        "9": {
            "class_type": "WanVaceToVideo",
            "inputs": {
                "positive": ["4", 0],
                "negative": ["5", 0],
                "vae": ["3", 0],
                "control_video": ["8", 0],
                "reference_image": ["7", 0],
                "width": width,
                "height": height,
                "length": frame_count,
                "batch_size": 1,
                "strength": reference_strength,
            },
        },
        "10": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["6", 0],
                "positive": ["9", 0],
                "negative": ["9", 1],
                "latent_image": ["9", 2],
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": sampler_name,
                "scheduler": scheduler,
                "denoise": 1.0,
            },
        },
        "11": {
            # WanVaceToVideo의 trim_latent 출력(참조이미지가 섞여 늘어난 latent 프레임을
            # 샘플링 후 제거) — 그대로 안 하면 출력 영상 맨 앞에 참조이미지 프레임이 낀다.
            "class_type": "TrimVideoLatent",
            "inputs": {"samples": ["10", 0], "trim_amount": ["9", 3]},
        },
        "12": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["11", 0], "vae": ["3", 0]},
        },
        "13": {
            "class_type": "VHS_VideoCombine",
            "inputs": {
                "images": ["12", 0],
                "frame_rate": fps,
                "filename_prefix": f"morph_{shot_id}",
                "format": "video/h264-mp4",
                "pingpong": False,
                "save_output": True,
                "loop_count": 0,
            },
        },
    }

    if mask_pass_dir:
        workflow["14"] = {
            # control_masks 시퀀스 로드 — apply_camera_path.py가 depth/normal과
            # 같은 프레임 수로 함께 렌더해둔 것(피사체=검정/비활성, 배경=흰색/활성).
            "class_type": "VHS_LoadImagesPath",
            "inputs": {
                "directory": mask_pass_dir,
                "image_load_cap": frame_count,
                "skip_first_images": 0,
            },
        }
        workflow["15"] = {
            # WanVaceToVideo의 control_masks는 MASK 타입을 받음 — 로드된 흑백
            # PNG(IMAGE)를 red 채널 기준으로 MASK로 변환(그레이스케일이라 채널
            # 무관하게 값 동일).
            "class_type": "ImageToMask",
            "inputs": {"image": ["14", 0], "channel": "red"},
        }
        workflow["9"]["inputs"]["control_masks"] = ["15", 0]

    return workflow


def write_workflow_json(out_path: str, backend: str = "sd15_animatediff", **kwargs) -> None:
    wf = build_workflow_vace(**kwargs) if backend == "wan_vace" else build_workflow(**kwargs)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(wf, f, indent=2, ensure_ascii=False)
    print(f"워크플로우 저장({backend}): {out_path} ({len(wf)} nodes)")


if __name__ == "__main__":
    # 데모 1개 샷으로 템플릿 생성 — Colab에서 노드팩/모델 설치 후 이 파일을 그대로
    # /prompt 로 POST해서 1차 동작 검증하는 용도.
    here = os.path.dirname(__file__)
    write_workflow_json(
        os.path.join(here, "workflows", "bullet_time_morph_vace.json"),
        backend="wan_vace",
        shot_id="demo_bullet_time",
        depth_pass_dir="/content/render/demo_bullet_time/depth",
        subject_image_path="subject_ref_clean.png",
        positive_prompt="cinematic photoreal subject, bullet time orbit shot, consistent identity",
    )
    write_workflow_json(
        os.path.join(here, "workflows", "bullet_time_morph_sd15_legacy.json"),
        backend="sd15_animatediff",
        shot_id="demo_bullet_time",
        depth_pass_dir="/content/render/demo_bullet_time/depth",
        subject_image_path="subject_ref.png",
        positive_prompt="cinematic photoreal subject, bullet time orbit shot, consistent identity",
    )
