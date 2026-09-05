from __future__ import annotations

import gc
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

app = FastAPI(title="Apex DreamShaper Low Resource Engine")
_generation_lock = threading.Lock()
_last_device = "not loaded"

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
    if any(k in p for k in ("2d", "anime", "manga", "waifu", "cel shaded", "anime girl")):
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

def build_pipe():
    global _last_device

    if not MODEL.is_file():
        raise RuntimeError(f"DreamShaper checkpoint missing: {MODEL}")
    if not LCM_LORA.is_file():
        raise RuntimeError(f"LCM adapter missing: {LCM_LORA}")

    import torch
    from diffusers import StableDiffusionPipeline, LCMScheduler

    # Keep CPU image work from monopolizing the machine.
    cpu_threads = int(os.environ.get("APEX_IMAGE_CPU_THREADS", "3"))
    cpu_threads = max(1, min(cpu_threads, os.cpu_count() or 4))
    try:
        torch.set_num_threads(cpu_threads)
    except Exception:
        pass
    try:
        torch.set_num_interop_threads(1)
    except Exception:
        pass

    cuda = bool(torch.cuda.is_available())
    device = "cuda" if cuda else "cpu"
    _last_device = device
    dtype = torch.float16 if cuda else torch.float32

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
        pipe.enable_attention_slicing("max")
    except Exception:
        pass
    try:
        pipe.enable_vae_slicing()
    except Exception:
        pass

    # Do not keep the full model permanently resident in GPU memory.
    if cuda:
        try:
            pipe.enable_model_cpu_offload()
        except Exception:
            pipe = pipe.to("cuda")
    else:
        pipe = pipe.to("cpu")

    return pipe, torch, device

def release_pipe(pipe, torch, device):
    try:
        if hasattr(pipe, "maybe_free_model_hooks"):
            pipe.maybe_free_model_hooks()
    except Exception:
        pass
    try:
        if device == "cuda":
            pipe.to("cpu")
    except Exception:
        pass

    try:
        del pipe
    except Exception:
        pass

    gc.collect()

    try:
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    except Exception:
        pass

def enhanced_prompt(prompt: str, style: str) -> tuple[str, str]:
    chosen = choose_style(prompt, style)
    return f"{prompt}, {STYLE_PREFIXES[chosen]}", chosen

@app.get("/health")
def health():
    model_ok = MODEL.is_file() and MODEL.stat().st_size > 1_800_000_000
    lora_ok = LCM_LORA.is_file() and LCM_LORA.stat().st_size > 100_000_000

    try:
        import peft
        peft_ok = True
        peft_version = getattr(peft, "__version__", "installed")
    except Exception:
        peft_ok = False
        peft_version = None

    return {
        "status": "ok" if model_ok and lora_ok and peft_ok else "degraded",
        "engine": "dreamshaper7-lcm-low-resource",
        "model_present": model_ok,
        "lcm_present": lora_ok,
        "peft_present": peft_ok,
        "peft_version": peft_version,
        "model": "DreamShaper 7 + LCM",
        "device": _last_device,
        "persistent_model_loaded": False,
        "low_resource_mode": True,
    }

@app.post("/generate")
def generate(req: GenerateRequest):
    with _generation_lock:
        pipe = None
        torch = None
        device = "cpu"

        try:
            pipe, torch, device = build_pipe()

            prompt, chosen_style = enhanced_prompt(req.prompt.strip(), req.style)
            negative = req.negative_prompt.strip()

            if chosen_style in {"anime", "illustration", "photo", "cinematic", "fantasy", "comic"}:
                negative += (
                    ", bad anatomy, malformed body, extra arms, extra legs, missing limbs, "
                    "extra hands, malformed hands, extra fingers, fused fingers, distorted face, "
                    "asymmetrical eyes"
                )

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

            buf = io.BytesIO()
            image.save(buf, format="PNG")
            payload = buf.getvalue()

            return Response(
                content=payload,
                media_type="image/png",
                headers={
                    "X-Apex-Image-Engine": "DreamShaper-7-LCM-Low-Resource",
                    "X-Apex-Image-Style": chosen_style,
                },
            )

        except Exception as exc:
            raise HTTPException(500, f"DreamShaper generation failed: {exc}")

        finally:
            if pipe is not None and torch is not None:
                release_pipe(pipe, torch, device)
