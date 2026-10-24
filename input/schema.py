"""
①입력 레이어의 구조화된 부분 — "샷 매니페스트". 연출 의도(자유 텍스트)는
input/cinematography_briefs/<shot_id>.yaml 의 narrative_note 필드에 두고,
기계가 읽어야 하는 부분(기법 선택 + 파라미터)만 구조화한다.

마크다운이 아니라 YAML인 이유: build_shot.py가 이걸 그대로
control.camera_paths.<technique>(**params) 에 **params로 꽂아야 해서,
사람이 쓰기 편하면서도 파싱 가능한 포맷이 필요했음.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ShotManifest(BaseModel):
    shot_id: str
    technique: str = Field(..., description="camera_paths.py 의 함수명과 일치해야 함")
    params: dict = Field(default_factory=dict, description="해당 기법 함수에 **로 전달")

    narrative_note: str = Field(default="", description="연출 의도 — 자유 텍스트, 기계는 안 읽음")
    subject_image_path: str = Field(..., description="Colab 쪽 경로. 로컬 경로 아님에 주의")
    subject_image_local_path: str | None = Field(
        default=None,
        description="로컬 원본 사진 경로(선택). 지정하면 build_shot.py가 rembg로 흰 배경 "
        "전처리까지 로컬에서 끝내고 output/<shot_id>/cp2_hero_frame/에 즉시 떨어뜨림 — "
        "Colab 없이도 CP2를 모니터 앱에서 바로 확인 가능.",
    )
    positive_prompt: str = Field(default="")
    negative_prompt: str = Field(
        default="blurry, distorted anatomy, extra limbs, low quality"
    )
    use_ip_adapter_faceid: bool = Field(
        default=False,
        description="2026-10-23 실험: depth ControlNet만으로 못 잡는 정체성을 "
        "IP-Adapter FaceID(SD1.5)로 추가 고정할지. backend=sd15_animatediff 일 때만 "
        "의미 있음 — True면 ComfyUI_IPAdapter_plus + InsightFace가 Colab에 설치돼 "
        "있어야 함.",
    )

    backend: str = Field(
        default="wan_vace",
        description="2026-10-24 결정: 생성 엔진 백엔드. 'wan_vace'(기본, Wan2.1-VACE-1.3B "
        "— 네이티브 ComfyUI 코어 노드만으로 동작, reference_strength로 정체성 고정) "
        "또는 'sd15_animatediff'(레거시 — depth 회전 베이스라인이 안 깨지는지 재확인하고 "
        "싶을 때만 폴백으로 사용).",
    )
    reference_strength: float = Field(
        default=1.2,
        description="backend=wan_vace 전용. WanVaceToVideo의 strength 입력 — 커뮤니티 "
        "가이드(arca.live, 10/24)가 '낮은 정체성 유사도' 문제의 해법으로 꼽은 값, "
        "1.0~1.5 권장 범위.",
    )
    vace_width: int = Field(default=480, description="backend=wan_vace 전용, 16의 배수")
    vace_height: int = Field(default=640, description="backend=wan_vace 전용, 16의 배수")

    # 2026-10-25 — 모니터 앱 "VACE 생성 파라미터" 패널에서 직접 조정 가능하도록 노출.
    # None이면 workflow_builder.build_workflow_vace()의 자체 기본값(steps=20, cfg=6.0,
    # sampler_name="uni_pc", scheduler="simple", model_shift=8.0, seed=0)을 그대로 쓴다 —
    # 기존 브리프 yaml에 이 필드들이 없어도 동작이 바뀌지 않아야 해서 전부 Optional.
    steps: int | None = Field(default=None, description="backend=wan_vace 전용, 샘플링 스텝 수")
    cfg: float | None = Field(default=None, description="backend=wan_vace 전용, CFG scale")
    sampler_name: str | None = Field(default=None, description="backend=wan_vace 전용, 기본은 uni_pc")
    scheduler: str | None = Field(default=None, description="backend=wan_vace 전용, 기본은 simple")
    model_shift: float | None = Field(
        default=None, description="backend=wan_vace 전용, ModelSamplingSD3 shift 값"
    )
    seed: int | None = Field(default=None, description="backend=wan_vace 전용, 0이면 매 실행 고정")
    diffusion_model_name: str | None = Field(
        default=None,
        description="backend=wan_vace 전용(고급). Colab ComfyUI models/diffusion_models/에 "
        "실제로 그 파일명이 있어야만 동작 — 기본값(wan2.1_vace_1.3B_fp16.safetensors) 그대로 "
        "두는 걸 권장.",
    )
    vae_name: str | None = Field(default=None, description="backend=wan_vace 전용(고급), 위와 동일 주의")
    clip_name: str | None = Field(default=None, description="backend=wan_vace 전용(고급), 위와 동일 주의")
