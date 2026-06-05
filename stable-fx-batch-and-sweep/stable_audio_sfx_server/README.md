# Stable Audio 3 Small SFX Local API Server

This project sets up **Stable Audio 3 Small SFX** as a local API server.

The goal is to keep the model loaded in memory and expose HTTP endpoints for:

- single sound-effect generation
- batch generation
- prompt comparison
- parameter sweeps
- mutation / audio-to-audio variation
- inpainting
- output file listing, retrieval, deletion
- generation history logging

This is designed for local sound-design workflows, especially use with **Max**, **Ableton Live**, shell scripts, or a custom browser interface.

---

## What this setup does

We use the official `stable-audio-3` repository and add a custom FastAPI server:

```text
server_sfx.py
```

The server loads:

```text
small-sfx
```

once at startup, then exposes local HTTP endpoints.

Generated WAV files are saved to:

```text
outputs/
```

Input WAV files for mutation and inpainting go in:

```text
inputs/
```

Every generation is logged to:

```text
history.jsonl
```

The server can write generated files at **48 kHz**, which is useful for Max, Ableton, and general audio-production workflows.

---

# Quick start

## 1. Go to the Stable Audio 3 folder

```bash
cd ~/stable-audio-3
```

or wherever you cloned the repository.

---

## 2. Launch the server at 48 kHz output

```bash
OUTPUT_SAMPLE_RATE=48000 uv run uvicorn server_sfx:app --host 127.0.0.1 --port 8000
```

Leave this Terminal window open.

You should see something like:

```text
Loading model: small-sfx
Model loaded.
Model sample rate: 44100
Output sample rate: 48000
Uvicorn running on http://127.0.0.1:8000
```

The model sample rate may differ depending on the installed model/version. The important part is:

```text
Output sample rate: 48000
```

---

## 3. Test that the server is alive

Open a second Terminal:

```bash
curl http://127.0.0.1:8000/health
```

Expected response:

```json
{
  "status": "ok",
  "model": "small-sfx",
  "model_sample_rate": 44100,
  "output_sample_rate": 48000
}
```

---

## 4. Generate one sound

```bash
curl -X POST http://127.0.0.1:8000/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "small plastic latch clicking shut, close microphone, dry realistic foley",
    "negative_prompt": "music, melody, speech, voice, reverb",
    "duration": 2,
    "seed": 1234,
    "steps": 8,
    "cfg_scale": 1.0,
    "sampler_type": "pingpong",
    "output_name": "latch_48k.wav"
  }'
```

Play the result:

```bash
afplay outputs/latch_48k.wav
```

Check the file sample rate:

```bash
afinfo outputs/latch_48k.wav | grep "sample rate"
```

---

# Project structure

```text
stable-audio-3/
  server_sfx.py
  inputs/
  outputs/
  history.jsonl
```

## `inputs/`

Put source audio files here for mutation or inpainting.

Example:

```text
inputs/source_click.wav
```

## `outputs/`

Generated WAV files are saved here.

Example:

```text
outputs/latch_48k.wav
```

## `history.jsonl`

Every generation is logged here as JSON Lines.

This records:

```text
prompt
negative_prompt
seed
duration
steps
cfg_scale
sampler_type
output path
sample rate
generation type
```

This matters because generated audio files quickly become hard to track without metadata.

---

# Available endpoints

## Basic status and parameter endpoints

```text
GET /health
GET /params
GET /params/generate
```

## Generation endpoints

```text
POST /generate
POST /batch
POST /prompt_batch
POST /sweep
```

## File management endpoints

```text
GET /outputs
GET /outputs/{filename}
DELETE /outputs/{filename}
GET /history
```

## Audio editing endpoints

```text
POST /mutate
POST /inpaint
```

---

# Endpoint guide

## `GET /health`

Checks that the server is running.

```bash
curl http://127.0.0.1:8000/health
```

---

## `GET /params`

Lists server configuration and available endpoints.

```bash
curl http://127.0.0.1:8000/params
```

---

## `GET /params/generate`

Shows the actual Python signature of the installed model’s `generate()` function.

This is useful because the model API may expose parameters such as:

```text
prompt
negative_prompt
duration
steps
cfg_scale
seed
init_audio
init_noise_level
inpaint_audio
inpaint_mask_start_seconds
inpaint_mask_end_seconds
apg_scale
duration_padding_sec
chunked_decode
```

Run:

```bash
curl http://127.0.0.1:8000/params/generate
```

---

# `POST /generate`

Generates one WAV file.

Example:

```bash
curl -X POST http://127.0.0.1:8000/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "tiny relay clicking inside a small metal enclosure, dry close microphone, no music",
    "negative_prompt": "music, melody, speech, voice",
    "duration": 3,
    "seed": 2000,
    "steps": 8,
    "cfg_scale": 1.0,
    "sampler_type": "pingpong",
    "output_name": "relay_click.wav"
  }'
```

---

# `POST /batch`

Generates multiple variations of the same prompt using sequential seeds.

This is one of the most useful endpoints for sound design.

Example:

```bash
curl -X POST http://127.0.0.1:8000/batch \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "small hobby servo motor twitching once, plastic gears, close microphone, dry realistic foley, no music",
    "negative_prompt": "music, melody, speech, reverb",
    "duration": 3,
    "count": 8,
    "seed_start": 1000,
    "steps": 8,
    "cfg_scale": 1.0,
    "sampler_type": "pingpong",
    "prefix": "servo_twitch"
  }'
```

This produces:

```text
outputs/servo_twitch_seed1000.wav
outputs/servo_twitch_seed1001.wav
outputs/servo_twitch_seed1002.wav
...
```

Use this when you want many takes of the same idea.

---

# `POST /prompt_batch`

Generates one file for each prompt in a prompt list.

Good for testing different wording.

Example:

```bash
curl -X POST http://127.0.0.1:8000/prompt_batch \
  -H "Content-Type: application/json" \
  -d '{
    "prompts": [
      "small plastic button click, dry close microphone, no music",
      "small metal toggle switch click, dry close microphone, no music",
      "rubber keypad button press, hollow plastic body resonance, no music"
    ],
    "negative_prompt": "music, melody, speech, voice",
    "duration": 2,
    "seed": 3000,
    "steps": 8,
    "cfg_scale": 1.0,
    "sampler_type": "pingpong",
    "prefix": "button_comparison"
  }'
```

---

# `POST /sweep`

Generates a grid of files while changing parameters.

This is for exploring the model’s behaviour.

Example:

```bash
curl -X POST http://127.0.0.1:8000/sweep \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "tiny relay clicking inside a small metal enclosure, dry close microphone, no music",
    "negative_prompt": "music, melody, speech, voice",
    "duration": 3,
    "seeds": [2000, 2001],
    "cfg_scales": [0.7, 1.0, 1.3],
    "steps_values": [4, 8],
    "sampler_types": ["pingpong"],
    "apg_scales": [1.0],
    "prefix": "relay_sweep"
  }'
```

This creates:

```text
2 seeds × 3 cfg values × 2 step values = 12 WAV files
```

Use this when you want to learn how `cfg_scale`, `steps`, `seed`, or `apg_scale` affect the sound.

---

# `GET /outputs`

Lists generated WAV files.

```bash
curl http://127.0.0.1:8000/outputs
```

Returns metadata such as:

```text
filename
path
size
duration
sample rate
channels
modified time
```

---

# `GET /outputs/{filename}`

Downloads or serves a generated WAV file.

Example:

```bash
curl http://127.0.0.1:8000/outputs/latch_48k.wav --output downloaded_latch.wav
```

This is useful for browser interfaces or Max/Node clients.

---

# `DELETE /outputs/{filename}`

Deletes a generated file.

Example:

```bash
curl -X DELETE http://127.0.0.1:8000/outputs/latch_48k.wav
```

---

# `GET /history`

Shows the generation history.

```bash
curl http://127.0.0.1:8000/history
```

Limit the number of returned entries:

```bash
curl "http://127.0.0.1:8000/history?limit=20"
```

---

# `POST /mutate`

Takes an input audio file and generates a variation of it using a prompt.

Put a WAV file into:

```text
inputs/source_click.wav
```

Then run:

```bash
curl -X POST http://127.0.0.1:8000/mutate \
  -H "Content-Type: application/json" \
  -d '{
    "input_path": "inputs/source_click.wav",
    "prompt": "same sound but more metallic, sharper transient, small resonant enclosure",
    "negative_prompt": "music, speech, melody",
    "init_noise_level": 0.35,
    "seed": 5000,
    "steps": 8,
    "cfg_scale": 1.0,
    "sampler_type": "pingpong",
    "output_name": "source_click_mutated.wav"
  }'
```

## `init_noise_level` guide

```text
0.10–0.25 = subtle variation
0.30–0.50 = medium transformation
0.60–0.80 = strong transformation
1.00      = almost full regeneration
```

---

# `POST /inpaint`

Replaces part of an existing audio file.

This is useful for keeping a real attack/transient but hallucinating a new tail/body/material response.

Example:

```bash
curl -X POST http://127.0.0.1:8000/inpaint \
  -H "Content-Type: application/json" \
  -d '{
    "input_path": "inputs/source_click.wav",
    "prompt": "short metallic resonant tail inside a small metal box, realistic foley",
    "negative_prompt": "music, melody, speech",
    "mask_start": 0.4,
    "mask_end": 2.5,
    "seed": 6000,
    "steps": 8,
    "cfg_scale": 1.0,
    "sampler_type": "pingpong",
    "output_name": "source_click_inpaint_tail.wav"
  }'
```

The region between:

```text
mask_start
mask_end
```

is the part the model is asked to replace.

---

# Parameter guide

## `prompt`

The positive description of the desired sound.

Good SFX prompts usually include:

```text
object
action
material
distance
recording style
space
things to avoid
```

Example:

```text
small hobby servo motor twitching once, plastic gears, close microphone, dry realistic foley, no music
```

---

## `negative_prompt`

Things to avoid.

Useful defaults:

```text
music, melody, speech, voice, singing, reverb, ambience
```

For sound effects, a good starting point is:

```text
music, melody, speech, voice, singing
```

---

## `duration`

Length in seconds.

Suggested values:

```text
click / switch / latch: 1–2 seconds
servo / mechanism: 2–4 seconds
door / scrape / impact: 3–6 seconds
ambience / texture: 10–30 seconds
```

---

## `seed`

Controls repeatability.

Same prompt + same seed + same settings should produce the same or very similar result.

Use different seeds for different takes.

---

## `steps`

Generation refinement steps.

The model default is:

```text
8
```

Useful test values:

```text
4
8
12
16
```

More steps are not always better.

---

## `cfg_scale`

Prompt guidance strength.

Typical range:

```text
0.5–2.0
```

Rough guide:

```text
lower = looser, stranger, less literal
higher = more prompt-following, sometimes more brittle
```

Default:

```text
1.0
```

---

## `sampler_type`

This setup commonly uses:

```text
pingpong
```

This is passed through to the model as a sampler keyword.

---

## `apg_scale`

Additional guidance control exposed by the model.

Default:

```text
1.0
```

This is worth exploring in sweeps, but it is not the first parameter to obsess over.

---

## `duration_padding_sec`

Padding used internally by the model around generated duration.

Default exposed by the model:

```text
6.0
```

Usually leave this alone.

---

## `chunked_decode`

Optional boolean.

Can be useful for memory handling on longer generation.

Usually leave unset unless needed.

---

# Installation guide on a new machine

## Requirements

Recommended:

```text
macOS on Apple Silicon
Python environment managed by uv
Hugging Face account
Accepted Stable Audio 3 Small SFX model terms
```

You need to be logged into Hugging Face and have accepted access to the gated model page:

```text
stabilityai/stable-audio-3-small-sfx
```

---

## 1. Install `uv`

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Restart Terminal or source your shell profile if needed.

Check:

```bash
uv --version
```

---

## 2. Clone the Stable Audio 3 repository

```bash
git clone https://github.com/Stability-AI/stable-audio-3
cd stable-audio-3
```

---

## 3. Install the base environment

```bash
uv sync
```

---

## 4. Log in to Hugging Face

Use the newer Hugging Face CLI command:

```bash
uv run hf auth login
```

Paste your Hugging Face token.

You must also accept the model terms in the browser for:

```text
stabilityai/stable-audio-3-small-sfx
```

---

## 5. Test the model from the CLI

```bash
uv run stable-audio \
  --model small-sfx \
  -p "small plastic button click, close microphone, dry realistic foley, no music" \
  --duration 2 \
  -o button_click.wav
```

Play it:

```bash
afplay button_click.wav
```

If this works, the model is installed correctly.

---

## 6. Install server dependencies

```bash
uv add fastapi uvicorn soundfile torchaudio
```

---

## 7. Add the custom API server

Create:

```bash
nano server_sfx.py
```

Paste in the full `server_sfx.py` code.

Save:

```text
Ctrl+O
Enter
Ctrl+X
```

---

## 8. Launch the API server

For 48 kHz output:

```bash
OUTPUT_SAMPLE_RATE=48000 uv run uvicorn server_sfx:app --host 127.0.0.1 --port 8000
```

For native model sample rate output:

```bash
uv run uvicorn server_sfx:app --host 127.0.0.1 --port 8000
```

---

## 9. Test the API

```bash
curl http://127.0.0.1:8000/health
```

Then:

```bash
curl -X POST http://127.0.0.1:8000/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "small plastic latch clicking shut, close microphone, dry realistic foley",
    "negative_prompt": "music, melody, speech, voice, reverb",
    "duration": 2,
    "seed": 1234,
    "steps": 8,
    "cfg_scale": 1.0,
    "sampler_type": "pingpong",
    "output_name": "latch_test.wav"
  }'
```

Play:

```bash
afplay outputs/latch_test.wav
```

---

# Suggested workflow

For sound design, the best workflow is usually:

```text
1. Generate batches, not single sounds.
2. Use seeds to create multiple takes.
3. Audition quickly.
4. Keep the best 5–10%.
5. Trim/process in Max or Ableton.
6. Use mutate/inpaint on promising source material.
```

Example:

```bash
curl -X POST http://127.0.0.1:8000/batch \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "small mechanical switch clicking inside a plastic enclosure, close microphone, dry foley, no music",
    "negative_prompt": "music, melody, speech, voice",
    "duration": 2,
    "count": 16,
    "seed_start": 1000,
    "steps": 8,
    "cfg_scale": 1.0,
    "sampler_type": "pingpong",
    "prefix": "plastic_switch"
  }'
```



and outputs the generated file path back to Max for loading into `buffer~`, `playlist~`, or a corpus browser.
