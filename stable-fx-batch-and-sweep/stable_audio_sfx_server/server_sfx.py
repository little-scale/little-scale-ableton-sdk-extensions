import os
import time
import json
import inspect
import random
from datetime import datetime
from typing import Optional, List

import numpy as np
import soundfile as sf
import torch
import torchaudio
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from stable_audio_3 import StableAudioModel


# -------------------------
# Config
# -------------------------

OUTPUT_DIR = "outputs"
INPUT_DIR = "inputs"
HISTORY_PATH = "history.jsonl"
MODEL_NAME = os.environ.get("SA3_MODEL", "small-sfx")

# Native model sample rate is discovered after load.
# Output sample rate can be overridden at launch:
# OUTPUT_SAMPLE_RATE=48000 uv run uvicorn server_sfx:app --host 127.0.0.1 --port 8000
OUTPUT_SAMPLE_RATE_ENV = os.environ.get("OUTPUT_SAMPLE_RATE", None)

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(INPUT_DIR, exist_ok=True)

app = FastAPI(title="Stable Audio 3 Small SFX Server")


# -------------------------
# Load model
# -------------------------

print(f"Loading model: {MODEL_NAME}")
model = StableAudioModel.from_pretrained(MODEL_NAME)
print("Model loaded.")

MODEL_SAMPLE_RATE = (
    getattr(model, "sample_rate", None)
    or getattr(model, "sampling_rate", None)
    or 44100
)

if OUTPUT_SAMPLE_RATE_ENV is not None:
    OUTPUT_SAMPLE_RATE = int(OUTPUT_SAMPLE_RATE_ENV)
else:
    OUTPUT_SAMPLE_RATE = MODEL_SAMPLE_RATE

print(f"Model sample rate: {MODEL_SAMPLE_RATE}")
print(f"Output sample rate: {OUTPUT_SAMPLE_RATE}")


# -------------------------
# Request models
# -------------------------

class GenerateRequest(BaseModel):
    prompt: str
    negative_prompt: Optional[str] = None

    duration: float = 3.0
    seed: Optional[int] = None
    output_name: Optional[str] = None

    steps: Optional[int] = None
    cfg_scale: Optional[float] = None
    sampler_type: Optional[str] = None
    apg_scale: Optional[float] = None
    duration_padding_sec: Optional[float] = None
    chunked_decode: Optional[bool] = None


class BatchRequest(BaseModel):
    prompt: str
    negative_prompt: Optional[str] = None

    duration: float = 3.0
    count: int = 8
    seed_start: Optional[int] = None
    prefix: Optional[str] = None

    steps: Optional[int] = None
    cfg_scale: Optional[float] = None
    sampler_type: Optional[str] = None
    apg_scale: Optional[float] = None
    duration_padding_sec: Optional[float] = None
    chunked_decode: Optional[bool] = None


class PromptBatchRequest(BaseModel):
    prompts: List[str]
    negative_prompt: Optional[str] = None

    duration: float = 3.0
    seed: Optional[int] = None
    prefix: str = "prompt_batch"

    steps: Optional[int] = None
    cfg_scale: Optional[float] = None
    sampler_type: Optional[str] = None
    apg_scale: Optional[float] = None
    duration_padding_sec: Optional[float] = None
    chunked_decode: Optional[bool] = None


class SweepRequest(BaseModel):
    prompt: str
    negative_prompt: Optional[str] = None

    duration: float = 3.0
    seeds: List[int] = [1000, 1001, 1002, 1003]
    cfg_scales: List[float] = [1.0]
    steps_values: List[int] = [8]
    sampler_types: List[str] = ["pingpong"]
    apg_scales: List[float] = [1.0]

    prefix: Optional[str] = None
    duration_padding_sec: Optional[float] = None
    chunked_decode: Optional[bool] = None


class MutateRequest(BaseModel):
    input_path: str

    prompt: str
    negative_prompt: Optional[str] = None

    duration: Optional[float] = None
    init_noise_level: Optional[float] = 0.35
    seed: Optional[int] = None
    output_name: Optional[str] = None

    steps: Optional[int] = None
    cfg_scale: Optional[float] = None
    sampler_type: Optional[str] = None
    apg_scale: Optional[float] = None
    duration_padding_sec: Optional[float] = None
    chunked_decode: Optional[bool] = None


class InpaintRequest(BaseModel):
    input_path: str

    prompt: str
    negative_prompt: Optional[str] = None

    mask_start: float
    mask_end: float
    duration: Optional[float] = None

    seed: Optional[int] = None
    output_name: Optional[str] = None

    steps: Optional[int] = None
    cfg_scale: Optional[float] = None
    sampler_type: Optional[str] = None
    apg_scale: Optional[float] = None
    duration_padding_sec: Optional[float] = None
    chunked_decode: Optional[bool] = None


# -------------------------
# Helpers
# -------------------------

def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def make_safe_filename(text: str):
    safe = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in text)
    safe = safe.strip("_")
    return safe[:80] or "sfx"


def get_generate_signature():
    sig = inspect.signature(model.generate)
    return list(sig.parameters.keys())


def model_accepts_var_kwargs():
    sig = inspect.signature(model.generate)
    return any(
        p.kind == inspect.Parameter.VAR_KEYWORD
        for p in sig.parameters.values()
    )


def seed_everything(seed: int):
    torch.manual_seed(seed)
    np.random.seed(seed % (2**32 - 1))
    random.seed(seed)


def audio_to_tensor_channels_first(audio):
    """
    Converts model output into torch tensor shape:
    [channels, samples]
    """
    if isinstance(audio, torch.Tensor):
        audio = audio.detach().cpu().float()
    else:
        audio = torch.from_numpy(np.asarray(audio)).float()

    # Remove batch dimension if present: [batch, channels, samples]
    if audio.ndim == 3:
        audio = audio[0]

    # Mono [samples] -> [1, samples]
    if audio.ndim == 1:
        audio = audio.unsqueeze(0)

    # If shape looks like [samples, channels], transpose to [channels, samples]
    if audio.ndim == 2:
        if audio.shape[1] <= 8 and audio.shape[0] > audio.shape[1]:
            audio = audio.T
        return audio

    raise ValueError(f"Unexpected audio shape: {tuple(audio.shape)}")


def resample_if_needed(audio_ch_first: torch.Tensor, source_sr: int, target_sr: int):
    """
    audio_ch_first shape: [channels, samples]
    """
    if source_sr == target_sr:
        return audio_ch_first

    return torchaudio.functional.resample(
        audio_ch_first,
        orig_freq=source_sr,
        new_freq=target_sr,
    )


def tensor_to_soundfile_shape(audio_ch_first: torch.Tensor):
    """
    Converts [channels, samples] to soundfile shape [samples, channels].
    Clips to normal audio range.
    """
    audio_ch_first = torch.clamp(audio_ch_first, -1.0, 1.0)

    if audio_ch_first.shape[0] == 1:
        return audio_ch_first[0].numpy()

    return audio_ch_first.T.numpy()


def load_audio_for_model(path):
    """
    Loads WAV/AIFF/etc and returns:
    sample_rate, tensor [channels, samples]
    """
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"Input file not found: {path}")

    audio, sr = sf.read(path, always_2d=True)

    # soundfile gives [samples, channels]
    # model wants [channels, samples]
    audio = torch.from_numpy(audio.T).float()

    return sr, audio


def build_generate_kwargs(
    prompt,
    duration,
    seed=None,
    steps=None,
    cfg_scale=None,
    sampler_type=None,
    negative_prompt=None,
    apg_scale=None,
    duration_padding_sec=None,
    chunked_decode=None,
    extra=None,
):
    sig_params = get_generate_signature()
    accepts_extra_kwargs = model_accepts_var_kwargs()

    kwargs = {
        "prompt": prompt,
        "duration": duration,
    }

    possible = {
        "negative_prompt": negative_prompt,
        "seed": seed,
        "steps": steps,
        "cfg_scale": cfg_scale,
        "apg_scale": apg_scale,
        "duration_padding_sec": duration_padding_sec,
        "chunked_decode": chunked_decode,
    }

    # model.generate has **sampler_kwargs, so sampler_type can be passed
    # even though it is not listed as an explicit argument.
    sampler_possible = {
        "sampler_type": sampler_type,
    }

    if extra:
        possible.update(extra)

    for key, value in possible.items():
        if value is not None and (key in sig_params or accepts_extra_kwargs):
            kwargs[key] = value

    for key, value in sampler_possible.items():
        if value is not None and accepts_extra_kwargs:
            kwargs[key] = value

    return kwargs


def save_audio(audio, filename):
    if not filename.lower().endswith(".wav"):
        filename += ".wav"

    path = os.path.join(OUTPUT_DIR, filename)

    audio_ch_first = audio_to_tensor_channels_first(audio)
    audio_ch_first = resample_if_needed(
        audio_ch_first,
        source_sr=MODEL_SAMPLE_RATE,
        target_sr=OUTPUT_SAMPLE_RATE,
    )

    audio_out = tensor_to_soundfile_shape(audio_ch_first)
    sf.write(path, audio_out, OUTPUT_SAMPLE_RATE)

    return path


def log_history(record):
    record["created"] = now_iso()

    with open(HISTORY_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_history():
    if not os.path.exists(HISTORY_PATH):
        return []

    rows = []

    with open(HISTORY_PATH, "r", encoding="utf-8") as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except Exception:
                pass

    return rows


def generate_one(req: GenerateRequest):
    seed = req.seed if req.seed is not None else random.randint(0, 2**31 - 1)
    seed_everything(seed)

    kwargs = build_generate_kwargs(
        prompt=req.prompt,
        duration=req.duration,
        seed=seed,
        steps=req.steps,
        cfg_scale=req.cfg_scale,
        sampler_type=req.sampler_type,
        negative_prompt=req.negative_prompt,
        apg_scale=req.apg_scale,
        duration_padding_sec=req.duration_padding_sec,
        chunked_decode=req.chunked_decode,
    )

    print("Generating:")
    print(kwargs)

    audio = model.generate(**kwargs)

    if req.output_name:
        filename = req.output_name
    else:
        stem = make_safe_filename(req.prompt)
        filename = f"{int(time.time())}_{stem}_seed{seed}.wav"

    path = save_audio(audio, filename)

    record = {
        "type": "generate",
        "path": path,
        "prompt": req.prompt,
        "negative_prompt": req.negative_prompt,
        "duration": req.duration,
        "seed": seed,
        "steps": req.steps,
        "cfg_scale": req.cfg_scale,
        "sampler_type": req.sampler_type,
        "apg_scale": req.apg_scale,
        "duration_padding_sec": req.duration_padding_sec,
        "chunked_decode": req.chunked_decode,
        "model_sample_rate": MODEL_SAMPLE_RATE,
        "output_sample_rate": OUTPUT_SAMPLE_RATE,
    }

    log_history(record)
    return record


# -------------------------
# Basic endpoints
# -------------------------

@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": MODEL_NAME,
        "model_sample_rate": MODEL_SAMPLE_RATE,
        "output_sample_rate": OUTPUT_SAMPLE_RATE,
    }


@app.get("/params")
def params():
    return {
        "model": MODEL_NAME,
        "model_sample_rate": MODEL_SAMPLE_RATE,
        "output_sample_rate": OUTPUT_SAMPLE_RATE,
        "output_dir": OUTPUT_DIR,
        "input_dir": INPUT_DIR,
        "history_path": HISTORY_PATH,
        "endpoints": [
            "GET /health",
            "GET /params",
            "GET /params/generate",
            "POST /generate",
            "POST /batch",
            "POST /prompt_batch",
            "POST /sweep",
            "GET /outputs",
            "GET /outputs/{filename}",
            "DELETE /outputs/{filename}",
            "GET /history",
            "POST /mutate",
            "POST /inpaint",
        ],
    }


@app.get("/params/generate")
def params_generate():
    sig = inspect.signature(model.generate)
    return {
        "generate_signature": str(sig),
        "generate_args_supported": list(sig.parameters.keys()),
        "accepts_sampler_kwargs": model_accepts_var_kwargs(),
        "note": "The server passes optional parameters if this installed model.generate() supports them.",
    }


# -------------------------
# Generation endpoints
# -------------------------

@app.post("/generate")
def generate(req: GenerateRequest):
    return generate_one(req)


@app.post("/batch")
def batch(req: BatchRequest):
    if req.count < 1:
        raise HTTPException(status_code=400, detail="count must be at least 1")

    if req.count > 128:
        raise HTTPException(status_code=400, detail="count too high; max is 128")

    seed_start = (
        req.seed_start
        if req.seed_start is not None
        else random.randint(0, 2**31 - 1000)
    )

    prefix = req.prefix or make_safe_filename(req.prompt)

    files = []

    for i in range(req.count):
        seed = seed_start + i
        output_name = f"{prefix}_seed{seed}.wav"

        result = generate_one(
            GenerateRequest(
                prompt=req.prompt,
                negative_prompt=req.negative_prompt,
                duration=req.duration,
                seed=seed,
                output_name=output_name,
                steps=req.steps,
                cfg_scale=req.cfg_scale,
                sampler_type=req.sampler_type,
                apg_scale=req.apg_scale,
                duration_padding_sec=req.duration_padding_sec,
                chunked_decode=req.chunked_decode,
            )
        )

        result["type"] = "batch"
        files.append(result)

    return {
        "status": "saved",
        "count": len(files),
        "files": files,
    }


@app.post("/prompt_batch")
def prompt_batch(req: PromptBatchRequest):
    if len(req.prompts) < 1:
        raise HTTPException(status_code=400, detail="prompts must not be empty")

    if len(req.prompts) > 128:
        raise HTTPException(status_code=400, detail="too many prompts; max is 128")

    base_seed = (
        req.seed
        if req.seed is not None
        else random.randint(0, 2**31 - 1000)
    )

    files = []

    for i, prompt in enumerate(req.prompts):
        seed = base_seed + i
        stem = make_safe_filename(prompt)
        output_name = f"{req.prefix}_{i:03d}_{stem}_seed{seed}.wav"

        result = generate_one(
            GenerateRequest(
                prompt=prompt,
                negative_prompt=req.negative_prompt,
                duration=req.duration,
                seed=seed,
                output_name=output_name,
                steps=req.steps,
                cfg_scale=req.cfg_scale,
                sampler_type=req.sampler_type,
                apg_scale=req.apg_scale,
                duration_padding_sec=req.duration_padding_sec,
                chunked_decode=req.chunked_decode,
            )
        )

        result["type"] = "prompt_batch"
        files.append(result)

    return {
        "status": "saved",
        "count": len(files),
        "files": files,
    }


@app.post("/sweep")
def sweep(req: SweepRequest):
    total = (
        len(req.seeds)
        * len(req.cfg_scales)
        * len(req.steps_values)
        * len(req.sampler_types)
        * len(req.apg_scales)
    )

    if total < 1:
        raise HTTPException(status_code=400, detail="sweep has no combinations")

    if total > 256:
        raise HTTPException(
            status_code=400,
            detail=f"sweep too large: {total}; max is 256",
        )

    prefix = req.prefix or make_safe_filename(req.prompt)
    files = []

    for seed in req.seeds:
        for cfg in req.cfg_scales:
            for steps in req.steps_values:
                for sampler in req.sampler_types:
                    for apg in req.apg_scales:
                        output_name = (
                            f"{prefix}"
                            f"_seed{seed}"
                            f"_cfg{cfg}"
                            f"_steps{steps}"
                            f"_apg{apg}"
                            f"_sampler{sampler}.wav"
                        )

                        result = generate_one(
                            GenerateRequest(
                                prompt=req.prompt,
                                negative_prompt=req.negative_prompt,
                                duration=req.duration,
                                seed=seed,
                                output_name=output_name,
                                steps=steps,
                                cfg_scale=cfg,
                                sampler_type=sampler,
                                apg_scale=apg,
                                duration_padding_sec=req.duration_padding_sec,
                                chunked_decode=req.chunked_decode,
                            )
                        )

                        result["type"] = "sweep"
                        files.append(result)

    return {
        "status": "saved",
        "count": len(files),
        "files": files,
    }


# -------------------------
# File endpoints
# -------------------------

@app.get("/outputs")
def outputs():
    files = []

    for filename in sorted(os.listdir(OUTPUT_DIR)):
        if not filename.lower().endswith(".wav"):
            continue

        path = os.path.join(OUTPUT_DIR, filename)

        try:
            info = sf.info(path)
            duration = info.frames / info.samplerate
            samplerate = info.samplerate
            channels = info.channels
        except Exception:
            duration = None
            samplerate = None
            channels = None

        files.append(
            {
                "filename": filename,
                "path": path,
                "size_bytes": os.path.getsize(path),
                "duration": duration,
                "sample_rate": samplerate,
                "channels": channels,
                "modified": datetime.fromtimestamp(
                    os.path.getmtime(path)
                ).isoformat(timespec="seconds"),
            }
        )

    return {
        "count": len(files),
        "files": files,
    }


@app.get("/outputs/{filename}")
def get_output(filename: str):
    path = os.path.join(OUTPUT_DIR, filename)

    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="file not found")

    return FileResponse(path, media_type="audio/wav", filename=filename)


@app.delete("/outputs/{filename}")
def delete_output(filename: str):
    path = os.path.join(OUTPUT_DIR, filename)

    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="file not found")

    os.remove(path)

    return {
        "status": "deleted",
        "filename": filename,
    }


@app.get("/history")
def history(limit: int = 100):
    rows = read_history()

    return {
        "count": min(limit, len(rows)),
        "history": rows[-limit:],
    }


# -------------------------
# Audio editing endpoints
# -------------------------

@app.post("/mutate")
def mutate(req: MutateRequest):
    input_sr, audio = load_audio_for_model(req.input_path)

    seed = req.seed if req.seed is not None else random.randint(0, 2**31 - 1)
    seed_everything(seed)

    duration = req.duration
    if duration is None:
        duration = audio.shape[-1] / input_sr

    kwargs = build_generate_kwargs(
        prompt=req.prompt,
        duration=duration,
        seed=seed,
        steps=req.steps,
        cfg_scale=req.cfg_scale,
        sampler_type=req.sampler_type,
        negative_prompt=req.negative_prompt,
        apg_scale=req.apg_scale,
        duration_padding_sec=req.duration_padding_sec,
        chunked_decode=req.chunked_decode,
        extra={
            "init_audio": (input_sr, audio),
            "init_noise_level": req.init_noise_level,
        },
    )

    print("Mutating:")
    print(kwargs.keys())

    generated = model.generate(**kwargs)

    filename = req.output_name or f"mutate_{int(time.time())}_seed{seed}.wav"
    path = save_audio(generated, filename)

    record = {
        "type": "mutate",
        "path": path,
        "input_path": req.input_path,
        "input_sample_rate": input_sr,
        "prompt": req.prompt,
        "negative_prompt": req.negative_prompt,
        "duration": duration,
        "seed": seed,
        "init_noise_level": req.init_noise_level,
        "steps": req.steps,
        "cfg_scale": req.cfg_scale,
        "sampler_type": req.sampler_type,
        "apg_scale": req.apg_scale,
        "duration_padding_sec": req.duration_padding_sec,
        "chunked_decode": req.chunked_decode,
        "model_sample_rate": MODEL_SAMPLE_RATE,
        "output_sample_rate": OUTPUT_SAMPLE_RATE,
    }

    log_history(record)
    return record


@app.post("/inpaint")
def inpaint(req: InpaintRequest):
    input_sr, audio = load_audio_for_model(req.input_path)

    seed = req.seed if req.seed is not None else random.randint(0, 2**31 - 1)
    seed_everything(seed)

    duration = req.duration
    if duration is None:
        duration = audio.shape[-1] / input_sr

    if req.mask_start < 0:
        raise HTTPException(status_code=400, detail="mask_start must be >= 0")

    if req.mask_end <= req.mask_start:
        raise HTTPException(
            status_code=400,
            detail="mask_end must be greater than mask_start",
        )

    if req.mask_end > duration:
        raise HTTPException(
            status_code=400,
            detail=f"mask_end exceeds duration. mask_end={req.mask_end}, duration={duration}",
        )

    kwargs = build_generate_kwargs(
        prompt=req.prompt,
        duration=duration,
        seed=seed,
        steps=req.steps,
        cfg_scale=req.cfg_scale,
        sampler_type=req.sampler_type,
        negative_prompt=req.negative_prompt,
        apg_scale=req.apg_scale,
        duration_padding_sec=req.duration_padding_sec,
        chunked_decode=req.chunked_decode,
        extra={
            "inpaint_audio": (input_sr, audio),
            "inpaint_mask_start_seconds": req.mask_start,
            "inpaint_mask_end_seconds": req.mask_end,
        },
    )

    print("Inpainting:")
    print(kwargs.keys())

    generated = model.generate(**kwargs)

    filename = req.output_name or f"inpaint_{int(time.time())}_seed{seed}.wav"
    path = save_audio(generated, filename)

    record = {
        "type": "inpaint",
        "path": path,
        "input_path": req.input_path,
        "input_sample_rate": input_sr,
        "prompt": req.prompt,
        "negative_prompt": req.negative_prompt,
        "duration": duration,
        "mask_start": req.mask_start,
        "mask_end": req.mask_end,
        "seed": seed,
        "steps": req.steps,
        "cfg_scale": req.cfg_scale,
        "sampler_type": req.sampler_type,
        "apg_scale": req.apg_scale,
        "duration_padding_sec": req.duration_padding_sec,
        "chunked_decode": req.chunked_decode,
        "model_sample_rate": MODEL_SAMPLE_RATE,
        "output_sample_rate": OUTPUT_SAMPLE_RATE,
    }

    log_history(record)
    return record