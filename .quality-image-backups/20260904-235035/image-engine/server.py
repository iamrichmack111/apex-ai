from pathlib import Path
from io import BytesIO
import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

MODEL_DIR = Path(os.environ.get("TINY_SD_MODEL_DIR", Path(__file__).resolve().parent / "models" / "tiny-sd"))
app = FastAPI(title="Apex Tiny Image Engine")

pipe = None
device = None

class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=3000)
    negative_prompt: str = "blurry, low quality, distorted, malformed"
    width: int = Field(default=256, ge=256, le=512)
    height: int = Field(default=256, ge=256, le=512)
    steps: int = Field(default=4, ge=2, le=12)

def load_pipe():
    global pipe, device
    if pipe is not None:
        return pipe

    import torch
    from diffusers import DiffusionPipeline

    if not MODEL_DIR.exists():
        raise RuntimeError(f"Model is missing at {MODEL_DIR}")

    # Lite edition intentionally uses CPU PyTorch so the dependency download
    # stays much smaller and works on any Linux machine.
    device = "cpu"
    torch.set_num_threads(max(1, min(os.cpu_count() or 4, 8)))

    pipe = DiffusionPipeline.from_pretrained(
        str(MODEL_DIR),
        torch_dtype=torch.float32,
        local_files_only=True,
        safety_checker=None,
        requires_safety_checker=False,
    )
    pipe = pipe.to(device)

    try:
        pipe.set_progress_bar_config(disable=True)
    except Exception:
        pass

    try:
        pipe.enable_vae_slicing()
    except Exception:
        pass

    try:
        pipe.enable_attention_slicing()
    except Exception:
        pass

    return pipe

@app.get("/health")
def health():
    return {
        "status": "ok",
        "model_present": MODEL_DIR.exists(),
        "model": "segmind/tiny-sd",
        "loaded": pipe is not None,
        "device": device or "cpu",
    }

@app.post("/generate")
def generate(req: GenerateRequest):
    try:
        pipeline = load_pipe()
        import torch
        with torch.inference_mode():
            image = pipeline(
                prompt=req.prompt,
                negative_prompt=req.negative_prompt,
                width=req.width,
                height=req.height,
                num_inference_steps=req.steps,
                guidance_scale=1.0,
            ).images[0]

        # Upscale cheap 256x256 previews to 512x512 after inference.
        if req.width == 256 and req.height == 256:
            image = image.resize((512, 512))

        buf = BytesIO()
        image.save(buf, format="PNG", optimize=True)
        return Response(content=buf.getvalue(), media_type="image/png")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
