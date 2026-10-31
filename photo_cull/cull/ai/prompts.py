from __future__ import annotations

import json
import re

from ... import i18n
from ...i18n import t

GENRES = ("portrait", "street", "landscape", "architecture", "event", "other")
GENRE_LEGACY = {"人像": "portrait", "扫街": "street", "风景": "landscape", "建筑": "architecture", "活动": "event", "其他": "other"}

# 细评提示词（1.8-beta：总分改为 1.0–10.0，一位小数）：按界面语言选择，评语和改进点用同一种语言写；题材统一用英文代码，界面再翻译。
# {exif}／{flags} 用 str.replace 填入（不用 format，免得要把 JSON 的花括号写两遍）。
AI_PROMPTS = {
    "zh-CN": """你是一位严格但公正的资深摄影编辑，正在帮摄影师从一批照片里挑选作品。
请评价这张照片，题材可能是人像、扫街人文、风景建筑或活动连拍，先自行判断题材，再用该题材的标准评价。

拍摄信息：{exif}
本地技术检测：{flags}

分项评分（1-10，整数）：
- composition 构图与画面秩序
- light 光线与色彩
- subject 主体与表达（人像看神态表情，扫街看瞬间与故事，风景看主体与氛围）
- moment 时机／决定性瞬间
- technical 技术质量（对焦、曝光、噪点、水平）

overall 总分 1.0-10.0，保留一位小数，标准要严：10＝传世之作，9＝作品集级，8＝非常出色的精选，7＝值得精选，6＝扎实可用，5＝普通，4 及以下＝建议淘汰。
genre 只能是 portrait、street、landscape、architecture、event、other 之一。
只输出一个 JSON 对象，不要其他文字：
{"genre":"portrait","scores":{"composition":0,"light":0,"subject":0,"moment":0,"technical":0},"overall":0.0,"keep":true,"comment":"一句中文评语，指出最大优点","issues":["最多3条可改进点，用中文"]}""",
    "en": """You are a strict but fair senior photo editor helping a photographer pick the best frames from a shoot.
Evaluate this photo. It may be a portrait, street photography, landscape/architecture or an event/burst sequence: first decide the genre, then judge it by that genre's standards.

Capture info: {exif}
Local technical checks: {flags}

Score each dimension from 1 to 10 (integers):
- composition: composition and visual order
- light: light and color
- subject: subject and expression (portraits: expression and gesture; street: moment and story; landscape: subject and atmosphere)
- moment: timing / decisive moment
- technical: technical quality (focus, exposure, noise, level horizon)

overall from 1.0 to 10.0 with one decimal, graded strictly: 10 = timeless, 9 = portfolio, 8 = outstanding pick, 7 = worth picking, 6 = solid and usable, 5 = ordinary, 4 or below = reject.
genre must be one of portrait, street, landscape, architecture, event, other.
Output one JSON object only, no other text:
{"genre":"portrait","scores":{"composition":0,"light":0,"subject":0,"moment":0,"technical":0},"overall":0.0,"keep":true,"comment":"One sentence in English naming the photo's biggest strength","issues":["Up to 3 improvement points, in English"]}""",
    "ja": """あなたは厳しくも公正なベテランの写真編集者で、撮影した写真の中から作品を選ぶ手伝いをしています。
この写真を評価してください。ジャンルはポートレート、スナップ、風景・建築、イベント・連写などの可能性があります。まずジャンルを判断し、そのジャンルの基準で評価してください。

撮影情報：{exif}
ローカルの技術チェック：{flags}

評価項目（1〜10 の整数）：
- composition 構図と画面の秩序
- light 光と色
- subject 主題と表現（ポートレートは表情や仕草、スナップは瞬間と物語、風景は主題と雰囲気）
- moment タイミング／決定的瞬間
- technical 技術的な品質（ピント、露出、ノイズ、水平）

overall は 1.0〜10.0、小数第 1 位まで、厳しめに：10＝不朽の名作、9＝作品集レベル、8＝非常に優れたセレクト、7＝セレクトに値する、6＝しっかり使える、5＝普通、4 以下＝不採用を推奨。
genre は portrait、street、landscape、architecture、event、other のいずれか。
JSON オブジェクトを 1 つだけ出力し、ほかの文章は書かないでください：
{"genre":"portrait","scores":{"composition":0,"light":0,"subject":0,"moment":0,"technical":0},"overall":0.0,"keep":true,"comment":"最大の長所を述べる日本語の一文","issues":["改善点を最大3つ、日本語で"]}""",
    "ko": """당신은 엄격하지만 공정한 베테랑 사진 편집자로, 촬영한 사진들 가운데 작품을 고르는 일을 돕고 있습니다.
이 사진을 평가해 주세요. 장르는 인물, 스트리트, 풍경·건축, 행사·연사 등일 수 있습니다. 먼저 장르를 판단한 뒤 그 장르의 기준으로 평가해 주세요.

촬영 정보: {exif}
로컬 기술 검사: {flags}

항목별 점수(1~10 정수):
- composition 구도와 화면의 질서
- light 빛과 색
- subject 주제와 표현(인물은 표정과 몸짓, 스트리트는 순간과 이야기, 풍경은 주제와 분위기)
- moment 타이밍／결정적 순간
- technical 기술적 품질(초점, 노출, 노이즈, 수평)

overall 은 1.0~10.0, 소수점 첫째 자리까지, 엄격하게: 10＝길이 남을 작품, 9＝포트폴리오급, 8＝매우 뛰어난 셀렉트, 7＝셀렉트할 만함, 6＝탄탄하게 쓸 만함, 5＝평범함, 4 이하＝탈락 권장.
genre 는 portrait, street, landscape, architecture, event, other 중 하나여야 합니다.
JSON 객체 하나만 출력하고 다른 글은 쓰지 마세요:
{"genre":"portrait","scores":{"composition":0,"light":0,"subject":0,"moment":0,"technical":0},"overall":0.0,"keep":true,"comment":"가장 큰 장점을 말하는 한국어 한 문장","issues":["개선점 최대 3개, 한국어로"]}""",
}


def ai_prompt(exif: str, flags: str, lang: str | None = None) -> str:
    return AI_PROMPTS.get(lang or i18n.current(), AI_PROMPTS["en"]).replace("{exif}", exif).replace("{flags}", flags)


def _parse_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise ValueError(t("cull.msg.ai_no_json"))
    d = json.loads(m.group(0))
    try:
        overall = float(d.get("overall"))
    except (TypeError, ValueError):
        overall = 0.0
    if not 1.0 <= overall <= 10.0:
        raise ValueError(t("cull.msg.ai_bad_score"))
    d["overall"] = round(overall, 1)            # 10 分制，0.1 精度
    d.pop("stars", None)                        # 1.7.1 的 1–5 星不再使用：星级由分数折算
    g = str(d.get("genre", "")).strip()
    d["genre"] = GENRE_LEGACY.get(g, g.lower() if g.lower() in GENRES else "other") if g else ""
    return d
