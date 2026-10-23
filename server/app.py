"""
CP1~CP4 모니터 앱 — 단계별 생성물(궤적 프리뷰/히어로 프레임/세그먼트 영상/최종본)을
브라우저에서 확인하고, 필요하면 특정 단계의 파일을 교체("대입")하기 위한 로컬 서버.

왜 필요한가: Colab에서 뭔가 생성되면 그동안 ffmpeg로 프레임 뽑아 Claude가 혼자
눈으로 보고 "괜찮다/이상하다" 판단했는데, CP1·CP2·CP4는 설계상 사람(성준님)이
직접 봐야 하는 지점(docs/architecture.md §6). 이 서버는 그 확인을 실제로
가능하게 하는 창구.

실행:
    pip install -r requirements.txt
    python server/app.py
    -> http://localhost:4100

output/<shot_id>/ 아래 다음 하위폴더를 스캔한다 (없으면 그냥 빈 상태로 표시):
    cp1_trajectory_preview/   카메라 궤적 프리뷰(이미지)
    cp2_hero_frame/           히어로 프레임 / 아이덴티티 앵커(이미지)
    cp3_segments/             세그먼트별 1차 생성 영상(영상, 여러 개 가능)
    cp4_final/                체이닝된 최종본(영상)

이 폴더 구조는 Colab 노트북 마지막 셀이 Drive에서 이 경로로 복사/다운로드하도록
맞춰야 한다 — 지금은 아직 수동 다운로드 단계이므로, 받은 파일을 이 구조에 맞게
넣기만 하면 바로 화면에 뜬다.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
STATIC_DIR = Path(__file__).resolve().parent / "static"

STAGES = {
    "cp1_trajectory_preview": {"label": "CP1 · 궤적 프리뷰", "kind": "image"},
    "cp2_hero_frame": {"label": "CP2 · 히어로 프레임(아이덴티티 앵커)", "kind": "image"},
    "cp3_segments": {"label": "CP3 · 세그먼트별 1차 생성", "kind": "video"},
    "cp4_final": {"label": "CP4 · 최종본(체이닝)", "kind": "video"},
}

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_EXT = {".mp4", ".webm", ".mov"}

app = FastAPI(title="stereo-morph-pipeline monitor")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/files", StaticFiles(directory=str(OUTPUT_DIR)), name="files")


def _list_stage_files(shot_dir: Path, stage_key: str) -> list[str]:
    stage_dir = shot_dir / stage_key
    if not stage_dir.is_dir():
        return []
    exts = IMAGE_EXT if STAGES[stage_key]["kind"] == "image" else VIDEO_EXT
    files = sorted(p.name for p in stage_dir.iterdir() if p.suffix.lower() in exts)
    return files


@app.get("/api/shots")
def list_shots():
    if not OUTPUT_DIR.is_dir():
        return []
    shots = []
    for shot_dir in sorted(p for p in OUTPUT_DIR.iterdir() if p.is_dir()):
        stages = {
            key: {
                "label": meta["label"],
                "kind": meta["kind"],
                "files": [f"/files/{shot_dir.name}/{key}/{fn}" for fn in _list_stage_files(shot_dir, key)],
            }
            for key, meta in STAGES.items()
        }
        shots.append({"shot_id": shot_dir.name, "stages": stages})
    return shots


@app.post("/api/shots/{shot_id}/{stage_key}/upload")
async def substitute_file(shot_id: str, stage_key: str, file: UploadFile = File(...)):
    """단계별 파일을 사람이 직접 교체("대입")할 때 쓰는 업로드 엔드포인트."""
    if stage_key not in STAGES:
        raise HTTPException(400, f"알 수 없는 단계: {stage_key}")
    if ".." in shot_id or "/" in shot_id or "\\" in shot_id:
        raise HTTPException(400, "잘못된 shot_id")

    ext = Path(file.filename or "").suffix.lower()
    expected = IMAGE_EXT if STAGES[stage_key]["kind"] == "image" else VIDEO_EXT
    if ext not in expected:
        raise HTTPException(400, f"{stage_key}에는 {sorted(expected)} 형식만 가능 (받은 파일: {ext})")

    stage_dir = OUTPUT_DIR / shot_id / stage_key
    stage_dir.mkdir(parents=True, exist_ok=True)
    dest = stage_dir / file.filename
    dest.write_bytes(await file.read())
    return {"saved": f"/files/{shot_id}/{stage_key}/{file.filename}"}


@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=4100)
