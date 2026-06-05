# Stable FX Batch and Sweep

An **Ableton Live extension** that generates sound effects from a text prompt and drops them straight into your Arrangement. Right‑click an audio track, describe a sound, and get back a series of takes — laid out back‑to‑back, ready to chop and use.

It does this by talking to a **local Stable Audio 3 Small SFX server** ([Stability AI's `stable-audio-3`](https://github.com/Stability-AI/stable-audio-3) wrapped in a small HTTP API you run on your own machine), so generation is offline, private, and free of per‑request limits. The extension adds **batch** generation (many takes of one idea), **parameter sweeps** (grids over guidance/steps/seeds), a **prompt matrix** (`{a|b|c}` alternation), automatic **silence‑trimming**, and a guard that detects and recovers the occasional garbled generation.

---

## Contents

1. [How it works (the big picture)](#how-it-works-the-big-picture)
2. [Prerequisites](#prerequisites)
3. [Part 1 — Set up & start the Stable Audio server](#part-1--set-up--start-the-stable-audio-server)
4. [Part 2 — Install / run the extension](#part-2--install--run-the-extension)
5. [Part 3 — Using the extension](#part-3--using-the-extension)
6. [The dialog, option by option](#the-dialog-option-by-option)
7. [Prompting tips & model quirks](#prompting-tips--model-quirks)
8. [Troubleshooting](#troubleshooting)
9. [Building & packaging](#building--packaging)
10. [Limitations](#limitations)

---

## How it works (the big picture)

```
┌────────────────────┐     HTTP (localhost:8000)      ┌──────────────────────────┐
│  Ableton Live       │  ─── POST /generate ─────────▶ │  Stable Audio SFX server  │
│  + this extension   │  ◀── WAV bytes ─────────────── │  (server_sfx.py, uvicorn) │
└────────────────────┘                                 └──────────────────────────┘
        │  importIntoProject → createAudioClip
        ▼
   Clips laid back‑to‑back on the right‑clicked track
```

There are **two separate pieces** you need running:

1. **The Stable Audio server** — a Python process you start in a terminal. It loads the AI model once and exposes HTTP endpoints. This is **not** part of the extension and must be started yourself (Part 1).
2. **The extension** — runs inside Ableton Live. It collects your prompt/settings in a dialog, calls the server once per sample, checks each result, and places the good ones in the Arrangement (Parts 2–3).

If the server isn't running, the extension shows a clear "can't reach the server" message and stops — it never hangs Live.

---

## Prerequisites

| Requirement | Why | Notes |
|---|---|---|
| **macOS on Apple Silicon** | The Stable Audio server is built/tested here | Other platforms may work for the server but are untested |
| **Ableton Live — Beta build** | Extensions only load in a Beta build (e.g. `Live 12.4.5b3`) | Regular Suite builds have no Extension Host |
| **Node.js ≥ 24.14.1** | Build tooling for the extension | Only needed to build/dev the extension, not to run an installed `.ablx` |
| **Python + [`uv`](https://docs.astral.sh/uv/)** | Runs the Stable Audio server | Installed in Part 1 |
| **Hugging Face account** | The model is gated | You must accept the model terms |
| **Stable Audio 3 Small SFX model** | The actual generator | `stabilityai/stable-audio-3-small-sfx` |

---

## Part 1 — Set up & start the Stable Audio server

> If you already have the server installed at `~/stable-audio-3`, skip to [Starting the server](#starting-the-server-every-session).

### One‑time setup

**1. Install `uv`** (Python environment manager):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
# restart your terminal, then verify:
uv --version
```

**2. Clone the Stable Audio 3 repo:**

```bash
git clone https://github.com/Stability-AI/stable-audio-3
cd stable-audio-3
```

**3. Install dependencies:**

```bash
uv sync
uv add fastapi uvicorn soundfile torchaudio
```

**4. Log in to Hugging Face and accept the model terms:**

```bash
uv run hf auth login        # paste your HF token when prompted
```

Then, in a browser, open the gated model page and click **Agree** to accept access:
`stabilityai/stable-audio-3-small-sfx`

**5. Add the API server file.** Create `server_sfx.py` in the `stable-audio-3` folder and paste in the server code (provided with the server distribution — see `README_stable_audio_sfx_server.md`). The folder should look like:

```
stable-audio-3/
  server_sfx.py
  inputs/        # (optional) source audio for mutate/inpaint
  outputs/       # generated WAVs land here
  history.jsonl  # generation log
```

### Starting the server (every session)

From the `stable-audio-3` folder, launch the server at **48 kHz** output (matches Ableton's project rate well):

```bash
cd ~/stable-audio-3
OUTPUT_SAMPLE_RATE=48000 uv run uvicorn server_sfx:app --host 127.0.0.1 --port 8000
```

**Leave this terminal window open** — the server must stay running the whole time you use the extension. You should see something like:

```
Loading model: small-sfx
Model loaded.
Output sample rate: 48000
Uvicorn running on http://127.0.0.1:8000
```

**Verify it's alive** (in a second terminal):

```bash
curl http://127.0.0.1:8000/health
# → {"status":"ok","model":"small-sfx","model_sample_rate":44100,"output_sample_rate":48000}
```

That's it — the server is ready. The extension will use `http://127.0.0.1:8000` by default.

---

## Part 2 — Install / run the extension

There are two ways to run the extension. Use **Developer Mode** while iterating; **install the `.ablx`** for everyday use.

### Option A — Installed (recommended for normal use)

1. In Live: **Preferences → Extensions**, turn **Developer Mode OFF**.
2. Drag **`Stable-FX-Batch-and-Sweep-1.0.0.ablx`** (in this folder) into the Extensions pane.
3. **Restart Live.**

Live extracts it to `~/Library/Application Support/Ableton/Extensions/Stable FX Batch and Sweep/` and loads it automatically on startup. Nothing to run in a terminal (other than the Stable Audio server from Part 1).

### Option B — Developer Mode (for development)

1. Create a `.env` file in this project folder pointing at your Live install:

   ```
   EXTENSION_HOST_PATH=/Applications/Ableton Live 12 Beta.app
   ```

2. In Live: **Preferences → Extensions**, turn **Developer Mode ON**. (Live shuts down its built‑in Extension Host so you can run your own.)
3. Open Live, then in this folder run:

   ```bash
   npm install      # first time only
   npm start        # builds (dev) + connects to Live
   ```

   Leave `npm start` running. Re‑run it after any code change to reload the extension.

> You can run **either** the installed `.ablx` **or** Developer Mode — not both at once. If you switch to Developer Mode, remove/disable the installed copy first (and vice‑versa).

---

## Part 3 — Using the extension

1. Make sure **the Stable Audio server is running** (Part 1) and the extension is loaded (Part 2).
2. In Live's **Arrangement view**, **right‑click on an audio track** — on an empty area where you want the clips to start. (Generated audio can only go on an **audio** track, not a MIDI track.)
3. Choose **“Generate SFX…”** from the context menu.
4. Fill in the dialog (see the next section), watch the **“N samples”** counter, and click **Generate** (or press **⌘/Ctrl + Enter**).
5. A progress bar shows each sample as it generates — you can **Cancel** at any point; whatever finished so far is still placed.
6. The finished clips appear **back‑to‑back on the track**, starting at where you clicked, each named with its seed/parameters.

The clips are committed audio files imported into your project — chop, move, and process them like any other audio.

---

## The dialog, option by option

| Field | What it does |
|---|---|
| **Prompt** | The sound to generate. Supports a **prompt matrix**: `{a\|b\|c}` tries every alternative. e.g. `small {wooden\|metal} {latch\|button} click` → 4 prompts. Combinations multiply with the sweep grid. |
| **Negative prompt** | Things to avoid. **Only has any effect when CFG > 1** (at CFG 1.0 the guidance math cancels it out entirely). |
| **Duration range (seconds)** | Min–max **whole seconds**; each sample gets a random integer length in the range (set min = max for a fixed length). Integers are used deliberately — see [model quirks](#prompting-tips--model-quirks). |
| **Sampler** | The diffusion sampler. Only **`pingpong`** (default) and **`euler`** are supported by this model. |
| **Mode: Batch** | Generate **Count** takes with **sequential seeds** from **Seed start**, all sharing **Steps**, **CFG scale**, and **APG scale**. |
| **Mode: Sweep** | Generate a **grid** over comma‑separated **Seeds × CFG scales × Steps values × APG scales** — every combination. Great for auditioning how a parameter changes the sound. |
| **CFG scale** | Prompt‑guidance strength. **1.0** = unguided baseline (negative prompt inert). This model **clips/distorts above ~1.7**, so useful range is roughly **1.0–1.6**. |
| **APG scale** | *Adaptive Projected Guidance* — an alternative guidance knob (default 1.0) that steers toward the prompt with fewer of CFG's harsh artifacts. |
| **Steps** | Diffusion refinement steps (default **8**). More is not always better for this model. |
| **Trim silence from clips** ✅ | Trims leading/trailing silence so each clip is tight to its actual sound — also gives natural length variety. On by default. |
| **Delete generated files from server after import** ✅ | Removes the WAVs from the server's `outputs/` folder once they're imported (the project keeps its own copy). On by default. |
| **Server URL** | Where the Stable Audio server is. Defaults to `http://127.0.0.1:8000`. |

**Shortcuts:** ⌘/Ctrl + Enter = Generate · Esc = Cancel.

The dialog **remembers your last‑used settings** and pre‑fills them next time.

---

## Prompting tips & model quirks

This is a **sound‑effects / foley** model. It's happiest with **discrete, percussive, close‑miked events** and weakest with **sustained ambience**. A good prompt names the **object, action, material, distance, and recording style**, and lists what to avoid:

> `small hobby servo motor twitching once, plastic gears, close microphone, dry realistic foley, no music`

Things worth knowing (all handled or designed around by the extension):

- **Negative prompts need CFG > 1.** At the default CFG 1.0 they do nothing. Bump CFG to ~1.3–1.6 if you want a negative prompt to bite — but don't go above ~1.7 (this model clips/distorts).
- **Durations are whole seconds on purpose.** The model occasionally **diverges into a clipped noise wall** at certain *fractional* durations (e.g. 3.7s, 3.8s). Integer seconds avoid this almost entirely, which is why the duration range is integer‑only.
- **Blown‑out takes are caught automatically.** If a generation does come back as a clipped/diverged wall, the extension detects it (by waveform shape, not just loudness) and **retries at a slightly different integer length** before giving up. If it still fails, that sample is skipped and you get a short report — nothing garbled is placed.
- **Ambient/textural prompts** (water, wind, rain) are more likely to produce odd results than crisp events. Rewording toward an *event* — “a single splash”, “one footstep in wet sand” — works far better than “ocean ambience”.
- **Use Batch to get options, Sweep to learn.** Batch gives you many takes to pick from; Sweep shows you how CFG/steps/APG/seed each change the sound.

---

## Troubleshooting

**“Can't reach the Stable Audio server …”**
The server isn't running (or is on a different URL). Start it (Part 1) and confirm `curl http://127.0.0.1:8000/health` returns `ok`. If you run it on another host/port, update the **Server URL** field.

**The menu item “Generate SFX…” doesn't appear**
- Right‑click an **audio** track in **Arrangement** view (not a MIDI track, not Session).
- Installed mode: confirm the extension shows in **Preferences → Extensions** and that you **restarted Live** after installing.
- Dev mode: confirm `npm start` is connected and **Developer Mode is ON**.

**Nothing was placed / some takes were skipped**
The model diverged on those parameter points even after retries. Try a different prompt, seed range, or duration — and prefer discrete event prompts (see tips above).

**Checking logs**
The extension's `console.log` output and any crash traces go to:
```
~/Library/Preferences/Ableton/Live <version>/ExtensionHost.txt
```
Lines are prefixed with `[stable-fx]`. If you see no `[stable-fx]` lines at all after triggering it, the extension may have failed to load at startup.

**Dev vs installed conflict**
Don't run `npm start` (Developer Mode) and the installed `.ablx` at the same time — disable one.

---

## Building & packaging

From this folder:

```bash
npm install          # first time only
npm run build        # production bundle (minified)  → dist/extension.js
npm run build:dev    # dev bundle (with sourcemaps)
npm start            # dev build + connect to Live (Developer Mode)
npm run package      # production build → Stable-FX-Batch-and-Sweep-1.0.0.ablx
```

To cut a new version: bump `version` in **both** `manifest.json` and `package.json`, then `npm run package`.

**Project layout:**

```
stable-fx-batch-and-sweep/
├── manifest.json          # extension metadata Live reads (name, entry, version)
├── package.json           # scripts + SDK/CLI deps (file: refs to the SDK tarballs)
├── build.ts               # esbuild bundler (CJS, inlines interface.html)
├── tsconfig.json
├── .env                   # EXTENSION_HOST_PATH (Developer Mode only; not committed)
├── src/
│   ├── extension.ts       # entry point: dialog, server calls, blow-out guard, import/layout
│   ├── interface.html     # the prompt dialog (themed WebView UI)
│   └── html.d.ts
└── Stable-FX-Batch-and-Sweep-1.0.0.ablx   # the packaged extension
```

---

## Limitations

- **Audio tracks only** — generated audio can't be placed on MIDI tracks.
- **The server is separate** — you must start `server_sfx.py` yourself; the extension can't launch it.
- **Sound‑effects model** — built for discrete foley/mechanical sounds, not music, speech, or long ambiences.
- **No real‑time processing** — the extension is an offline editing tool; it generates and places audio when you ask, it doesn't process Live's audio stream.
- Generated clips are **committed audio files** imported into the project (one file per kept sample).
