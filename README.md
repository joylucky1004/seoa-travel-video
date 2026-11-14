# SEOA Travel AI Video Automation

SEOA 캐릭터가 등장하는 여행 인스타그램 릴스(9:16)를 자동으로 만드는 프로젝트입니다.
**Claude Code**로 개발하고, **공식 Higgsfield API**로 AI 영상을 만든 뒤, **Python + FFmpeg**로
편집 · 한국어 자막 · 마지막 CTA(`Follow @staypick.kr`)까지 자동으로 처리합니다.

> ⚠️ 기본값은 **Mock 모드**입니다. Higgsfield API를 호출하지 않으므로 크레딧이 사용되지 않습니다.
> Mock 모드에서는 FFmpeg가 색상 화면으로 된 임시 클립을 만들어 전체 흐름을 무료로 테스트합니다.
> 실제 생성(Live 모드)은 환경변수 두 개를 켜고, 작업마다 **예상 비용을 확인한 뒤 승인**해야 시작됩니다.

## 주요 기능

| 기능 | 상태 |
|---|---|
| iPad에서 쓰는 웹 화면 (Safari, 홈 화면 추가 지원) | ✅ |
| SEOA 레퍼런스 이미지 업로드 / 삭제 | ✅ |
| 캐릭터 일관성 규칙 편집 → 모든 프롬프트에 자동 삽입 | ✅ |
| 9:16 (1080×1920) 영상 생성 파이프라인 | ✅ |
| Higgsfield 공식 API 연동 (레퍼런스 기반 9:16 모델) | ✅ 실제 생성은 승인 후 |
| 크레딧 절약 기본값: 최저 해상도(≤720p) · 최소 길이 · 오디오 끔 · 1개 장면 테스트 | ✅ |
| 모델별 무료 비용 비교 → 직접 선택 (자동 전환 없음) | ✅ |
| 무료 프롬프트 · 장면 구성 미리보기, MOCK 실행 | ✅ |
| 같은 장면 재사용 (중복 생성 방지) | ✅ |
| 작업 전 무료 비용 견적 → iPad에서 승인 / 취소 | ✅ |
| 장면별 생성 상태 · 오류 표시, 실패 장면만 다시 시도 | ✅ |
| 장면 클립 · 최종 릴스 MP4 다운로드 | ✅ |
| FFmpeg 자동 편집 (정규화 · 이어붙이기 · 인코딩) | ✅ |
| 한국어 자막 자동 삽입 (ASS / libass) | ✅ |
| 엔딩 CTA “Follow @staypick.kr” | ✅ |
| 환경변수(.env)로 API 키 관리 | ✅ |
| 배경음악, 업로드 자동화 | ⏳ 예정 |

## 폴더 구조

```
seoa-travel-video/
├── app/
│   ├── main.py                  # FastAPI 웹 서버 + API
│   ├── config.py                # 환경변수 설정 (API 키는 SecretStr로 보호)
│   ├── models.py                # 릴스/장면/작업 데이터 모델
│   ├── services/
│   │   ├── character.py         # SEOA 프로필 + 레퍼런스 이미지 관리
│   │   ├── prompt_builder.py    # 일관성 규칙이 포함된 프롬프트 생성
│   │   ├── higgsfield/
│   │   │   ├── base.py          # 영상 생성기 인터페이스
│   │   │   ├── mock.py          # Mock 클라이언트 (무료, 로컬 FFmpeg)
│   │   │   └── live.py          # 공식 API 클라이언트 스켈레톤 (아직 호출 안 함)
│   │   ├── subtitles.py         # 한국어 자막 + CTA (ASS)
│   │   ├── editor.py            # FFmpeg 편집 파이프라인
│   │   └── pipeline.py          # 작업 실행 흐름
│   ├── templates/index.html     # iPad용 화면
│   └── static/                  # CSS / JS
├── config/
│   ├── seoa_character.yaml      # SEOA 캐릭터 설정 (외모, 의상, 일관성 규칙)
│   └── video_presets.yaml       # 9:16 출력 · 자막 · CTA 스타일
├── assets/
│   ├── characters/seoa/references/  # 레퍼런스 이미지 (git에 올라가지 않음)
│   └── fonts/                   # 한글 폰트 (.ttf/.otf) 넣는 곳
├── data/                        # 작업 결과 · 렌더링 영상 (git 제외)
├── scripts/run_dev.sh           # 개발 서버 실행
├── tests/                       # pytest
├── .env.example                 # 환경변수 예시
├── CLAUDE.md                    # Claude Code 작업 규칙
└── requirements.txt
```

## 실행 방법

필요한 것: Python 3.11 이상, FFmpeg (libass 포함 빌드)

```bash
python -m venv .venv && source .venv/bin/activate
```

```bash
pip install -r requirements.txt
```

```bash
./scripts/run_dev.sh
```

`.env`가 없으면 `.env.example`을 복사해 Mock 모드로 시작합니다.
브라우저에서 `http://localhost:8000` 을 엽니다.

### iPad에서 사용하기

1. 서버를 실행한 컴퓨터와 iPad를 같은 Wi-Fi에 연결합니다.
2. iPad Safari에서 `http://<컴퓨터의 IP>:8000` 으로 접속합니다.
3. 공유 버튼 → **홈 화면에 추가**를 누르면 앱처럼 사용할 수 있습니다.
4. 네트워크에 열어둘 때는 `.env`에 `APP_PASSWORD`를 꼭 설정하세요 (아이디: `seoa`).

### 한글 자막 폰트

`assets/fonts/`에 [Noto Sans KR](https://fonts.google.com/noto/specimen/Noto+Sans+KR) 같은
한글 폰트 파일을 넣고, `.env`의 `SUBTITLE_FONT_NAME`을 폰트 이름과 맞춰주세요.
폰트가 없으면 시스템에 설치된 한글 폰트로 대체됩니다.

## 크레딧 절약 규칙

| 규칙 | 동작 |
|---|---|
| 가장 저렴한 설정 | 모델마다 문서상 최저 해상도(720p 이하) · 최소 길이 · 오디오 끔으로 요청 |
| 모델 | 허용 목록(`app/services/higgsfield/models.py`)만 사용. 비용 비교 후 **직접 선택할 때만** 변경 |
| 무료 검증 | "프롬프트 · 장면 구성 미리보기"와 MOCK 실행은 API를 호출하지 않음 |
| 1개 장면 테스트 | Live 작업은 `MAX_CLIPS_PER_JOB`(기본 1)개 장면까지만 생성 |
| 비용 확인 · 승인 | 무료 견적 → 예상 비용 표시 → **승인하고 생성**을 눌러야 요청 전송 |
| 비용 한도 | 견적이 `MAX_USD_PER_JOB`(기본 $1.00)를 넘으면 승인 불가 |
| 재사용 | 모델 · 설정 · 프롬프트 · 레퍼런스가 같은 장면은 저장된 클립을 재사용 ($0) |
| 재시도 | 실패 시 자동 재시도 없음. "실패 장면 다시 시도" → 다시 견적 → 다시 승인 |
| 편집 | 자막 · 장면 연결 · CTA · 길이 맞춤(최대 2배 슬로모션 + 마지막 장면 정지)은 서버 FFmpeg로 처리 |

> 공식 문서에는 모델별 가격이 없고 "Mini" 모델도 없습니다. 실제 가격은 계정마다 다를 수 있어
> "모델별 비용 비교" 버튼이 무료 견적 API(`POST /estimate/{model}`)로 확인합니다.
> 그 전까지 기본 모델은 문서상 해상도가 가장 낮고(480p) 최소 길이가 가장 짧은(1초)
> `xai/grok-imagine-video/v1.5/reference-to-video`입니다.

## Higgsfield Live 모드 설정 (Render)

공식 문서(https://docs.higgsfield.ai) 기준으로 구현했습니다. 인증은
`Authorization: Key KEY_ID:KEY_SECRET`이며 서버에서만 사용합니다.

Render 대시보드 → 서비스 → **Environment**에서 아래 값을 설정합니다.

| 변수 | 설명 |
|---|---|
| `HF_API_KEY` | Higgsfield Console의 `KEY_ID:KEY_SECRET` (또는 `HF_API_KEY_ID` + `HF_API_KEY_SECRET`) |
| `APP_PASSWORD` | **필수.** 없으면 Live 작업과 비용 비교가 거부됩니다 (아이디 `seoa`) |
| `HIGGSFIELD_MODE` | `live` |
| `ALLOW_PAID_API_CALLS` | `true` |
| `HIGGSFIELD_MODEL` | 선택. 비용 비교로 확인한 모델을 고정하려면 입력 (재시작해도 유지) |

설정 후에도 영상은 자동으로 만들어지지 않습니다. 작업 목록에서 예상 비용을 확인하고
**승인하고 생성**을 눌러야 크레딧이 사용됩니다. 실패하거나 검수(NSFW)에 걸린 요청은
Higgsfield가 과금하지 않습니다.

> Render 무료 플랜은 디스크가 영구적이지 않아 재시작 · 재배포 시 레퍼런스 이미지, 결과물,
> 재사용 캐시, UI에서 고른 모델이 지워집니다. 고른 모델은 `HIGGSFIELD_MODEL`에도 넣어두세요.

## 보안 · 크레딧 안전장치

- API 키는 **`.env`에만** 저장하며 `.gitignore`로 git에서 제외됩니다. 코드에서는 `SecretStr`로 감싸
  로그나 API 응답에 노출되지 않습니다.
- 실제 Higgsfield 호출은 **두 가지 스위치가 모두 켜져야만** 가능합니다.
  - `HIGGSFIELD_MODE=live`
  - `ALLOW_PAID_API_CALLS=true`
- 두 스위치가 켜져 있어도 작업마다 **iPad에서 승인**해야 생성 요청이 전송됩니다.
- Live 모드는 `APP_PASSWORD`가 설정되어 있어야만 동작합니다 (URL만 알면 크레딧을 쓰는 상황 방지).
- Live 모드에서도 `MAX_CLIPS_PER_JOB`로 작업당 클립 수를 제한합니다.
- 브라우저에는 키가 전달되지 않으며 `/api/status`는 키 설정 여부(ok / incomplete / missing)만 알려줍니다.
- 레퍼런스 이미지(`assets/characters/seoa/references/`)와 결과물(`data/`)은 git에 올라가지 않습니다.

## 영상 처리 흐름

```
iPad 입력 (제목 · 장소 · 장면별 내용/자막)
   │
   ▼
프롬프트 생성 ── SEOA 외모 + 의상 + 일관성 규칙 + 9:16 + 네거티브 프롬프트
   │
   ▼
영상 생성 ── Mock: FFmpeg 임시 클립   |   Live: Higgsfield API (레퍼런스 이미지 첨부)
   │
   ▼
FFmpeg 편집 ── 1080×1920 / 30fps 정규화 → CTA 카드 추가 → 이어붙이기
   │
   ▼
자막 삽입 ── 장면별 한국어 자막 + 마지막 “Follow @staypick.kr”
   │
   ▼
reel_final.mp4 (H.264 + AAC, faststart)
```

## 테스트

```bash
python -m pytest -q
```

## 다음 단계 (제안)

1. 짧은 장면 1개로 Live 모드 첫 테스트 (승인 후)
2. 레퍼런스 이미지 · 결과물을 영구 저장소로 옮기기 (Render 디스크 또는 외부 스토리지)
3. 배경음악 · 효과음 믹싱
4. Claude로 장소 정보 → 장면 구성/자막 자동 작성
5. 원격 접속이 필요하면 배포 (HTTPS + 인증)
