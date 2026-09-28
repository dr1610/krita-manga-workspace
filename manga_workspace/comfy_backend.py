"""Small ComfyUI client used by the first real AI preview path."""
import json
import time
import uuid
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SERVER = "http://127.0.0.1:8188"
ANIMA_CHECKPOINT = "_Anima\\anima_baseV10_test03_baked.safetensors"
ANIMA_TEXT_ENCODER = "qwen_3_06b_base.safetensors"
ANIMA_VAE = "qwen_image_vae.safetensors"


def model_options(server=SERVER):
    """Return models ComfyUI actually exposes, with the loader each architecture needs."""
    options = [("Anima Base v1.0", "anima:" + ANIMA_CHECKPOINT)]
    try:
        info = _json(server + "/object_info/CheckpointLoaderSimple", timeout=3)
        names = info["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]
    except Exception:
        return options
    seen = {ANIMA_CHECKPOINT.lower()}
    for name in names:
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        stem = name.replace("\\", " / ").rsplit(".", 1)[0]
        kind = "anima" if name.lower().startswith("_anima\\") else "checkpoint"
        options.append((stem, kind + ":" + name))
    return options


def server_available(server=SERVER):
    try:
        return bool(_json(server + "/system_stats", timeout=3))
    except Exception:
        return False


def model_spec(model_id):
    if not model_id or model_id.lower() == "anima":
        return "anima", ANIMA_CHECKPOINT
    if ":" not in model_id:
        return "checkpoint", model_id
    kind, name = model_id.split(":", 1)
    return kind, name


def generation_size(bounds, maximum=768, minimum=256):
    """Fit a target rectangle to practical, 32-aligned diffusion dimensions."""
    width, height = float(bounds[2]), float(bounds[3])
    scale = min(1.0, maximum / max(width, height))
    width, height = width * scale, height * scale
    if max(width, height) < minimum:
        scale = minimum / max(width, height)
        width, height = width * scale, height * scale
    width = max(64, min(maximum, int(round(width / 32)) * 32))
    height = max(64, min(maximum, int(round(height / 32)) * 32))
    return width, height


def partition_regions(regions):
    """Make rectangular character/object regions disjoint at their center boundary."""
    result = [dict(region, bbox=list(region["bbox"])) for region in regions]
    for first_index in range(len(result)):
        for second_index in range(first_index + 1, len(result)):
            first, second = result[first_index]["bbox"], result[second_index]["bbox"]
            left, top = max(first[0], second[0]), max(first[1], second[1])
            right = min(first[0] + first[2], second[0] + second[2])
            bottom = min(first[1] + first[3], second[1] + second[3])
            if right <= left or bottom <= top:
                continue
            first_center = [first[0] + first[2] / 2, first[1] + first[3] / 2]
            second_center = [second[0] + second[2] / 2, second[1] + second[3] / 2]
            if abs(first_center[0] - second_center[0]) >= abs(first_center[1] - second_center[1]):
                boundary = (first_center[0] + second_center[0]) / 2
                left_region, right_region = ((first, second) if first_center[0] <= second_center[0]
                                             else (second, first))
                left_region[2] = max(1, boundary - left_region[0])
                old_right = right_region[0] + right_region[2]
                right_region[0] = boundary
                right_region[2] = max(1, old_right - boundary)
            else:
                boundary = (first_center[1] + second_center[1]) / 2
                top_region, bottom_region = ((first, second) if first_center[1] <= second_center[1]
                                             else (second, first))
                top_region[3] = max(1, boundary - top_region[1])
                old_bottom = bottom_region[1] + bottom_region[3]
                bottom_region[1] = boundary
                bottom_region[3] = max(1, old_bottom - boundary)
    return result


def scaled_regions(regions, bounds, width, height):
    """Clip document BBoxes to the target and map them into generation pixels."""
    x, y, target_width, target_height = bounds
    mapped = []
    for region in partition_regions(regions):
        rx, ry, rw, rh = region["bbox"]
        left, top = max(x, rx), max(y, ry)
        right, bottom = min(x + target_width, rx + rw), min(y + target_height, ry + rh)
        if right <= left or bottom <= top:
            continue
        px = max(0, min(width - 1, round((left - x) / target_width * width)))
        py = max(0, min(height - 1, round((top - y) / target_height * height)))
        pr = max(px + 1, min(width, round((right - x) / target_width * width)))
        pb = max(py + 1, min(height, round((bottom - y) / target_height * height)))
        mapped.append(dict(region, bbox=[px, py, pr - px, pb - py]))
    return mapped


def workflow(prompt, negative, seed, steps, guidance, width, height, regions=None,
             checkpoint=ANIMA_CHECKPOINT, prefix="krita_manga_preview", model_id="anima"):
    kind, selected_checkpoint = model_spec(model_id)
    if checkpoint != ANIMA_CHECKPOINT and model_id == "anima":
        selected_checkpoint = checkpoint
    graph = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": selected_checkpoint}},
        "4": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height,
                                                                  "batch_size": 1}},
        "5": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "seed": seed,
                "steps": steps, "cfg": guidance,
                "sampler_name": "er_sde" if kind == "anima" else "euler_ancestral",
                "scheduler": "simple" if kind == "anima" else "normal",
                "positive": ["2", 0], "negative": ["3", 0],
                "latent_image": ["4", 0], "denoise": 1.0}},
        "7": {"class_type": "SaveImage", "inputs": {"images": ["6", 0], "filename_prefix": prefix}},
    }
    if kind == "anima":
        graph["8"] = {"class_type": "CLIPLoader", "inputs": {"clip_name": ANIMA_TEXT_ENCODER,
                                                                  "type": "stable_diffusion", "device": "default"}}
        graph["9"] = {"class_type": "VAELoader", "inputs": {"vae_name": ANIMA_VAE}}
        clip, vae = ["8", 0], ["9", 0]
    else:
        clip, vae = ["1", 1], ["1", 2]
    graph["2"] = {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": clip}}
    graph["3"] = {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": clip}}
    graph["6"] = {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": vae}}
    if regions:
        graph["10"] = {"class_type": "ETN_BackgroundRegion",
                       "inputs": {"conditioning": ["2", 0]}}
        previous = ["10", 0]
        for index, region in enumerate(regions):
            base = 20 + index * 5
            clip, blank, solid, composite, define = [str(base + offset) for offset in range(5)]
            x, y, region_width, region_height = [int(round(v)) for v in region["bbox"]]
            graph[clip] = {"class_type": "CLIPTextEncode",
                           "inputs": {"text": region["prompt"], "clip": graph["2"]["inputs"]["clip"]}}
            graph[blank] = {"class_type": "SolidMask",
                            "inputs": {"value": 0.0, "width": width, "height": height}}
            graph[solid] = {"class_type": "SolidMask",
                            "inputs": {"value": 1.0, "width": region_width, "height": region_height}}
            graph[composite] = {"class_type": "MaskComposite",
                                "inputs": {"destination": [blank, 0], "source": [solid, 0],
                                           "x": x, "y": y, "operation": "add"}}
            graph[define] = {"class_type": "ETN_DefineRegion",
                             "inputs": {"mask": [composite, 0], "conditioning": [clip, 0],
                                        "regions": previous}}
            previous = [define, 0]
        graph["11"] = {"class_type": "ETN_AttentionMask",
                       "inputs": {"model": ["1", 0], "regions": previous}}
        graph["5"]["inputs"]["model"] = ["11", 0]
    return graph


def _json(url, payload=None, timeout=30):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(url, data=data, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def generate(prompt, negative, seed, steps, guidance, bounds, regions=None, progress=None,
             server=SERVER, timeout=300, model_id="anima", maximum=768):
    width, height = generation_size(bounds, maximum=maximum)
    mapped_regions = scaled_regions(regions or [], bounds, width, height)
    client_id = str(uuid.uuid4())
    queued = _json(server + "/prompt", {"prompt": workflow(prompt, negative, seed, steps,
                                                             guidance, width, height, mapped_regions,
                                                             model_id=model_id),
                                         "client_id": client_id})
    prompt_id = queued["prompt_id"]
    if progress:
        progress("ComfyUIで生成中… %d×%d" % (width, height))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        history = _json(server + "/history/" + prompt_id, timeout=15)
        record = history.get(prompt_id)
        if record:
            status = record.get("status", {})
            if status.get("status_str") == "error":
                messages = status.get("messages", [])
                raise RuntimeError("ComfyUI生成エラー: " + str(messages[-1] if messages else status))
            for output in record.get("outputs", {}).values():
                images = output.get("images", [])
                if images:
                    image = images[0]
                    query = urlencode({"filename": image["filename"],
                                       "subfolder": image.get("subfolder", ""),
                                       "type": image.get("type", "output")})
                    with urlopen(server + "/view?" + query, timeout=30) as response:
                        return response.read(), {"prompt_id": prompt_id, "seed": seed,
                                                 "size": [width, height], "image": image,
                                                 "regional_prompts": len(mapped_regions)}
        time.sleep(.5)
    raise TimeoutError("ComfyUIの生成が5分以内に完了しませんでした")
