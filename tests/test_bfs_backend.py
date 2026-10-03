"""BFS graph and local ComfyUI transport checks without model downloads."""
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).parents[1] / "manga_workspace"
package = types.ModuleType("manga_workspace")
package.__path__ = [str(ROOT)]
sys.modules.setdefault("manga_workspace", package)
for name in ("comfy_backend", "bfs_backend"):
    spec = importlib.util.spec_from_file_location("manga_workspace." + name, ROOT / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

from manga_workspace import bfs_backend as bfs


class Response:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.data


class BfsBackendTests(unittest.TestCase):
    def test_two_images_have_fixed_base_then_reference_order(self):
        models = {"unet": "qwen_image_2.1_bf16.safetensors", "clip": "qwen3vl_8b_bf16.safetensors",
                  "vae": "qwen_image_2.1_vae_bf16.safetensors", "lora": bfs.HEAD_LORA}
        graph = bfs.workflow("head", models, ("panel.png", "character.png"), "漫画調", "", 123, 35)
        self.assertEqual(graph["5"]["inputs"]["image"], "panel.png")
        self.assertEqual(graph["6"]["inputs"]["image"], "character.png")
        self.assertEqual(graph["7"]["inputs"]["images.image_1"], ["5", 0])
        self.assertEqual(graph["7"]["inputs"]["images.image_2"], ["6", 0])
        self.assertEqual(graph["8"]["inputs"]["latent_image"], ["7", 2])
        self.assertEqual(graph["8"]["inputs"]["cfg"], 1.0)
        self.assertIn("head_swap", graph["7"]["inputs"]["prompt"])
        self.assertEqual(graph["4"]["inputs"]["lora_name"], bfs.HEAD_LORA)

    def test_choose_installed_qwen_family_and_matching_body_lora(self):
        names = {"UNETLoader": ("unet_name", ["other.safetensors", "qwen_image_2.1_int8_convrot.safetensors"]),
                 "CLIPLoader": ("clip_name", ["qwen3vl_8b_bf16.safetensors"]),
                 "VAELoader": ("vae_name", ["qwen_image_2.1_vae_bf16.safetensors"]),
                 "LoraLoaderModelOnly": ("lora_name", [bfs.HEAD_LORA, bfs.BODY_LORA])}

        def object_info(url, payload=None, timeout=8):
            node = url.rsplit("/", 1)[-1]
            if node == "system_stats":
                return {"system": {}}
            if node == "TextEncodeQwenImage21":
                return {node: {}}
            field, choices = names[node]
            return {node: {"input": {"required": {field: [choices]}}}}

        with patch.object(bfs.comfy_backend, "_json", side_effect=object_info):
            selected = bfs.components("http://127.0.0.1:8188", "body")
        self.assertEqual(selected["lora"], bfs.BODY_LORA)
        self.assertIn("qwen_image_2.1", selected["unet"])

    def test_upload_uses_multipart_png(self):
        requests = []

        def fake_urlopen(request, timeout=60):
            requests.append(request)
            return Response(json.dumps({"name": "stored.png", "subfolder": ""}).encode())

        with patch.object(bfs, "urlopen", side_effect=fake_urlopen):
            name = bfs.upload_png("http://127.0.0.1:8188", b"\x89PNGtest", "base")
        self.assertEqual(name, "stored.png")
        self.assertIn(b"name=\"image\"", requests[0].data)
        self.assertIn(b"\x89PNGtest", requests[0].data)

    def test_generate_submits_two_uploaded_images_and_reads_output(self):
        submitted = []
        models = {"unet": "qwen_image_2.1_bf16.safetensors", "clip": "qwen3vl_8b_bf16.safetensors",
                  "vae": "qwen_image_2.1_vae_bf16.safetensors", "lora": bfs.BODY_LORA}

        def api(url, payload=None, timeout=30):
            if url.endswith("/prompt"):
                submitted.append(payload["prompt"])
                return {"prompt_id": "job1"}
            return {"job1": {"status": {"status_str": "success"},
                             "outputs": {"10": {"images": [{"filename": "result.png"}]}}}}

        with patch.object(bfs, "components", return_value=models), \
             patch.object(bfs, "upload_png", side_effect=["base.png", "ref.png"]), \
             patch.object(bfs.comfy_backend, "_json", side_effect=api), \
             patch.object(bfs, "urlopen", return_value=Response(b"result bytes")):
            output, info = bfs.generate("body", b"base", b"ref", "漫画調", "", 9, 25)
        self.assertEqual(output, b"result bytes")
        self.assertEqual(info["mode"], "bfs_body")
        self.assertEqual(submitted[0]["5"]["inputs"]["image"], "base.png")
        self.assertEqual(submitted[0]["6"]["inputs"]["image"], "ref.png")


if __name__ == "__main__":
    unittest.main()
