"""Embedded prompts must be extracted without treating arbitrary workflows as text."""
import json
import importlib.util
from pathlib import Path
import struct
import unittest
import zlib


source = Path(__file__).parents[1] / "manga_workspace" / "reference_prompt.py"
spec = importlib.util.spec_from_file_location("reference_prompt", source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
png_metadata = module.png_metadata
prompt_from_metadata = module.prompt_from_metadata


def chunk(kind, value):
    return struct.pack(">I", len(value)) + kind + value + b"\0\0\0\0"


class ReferencePromptTests(unittest.TestCase):
    def test_a1111_parameters_keep_only_positive(self):
        data = b"\x89PNG\r\n\x1a\n" + chunk(
            b"tEXt", b"parameters\0black hair, red coat\nNegative prompt: blurry\nSteps: 20")
        metadata = png_metadata(data)
        self.assertEqual(prompt_from_metadata(metadata), "black hair, red coat")

    def test_novelai_json_comment(self):
        comment = json.dumps({"prompt": "1girl, short hair", "steps": 28})
        self.assertEqual(prompt_from_metadata({"Comment": comment}), "1girl, short hair")

    def test_comfy_workflow_is_not_mistaken_for_prompt(self):
        workflow = json.dumps({"1": {"class_type": "CLIPTextEncode"}})
        self.assertEqual(prompt_from_metadata({"prompt": workflow}), "")

    def test_compressed_png_text(self):
        data = b"\x89PNG\r\n\x1a\n" + chunk(
            b"zTXt", b"parameters\0\0" + zlib.compress(b"blue eyes"))
        self.assertEqual(prompt_from_metadata(png_metadata(data)), "blue eyes")


if __name__ == "__main__":
    unittest.main()
