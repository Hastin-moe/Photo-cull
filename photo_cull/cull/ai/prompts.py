from __future__ import annotations

import json
import re

from ... import i18n
from ...i18n import t

GENRES = ("portrait", "street", "landscape", "architecture", "event", "other")
GENRE_LEGACY = {"人像": "portrait", "扫街": "street", "风景": "landscape", "建筑": "architecture", "活动": "event", "其他": "other"}

# 细评提示词：按界面语言选择，评语和改进点用同一种语言写；题材统一用英文代码，界面再翻译。
# {exif}／{flags} 用 str.replace 填入（不用 format，免得要把 JSON 的花括号写两遍）。
AI_PROMPTS = {
    "zh-CN": """你是一位严格但公正的资深摄影编辑，正在帮摄影师从一批照片里挑选作品。
请评价这张照片，题材可能是人像、扫街人文、风景建筑或活动连拍，先自行判断题材，再用该题材的标准评价。

拍摄信息：{exif}
本地技术检测：{flags}

评分维度（1-10，整数）：
- composition 构图与画面秩序
- light 光线与色彩
- subject 主体与表达（人像看神态表情，扫街看瞬间与故事，风景看主体与氛围）
- moment 时机／决定性瞬间
- technical 技术质量（对焦、曝光、噪点、水平）

stars 给 1-5 星：5=作品级，4=精选，3=可用，2=一般，1=建议淘汰。
genre 只能是 portrait、street、landscape、architecture、event、other 之一。
只输出一个 JSON 对象，不要其他文字：
{"genre":"portrait","scores":{"composition":0,"light":0,"subject":0,"moment":0,"technical":0},"overall":0,"stars":0,"keep":true,"comment":"一句中文评语，指出最大优点","issues":["最多3条可改进点，用中文"]}""",
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

stars from 1 to 5: 5 = portfolio, 4 = pick, 3 = usable, 2 = weak, 1 = reject.
genre must be one of portrait, street, landscape, architecture, event, other.
Output one JSON object only, no other text:
{"genre":"portrait","scores":{"composition":0,"light":0,"subject":0,"moment":0,"technical":0},"overall":0,"stars":0,"keep":true,"comment":"One sentence in English naming the photo's biggest strength","issues":["Up to 3 improvement points, in English"]}""",
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

stars は 1〜5：5＝作品レベル、4＝セレクト、3＝使える、2＝いまひとつ、1＝不採用を推奨。
genre は portrait、street、landscape、architecture、event、other のいずれか。
JSON オブジェクトを 1 つだけ出力し、ほかの文章は書かないでください：
{"genre":"portrait","scores":{"composition":0,"light":0,"subject":0,"moment":0,"technical":0},"overall":0,"stars":0,"keep":true,"comment":"最大の長所を述べる日本語の一文","issues":["改善点を最大3つ、日本語で"]}""",
}


def ai_prompt(exif: str, flags: str, lang: str | None = None) -> str:
    return AI_PROMPTS.get(lang or i18n.current(), AI_PROMPTS["en"]).replace("{exif}", exif).replace("{flags}", flags)


def _parse_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise ValueError(t("cull.msg.ai_no_json"))
    d = json.loads(m.group(0))
    stars = int(d.get("stars", 0))
    if not 1 <= stars <= 5:
        raise ValueError(t("cull.msg.ai_bad_stars"))
    d["stars"] = stars
    g = str(d.get("genre", "")).strip()
    d["genre"] = GENRE_LEGACY.get(g, g.lower() if g.lower() in GENRES else "other") if g else ""
    try:
        d["overall"] = int(round(float(d.get("overall", 0))))
    except (TypeError, ValueError):
        d["overall"] = 0
    return d
