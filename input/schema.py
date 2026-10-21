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
    positive_prompt: str = Field(default="")
    negative_prompt: str = Field(
        default="blurry, distorted anatomy, extra limbs, low quality"
    )
