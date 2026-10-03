"""Optional two-image BFS head/body edit on a local ComfyUI Qwen Image 2.1 server."""
import json
import time
import uuid
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from . import comfy_backend


HEAD_LORA = "bfs_head_v1.1_qwen_2.1.safetensors"
BODY_LORA = "bfs_body_swap_v1.0_qwen_2.1.safetensors"


def _choices(server, node_type, field):
    try:
        info = comfy_backend._json(server + "/object_info/" + node_type, timeout=8)
        return info[node_type]["input"]["required"][field][0]
    except Exception as error:
        raise ValueError("ComfyUIに%sがありません。Qwen Image 2.1対応版へ更新してください。" % node_type) from error


def _choose(names, fragments, folder):
    for fragment in fragments:
        match = next((name for name in names if fragment in name.replace("\\", "/").rsplit("/", 1)[-1].lower()), None)
        if match:
            return match
    raise ValueError("ComfyUIのmodels/%sに対応ファイルがありません：%s" % (folder, fragments[0]))


def components(server, mode):
    if mode not in ("head", "body"):
        raise ValueError("BFSの種類が不正です")
    try:
        comfy_backend._json(server + "/system_stats", timeout=3)
    except Exception as error:
        raise ValueError("ComfyUIに接続できません。AI作画の設定でURLと起動状態を確認してください。") from error
    # Query the running server; paths and installed file names are user-owned.
    try:
        comfy_backend._json(server + "/object_info/TextEncodeQwenImage21", timeout=8)["TextEncodeQwenImage21"]
    except Exception as error:
        raise ValueError("ComfyUIにTextEncodeQwenImage21がありません。Qwen Image 2.1対応版へ更新してください。") from error
    unet = _choose(_choices(server, "UNETLoader", "unet_name"),
                   ("qwen_image_2.1_int8", "qwen_image_2.1_bf16", "qwen_image_2.1"), "diffusion_models")
    clip = _choose(_choices(server, "CLIPLoader", "clip_name"),
                   ("qwen3vl_8b_int8", "qwen3vl_8b_bf16", "qwen3vl"), "text_encoders")
    vae = _choose(_choices(server, "VAELoader", "vae_name"),
                  ("qwen_image_2.1_vae",), "vae")
    lora = _choose(_choices(server, "LoraLoaderModelOnly", "lora_name"),
                   ("bfs_head_v1.1_qwen_2.1", "bfs_head_v1_qwen_2.1") if mode == "head"
                   else ("bfs_body_swap_v1.0_qwen_2.1",), "loras")
    return {"unet": unet, "clip": clip, "vae": vae, "lora": lora}


def edit_prompt(mode, user_prompt):
    if mode == "head":
        instruction = ("head_swap: Edit <image1>. Replace only the head with the person in <image2>. "
                       "Keep the pose, expression, framing, lighting, clothing and background of <image1>. "
                       "Use the face and hair identity of <image2>.")
    elif mode == "body":
        instruction = ("body_swap: Edit <image1>. Replace its person with the person in <image2>. "
                       "Keep the pose, framing, lighting and background of <image1>. "
                       "Use the face, hair, clothes and body proportions of <image2>.")
    else:
        raise ValueError("BFSの種類が不正です")
    return instruction + ("\n" + user_prompt.strip() if user_prompt.strip() else "")


def workflow(mode, files, image_names, prompt, negative, seed, steps):
    if len(image_names) != 2:
        raise ValueError("編集対象画像と参照画像の2枚が必要です")
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": files["unet"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": files["clip"], "type": "qwen_image", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": files["vae"]}},
        "4": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["1", 0], "lora_name": files["lora"], "strength_model": 1.0}},
        "5": {"class_type": "LoadImage", "inputs": {"image": image_names[0]}},
        "6": {"class_type": "LoadImage", "inputs": {"image": image_names[1]}},
        "7": {"class_type": "TextEncodeQwenImage21", "inputs": {
            "clip": ["2", 0], "vae": ["3", 0], "prompt": edit_prompt(mode, prompt),
            "negative_prompt": negative, "resolution": 0,
            "images.image_1": ["5", 0], "images.image_2": ["6", 0]}},
        "8": {"class_type": "KSampler", "inputs": {
            "model": ["4", 0], "seed": seed, "steps": steps, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "simple", "positive": ["7", 0],
            "negative": ["7", 1], "latent_image": ["7", 2], "denoise": 1.0}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {"images": ["9", 0], "filename_prefix": "krita_manga_bfs"}},
    }


def upload_png(server, data, label):
    if not data or not isinstance(data, bytes):
        raise ValueError("画像データが空です")
    boundary = "----KritaManga" + uuid.uuid4().hex
    filename = "krita_manga_%s_%s.png" % (label, uuid.uuid4().hex)
    body = ("--%s\r\nContent-Disposition: form-data; name=\"image\"; filename=\"%s\"\r\n"
            "Content-Type: image/png\r\n\r\n" % (boundary, filename)).encode("ascii") + data + ("\r\n--%s--\r\n" % boundary).encode("ascii")
    request = Request(server + "/upload/image", data=body,
                      headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
    with urlopen(request, timeout=60) as response:
        result = json.loads(response.read().decode("utf-8"))
    name = result.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("ComfyUIが画像アップロード名を返しませんでした")
    subfolder = result.get("subfolder") or ""
    return subfolder.replace("\\", "/").strip("/") + "/" + name if subfolder else name


def generate(mode, base_png, reference_png, prompt, negative, seed, steps,
             server=comfy_backend.SERVER, timeout=600, progress=None):
    if progress:
        progress("BFS用モデルを確認中…")
    files = components(server, mode)
    if progress:
        progress("コマ画像と参照画像をComfyUIへ送信中…")
    base_name = upload_png(server, base_png, "base")
    reference_name = upload_png(server, reference_png, "reference")
    graph = workflow(mode, files, (base_name, reference_name), prompt, negative, seed, steps)
    try:
        queued = comfy_backend._json(server + "/prompt", {"prompt": graph, "client_id": str(uuid.uuid4())}, timeout=30)
    except HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:1000]
        raise RuntimeError("ComfyUIがBFSワークフローを受け付けませんでした: " + detail) from error
    prompt_id = queued["prompt_id"]
    if progress:
        progress("BFS画像を生成中…")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = comfy_backend._json(server + "/history/" + prompt_id, timeout=15).get(prompt_id)
        if record:
            status = record.get("status", {})
            if status.get("status_str") == "error":
                raise RuntimeError("ComfyUI生成エラー: " + str(status.get("messages", [])[-1:]))
            for output in record.get("outputs", {}).values():
                images = output.get("images", [])
                if images:
                    image = images[0]
                    query = urlencode({"filename": image["filename"], "subfolder": image.get("subfolder", ""),
                                       "type": image.get("type", "output")})
                    with urlopen(server + "/view?" + query, timeout=30) as response:
                        return response.read(), {"prompt_id": prompt_id, "seed": seed, "mode": "bfs_" + mode,
                                                 "models": files, "image": image}
            if status.get("status_str") == "success":
                raise RuntimeError("ComfyUIは完了しましたが、BFS画像を返しませんでした")
        time.sleep(0.5)
    raise TimeoutError("BFS画像の生成が制限時間内に終わりませんでした")
