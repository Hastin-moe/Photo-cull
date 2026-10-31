# 기여하기

[简体中文](CONTRIBUTING.md) · [English](CONTRIBUTING.en.md) · [日本語](CONTRIBUTING.ja.md) · **한국어**

개선, 수정, 번역, 아이디어를 환영합니다. 이 프로젝트는 MIT 라이선스이며, 기여한 내용도 MIT 라이선스로 공개되는 데 동의한 것으로 봅니다. Issue와 PR은 중국어, 영어, 일본어, 한국어 중 어느 것으로 써도 됩니다.

## 참여 방법
1. 먼저 Issue를 열어 하려는 일을 설명해 주세요(작은 수정은 바로 PR을 보내도 됩니다).
2. 저장소를 포크하고 `main`에서 브랜치를 만드세요. 예: `feat/xxx`, `fix/xxx`, `i18n/xx`.
3. 테스트(`python3 tests/run.py`)를 실행하고 바꾼 기능을 직접 써 보세요. PR에는 무엇을, 왜 바꿨는지, 어떻게 확인했는지, 기존 결과에 영향이 있는지 적어 주세요.
4. Pull Request를 보내세요. PR 하나에는 변경 하나만 담아 주세요.

## 로컬에서 실행
- macOS: `安装环境.command`(환경 설치)를 더블클릭한 다음 `启动筛选.command`(사진 선별)／`启动编辑.command`(사진 편집)를 여세요.
- Windows: `安装环境.bat`, `启动筛选.bat`, `启动编辑.bat`.
- 터미널에서는 `python3 tools/setup_env.py` 다음에 `.venv/bin/python gui.py`(창 하나. `--start edit`이면 사진 편집을 먼저 보여 주고, `--app cull|edit`이면 하나만 실행, `--lang ko`로 화면 언어 지정).
- 명령줄로만 쓰기: `.venv/bin/python cull.py "사진 폴더"`(`python3 -m photo_cull.cull`과 같음).
- 환경 확인: `python3 tools/setup_env.py --check`.

## 테스트
`python3 tests/run.py`는 `tests/test_*.py`를 하나씩 별도 프로세스에서 실행하며 `HOME`을 임시 폴더로 바꿉니다(본인의 설정은 건드리지 않습니다). 테스트용 사진은 코드로 만들고(`tests/fixtures.py`), AI 정밀 평가는 로컬 가짜 API로 테스트하므로 비용이 들지 않습니다. 파일 하나만 실행하려면 `python3 tests/run.py test_scoring.py`. 버그를 고치거나 기능을 더할 때는 테스트도 추가해 주세요.

## 소스 구조

```
photo_cull/
  version.py     버전 번호(여기에만 씁니다)
  paths.py       고정 위치: 함께 제공되는 리소스(web/, locales/, luts/)와 ~/.photo-cull
  i18n.py        다국어: locales/를 읽고 t("키")로 현재 언어의 문구를 돌려줌
  imaging/       이미지와 EXIF 읽기: 형식, TIFF 구조 RAW, 후지필름 RAF, 미리 보기(선별과 편집이 함께 씀)
  cull/          사진 선별
    model.py       사진 데이터와 results.json 형식(schema 2. 예전 결과는 불러올 때 변환)
    analysis.py    선명도, 노출, 얼굴／눈／미소
    grouping.py    연사와 같은 장면 재촬영 그룹 나누기
    scoring.py     10점 만점 점수, 결정적 순간 가중치, 셀렉트／연사 결정적 순간／사용 가능
    ai/            providers.py(모델과 API 호출), prompts.py(언어별 프롬프트), review.py
    xmp.py         사이드카 XMP와 JPEG 내장 XMP
    organize.py    출력 정리와 이름 바꾸기. trash.py는 휴지통으로 옮기기
    report.py      results.json／csv／report.html
    pipeline.py    단계를 순서대로 실행. cli.py는 명령줄 옵션
  edit/          사진 편집: color, logspace, lut3d, refs／styles(LUT 참조, 사용자 LUT), presets, curves,
                 decode, render, auto, session, records(편집 기록), library, export
  server/        로컬 웹 서버: settings, jobs, apps(두 프로그램), pages, actions(보고서에서의 동작),
                 handler(/api), runtime(창 하나), main
cull.py · gui.py · desktop.py   진입점(명령줄, 로컬 웹 화면, Mac 앱)
web/           프런트엔드: common/(디자인 변수 tokens.css, i18n.js, shell.js), cull/, edit/, report/, shell/
locales/       언어 팩: zh-CN.json, en.json, ja.json, ko.json
luts/          내장 LUT(sRGB)
tests/         테스트(run.py, fixtures.py, test_*.py)
tools/         setup_env.py(환경 구성), build_mac_app.py(Mac 앱), make_release.py(패키지), check_i18n.py(언어 팩 확인)
docs/          작업 기록, 구조 메모, 디자인 방향, 테스트 계획(중국어)
```

## 약속
- **프런트엔드와 백엔드를 나눕니다**: Python에 HTML을 쓰지 마세요. 화면은 `web/`의 파일을 고치고 브라우저를 새로 고치면 됩니다(다시 시작할 필요 없음).
- **사용자에게 보이는 문구는 모두 언어 팩에**: Python은 `t("그룹.키")`, 웹 페이지는 `T("그룹.키")`나 HTML의 `data-i18n="그룹.키"`. 새 문구는 네 언어 모두에 추가하세요. 모르는 언어는 일단 영어로 쓰고 PR에 적어 두면 다른 사람이 번역합니다. 제출 전에 `python3 tools/check_i18n.py`를 실행하세요.
- **색, 글꼴, 모서리 둥글기는 `web/common/tokens.css`의 변수만 씁니다**. 페이지에 색을 직접 쓰지 마세요.
- `photo_cull/cull`과 `photo_cull/edit`는 서로 import하지 않습니다. 둘 다 쓰는 것은 `photo_cull/imaging`에 둡니다.
- 점수는 내부적으로 0.1 단위이고 화면에는 정수로 보여 줍니다. XMP 별점은 항상 점수에서 환산하며(`model.xmp_stars`) 따로 저장하지 않습니다.
- 편집기의 미리 보기와 내보내기는 같은 렌더링 파이프라인을 써야 합니다. 바꾼 뒤에는 둘이 일치하는지 확인하세요.
- 사용자의 원본을 절대 덮어쓰지 않습니다: 쓰기 전에 경로를 확인하고, 삭제는 반드시 휴지통을 거칩니다.
- 저장하는 데이터에는 문장이 아니라 코드를 넣습니다(문제 표시는 `blur`, `clip_high:0.05`, 분류는 `pick`, `moment`… 로 저장하고 표시할 때 번역). 그래야 언어를 바꿔도 예전 결과가 제대로 보입니다. 결과 형식을 바꾸면 `cull/model.py`의 `SCHEMA`를 하나 올리고 `photos_from_json`에서 예전 형식을 변환하세요.
- `.venv`, `dist/`, 개인 사진, API 키는 커밋하지 마세요.

## 번역과 새 언어
- 번역을 고치려면 `locales/<언어>.json`을 편집하세요. 키 이름은 바꾸지 말고 `{자리표시자}`는 그대로 두세요.
- 새 언어를 추가하려면 `locales/en.json`을 `locales/<언어 코드>.json`으로 복사해 번역하고 `photo_cull/i18n.py`의 `LANGS`에 등록합니다. 그리고 `photo_cull/cull/ai/prompts.py`의 `AI_PROMPTS`에 그 언어의 평가 프롬프트(그 언어로 평가를 쓰라고 지시하는 것)를 추가한 뒤 `python3 tools/check_i18n.py`를 실행하세요.
- README는 네 언어로 있습니다(`README.md`, `README.en.md`, `README.ja.md`, `README.ko.md`). 기능을 바꾸면 되도록 함께 고쳐 주세요.

## LUT
- `luts/`에는 내장 LUT가 있으며 작업 색공간은 모두 sRGB입니다. 새 내장 LUT는 후지필름은 「기종 + 필름 시뮬레이션 이름 (sRGB)」, 라이카는 「Leica Look + 필터 이름 (sRGB)」으로 이름을 짓고, 파일 머리에 작업 색공간을 적으세요.
- 혼자 쓸 LUT는 코드를 바꿀 필요가 없습니다. 사진 편집의 「LUT 추가…」를 쓰세요.

## AI 모델
- 고를 수 있는 모델은 `photo_cull/cull/ai/providers.py`의 `PROVIDERS`에 있으며 이미지를 다룰 수 있는 모델만 올립니다. 목록을 바꿀 때는 확인한 날짜와 출처를 적어 주세요.
- OpenAI Chat Completions를 지원하는 새 서비스는 대개 코드를 바꿀 필요가 없습니다(사용자가 「사용자 지정」을 고르고 주소를 넣으면 됩니다). 많이 쓰는 서비스는 `PROVIDERS`에 `api: "chat"`으로 추가하세요.

## 환영하는 방향
- 화면의 디자인과 사용감([docs/GUI设计方向.md](docs/GUI设计方向.md) 참고, 중국어).
- 더 많은 언어로의 번역.
- 얼굴·눈·미소 검출 개선(결정적 순간 가중치가 여기에 달려 있습니다).
- 더 많은 RAW와 EXIF 지원(후지필름 RAF는 실제 샘플이 필요).
- Windows 실기 테스트(지금까지는 정적 검사만 함).
- 자동 조정 방식과 렌즈 비네팅 데이터 개선.
- HDR 표시와 측광(계획 중).

로드맵은 [docs/工作记录.md](docs/工作记录.md)와 [docs/测试计划.md](docs/测试计划.md)(모두 중국어)에 있습니다. 큰 변경에서는 [CHANGELOG.md](CHANGELOG.md)도 함께 고쳐 주세요.
