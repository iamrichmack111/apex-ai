from __future__ import annotations

import io
import os
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
MODEL = Path(os.environ.get(
    "APEX_DREAMSHAPER_MODEL",
    ROOT / "models" / "dreamshaper7" / "DreamShaper_7_pruned.safetensors",
))
LCM_LORA = Path(os.environ.get(
    "APEX_LCM_LORA",
    ROOT / "models" / "dreamshaper7" / "pytorch_lora_weights.safetensors",
))

app = FastAPI(title="Apex DreamShaper Quality Image Engine")

_pipe = None
_pipe_lock = threading.Lock()
_device = "cpu"

class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=3000)
    negative_prompt: str = (
        "worst quality, low quality, lowres, blurry, deformed, malformed anatomy, "
        "extra limbs, extra fingers, fused fingers, bad hands, bad face, duplicate, "
        "text, watermark, logo"
    )
    width: int = Field(default=512, ge=256, le=768)
    height: int = Field(default=512, ge=256, le=768)
    steps: int = Field(default=6, ge=4, le=10)
    style: str = "auto"

STYLE_PREFIXES = {
    "anime": (
        "masterpiece, best quality, polished 2D anime illustration, clean crisp line art, "
        "cel shading, expressive detailed eyes, coherent anatomy, detailed face, natural pose"
    ),
    "illustration": (
        "masterpiece, professional digital illustration, polished concept art, coherent anatomy, "
        "clean shapes, detailed subject, strong composition"
    ),
    "photo": (
        "professional photography, photorealistic, realistic proportions, detailed face, "
        "natural skin texture, sharp focus, cinematic lighting"
    ),
    "cinematic": (
        "cinematic film still, dramatic lighting, detailed environment, coherent anatomy, "
        "atmospheric, high detail, professional composition"
    ),
    "fantasy": (
        "masterpiece fantasy art, polished character design, coherent anatomy, rich detail, "
        "dramatic lighting, professional digital painting"
    ),
    "comic": (
        "professional comic illustration, clean ink lines, controlled shading, expressive face, "
        "coherent anatomy, polished graphic novel art"
    ),
    "pixel": (
        "high quality pixel art, clean readable silhouette, intentional pixel clusters, "
        "detailed sprite art, crisp edges"
    ),
    "general": "masterpiece, best quality, detailed, coherent subject, polished composition",
}

def choose_style(prompt: str, requested: str) -> str:
    requested = (requested or "auto").lower().strip()
    if requested in STYLE_PREFIXES:
        return requested
    p = prompt.lower()
    if any(k in p for k in ("2d", "anime", "manga", "waifu", "cel shaded", "cartoon girl", "anime girl")):
        return "anime"
    if any(k in p for k in ("pixel art", "8-bit", "16-bit", "sprite")):
        return "pixel"
    if any(k in p for k in ("comic", "graphic novel", "inked")):
        return "comic"
    if any(k in p for k in ("photo", "photograph", "photoreal", "realistic photography", "camera")):
        return "photo"
    if any(k in p for k in ("cinematic", "film still", "movie still")):
        return "cinematic"
    if any(k in p for k in ("fantasy", "wizard", "dragon", "elf", "magic")):
        return "fantasy"
    if any(k in p for k in ("illustration", "drawing", "digital art", "painting")):
        return "illustration"
    return "general"

def enhanced_prompt(prompt: str, style: str) -> tuple[str, str]:
    chosen = choose_style(prompt, style)
    return f"{prompt}, {STYLE_PREFIXES[chosen]}", chosen

def load_pipe():
    global _pipe, _device
    if _pipe is not None:
        return _pipe

    with _pipe_lock:
        if _pipe is not None:
            return _pipe

        if not MODEL.is_file():
            raise RuntimeError(f"DreamShaper checkpoint missing: {MODEL}")
        if not LCM_LORA.is_file():
            raise RuntimeError(f"LCM adapter missing: {LCM_LORA}")

        import torch
        from diffusers import StableDiffusionPipeline, LCMScheduler

        cuda = bool(torch.cuda.is_available())
        _device = "cuda" if cuda else "cpu"
        dtype = torch.float16 if cuda else torch.float32

        # The checkpoint is local; only small SD1.5 config/tokenizer metadata may be
        # resolved through the normal diffusers cache on first load.
        pipe = StableDiffusionPipeline.from_single_file(
            str(MODEL),
            torch_dtype=dtype,
            safety_checker=None,
            requires_safety_checker=False,
        )

        pipe.load_lora_weights(
            str(LCM_LORA.parent),
            weight_name=LCM_LORA.name,
            adapter_name="apex_lcm",
        )
        pipe.fuse_lora(adapter_names=["apex_lcm"], lora_scale=1.0)
        pipe.scheduler = LCMScheduler.from_config(pipe.scheduler.config)
        pipe.set_progress_bar_config(disable=True)

        try:
            pipe.enable_attention_slicing()
        except Exception:
            pass
        try:
            pipe.enable_vae_slicing()
        except Exception:
            pass

        pipe = pipe.to(_device)
        _pipe = pipe
        return _pipe

@app.get("/health")
def health():
    model_ok = MODEL.is_file() and MODEL.stat().st_size > 1_800_000_000
    lora_ok = LCM_LORA.is_file() and LCM_LORA.stat().st_size > 100_000_000
    return {
        "status": "ok" if model_ok and lora_ok else "degraded",
        "engine": "dreamshaper7-lcm-diffusers",
        "model_present": model_ok,
        "lcm_present": lora_ok,
        "model": "DreamShaper 7 + LCM",
        "device": _device,
        "loaded": _pipe is not None,
        "model_path": str(MODEL),
    }

@app.post("/generate")
def generate(req: GenerateRequest):
    try:
        pipe = load_pipe()
    except Exception as exc:
        raise HTTPException(503, f"Could not load DreamShaper: {exc}")

    prompt, chosen_style = enhanced_prompt(req.prompt.strip(), req.style)

    negative = req.negative_prompt.strip()
    if chosen_style in {"anime", "illustration", "photo", "cinematic", "fantasy", "comic"}:
        negative += (
            ", bad anatomy, malformed body, extra arms, extra legs, missing limbs, "
            "extra hands, malformed hands, extra fingers, fused fingers, distorted face, "
            "asymmetrical eyes"
        )

    try:
        import torch
        with torch.inference_mode():
            result = pipe(
                prompt=prompt,
                negative_prompt=negative,
                width=req.width,
                height=req.height,
                num_inference_steps=req.steps,
                guidance_scale=1.0,
            )
        image = result.images[0]
    except Exception as exc:
        raise HTTPException(500, f"DreamShaper generation failed: {exc}")

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return Response(
        content=buf.getvalue(),
        media_type="image/png",
        headers={
            "X-Apex-Image-Engine": "DreamShaper-7-LCM",
            "X-Apex-Image-Style": chosen_style,
        },
    )
