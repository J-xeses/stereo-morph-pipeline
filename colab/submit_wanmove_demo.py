"""
Wan-Move 오빗 데모 샷을 이미 떠있는 ComfyUI 서버에 제출하는 원샷 스크립트.

전제: bootstrap_wanmove_and_tunnel.py로 ComfyUI가 이미 127.0.0.1:8188에서 돌고 있고,
/content/subject_ref.png가 Colab 파일 패널로 업로드되어 있을 것.

Colab에서 쓰는 법:
    !python /content/stereo-morph-pipeline/colab/submit_wanmove_demo.py
"""
from __future__ import annotations

import json
import shutil

import requests

SUBJECT_SRC = "/content/subject_ref.png"
SUBJECT_DST = "/content/ComfyUI/input/subject_ref.png"
WORKFLOW_PATH = (
    "/content/stereo-morph-pipeline/comfyui/workflows/demo_rotating_long_take_wanmove.json"
)

shutil.copy(SUBJECT_SRC, SUBJECT_DST)
print(f"참조 이미지 복사 완료: {SUBJECT_DST}")

with open(WORKFLOW_PATH, encoding="utf-8") as f:
    workflow = json.load(f)

resp = requests.post("http://127.0.0.1:8188/prompt", json={"prompt": workflow})
print(resp.status_code, resp.text[:1000])
