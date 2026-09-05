from pathlib import Path
import os
import random
import subprocess
import tempfile

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
SD_CLI = Path(os.environ.get("APEX_SD_CLI", ROOT / "stable-diffusion.cpp" / "build" / "bin" / "sd-cli"))
MODEL = Path(os.environ.get("APEX_IMAGE_MODEL", ROOT / "models" / "dreamshaper-7-lcm-q4_0.gguf"))

app = FastAPI(title="Apex DreamShaper Image Engine")

class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=3000)
    negative_prompt: str = "worst quality, low quality, lowres, blurry, deformed, malformed anatomy, extra limbs, extra fingers, fused fingers, bad hands, bad face, duplicate, text, watermark, logo"
    width: int = Field(default=512, ge=256, le=768)
    height: int = Field(default=512, ge=256, le=768)
    steps: int = Field(default=6, ge=4, le=12)
    style: str = "auto"

STYLE_PREFIXES = {
    "anime": "masterpiece, best quality, high quality, polished 2D anime illustration, clean crisp line art, cel shading, expressive eyes, coherent anatomy, detailed face, natural pose, attractive composition",
    "illustration": "masterpiece, high quality digital illustration, polished concept art, clean shapes, strong composition, detailed subject, coherent anatomy",
    "photo": "professional photography, realistic, natural proportions, detailed face, natural skin texture, sharp focus, balanced lighting, high detail",
    "cinematic": "cinematic composition, dramatic lighting, detailed environment, coherent anatomy, film still, high detail, atmospheric",
    "fantasy": "masterpiece fantasy illustration, detailed character design, coherent anatomy, dramatic lighting, rich environment, polished digital art",
    "comic": "high quality comic book illustration, clean ink lines, controlled shading, expressive character, coherent anatomy, professional panel art",
    "pixel": "high quality pixel art, clean sprite design, readable silhouette, intentional limited palette, detailed pixel work",
    "general": "masterpiece, best quality, coherent subject, clean composition, detailed, polished",
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
    if any(k in p for k in ("photo", "photograph", "photoreal", "realistic portrait", "camera")):
        return "photo"
    if any(k in p for k in ("cinematic", "movie still", "film still")):
        return "cinematic"
    if any(k in p for k in ("fantasy", "wizard", "dragon", "elf", "magic")):
        return "fantasy"
    if any(k in p for k in ("illustration", "digital art", "drawing", "painted")):
        return "illustration"
    return "general"

def enhanced_prompt(prompt: str, style: str) -> tuple[str, str]:
    chosen = choose_style(prompt, style)
    prefix = STYLE_PREFIXES[chosen]
    # Put the user's actual request first so the style booster doesn't overpower it.
    return f"{prompt}, {prefix}", chosen

@app.get("/health")
def health():
    binary_present = SD_CLI.is_file() and os.access(SD_CLI, os.X_OK)
    model_present = MODEL.is_file() and MODEL.stat().st_size > 100_000_000
    return {
        "status": "ok" if binary_present and model_present else "degraded",
        "model_present": model_present,
        "binary_present": binary_present,
        "model": "DreamShaper-7 LCM Q4",
        "model_path": str(MODEL),
        "binary_path": str(SD_CLI),
    }

@app.post("/generate")
def generate(req: GenerateRequest):
    if not SD_CLI.is_file():
        raise HTTPException(503, f"stable-diffusion.cpp binary missing at {SD_CLI}")
    if not MODEL.is_file():
        raise HTTPException(503, f"DreamShaper image model missing at {MODEL}")

    prompt, chosen_style = enhanced_prompt(req.prompt.strip(), req.style)
    negative = req.negative_prompt.strip()
    # Add anatomy failures that matter especially for character images.
    if chosen_style in {"anime", "illustration", "photo", "cinematic", "fantasy", "comic"}:
        negative = (
            negative
            + ", bad anatomy, malformed body, extra arms, extra legs, missing limbs, "
              "extra hands, malformed hands, extra fingers, fused fingers, distorted face, asymmetrical eyes"
        )

    with tempfile.TemporaryDirectory(prefix="apex-image-") as td:
        out = Path(td) / "output.png"
        seed = random.randint(1, 2_147_483_647)
        cmd = [
            str(SD_CLI),
            "-m", str(MODEL),
            "-p", prompt,
            "-n", negative,
            "--sampling-method", "lcm",
            "--steps", str(req.steps),
            "--cfg-scale", "1.0",
            "-W", str(req.width),
            "-H", str(req.height),
            "-s", str(seed),
            "-o", str(out),
        ]

        try:
            completed = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=1200,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise HTTPException(504, "Image generation timed out")

        if completed.returncode != 0 or not out.is_file():
            tail = (completed.stdout or "")[-3000:]
            raise HTTPException(500, f"DreamShaper generation failed: {tail}")

        data = out.read_bytes()
        return Response(
            content=data,
            media_type="image/png",
            headers={"X-Apex-Image-Style": chosen_style},
        )
