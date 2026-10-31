# Veracity

**Live AI-voice and scam-call detection for normal phone calls.**

*ve·rac·i·ty (noun): truthfulness; conformity to fact.*

Veracity listens to a normal phone call on an Android phone plugged into a laptop by USB. While the call is still going on, a web dashboard shows:

1. **The number:** what public numbering data says about the caller's number, and a risk score with its reasons.
2. **The voice:** how likely it is that the caller's voice is AI-generated, updated every second.
3. **The words:** a live transcript, with the caller's exact words highlighted when they match a known scam script ("digital arrest", "share the OTP", "safe account"…).

When the call ends, Veracity writes a **JSON evidence report** the victim can attach when reporting on **1930**, **cybercrime.gov.in** or **Chakshu**.

Everything runs **offline on one laptop**. There are no cloud APIs and no internet during the call, and audio is never saved unless the user turns that on.

Built for **Hackathon 2026 (30–31 October 2026)**.

---

## Contents

1. [Status](#1-status)
2. [How it works](#2-how-it-works)
3. [Getting started](#3-getting-started)
4. [Connecting a real phone](#4-connecting-a-real-phone)
5. [Configuration](#5-configuration)
6. [Codebase tour](#6-codebase-tour)
7. [API reference](#7-api-reference)
8. [The evidence report](#8-the-evidence-report)
9. [Measured results](#9-measured-results)
10. [Testing](#10-testing)
11. [Troubleshooting](#11-troubleshooting)
12. [Limitations](#12-limitations)
13. [Rules we follow](#13-rules-we-follow)
14. [Further reading](#14-further-reading)

---

## 1. Status

| Part | Status | Notes |
| --- | --- | --- |
| **Step 1 · Check setup** | ✅ Working | adb, phone, scrcpy, audio input and all three models are really checked. |
| **Step 2 · Check number** | ✅ Working | Validity, line type, India series (1600 / 140), country, original carrier, community reports and a transparent rule score. Fills in the number from an incoming call. |
| **Step 3 · Live call** | ✅ Working | Real capture from the phone, AI-voice score every second, live transcript, red flags, alerts. |
| **Step 4 · Report** | ✅ Working | Risk fusion, JSON report saved and downloadable, reporting links, community reports. |
| Light and dark themes | ✅ Working | Follows the system; toggle in the header. |
| Tests | ✅ 13 passing | Number score, fusion, report schema, report and community endpoints. |
| AI-voice accuracy on real calls | 🟡 Needs calibration | Good on simulated phone audio (see [§9](#9-measured-results)); still raises some false alarms on real calls. Thresholds must be calibrated on recordings from your own phone. |
| Number ML model (§1.4 of the project document) | ❌ Not built | The rule score works; the logistic-regression % does not exist yet. |
| Backend simulation mode (`VERA_FAKE=1`) | 🟡 Partial | It only lets Step 1 continue without a phone. A live call still needs the BlackHole audio input. |

---

## 2. How it works

### The pipeline

```text
Caller ──call──► Android phone ──USB (adb)──► scrcpy --audio-source=voice-call-downlink
                                                   │  plays the caller on the Mac
                                                   ▼
                                  macOS Multi-Output Device ──► speakers/headphones + BlackHole 2ch
                                                   │
                                                   ▼
                                  Python reads BlackHole: 0.1 s blocks, 48 kHz → mono 16 kHz
                                        │                                   │
                          every 1 s, last 4 s of audio            6–12 s chunks, cut at pauses
                                        ▼                                   ▼
                          wav2vec2 XLS-R deepfake model           faster-whisper large-v3-turbo
                          → calibrated AI-voice %                  → transcript
                          → smoothed: human / uncertain / AI       → 11 scam-rule categories
                                        │                          → local LLM (Ollama) every ~16 s
                                        └───────────────┬──────────────────┘
                                                        ▼
                     number rule score ──► fusion ──► JSON report ──► FastAPI ──WebSocket──► dashboard
```

**Why a USB cable?** Android doesn't let normal apps record phone calls. `scrcpy` runs its capture code on the phone through `adb` (Android's developer connection), and since v3.2 it can capture the caller's side of a call. Whether that works depends on the phone model, so [test your phone first](#44-the-critical-test-does-this-phone-give-you-call-audio).

### The two programs

```text
┌──────────────────────────┐  HTTP + WebSocket  ┌───────────────────────────┐   runs on the Mac   ┌─────────────────────┐
│ FRONTEND · React + Vite  │ ─────────────────► │ BACKEND · FastAPI         │ ──────────────────► │ adb, scrcpy,        │
│ veracity-frontend/       │ ◄───────────────── │ veracity-backend/         │ ◄────────────────── │ BlackHole, models,  │
│ http://localhost:5173    │        JSON        │ http://localhost:8000     │                     │ Ollama, SQLite      │
└──────────────────────────┘                    └───────────────────────────┘                     └─────────────────────┘
```

- **The frontend only draws screens.** It shows what the backend decided and never works out a verdict itself.
- **The backend does all the real work.** It runs the tools and models on the Mac and pushes results over one WebSocket per call.

### The four dashboard steps

| Step | What the user sees | Backend |
| --- | --- | --- |
| 1 · Check setup | Phone, scrcpy, audio input and models: green or red, with the command that fixes each problem | `GET /api/health` |
| 2 · Check number | Facts about the caller's number and its rule score; filled in automatically when the phone rings | `GET /api/call/state`, `POST /api/number/check` |
| 3 · Live call | Input level, AI-voice % and its timeline, transcript with highlighted evidence, red flags, script score, one alert banner | `POST /api/session/start`, `WS /ws/live/{id}`, `POST /api/session/{id}/stop` |
| 4 · Report | Risk level and how the score was built, what to do now (1930 / cybercrime.gov.in / Chakshu), evidence, Download JSON, community report | `GET /api/report/{id}`, `POST /api/number/report` |

---

## 3. Getting started

### Prerequisites

| Tool | Version | Why |
| --- | --- | --- |
| macOS on Apple Silicon | recommended | The live pipeline (BlackHole, Metal for the voice model) is built and tested on a Mac. |
| [Python](https://www.python.org/downloads/) | 3.12 or 3.13 | Backend. Tested on 3.13. |
| [Node.js](https://nodejs.org/) | 20.19+ | Frontend. |
| [Ollama](https://ollama.com/) | any recent | Optional local LLM. Without it the scam rules still work. |
| About 9 GB of free disk | | Models: voice ≈ 1.3 GB, Whisper ≈ 1.6 GB, Llama 3.1 8B ≈ 4.9 GB. |

### 1. Clone

```bash
git clone https://github.com/YADUNANDAN-SINGH/Veracity.git
cd Veracity
```

### 2. Backend

```bash
cd veracity-backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt -r requirements-ml.txt
```

Download the models once. After this, everything works with Wi-Fi off:

```bash
# AI-voice model (≈ 1.3 GB)
hf download Gustking/wav2vec2-large-xlsr-deepfake-audio-classification

# Speech-to-text (≈ 1.6 GB)
python -c "from faster_whisper import WhisperModel; WhisperModel('large-v3-turbo', device='cpu', compute_type='int8')"

# Local LLM (≈ 4.9 GB, optional)
ollama pull llama3.1:8b
```

> If `hf` isn't found, your `huggingface_hub` is older: use `huggingface-cli download …` instead.

Start the server:

```bash
uvicorn main:app --reload --port 8000
```

- http://localhost:8000/docs has interactive docs for every endpoint.
- The voice model and Whisper load in the background at start-up (a few seconds), so the first call is scored at once.

### 3. Frontend

In a second terminal:

```bash
cd veracity-frontend/veracity
npm install
npm run dev
```

Open **http://localhost:5173**. Vite forwards `/api/...` and `/ws/...` to the backend on port 8000, so there's nothing to configure.

### Without a phone

- **Browser demo:** if the backend has no session API (an older backend, or the frontend running alone), Step 3 plays a scripted "digital arrest" call in the browser, clearly marked *Demo call*, and builds a demo report from it. Good for UI work.
- **Test a live session without a call:** set the Mac's sound output to BlackHole and play speech into it (for example `say -a "BlackHole 2ch" "You are under digital arrest"`). The backend treats it exactly like call audio.

### Docker (UI work only)

```bash
docker compose up --build                                       # http://localhost:5173
docker compose --profile dev up --build backend frontend-dev    # hot reload: http://localhost:5174
```

> ⚠️ **A backend in Docker can never see your phone or BlackHole.** Docker on a Mac has no USB or audio access. To use the Docker frontend with a local backend, start the backend with `--host 0.0.0.0` and run `BACKEND_URL=http://host.docker.internal:8000 docker compose up -d --no-deps frontend`.

---

## 4. Connecting a real phone

### 4.1 Install the tools

```bash
brew install --cask android-platform-tools   # adb
brew install scrcpy                          # 3.2 or newer
brew install blackhole-2ch                   # virtual audio cable; restart the Mac if it doesn't appear
```

### 4.2 Turn on USB debugging

1. **Settings → About phone** → tap **Build number** 7 times (Xiaomi: *MIUI version*; Samsung: under *Software information*).
2. **Developer options** → turn on **USB debugging** (Xiaomi: also *USB debugging (Security settings)*).
3. Plug in with a **data** cable, set USB mode to **File transfer**, and accept **"Allow USB debugging?"**.

```bash
adb devices
# EIPNLJZXM7GIVKXG	device      ← "device" is good; "unauthorized" means accept the prompt on the phone
```

### 4.3 Route the call audio into BlackHole

scrcpy plays the caller through the Mac's **current sound output**. It can't be pointed at BlackHole directly, so the output must include BlackHole:

1. Open **Audio MIDI Setup** → **+** → **Create Multi-Output Device**.
2. Tick your speakers or headphones **first**, then **BlackHole 2ch**. Turn on **Drift Correction** for BlackHole only.
3. Right-click the device → **Use This Device For Sound Output**.
4. Restart the backend, which reads BlackHole's settings when it starts.

> macOS asks the terminal running `uvicorn` for **Microphone** permission the first time. Allow it, or BlackHole records silence.

If nothing reaches BlackHole for 6 seconds, Step 3 shows a **"No call audio"** banner naming the output the Mac is actually using.

### 4.4 The critical test: does this phone give you call audio?

Call the phone from another phone, answer, and during the call run:

```bash
scrcpy --no-video --no-playback --require-audio --audio-source=voice-call-downlink \
  --audio-codec=aac --record=downlink_test.m4a --time-limit=20
```

- **You hear the caller in `downlink_test.m4a`:** this phone works.
- **Silence:** retry with `--audio-source=voice-call` and run the backend with `VERA_AUDIO_SOURCE=voice-call`.
- **Still silent:** use another phone, or the fallback of the phone on speaker into the laptop mic: `VERA_AUDIO_DEVICE="MacBook Air Microphone" VERA_CAPTURE_METHOD=laptop_mic_speakerphone`.

### 4.5 A monitored call

1. Step 1: all checks green. Optionally turn on **Save audio**.
2. Step 2: the number fills in when the phone rings (or type it); check it.
3. Step 3: the backend starts scrcpy itself (unless one is already running) and starts listening.
4. **End call & build report** → Step 4.

---

## 5. Configuration

All settings are environment variables read by the backend. Every one is optional.

| Variable | Default | What it does |
| --- | --- | --- |
| `VERA_AUDIO_DEVICE` | `BlackHole 2ch` | Input device Python records from. |
| `VERA_AUDIO_SOURCE` | `voice-call-downlink` | scrcpy audio source; `voice-call` mixes both sides. |
| `VERA_CAPTURE_METHOD` | `scrcpy_<source>` | Written to the report; anything not starting with `scrcpy` stops the backend from launching scrcpy. |
| `VERA_VOICE_MODEL` | `Gustking/wav2vec2-large-xlsr-deepfake-audio-classification` | Hugging Face audio-classification model for the AI-voice score. |
| `VERA_VOICE_T` | `1.0` | Calibration temperature: p = sigmoid(logit(p_raw) / T). |
| `VERA_T_AI` | `0.75` | Window score that counts towards **Likely AI** (3 windows in a row). |
| `VERA_T_UNCERTAIN` | `0.40` | Smoothed score for **Uncertain**. |
| `VERA_WHISPER_MODEL` | `large-v3-turbo` | Whisper size; use `small` on a slower Mac. |
| `VERA_WHISPER_THREADS` | up to 8 | CPU threads for Whisper. |
| `VERA_LANGUAGE` | `hi` | Transcription language: `hi`, `en`, or `auto` to detect it per chunk. |
| `VERA_LLM_MODEL` | `llama3.1:8b` | Ollama model for the second scam-script layer. |
| `OLLAMA_HOST` | `http://localhost:11434` | Where Ollama runs. |
| `VERA_DB` | `app/data/veracity.db` | SQLite file for community reports and saved reports. |
| `VERA_FAKE` | unset | `1` lets Step 1 continue without a phone. |

Example: `VERA_LANGUAGE=en VERA_WHISPER_MODEL=small uvicorn main:app --reload --port 8000`

---

## 6. Codebase tour

```text
Veracity/
├── README.md
├── CODEBASE_GUIDE.md              older file-by-file walkthrough (Steps 1–2)
├── docker-compose.yml
├── Claude outputs/Veracity_Design_System.pdf
│
├── veracity-backend/              ── Python · FastAPI ──
│   ├── main.py                    app, CORS, routers; loads the models in the background
│   ├── requirements.txt           web + number + audio input
│   ├── requirements-ml.txt        torch, transformers, faster-whisper, scipy, ollama
│   ├── tests/test_report.py
│   └── app/
│       ├── routes/                web layer: one file per group of URLs
│       │   ├── health.py          GET  /api/health
│       │   ├── call.py            GET  /api/call/state
│       │   ├── number.py          POST /api/number/check, POST /api/number/report
│       │   ├── session.py         POST /api/session/start · /stop, WS /ws/live/{id}
│       │   └── report.py          GET  /api/report/{id}
│       ├── feature/               logic layer: plain Python, no web code
│       │   ├── call_state.py      ringing / in-call / caller number over adb
│       │   ├── number_intelligence.py   libphonenumber facts, India series, rule score
│       │   ├── audio_capture.py   BlackHole capture, resampling, starts/stops scrcpy
│       │   ├── voice.py           deepfake model, calibration, verdict smoother
│       │   ├── transcriber.py     faster-whisper, tuned for Hindi phone audio
│       │   ├── scam_rules.py      11 categories, Whisper-tolerant Hindi matching, script score
│       │   ├── scam_llm.py        Ollama structured output, quote checking
│       │   ├── session.py         one live call: audio, transcriber and LLM threads → events
│       │   ├── report.py          Pydantic report schema + fusion
│       │   └── reports_db.py      SQLite: community reports, saved reports
│       └── data/                  (git-ignored) veracity.db, audio/ recordings
│
└── veracity-frontend/veracity/    ── React 19 · Vite 8 ──
    ├── vite.config.js             dev server :5173, proxies /api and /ws to :8000
    └── src/
        ├── App.jsx                current step and state shared between steps
        ├── api/                   talks to the backend (no React here)
        │   ├── client.js          fetch wrapper: timeouts, ApiError, wsUrl()
        │   ├── health.js · number.js · call.js
        │   ├── session.js         start / stop / live socket; documents every event
        │   ├── report.js          reporting links, scam types, community report, download
        │   └── demoCall.js        the scripted browser demo
        ├── hooks/                 useHealth, useNumberCheck, useCallState, useLiveSession, useTheme
        ├── pages/                 SetupPage, NumberPage, LivePage, ReportPage
        ├── components/
        │   ├── layout/            AppHeader (steps, call timer, theme toggle), FlowSteps
        │   ├── live/              LevelMeter, ScoreMeter, VoiceTimeline, Transcript, RedFlagList
        │   ├── report/            RiskSummary, CommunityReport, ReportJson
        │   └── ui/                Button, Panel, AlertBanner, Badge, Toggle, Icon, CallStatus…
        ├── constants/             steps, scam categories in words
        └── styles/                tokens.css (every colour, light + dark), base.css
```

**Backend layers.** `routes/` holds web code only: it validates the request with Pydantic, calls a feature and turns errors into HTTP codes. `feature/` holds pure logic you can test or reuse without a server.

**Frontend layers.** `api/` (URLs and JSON shapes) → `hooks/` (loading and error state) → `pages/` (one screen) → `components/` (how one piece looks). If the backend renames a field, only `api/` changes.

### One live call, end to end

```text
LivePage mounts → useLiveSession.start()
  POST /api/session/start ──► Session: starts scrcpy, opens BlackHole, starts 3 threads
  WS   /ws/live/{id}      ◄── level 10×/s · voice 1×/s · transcript at each pause · flag · script · alert
  "End call" → POST /api/session/{id}/stop
                          ──► finishes the last chunk, stops scrcpy, analyse_number(),
                              build_report(), saves it to SQLite, publishes report + ended
  ReportPage ◄── the same report JSON
```

---

## 7. API reference

Interactive docs: **http://localhost:8000/docs**.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Backend, phone, scrcpy, audio device and model status |
| GET | `/api/call/state` | `{connected, state: idle \| ringing \| in_call, number}` from the phone |
| POST | `/api/number/check` | `{number, region}` → number facts, series, community reports, rule score and reasons |
| POST | `/api/number/report` | `{number, category, note}` → saves a community report, returns new totals |
| POST | `/api/session/start` | `{caller_number, save_audio}` → `{session_id}`; 503 if the audio input is missing |
| POST | `/api/session/{id}/stop` | Ends the call; returns and saves the JSON report |
| GET | `/api/report/{id}` | A saved report; `?download=1` sends it as a file |
| WS | `/ws/live/{id}` | Live events; late joiners get the history replayed |

### `POST /api/number/check`

```json
{ "number": "+855 12345678" }
```
```json
{
  "valid": true, "number_type": "MOBILE", "country": "Cambodia", "location": "Cambodia",
  "original_carrier": "Cellcard", "is_international": true, "e164_format": "+85512345678",
  "national_digits": "12345678", "timezones": ["Asia/Phnom_Penh"],
  "series": "international", "community_reports": 0, "reports_7d": 0,
  "rule_score": 25, "rule_reasons": ["International number (+25)"]
}
```

**Rule score** (shown to the user, clamped to 0–100):

| Signal | Points |
| --- | --- |
| Invalid or unparseable number | +40 |
| International number | +25 |
| Community reports | +10 × log2(1 + reports), at most +30 |
| Reported in the last 7 days | +10 |
| 140 telemarketing series | +5 |
| 1600 series (regulated banks and agencies) | −20 |

`original_carrier` is the operator the number range was **first** issued to; the number may have been ported since.

### WebSocket events

| `type` | Fields | Dashboard |
| --- | --- | --- |
| `level` | `t, dbfs` | input meter and waveform |
| `voice` | `t, p_ai, smoothed, state, speech` | AI-voice %, state badge, timeline colour |
| `transcript` | `t, text` | transcript line |
| `flag` | `category, severity, evidence, t, source` (`rule` or `llm`) | red-flag list, highlighted words |
| `script` | `score` | script score |
| `alert` | `kind` (`voice`, `script`, `audio`), `message` | the one banner |
| `report` | `report` | Step 4 |
| `ended` | — | closes the socket |

`t` is seconds since the call started. `state` is `LIKELY_HUMAN`, `UNCERTAIN` or `LIKELY_AI`.

---

## 8. The evidence report

Built by `app/feature/report.py` when the call ends, saved in SQLite, and downloadable from Step 4.

```json
{
  "schema_version": "1.0",
  "report_id": "1e9928a6…",
  "generated_at": "2026-10-31T01:18:36Z",
  "call":   { "caller_number": "+85512345678", "duration_s": 34.0,
              "capture_method": "scrcpy_voice_call_downlink", "audio_device": "BlackHole 2ch" },
  "number": { "e164": "+85512345678", "series": "international", "community_reports": 0,
              "rule_score": 25, "reasons": ["International number (+25)"] },
  "voice":  { "model_id": "Gustking/wav2vec2-large-xlsr-deepfake-audio-classification",
              "calibration_t": 1.0, "threshold": 0.75,
              "windows": [{ "t_start": 0.0, "t_end": 4.0, "p_ai": 0.91 }],
              "max_p_ai": 0.91, "mean_p_ai": 0.88, "final_state": "LIKELY_AI" },
  "script": { "script_score": 100, "scam_type": "digital_arrest",
              "red_flags": [{ "category": "THREAT_ARREST", "severity": 3,
                              "evidence": "digital arrest", "t": 6.0, "source": "rule" }],
              "transcript_excerpt": "…" },
  "overall":  { "risk_level": "HIGH", "score": 100,
                "top_reasons": ["Voice sounded synthetic (peak 91%)",
                                "Scam-script red flags (score 100)",
                                "Number: International number (+25)"] },
  "evidence": { "audio_saved": false, "audio_sha256": null },
  "next_steps": ["Lost money? Call 1930 now and file a complaint at https://cybercrime.gov.in. …",
                 "No money lost? Report the number on Chakshu … within 30 days of the call."],
  "disclaimer": "This report is evidence, not proof. …"
}
```

**Fusion:** `overall = round(0.25 × number + 0.40 × voice peak + 0.35 × script)`. A voice peak ≥ 85 or a script score ≥ 80 is enough on its own. **HIGH ≥ 70**, **MEDIUM ≥ 40**, otherwise LOW. Step 4 shows this calculation, so nobody has to trust a bare number.

**Script score:** 8 × the sum of the severities of distinct categories, +20 for authority + payment (digital arrest), +20 for family emergency + payment (voice clone), +10 for an OTP or PIN request; at most 100.

**Privacy:** audio is processed in memory. With **Save audio** on, the call is written to `app/data/audio/<id>.wav` and the report stores its SHA-256, so anyone can check the file was not changed.

---

## 9. Measured results

All numbers below were measured by us on 31 October 2026, on an M-series MacBook. **They use simulated phone audio**: real human speech (LibriSpeech) and synthetic speech (macOS voices), passed through a 300–3400 Hz filter, μ-law at 8 kHz and AAC. Real calls differ, so treat these as a starting point, not accuracy claims.

### Choosing the AI-voice model

Share of 4-second windows scored ≥ 0.75 (the "AI" threshold), on phone-channel audio:

| Model | Real human voices (want low) | Synthetic voices (want high) |
| --- | --- | --- |
| mo-thecreator/Deepfake-audio-detection (first choice) | 26% | 100% |
| garystafford/wav2vec2-deepfake-voice-detector | 21% | 100% |
| Hemgg/Deepfake-audio-detection | 31% | 93% |
| MelodyMachine/Deepfake-audio-detection-V2 | 0% | 58% |
| **Gustking/wav2vec2-large-xlsr-deepfake-audio-classification (used)** | **1%** | **100%** |

Scoring takes 0.07 s per window on Apple Silicon (Metal). Through a full live session, 32 s of human speech stayed **Likely human** and the synthetic voice turned **Likely AI**.

### Choosing the speech-to-text setup

Hindi scam script, phone-channel audio, 8 s chunks:

| Setup | Time per 8 s chunk | Characters wrong |
| --- | --- | --- |
| small, Whisper defaults (language auto-detect) | 6.8–9.8 s | 25–27%, with garbled chunks |
| small, tuned settings | 2.5 s | 22% |
| medium, tuned settings | 8.1 s (too slow to keep up) | 21% |
| **large-v3-turbo, tuned settings (used)** | **5.0 s** | **10%** |

"Tuned settings" means Hindi fixed, temperature 0 with one small retry (no fallback to random decoding), no repeated 3-word phrases, and segments Whisper rates as non-speech dropped. On top of that, the rules fold together the letters Whisper confuses on phone audio (ट/त, ड/द, ष/श/स, long and short vowels), so "दिजिटल आरेष्ट" still matches "डिजिटल अरेस्ट". On the test script this took the rules from 0 to 7 red flags, with no flags on everyday sentences.

---

## 10. Testing

```bash
cd veracity-backend
pip install pytest httpx      # first time
python -m pytest              # 13 tests

cd ../veracity-frontend/veracity
npm run lint
npm run build
```

The tests cover the number rule score against the project document's table, fusion and its overrides, the report schema, and the report and community-report endpoints, using a temporary database.

---

## 11. Troubleshooting

| Problem | Fix |
| --- | --- |
| **"No call audio"** banner, flat waveform | The Mac's sound output doesn't include BlackHole. Set up the Multi-Output Device ([§4.3](#43-route-the-call-audio-into-blackhole)). The banner names the output actually in use. |
| Flat waveform even with the Multi-Output Device | The phone isn't sharing call audio: run the [critical test](#44-the-critical-test-does-this-phone-give-you-call-audio) and try `VERA_AUDIO_SOURCE=voice-call`. Also check the terminal has Microphone permission. |
| **"Couldn't monitor this call"** | BlackHole isn't installed, or was installed after the backend started. Restart the backend. |
| Real voice shown as **Likely AI** | The thresholds aren't calibrated for your phone yet. Record a few normal calls with Save audio on and calibrate `VERA_VOICE_T` / `VERA_T_AI` on them. |
| Transcript in the wrong script or language | Set `VERA_LANGUAGE` (`hi`, `en`); `auto` guesses per chunk and can pick the wrong language on phone audio. |
| Transcript lines lag behind the call | Use `VERA_WHISPER_MODEL=small`, or stop other heavy apps. |
| No `local LLM` flags | Ollama isn't running or the model isn't pulled: `ollama pull llama3.1:8b`. The rules work without it. |
| Step 1: **"No phone found"** | Run `adb devices`; replug, set USB mode to *File transfer*, or accept the debugging prompt. |
| **"Can't reach the backend"** | Start `uvicorn` on port 8000. |
| `address already in use` | Another copy (often Docker) is running: `docker compose stop` or `lsof -nP -iTCP:8000 -sTCP:LISTEN`. |
| BlackHole missing in Audio MIDI Setup | Restart the Mac after `brew install blackhole-2ch`. |

---

## 12. Limitations

- **Not proof.** The AI-voice % is a model estimate meant to warn the user, not legal evidence. The report says so.
- **Calibration.** The voice model and its thresholds were chosen on simulated phone audio. Real calls still produce some false "Likely AI" stretches until calibrated on recordings from the phone and network actually used.
- **Transcription.** Whisper still makes mistakes on narrow-band Hindi and Hinglish. The rules only catch phrases on their list; keep adding real scam phrases from news reports.
- **The local LLM can mislabel.** Its flags are only kept when their exact quote is in the transcript and it is confident, but it can still pick the wrong category.
- **Spoofing.** Veracity checks the caller ID the network shows. It cannot reveal the real number behind a spoofed call or locate the caller.
- **Phone support varies**, and a laptop and cable are needed today: a normal Android app can't capture call audio.

---

## 13. Rules we follow

**Product honesty**
- No external APIs at runtime. Models are downloaded once, then everything works offline.
- Privacy by default: audio stays in memory unless the user turns on Save audio.
- Never quote accuracy we didn't measure ourselves.
- Say "Likely AI", never "Confirmed fake".

**UI**
- Calm, plain language: second person, sentence case, no emoji, no exclamation marks.
- Never colour alone: every status pairs a colour with an icon and a word.
- One primary button and at most one banner per screen.
- Numbers, percentages, times and JSON are set in the mono font.
- Show the backend's verdict; never work it out in the browser.

**Code**
- Backend: logic in `feature/`, URLs in `routes/`. Frontend: `api/` → `hooks/` → `pages/` → `components/`.
- Every colour comes from `src/styles/tokens.css` (light and dark).
- Short comments that explain *why*.
- Run the tests and `npm run lint` before pushing.

---

## 14. Further reading

| Document | What's in it |
| --- | --- |
| *Veracity Project Document v1.1* (shared by the team) | Full feature specs, thresholds, stack versions, pitch |
| `Claude outputs/Veracity_Design_System.pdf` | Colours, type, every screen and component |
| [CODEBASE_GUIDE.md](CODEBASE_GUIDE.md) | Detailed walkthrough of Steps 1–2 (written before Steps 3–4) |
| [veracity-frontend/veracity/README.md](veracity-frontend/veracity/README.md) | Frontend-only notes |
