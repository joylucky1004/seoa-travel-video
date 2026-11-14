# SEOA Travel AI Video Automation

SEOA 캐릭터가 등장하는 여행 인스타그램 릴스(9:16)를 자동으로 만드는 프로젝트입니다.
**Claude Code**로 개발하고, **공식 Higgsfield API**로 AI 영상을 만든 뒤, **Python + FFmpeg**로
편집 · 한국어 자막 · 마지막 CTA(`Follow @staypick.kr`)까지 자동으로 처리합니다.

> ⚠️ 현재 버전(v0.1)은 **Mock 모드 전용 프로토타입**입니다. Higgsfield API를 호출하지 않으며
> 크레딧이 전혀 사용되지 않습니다. Mock 모드에서는 FFmpeg가 색상 화면으로 된 임시 클립을 만들어
> 전체 흐름(입력 → 프롬프트 → 편집 → 자막 → CTA)을 무료로 테스트할 수 있습니다.

## 주요 기능

| 기능 | 상태 |
|---|---|
| iPad에서 쓰는 웹 화면 (Safari, 홈 화면 추가 지원) | ✅ |
| SEOA 레퍼런스 이미지 업로드 / 삭제 | ✅ |
| 캐릭터 일관성 규칙 편집 → 모든 프롬프트에 자동 삽입 | ✅ |
| 9:16 (1080×1920) 영상 생성 파이프라인 | ✅ (Mock) |
| Higgsfield 공식 API 연동 | 🟡 구조만 준비 (`live.py` 스켈레톤) |
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

## 보안 · 크레딧 안전장치

- API 키는 **`.env`에만** 저장하며 `.gitignore`로 git에서 제외됩니다. 코드에서는 `SecretStr`로 감싸
  로그나 API 응답에 노출되지 않습니다.
- 실제 Higgsfield 호출은 **두 가지 스위치가 모두 켜져야만** 가능합니다.
  - `HIGGSFIELD_MODE=live`
  - `ALLOW_PAID_API_CALLS=true`
- Live 모드에서도 `MAX_CLIPS_PER_JOB`로 작업당 클립 수를 제한합니다.
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

1. Higgsfield 공식 API 문서를 확인하고 `app/services/higgsfield/live.py` 구현
2. 짧은 클립 1개로 Live 모드 테스트 (크레딧 사용 전 승인)
3. 배경음악 · 효과음 믹싱
4. Claude로 장소 정보 → 장면 구성/자막 자동 작성
5. 원격 접속이 필요하면 배포 (HTTPS + 인증)
