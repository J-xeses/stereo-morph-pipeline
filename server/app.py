"""
CP1~CP4 모니터 앱 — 단계별 생성물(궤적 프리뷰/히어로 프레임/세그먼트 영상/최종본)을
브라우저에서 확인·승인하고, 생성 파라미터(Wan2.1-VACE reference_strength 등)를
직접 고쳐서 재생성까지 트리거하는 로컬 제어판.

왜 필요한가: Colab에서 뭔가 생성되면 그동안 ffmpeg로 프레임 뽑아 Claude가 혼자
눈으로 보고 "괜찮다/이상하다" 판단했는데, CP1·CP2·CP4는 설계상 사람(성준님)이
직접 봐야 하는 지점(docs/architecture.md §6)이고, CP3는 위임 가능하지만 사람
최종확인은 여전히 필요하다. 2026-10-25 사고: 이 확인을 거치지 않고 GPU 생성까지
내달려버린 사고가 있었음 — 그래서 여기서부터는 "확인만 보여주는 화면"이 아니라
승인 전에는 다음 단계 업로드 자체를 서버가 막는 구조로 바꿨다(아래 GATE_REQUIRES).

실행:
    pip install -r requirements.txt
    python server/app.py
    -> http://localhost:4100

output/<shot_id>/ 아래 다음 하위폴더를 스캔한다 (없으면 그냥 빈 상태로 표시):
    cp1_trajectory_preview/   카메라 궤적 프리뷰(이미지) — 승인 필수
    cp2_hero_frame/           히어로 프레임 / 아이덴티티 앵커(이미지) — 승인 필수
    cp3_segments/             세그먼트별 1차 생성 영상(영상, 여러 개 가능) — 승인 가능(위임 가능하지만 기본은 사람 확인)
    cp4_final/                체이닝된 최종본(영상) — 승인 필수

각 샷의 승인 상태는 output/<shot_id>/pipeline_state.json 에 저장한다.
CP1·CP2 승인 전에는 cp3_segments 업로드가, CP3 승인 전에는 cp4_final 업로드가
409로 막힌다 — Colab에서 GPU 생성을 돌리기 전에 반드시 여기서 승인해야 한다는
뜻. (파일을 output/ 폴더에 직접 복사해 넣는 수동 경로는 이 체크를 안 거치므로,
앞으로는 "모니터 업로드" 또는 Colab 노트북이 이 API를 거치는 경로로만 넣을 것.)

생성 파라미터 패널(GET/POST /api/shots/{shot_id}/params)은
input/cinematography_briefs/<shot_id>.yaml 을 직접 읽고 쓴 뒤
input/build_shot.py 를 그 자리에서 재실행한다 — 즉 reference_strength나
프롬프트를 여기서 고치면 control/presets·comfyui/workflows·CP1/CP2 프리뷰가
전부 그 자리에서 다시 만들어지고, 파라미터가 바뀌었으니 CP1/CP2 승인은
자동으로 "재승인 필요" 상태로 되돌아간다.
"""
from __future__ import annotations

import importlib.util
import inspect
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from ruamel.yaml import YAML

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
STATIC_DIR = Path(__file__).resolve().parent / "static"
BRIEFS_DIR = ROOT / "input" / "cinematography_briefs"
STATE_FILENAME = "pipeline_state.json"

STAGES = {
    "cp1_trajectory_preview": {"label": "CP1 · 궤적 프리뷰", "kind": "image"},
    "cp2_hero_frame": {"label": "CP2 · 히어로 프레임(아이덴티티 앵커)", "kind": "image"},
    "cp3_segments": {"label": "CP3 · 세그먼트별 1차 생성", "kind": "video"},
    "cp4_final": {"label": "CP4 · 최종본(체이닝)", "kind": "video"},
}
STAGE_ORDER = list(STAGES)

# 이 단계에 업로드하려면 먼저 "approved"여야 하는 선행 단계들.
# CP1·CP2 승인 전에는 CP3(=GPU 생성 결과물) 업로드 불가 — 오늘 사고의 재발 방지.
GATE_REQUIRES: dict[str, list[str]] = {
    "cp1_trajectory_preview": [],
    "cp2_hero_frame": [],
    "cp3_segments": ["cp1_trajectory_preview", "cp2_hero_frame"],
    "cp4_final": ["cp3_segments"],
}
DELEGATABLE_GATES = {"cp3_segments"}  # 위임 가능(architecture.md §6) — 그래도 기본은 사람 확인
VALID_STATUSES = {"pending", "approved", "rejected"}

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_EXT = {".mp4", ".webm", ".mov"}

TECHNIQUE_LABELS = {
    "orbit_bullet_time": "① 불릿타임(오빗)",
    "rotating_long_take": "② 회전 롱테이크",
    "continuous_long_take": "③ 연속 롱테이크",
    "loop_flight": "④ 예측불가 카메라 루프 비행",
}

# VACE 엔진(WanVaceToVideo) 쪽 노브 — control/camera_paths.py의 "연출 기법" 파라미터와는
# 레이어가 다르다(②제어 vs ③생성). build_workflow_vace()의 실제 함수 시그니처 기본값과
# 항상 같은 값을 쓴다 — 아래 _vace_param_schema()가 그 함수를 직접 inspect해서 뽑으므로
# 여기서 숫자를 다시 베껴 적지 않는다.
VACE_ADVANCED_FIELDS = {"diffusion_model_name", "vae_name", "clip_name"}


def _load_module_from_dir(dir_path: Path, module_filename: str, module_name: str):
    """input/build_shot.py와 동일한 트릭 — control/schema.py와 input/schema.py가
    이름이 같아서 둘 다 sys.path에 얹으면 import가 충돌하므로, 한 폴더씩만 얹고
    바로 되돌린다."""
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


def _param_schema_from_signature(fn, skip: set[str]) -> dict[str, dict[str, Any]]:
    fields = {}
    for pname, p in inspect.signature(fn).parameters.items():
        if pname in skip:
            continue
        required = p.default is inspect.Parameter.empty
        fields[pname] = {
            "default": None if required else p.default,
            "required": required,
            "type": "list_vec3" if pname == "waypoints" else type(p.default).__name__ if not required else "float",
        }
    return fields


def _technique_schema() -> dict[str, dict[str, Any]]:
    camera_paths = _load_module_from_dir(ROOT / "control", "camera_paths.py", "_cmp_camera_paths_monitor")
    schema = {}
    for name, label in TECHNIQUE_LABELS.items():
        fn = getattr(camera_paths, name)
        schema[name] = {"label": label, "fields": _param_schema_from_signature(fn, skip={"shot_id"})}
    return schema


def _vace_param_schema() -> dict[str, dict[str, Any]]:
    workflow_builder = _load_module_from_dir(ROOT / "comfyui", "workflow_builder.py", "_cmp_workflow_builder_monitor")
    skip = {"shot_id", "depth_pass_dir", "subject_image_path", "positive_prompt", "negative_prompt", "frame_count", "fps"}
    return _param_schema_from_signature(workflow_builder.build_workflow_vace, skip=skip)


# 둘 다 소스 파일이 바뀌지 않는 한 고정값이라 요청마다 다시 inspect할 필요 없음.
TECHNIQUE_SCHEMA = _technique_schema()
VACE_PARAM_SCHEMA = _vace_param_schema()

_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.width = 10_000  # 긴 프롬프트/narrative_note가 줄바꿈으로 깨지는 것 방지

app = FastAPI(title="stereo-morph-pipeline monitor")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/files", StaticFiles(directory=str(OUTPUT_DIR)), name="files")
# index.html 자체는 /에서 텍스트로 직접 서빙(아래)하지만, 그 안에서 참조하는 로고
# 이미지 같은 정적 자산은 별도 마운트가 있어야 브라우저가 받아감.
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _list_stage_files(shot_dir: Path, stage_key: str) -> list[str]:
    stage_dir = shot_dir / stage_key
    if not stage_dir.is_dir():
        return []
    exts = IMAGE_EXT if STAGES[stage_key]["kind"] == "image" else VIDEO_EXT
    files = sorted(p.name for p in stage_dir.iterdir() if p.suffix.lower() in exts)
    return files


def _state_path(shot_id: str) -> Path:
    return OUTPUT_DIR / shot_id / STATE_FILENAME


def _load_pipeline_state(shot_id: str) -> dict[str, dict[str, Any]]:
    path = _state_path(shot_id)
    state: dict[str, dict[str, Any]] = {}
    if path.is_file():
        state = json.loads(path.read_text(encoding="utf-8"))
    for key in STAGES:
        state.setdefault(key, {"status": "pending", "note": "", "at": None})
    return state


def _save_pipeline_state(shot_id: str, state: dict[str, dict[str, Any]]) -> None:
    path = _state_path(shot_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _stage_locked(state: dict, stage_key: str) -> bool:
    return any(state.get(req, {}).get("status") != "approved" for req in GATE_REQUIRES[stage_key])


def _lock_reason(state: dict, stage_key: str) -> str | None:
    missing = [STAGES[r]["label"] for r in GATE_REQUIRES[stage_key] if state.get(r, {}).get("status") != "approved"]
    return " / ".join(missing) + " 승인 전에는 업로드할 수 없습니다" if missing else None


def _next_action(state: dict, stage_files: dict[str, list[str]]) -> str:
    for key in STAGE_ORDER:
        label = STAGES[key]["label"]
        status = state.get(key, {}).get("status")
        files = stage_files.get(key, [])
        if not files:
            if key == "cp1_trajectory_preview":
                return f"{label} 없음 — python input/build_shot.py 또는 모니터 ⚙ 파라미터 저장으로 생성"
            if key == "cp2_hero_frame":
                return f"{label} 없음 — manifest.subject_image_local_path 지정 후 ⚙ 파라미터 저장, 또는 Colab에서 직접 전처리"
            if key == "cp3_segments":
                return "CP1·CP2 승인 완료 — Colab 3번 셀(워크플로우 조립+큐 전송) 실행 가능"
            if key == "cp4_final":
                return "CP3 승인 완료 — Colab 5번 셀(결과 다운로드) 후 CP4에 업로드"
        if status != "approved":
            tag = "검토 후 승인(위임 가능)" if key in DELEGATABLE_GATES else "검토 후 승인 필수"
            return f"{label} {tag} (현재: {status})"
    return "전 단계 승인 완료 ✅"


def _plain(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_plain(v) for v in obj]
    return obj


@app.get("/api/shots")
def list_shots():
    if not OUTPUT_DIR.is_dir():
        return []
    shots = []
    for shot_dir in sorted(p for p in OUTPUT_DIR.iterdir() if p.is_dir()):
        state = _load_pipeline_state(shot_dir.name)
        stage_files = {key: _list_stage_files(shot_dir, key) for key in STAGES}
        stages = {
            key: {
                "label": meta["label"],
                "kind": meta["kind"],
                "delegatable": key in DELEGATABLE_GATES,
                "files": [f"/files/{shot_dir.name}/{key}/{fn}" for fn in stage_files[key]],
                "approval": state[key],
                "locked": _stage_locked(state, key),
                "lock_reason": _lock_reason(state, key),
            }
            for key, meta in STAGES.items()
        }
        shots.append(
            {
                "shot_id": shot_dir.name,
                "stages": stages,
                "next_action": _next_action(state, stage_files),
                "has_params": (BRIEFS_DIR / f"{shot_dir.name}.yaml").is_file(),
            }
        )
    return shots


class ApprovalUpdate(BaseModel):
    status: str
    note: str = ""


@app.post("/api/shots/{shot_id}/{stage_key}/approval")
def set_approval(shot_id: str, stage_key: str, body: ApprovalUpdate):
    if stage_key not in STAGES:
        raise HTTPException(400, f"알 수 없는 단계: {stage_key}")
    if body.status not in VALID_STATUSES:
        raise HTTPException(400, f"status는 {sorted(VALID_STATUSES)} 중 하나")
    state = _load_pipeline_state(shot_id)
    state[stage_key] = {"status": body.status, "note": body.note, "at": _now()}
    _save_pipeline_state(shot_id, state)
    return state


@app.post("/api/shots/{shot_id}/{stage_key}/upload")
async def substitute_file(shot_id: str, stage_key: str, file: UploadFile = File(...)):
    """단계별 파일을 사람이 직접 교체/등록할 때 쓰는 업로드 엔드포인트.

    GATE_REQUIRES에 걸린 선행 단계가 approved가 아니면 409 — Colab 생성 결과를
    CP1/CP2 승인 없이 CP3에 밀어넣는 걸 서버가 구조적으로 막는다.
    """
    if stage_key not in STAGES:
        raise HTTPException(400, f"알 수 없는 단계: {stage_key}")
    if ".." in shot_id or "/" in shot_id or "\\" in shot_id:
        raise HTTPException(400, "잘못된 shot_id")

    state = _load_pipeline_state(shot_id)
    if _stage_locked(state, stage_key):
        raise HTTPException(409, _lock_reason(state, stage_key) or "이 단계는 아직 잠겨 있습니다")

    ext = Path(file.filename or "").suffix.lower()
    expected = IMAGE_EXT if STAGES[stage_key]["kind"] == "image" else VIDEO_EXT
    if ext not in expected:
        raise HTTPException(400, f"{stage_key}에는 {sorted(expected)} 형식만 가능 (받은 파일: {ext})")

    stage_dir = OUTPUT_DIR / shot_id / stage_key
    stage_dir.mkdir(parents=True, exist_ok=True)
    dest = stage_dir / file.filename
    dest.write_bytes(await file.read())
    return {"saved": f"/files/{shot_id}/{stage_key}/{file.filename}"}


@app.get("/api/techniques")
def list_techniques():
    """control/camera_paths.py의 4종 기법 + ComfyUI Wan2.1-VACE 엔진 파라미터를
    함수 시그니처에서 직접 뽑아 반환 — 사이드바의 "기법 둘러보기"와 파라미터
    패널의 기법별 폼이 이 응답 하나로 그려진다. 코드가 바뀌면 여기도 자동으로
    맞춰지므로 숫자를 이 파일에 따로 베껴 적지 않는다."""
    return {"techniques": TECHNIQUE_SCHEMA, "vace_params": VACE_PARAM_SCHEMA}


@app.get("/api/shots/{shot_id}/params")
def get_params(shot_id: str):
    brief_path = BRIEFS_DIR / f"{shot_id}.yaml"
    if not brief_path.is_file():
        raise HTTPException(404, f"매니페스트 없음: {brief_path.relative_to(ROOT)}")
    data = _yaml.load(brief_path.read_text(encoding="utf-8"))
    return _plain(data)


@app.post("/api/shots/{shot_id}/params")
def update_params(shot_id: str, payload: dict):
    """생성 파라미터를 cinematography_briefs/<shot_id>.yaml에 반영하고
    input/build_shot.py를 즉시 재실행해 궤적·워크플로우·CP1/CP2 프리뷰를
    새로 뽑는다. 파라미터가 바뀌었으니 CP1/CP2 승인은 재승인 필요로 리셋."""
    brief_path = BRIEFS_DIR / f"{shot_id}.yaml"
    if not brief_path.is_file():
        raise HTTPException(404, f"매니페스트 없음: {brief_path.relative_to(ROOT)}")

    data = _yaml.load(brief_path.read_text(encoding="utf-8"))
    nested_params = payload.pop("params", None)
    for k, v in payload.items():
        data[k] = v
    if nested_params is not None:
        # 부분 병합이 아니라 전체 교체 — technique을 바꾸면 이전 기법의 파라미터
        # 이름(예: radius/height)이 새 기법 함수가 모르는 인자로 남아 build_shot.py가
        # TypeError로 죽는다. 폼은 항상 현재 기법의 전체 필드를 보내므로 교체가 맞다.
        data["params"] = nested_params

    with brief_path.open("w", encoding="utf-8") as f:
        _yaml.dump(data, f)

    result = subprocess.run(
        [sys.executable, str(ROOT / "input" / "build_shot.py"), str(brief_path)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise HTTPException(500, f"build_shot.py 실패:\n{result.stderr or result.stdout}")

    state = _load_pipeline_state(shot_id)
    for gate in ("cp1_trajectory_preview", "cp2_hero_frame"):
        state[gate] = {"status": "pending", "note": "파라미터 변경으로 재승인 필요", "at": _now()}
    _save_pipeline_state(shot_id, state)

    return {"saved": True, "build_log": result.stdout, "state": state}


@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=4100)
