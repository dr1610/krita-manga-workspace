# Third-party notices

## Tag completion data

`manga_workspace/tags/Danbooru.csv` and `Danbooru NSFW.csv` were obtained from the tag autocomplete data distributed with Krita AI Diffusion:

- Project: https://github.com/Acly/krita-ai-diffusion
- License: GNU General Public License v3.0
- Upstream description: the files were generated from the Danbooru public tag dataset in Google BigQuery.

The files contain tag names, categories, usage counts and aliases. They do not contain manga or illustration images.

## Optional manga detector

The detector model is not bundled in the plugin ZIP. If the user explicitly chooses installation, the setup downloads:

- RT-DETRv4-X Manga109-s: https://huggingface.co/tori29umai/rtdetrv4-x-manga109s
- Model license: Apache License 2.0
- Fixed revision and SHA256 are recorded in `manga_workspace/DETECTOR-NOTICES.md` and `Setup-Detector.ps1`.

The Manga109-s dataset and its comic images are not bundled. See `manga_workspace/DETECTOR-NOTICES.md` for the model publisher's attribution and citation requirements.

The optional isolated runtime also downloads Python, ONNX Runtime, NumPy and Pillow. Their licenses are included in their respective distributions or installed package metadata. They are installed outside Krita in a dedicated user-selected runtime.

## Optional AI generation

ComfyUI, image-generation checkpoints, VAE, text encoders, LoRA and Custom Nodes are not bundled. Users must obtain them separately under their respective licenses.

## Fonts

The optional font collection under the development repository's `resources/fonts` is not included in the core prototype ZIP. If distributed separately, every font must retain its SIL Open Font License text.
## Linked external material sites

The plugin can open DDD FONT, Manga Parts STOCK and Fukidashi Design websites and import image files explicitly selected by the user. Assets from those sites are not bundled, mirrored, scraped, or downloaded by this plugin. Users are responsible for reviewing and following each material provider's terms before importing or distributing a work that uses those assets.
