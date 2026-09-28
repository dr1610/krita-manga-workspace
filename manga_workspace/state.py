"""Versioned document metadata; independent of Qt and model backends."""
import json
import math
import uuid

ANNOTATION = "manga_workspace/v1"
DEFAULT_SCENE_PROMPT = "masterpiece, best_quality, very_aesthetic, detailed, clean_lineart, manga"
DEFAULT_NEGATIVE_PROMPT = "worst_quality, low_quality, lowres, blurry, bad_anatomy, bad_hands, text, watermark"


def empty():
    return {"version": 1, "page_id": str(uuid.uuid4()), "scene_prompt": DEFAULT_SCENE_PROMPT,
            "negative_prompt": DEFAULT_NEGATIVE_PROMPT, "prompt_defaults_version": 1,
            "target": None, "target_mode": "current_panel",
            "model": "anima:" + "_Anima\\anima_baseV10_test03_baked.safetensors",
            "seed": -1, "steps": 28, "guidance": 7.0,
            "regions": []}


def normalize(state):
    """Add fields introduced after v1 without invalidating existing .kra files."""
    if not isinstance(state, dict):
        return state
    state.setdefault("negative_prompt", "")
    if "prompt_defaults_version" not in state:
        if not state.get("scene_prompt", "").strip():
            state["scene_prompt"] = DEFAULT_SCENE_PROMPT
        if not state.get("negative_prompt", "").strip():
            state["negative_prompt"] = DEFAULT_NEGATIVE_PROMPT
        state["prompt_defaults_version"] = 1
    state.setdefault("target_mode", "current_panel")
    state.setdefault("model", "Anima")
    state.setdefault("seed", -1)
    state.setdefault("steps", 28)
    state.setdefault("guidance", 7.0)
    for region in state.get("regions", []):
        region.setdefault("kind", "character")
        region.setdefault("negative_prompt", "")
        region.setdefault("position_mode", "custom")
        region.setdefault("point", None)
        region.setdefault("text_type", "未分類")
        region.setdefault("text_render", "文字を描かず空間を確保")
        region.setdefault("text_content", "")
        region.setdefault("parent_panel_id", None)
    return state


def bbox(value):
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError("領域の座標形式が不正です")
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in value):
        raise ValueError("領域の座標は有限の数値である必要があります")
    x, y, w, h = value
    if x < 0 or y < 0 or w <= 0 or h <= 0:
        raise ValueError("領域の位置または大きさが不正です")
    return value


def validate(state):
    normalize(state)
    if not isinstance(state, dict) or state.get("version") != 1:
        raise ValueError("この配置データのバージョンには対応していません")
    if not isinstance(state.get("page_id"), str) or not state["page_id"]:
        raise ValueError("ページIDがありません")
    if not isinstance(state.get("scene_prompt"), str) or not isinstance(state.get("negative_prompt"), str):
        raise ValueError("場面Promptが不正です")
    if state.get("target_mode") not in ("current_panel", "selection", "full_page"):
        raise ValueError("生成対象が不正です")
    if not isinstance(state.get("model"), str) or not state["model"]:
        raise ValueError("モデル名が不正です")
    if type(state.get("seed")) is not int or type(state.get("steps")) is not int:
        raise ValueError("生成設定が不正です")
    if type(state.get("guidance")) not in (int, float) or not math.isfinite(state["guidance"]):
        raise ValueError("Guidanceが不正です")
    if state.get("target") is not None:
        bbox(state["target"])
    regions = state.get("regions")
    if not isinstance(regions, list) or len(regions) > 1000:
        raise ValueError("配置一覧が不正です")
    ids = set()
    for region in regions:
        if not isinstance(region, dict):
            raise ValueError("配置データが不正です")
        rid = region.get("id")
        if not isinstance(rid, str) or not rid or rid in ids:
            raise ValueError("配置IDが重複または欠落しています")
        ids.add(rid)
        bbox(region.get("bbox"))
        if any(not isinstance(region.get(key), str) for key in
               ("name", "prompt", "negative_prompt", "kind", "position_mode",
                "text_type", "text_render", "text_content")):
            raise ValueError("配置名またはPromptが不正です")
        if region["text_type"] not in ("未分類", "台詞", "オノマトペ", "効果音", "モノローグ", "ナレーター"):
            raise ValueError("テキスト分類が不正です")
        if region["text_render"] not in ("文字を描かず空間を確保", "吹き出しを残し文字は描かない", "指定した文字を描く"):
            raise ValueError("文字の描画方法が不正です")
        if region.get("parent_panel_id") is not None and not isinstance(region["parent_panel_id"], str):
            raise ValueError("所属コマIDが不正です")
        point = region.get("point")
        if point is not None and (not isinstance(point, list) or len(point) != 2 or
                                  any(type(v) not in (int, float) or not math.isfinite(v) for v in point)):
            raise ValueError("配置点が不正です")
    return state


def decode(data):
    return validate(normalize(json.loads(data.decode("utf-8")))) if data else empty()


def encode(state):
    return json.dumps(validate(state), ensure_ascii=False).encode("utf-8")


def add_region(state, bounds):
    region = {"id": str(uuid.uuid4()), "name": "配置 %d" % (len(state["regions"]) + 1),
              "prompt": "", "negative_prompt": "", "kind": "character",
              "position_mode": "custom", "point": [bounds[0] + bounds[2] / 2,
                                                       bounds[1] + bounds[3] / 2],
              "bbox": list(bbox(bounds)), "parent_panel_id": None,
              "text_type": "未分類", "text_render": "文字を描かず空間を確保",
              "text_content": ""}
    state["regions"].append(region)
    return region
