# stereo-morph-pipeline

불릿타임 / 회전 롱테이크 / 연속 롱테이크 / 예측불가 카메라 루프 비행 —
4D 카메라 궤적을 수치로 코딩해 생성 엔진에 직접 주입하는 하이브리드 모핑 파이프라인.

왜: 텍스트 프롬프트만으로 카메라 타이밍을 지시하면 디퓨전 모델이 타이밍을 "잊는"
한계가 실측으로 확인됨(`docs/architecture.md` §0). 그래서 카메라 궤적을 텍스트가
아니라 JSON으로 고정해, Blender(기하학) → ComfyUI(질감)로 넘기는 2단 생성 구조로 전환.

**먼저 읽을 것: [`docs/architecture.md`](docs/architecture.md)** — 5개 레이어
(입력→제어→생성→복원→출력)와 로컬/GitHub/Colab 3단 실행 흐름 전체 설계.
기법별 카메라 수식은 [`docs/camera-techniques.md`](docs/camera-techniques.md).

## 빠른 시작

### 1. 로컬 — 샷 매니페스트 작성 → 궤적 + 워크플로우 자동 생성

```bash
pip install -r requirements.txt

# input/cinematography_briefs/<shot_id>.yaml 로 연출 의도 + 기법 파라미터 작성
# (demo_bullet_time.yaml 참고)

python input/build_shot.py input/cinematography_briefs/<shot_id>.yaml
# -> control/presets/<shot_id>.json      (카메라 궤적)
# -> comfyui/workflows/<shot_id>.json    (ComfyUI 워크플로우)
```

기법 함수를 직접 실행해 4종 데모만 빠르게 보려면:
```bash
cd control && python camera_paths.py
```

### 2. GitHub — 산출물 커밋 & 푸시

```bash
git add control/presets/<shot_id>.json comfyui/workflows/<shot_id>.json
git commit -m "add shot: <shot_id>"
git push
```

### 3. Colab — 실제 생성 (무료 GPU)

`colab/stereo_morph_pipeline.ipynb`를 Colab에서 열고 위에서부터 순서대로 실행.
`REPO_URL`, `SHOT_ID`를 바꿔서 원하는 샷을 생성.

## 상태

- ✅ `control/` — 로컬에서 실행 검증 완료 (4종 기법 전부 JSON 출력 확인)
- ✅ `input/build_shot.py` — 매니페스트 YAML 1장 → 궤적 JSON + ComfyUI 워크플로우
  자동 생성, 로컬에서 end-to-end 검증 완료 (demo_bullet_time 기준)
- ⚠️ `blender/`, `comfyui/`(워크플로우 실행 자체), `refinement/` — 코드는 있지만
  **Colab 실제 실행으로 아직 검증 안 됨**. 노드 이름(class_type)·Blender 버전은
  실행 시 다를 수 있어 조정 필요.
- 다음 단계: Colab에서 `demo_bullet_time` 1개 end-to-end 1차 실행 → 깨지는
  지점 보정 (이 단계는 GPU/브라우저가 필요해 직접 실행해야 함)
