# Veracity

**Live AI-voice and scam-call detection for normal phone calls.**

*ve·rac·i·ty (noun): truthfulness; conformity to fact.*

Veracity listens to a normal phone call on an Android phone plugged into a laptop by USB. While the call is still going on, a web dashboard shows:

1. **The number:** what public numbering data says about the caller's number, plus a risk score with reasons.
2. **The voice:** how likely it is that the caller's voice is AI-generated, as a percentage updated every second.
3. **The words:** whether the conversation follows a known scam script ("digital arrest", "share the OTP", "safe account"…), with the exact words as evidence.

When the call ends, Veracity writes a **JSON evidence report** the victim can attach when reporting on **1930**, **cybercrime.gov.in** or **Chakshu**.

Everything runs **offline on one laptop**. There are no cloud APIs, no internet during the call, and audio is never saved unless the user turns that on.

Built for **Hackathon 2026 (30–31 October 2026)**.

---

## Contents

1. [Project status](#1-project-status)
2. [How it works](#2-how-it-works)
3. [Getting started](#3-getting-started)
4. [Connecting a real phone](#4-connecting-a-real-phone)
5. [Codebase tour](#5-codebase-tour)
6. [API reference](#6-api-reference)
7. [How to add a feature](#7-how-to-add-a-feature)
8. [Rules we follow](#8-rules-we-follow)
9. [Troubleshooting](#9-troubleshooting)
10. [Limitations](#10-limitations)
11. [Further reading](#11-further-reading)

---

## 1. Project status

Read this first so you know what is real and what is still planned.

| Part | Status | Notes |
|---|---|---|
| Project skeleton (FastAPI + React + Docker) | ✅ Done | |
| Design system in code (colours, fonts, components) | ✅ Done | `src/styles/tokens.css`, `src/components/ui/` |
| **Step 1 · Check setup** screen + `GET /api/health` | 🟡 Partly done | adb, phone, scrcpy and the audio input (BlackHole 2ch via `sounddevice`) are really checked. Models are hard-coded as "not ready". |
| **Step 2 · Check number** screen + `POST /api/number/check` | 🟡 Partly done | Fills in the number from an incoming call (`GET /api/call/state`). Validity, line type, country, original carrier, time zone. Not yet: 1600/140 series rules, rule score, community reports, ML %. |
| Simulation mode (`VERA_FAKE=1`) | 🟡 Partly done | The flag is read and unlocks Step 1. Scripted fake call events are not built yet. |
| **Step 3 · Live call** (WebSocket, live screen) | ❌ Not started | |
| AI-voice detection (wav2vec2 model) | ❌ Not started | |
| Scam-script detection (Whisper + rules + local LLM) | ❌ Not started | |
| **Step 4 · Report** (JSON report, risk fusion) | ❌ Not started | |
| Tests | ❌ None yet | |

---

## 2. How it works

### The two programs

```
┌──────────────────────────┐   HTTP / WebSocket   ┌───────────────────────────┐   runs on the Mac    ┌──────────────────┐
│  FRONTEND · React + Vite │ ───────────────────► │  BACKEND · FastAPI        │ ───────────────────► │ adb, scrcpy,     │
│  veracity-frontend/      │ ◄─────────────────── │  veracity-backend/        │ ◄─────────────────── │ phonenumbers,    │
│  http://localhost:5173   │        JSON          │  http://localhost:8000    │                      │ (later) ML models│
└──────────────────────────┘                      └───────────────────────────┘                      └──────────────────┘
```

- **The frontend only draws screens.** It knows nothing about phones or numbers. It asks the backend and shows the answer.
- **The backend does all the real work.** It runs command-line tools and Python libraries on the Mac and replies with JSON.
- The browser never talks to the phone. Everything goes **browser → backend → Mac tools → phone**.

### The full pipeline (target design)

```
Caller phone ──call──► Victim's Android phone ──USB (adb)──► scrcpy --audio-source=voice-call-downlink
                                                                  │
                                                                  ▼
                                              macOS Multi-Output Device ──► speakers + BlackHole 2ch (virtual cable)
                                                                  │
                                                                  ▼
                                              Python reads BlackHole at 48 kHz → mono 16 kHz
                                                   │                                  │
                                    every 1 s, 4 s window                     every 8 s of audio
                                                   ▼                                  ▼
                                      wav2vec2 deepfake model             faster-whisper (speech-to-text)
                                      → calibrated AI-voice %                     → rule engine + local LLM
                                                   │                                  │
                                                   └────────────┬─────────────────────┘
                                                                ▼
                               number intelligence ──► fusion → JSON report ──► FastAPI ──WebSocket──► dashboard
```

**Why a USB cable?** Android doesn't let normal apps record phone calls. `scrcpy` runs its capture code on the phone through `adb` (Android's developer USB connection), and since v3.2 it can capture the caller's side of a call (`voice-call-downlink`). Whether this works depends on the phone model, so **test your phone first** ([§4](#4-connecting-a-real-phone)).

### The four dashboard steps

| Step | Screen | Backend |
|---|---|---|
| 1 · Check setup | Is the backend up? Is a phone connected? scrcpy, audio input, models? | `GET /api/health` |
| 2 · Check number | Facts and risk about the caller's number | `POST /api/number/check` |
| 3 · Live call | Voice %, transcript, red flags, alert banner | `POST /api/session/start`, `WS /ws/live/{id}` *(planned)* |
| 4 · Report | Risk level, reasons, evidence, Download JSON, 1930 / Chakshu links | `POST /api/session/{id}/stop` *(planned)* |

---

## 3. Getting started

### Prerequisites

| Tool | Version | Why |
|---|---|---|
| [Git](https://git-scm.com/downloads) | any | clone the repo |
| [Python](https://www.python.org/downloads/) | **3.12 recommended** (3.11 also fine) | backend. The ML libraries (torch, faster-whisper) are not reliable on 3.13 yet. |
| [Node.js](https://nodejs.org/) | 20.19+ (includes `npm`) | frontend |
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | optional | run everything without installing Python/Node |

On Windows, tick **"Add Python to PATH"** when installing Python.

### Clone

```bash
git clone https://github.com/YADUNANDAN-SINGH/Veracity.git
cd Veracity
```

### Option A — run locally (recommended, and required for a real phone)

You need **two terminals**: one for the backend and one for the frontend.

**Terminal 1 — backend**

macOS / Linux:
```bash
cd veracity-backend
python3.12 -m venv venv           # first time only
source venv/bin/activate
pip install -r requirements.txt   # first time, or when requirements.txt changes
uvicorn main:app --reload --port 8000
```

Windows (PowerShell):
```powershell
cd veracity-backend
py -3.12 -m venv venv             # first time only
venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```
> If PowerShell says running scripts is disabled, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once. In Command Prompt use `venv\Scripts\activate.bat` instead.

Check that it works:
- http://localhost:8000 → `{"message": "Backend is ready!"}`
- http://localhost:8000/docs → interactive API docs, where you can try every endpoint
- `--reload` restarts the server automatically when you save a Python file.

**Terminal 2 — frontend**

```bash
cd veracity-frontend/veracity
npm install        # first time, or when package.json changes
npm run dev
```

Open **http://localhost:5173**. Vite forwards every `/api/...` and `/ws/...` request to the backend on port 8000, so there's nothing to configure.

Stop either server with `Ctrl + C`.

### Option B — simulation mode (no phone needed)

Start the backend with `VERA_FAKE=1`:

```bash
VERA_FAKE=1 uvicorn main:app --reload --port 8000          # macOS / Linux
$env:VERA_FAKE="1"; uvicorn main:app --reload --port 8000  # Windows PowerShell
```

The dashboard shows **SIMULATION MODE** and lets you continue past Step 1 without a phone. Today that's all it does. Scripted fake calls are on the to-do list. Use this mode for frontend and rules work.

### Option C — Docker

From the repo root:

```bash
docker compose up --build                                       # prod-style: http://localhost:5173
docker compose --profile dev up --build backend frontend-dev    # hot reload: http://localhost:5174
docker compose down                                             # stop
```

> ⚠️ **A backend running in Docker can never see your phone.** Docker on a Mac has no USB access, and the container has no adb, scrcpy or audio devices. Step 1 will always show "adb wasn't found". Use Docker only for UI work or simulation mode.
>
> If you want the Docker frontend with a **local** backend (real phone), run the backend as in Option A with `--host 0.0.0.0`, then:
> ```bash
> BACKEND_URL=http://host.docker.internal:8000 docker compose up -d --no-deps frontend
> ```

Only one backend (port 8000) and one frontend (port 5173) can run at a time. Stop Docker (`docker compose stop`) before running locally, and the other way round.

---

## 4. Connecting a real phone

Only the person running the live demo needs this. Everyone else can use simulation mode.

### 4.1 Install the tools (macOS)

```bash
brew install --cask android-platform-tools   # adb
brew install scrcpy                          # needs version 3.2 or newer
brew install blackhole-2ch                   # virtual audio cable; restart the Mac if it doesn't appear
```

### 4.2 Turn on USB debugging (on the phone)

1. **Settings → About phone** → tap **Build number** 7 times. On Xiaomi this is *MIUI version*; on Samsung it's under *Software information*.
2. **Developer options** → turn on **USB debugging**. On Xiaomi, also turn on *USB debugging (Security settings)*.
3. Plug the phone into the Mac with a **data** cable (some cables only charge).
4. Set the USB mode to **File transfer** in the notification shade.
5. Accept **"Allow USB debugging?"**, tick *Always allow*.

Check it:
```bash
adb devices
# List of devices attached
# EIPNLJZXM7GIVKXG	device      ← "device" = good; "unauthorized" = accept the prompt on the phone
```

### 4.3 How the dashboard knows the phone is connected

When Step 1 loads, or you click **Check again**:

1. The frontend calls `GET /api/health` (`src/api/health.js`).
2. The backend (`app/routes/health.py`):
   - uses `shutil.which("adb")` to check that `adb` is installed;
   - uses `subprocess` to run `adb devices`, and counts the lines that end in `\tdevice` (ignoring `unauthorized` and `offline`);
   - does the same for `scrcpy --version`.
3. It returns `{"adb_found": true, "adb_devices": 1, ...}`.
4. `buildChecks()` in `src/api/health.js` turns that into green or red rows.

**So "phone connected" means exactly this: `adb devices`, run on the machine where the backend runs, lists the phone as `device`.** If the dashboard disagrees with you, run `adb devices` yourself. The dashboard can't know more than that command.

### 4.4 The critical test: does this phone give you call audio?

Call the phone from another phone, answer, and run this during the call:

```bash
scrcpy --no-video --no-playback --require-audio --audio-source=voice-call-downlink \
  --audio-codec=aac --record=downlink_test.m4a --time-limit=20
```

Then play `downlink_test.m4a`:
- **You hear the caller clearly:** this phone works.
- **Silence:** retry with `--audio-source=voice-call`. If it's still silent, try another phone. Results differ by manufacturer.
- **No phone works:** use the fallback of the phone on speaker and the laptop microphone.

### 4.5 Route the audio into Python

1. Open **Audio MIDI Setup** → **+** → **Create Multi-Output Device**.
2. Tick **the built-in speakers** (keep them first) and **BlackHole 2ch**. Enable **Drift Correction** on BlackHole and set the device to **48 kHz**.
3. Right-click the device → **Use This Device For Sound Output**.
4. During a call:
   ```bash
   scrcpy --no-video --no-control --audio-source=voice-call-downlink --audio-codec=aac --audio-buffer=200
   ```
   You hear the caller on the speakers, and the same sound goes into BlackHole for Python to read.

---

## 5. Codebase tour

```
Veracity/
├── README.md                    ← you are here
├── CODEBASE_GUIDE.md            deeper, file-by-file walkthrough with request flows
├── docker-compose.yml           backend + frontend containers (+ a hot-reload "dev" profile)
├── Claude outputs/
│   └── Veracity_Design_System.pdf   visual design spec for every screen
│
├── veracity-backend/            ── Python · FastAPI ──
│   ├── main.py                  creates the app, adds CORS, registers the routers
│   ├── requirements.txt         fastapi, uvicorn[standard], phonenumbers
│   ├── Dockerfile               Python 3.12 image (simulation / UI work only)
│   └── app/
│       ├── routes/              web layer: one file per group of URLs
│       │   ├── health.py        GET  /api/health          (Step 1)
│       │   └── number.py        POST /api/number/check    (Step 2)
│       ├── feature/             logic layer: plain Python, no web code
│       │   └── number_intelligence.py   phone-number facts via libphonenumber
│       └── data/                (empty) for SQLite community reports, calibration files
│
└── veracity-frontend/veracity/  ── React 19 · Vite 8 ──
    ├── vite.config.js           dev server :5173, proxies /api and /ws to :8000
    ├── nginx.conf.template      the same proxy for the Docker image
    ├── Dockerfile               stages: deps → dev | build → prod (nginx)
    └── src/
        ├── main.jsx             starts React, loads local fonts + global CSS
        ├── App.jsx              current step (1–4) and state shared between steps
        ├── api/                 talks to the backend (no React here)
        │   ├── client.js        fetch wrapper: timeouts, ApiError, wsUrl()
        │   ├── health.js        fetchHealth() + buildChecks() + FIX_COMMANDS
        │   └── number.js        checkNumber() + buildNumberRows()
        ├── hooks/               React state glue (loading / error / data)
        │   ├── useHealth.js     runs the health check, "Check again"
        │   └── useNumberCheck.js
        ├── pages/               one folder per screen
        │   ├── SetupPage/       Step 1
        │   └── NumberPage/      Step 2
        ├── components/
        │   ├── layout/          AppHeader, FlowSteps
        │   ├── setup/           SetupStep (one row of the system check)
        │   └── ui/              Button, Panel, AlertBanner, Toggle, Icon, Logo, CallStatus
        ├── constants/steps.js   the four steps
        └── styles/
            ├── tokens.css       every colour, size and spacing value
            └── base.css         resets + type scale (t-display, t-label, t-code…)
```

### Why it's split this way

**Backend: `routes/` vs `feature/`**
- `routes/` holds **web code only**. It reads the request (validated by Pydantic models), calls a feature, and turns errors into HTTP codes.
- `feature/` holds **pure logic** with no FastAPI imports. You can test it, or reuse it in the final report, without a server.

**Frontend: four layers**

| Layer | Job | Must not |
|---|---|---|
| `api/` | URLs, JSON shapes, turning JSON into display rows | import React |
| `hooks/` | loading / error / data state, cancelling stale requests | know URLs or layout |
| `pages/` | one full screen: what to show, when "Continue" is enabled | call `fetch` directly |
| `components/` | how one piece looks | know where data comes from |

If the backend renames a field, you only edit `api/`. If the design changes, you only edit `components/` and `styles/`.

**Why a proxy?** The frontend only uses relative URLs (`/api/health`). In development Vite forwards them to the backend, and in Docker nginx does. So the backend address is never hard-coded, and there are no CORS problems.

### Request flow example: Step 2

```
NumberPage.jsx         user types "+91 98765 43210" → "Check number"
 └ useNumberCheck.js   loading = true, cancels any older request
   └ api/number.js     POST /api/number/check {"number": "...", "region": "IN"}
     └ (Vite proxy)    → localhost:8000
       └ routes/number.py               Pydantic checks the body
         └ feature/number_intelligence.py   phonenumbers: parse, valid?, type, country, carrier, time zone
       ◄ JSON (or 422 if it isn't a phone number at all)
   └ buildNumberRows()  → "Line type: Mobile", "Original carrier: Airtel", …
 └ NumberPage renders the rows; an invalid number gets a caution banner
```

For every file explained in detail, see **[CODEBASE_GUIDE.md](CODEBASE_GUIDE.md)**.

---

## 6. API reference

Live, clickable docs: **http://localhost:8000/docs** (generated by FastAPI).

### `GET /api/health` — built

```json
{
  "status": "ok",
  "fake_mode": false,
  "port": 8000,
  "adb_found": true,
  "adb_devices": 1,
  "scrcpy_found": true,
  "scrcpy_version": "5.0.1",
  "audio_device": null,
  "audio_sample_rate": null,
  "models": {
    "voice":   { "id": "mo-thecreator/Deepfake-audio-detection", "ready": false },
    "whisper": { "id": "small", "ready": false },
    "llm":     { "id": "llama3.1:8b", "ready": false }
  }
}
```
`models.*.ready` is a placeholder until the TODO in `health.py` is done. `audio_device` is the input named by `VERA_AUDIO_DEVICE` (default `BlackHole 2ch`), or `null` if it isn't found. The frontend's "Continue" unlocks when every blocking check passes, or when `fake_mode` is `true`. A missing LLM is only a warning, because the rules still work without it.

### `POST /api/number/check` — built

Request:
```json
{ "number": "+91 98765 43210", "region": "IN" }
```
`region` is only used when the number has no `+country` code.

Response `200`:
```json
{
  "valid": true,
  "number_type": "MOBILE",
  "country": "India",
  "location": "India",
  "original_carrier": "Airtel",
  "is_international": false,
  "e164_format": "+919876543210",
  "national_digits": "9876543210",
  "timezones": ["Asia/Calcutta"]
}
```
Response `422`: `{"detail": "That doesn't look like a phone number."}`

`original_carrier` is the operator the number range was **first** issued to. The number may have been ported since.

### `GET /api/call/state` — built

Polled about once a second by Step 2. Reads `adb shell dumpsys telephony.registry` on the USB-connected phone.

```json
{ "connected": true, "state": "ringing", "number": "+919876543210" }
```
`state` is `idle`, `ringing` or `in_call`. `number` is `null` when there's no call, or when the phone hides it (common on Android 12+). Then the user types the number. When a number arrives, Step 2 fills it in and runs `POST /api/number/check` automatically.

### Planned (from the project document)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/number/report` | `{number, category, note}` → add a community report |
| POST | `/api/session/start` | `{caller_number}` → `session_id`, starts capture + analysis |
| POST | `/api/session/{id}/stop` | stops capture, returns and saves the JSON report |
| GET | `/api/report/{id}` | the finished report |
| WS | `/ws/live/{id}` | stream of live events (below) |

Live WebSocket events:

| `type` | Fields | Dashboard reaction |
|---|---|---|
| `level` | `t, dbfs` | input level meter |
| `voice` | `t, p_ai, smoothed, state, speech` | big %, state badge, chart point |
| `transcript` | `t, text` | transcript line |
| `flag` | `category, severity, evidence, t, source` | red-flag list |
| `script` | `score` | script score meter |
| `alert` | `kind, message` | red alert banner |
| `report` | `report` | report screen |
| `ended` | — | close the socket |

> The project document calls the number endpoint `/api/number/analyze`. The code uses `/api/number/check`. Keep `/check` unless the team agrees to rename it in both places.

---

## 7. How to add a feature

Follow the same pattern every time:

**Backend**
1. Put the logic in `app/feature/<name>.py`, as plain functions with no FastAPI imports.
2. Put the URL in `app/routes/<name>.py`: an `APIRouter`, Pydantic request and response models, and errors raised as `HTTPException`.
3. Register it in `main.py` with `app.include_router(<name>.router)`.
4. Add any new package to `requirements.txt`.

**Frontend**
1. Add `src/api/<name>.js`: the call (through `apiRequest`), the JSON shape documented in a comment at the top, and a pure `build…Rows()` helper if needed.
2. Add `src/hooks/use<Name>.js` for loading / error / data state, using an `AbortController` like the existing hooks.
3. Build the screen in `src/pages/<Name>Page/` from components in `src/components/`.
4. Take every colour and size from `src/styles/tokens.css`. Never hard-code a hex value.

**Where the planned features go**

| Feature | Backend | Frontend |
|---|---|---|
| Model checks | `routes/health.py` (the TODO) | nothing, already handled |
| Simulation events | `feature/fakes.py` (when `VERA_FAKE=1`) | — |
| Rule score, 1600/140 series, community reports | `feature/number_intelligence.py`, `feature/reports_db.py` (SQLite in `app/data/`) | `api/number.js` → `buildNumberRows` |
| Number ML % | `feature/number_model.py` | number card |
| Audio capture | `feature/audio_sources.py` | — |
| AI-voice score | `feature/voice.py` | `components/live/ScoreMeter`, `ScoreTimeline` |
| Transcription + scam rules + LLM | `feature/transcriber.py`, `scam_rules.py`, `scam_llm.py` | `components/live/Transcript`, `RedFlag` |
| Live session + WebSocket | `routes/session.py` | `api/session.js`, `hooks/useLiveSession.js`, `pages/LivePage/` |
| Report + fusion | `feature/report.py` | `pages/ReportPage/` |

### Git workflow

```bash
git checkout -b feature/scam-rules     # one branch per feature
# ...work, commit...
git push -u origin feature/scam-rules  # then open a pull request into main
```

---

## 8. Rules we follow

These come from the project document and the design system. Please keep them.

**Product honesty**
- **No external APIs at runtime.** Models are downloaded once, and then everything works with Wi-Fi off.
- **Privacy by default.** Audio is processed in memory and only saved if the user turns it on. Then the report stores its SHA-256.
- **Never quote numbers we didn't measure.** That includes the voice model card's "98.82% accuracy". Measure our own accuracy on our own recordings.
- The AI-voice % is *"a calibrated model estimate, not proof"*. Say "Likely AI", never "Confirmed fake".
- The number ML model is trained on **synthetic data**. Always label it so.

**UI**
- Use calm, plain language. Second person, sentence case, no emoji, no exclamation marks.
- **Never use colour alone.** Every status pairs a colour with a shape and a word.
- **One primary button per screen**, and **at most one banner per screen**.
- Anything the user may read back exactly (phone numbers, %, times, JSON) is set in the mono font (`t-code`).
- Show the backend's voice `state`. Never work it out in the browser.

**Code**
- Logic goes in `feature/`, URLs in `routes/`. In the frontend: `api/` → `hooks/` → `pages/` → `components/`.
- Write short comments that explain *why*, matching the existing files.
- Run `npm run lint` in the frontend before pushing.

---

## 9. Troubleshooting

| Problem | Fix |
|---|---|
| Step 1 says **"adb wasn't found"** / **"scrcpy wasn't found"** | The backend is running in Docker, or the tools aren't installed. Run the backend locally ([§3 Option A](#option-a--run-locally-recommended-and-required-for-a-real-phone)) and check `which adb scrcpy`. |
| Step 1 says **"No phone found"** | Run `adb devices`. If it's empty, replug the cable, set USB mode to *File transfer*, turn USB debugging off and on again, or try another cable. If it says `unauthorized`, accept the prompt on the phone. |
| **"Can't reach the backend"** | Start the backend on port 8000 and check http://localhost:8000. |
| **`address already in use`** / **`ports are not available`** | Another copy is running, often Docker. Run `docker compose stop`, or find the process with `lsof -nP -iTCP:8000 -sTCP:LISTEN` (or `:5173`) and stop it. |
| **`npm error Missing script: "dev"`** | You're in the wrong folder. Run npm inside `veracity-frontend/veracity`. |
| **`uvicorn: command not found`** | The virtual environment isn't active. Run `source venv/bin/activate`. |
| **`ModuleNotFoundError: phonenumbers`** | Run `pip install -r requirements.txt` inside the active venv. |
| **502 Bad Gateway** from the Docker frontend | The backend it points at isn't running (yet). Wait a few seconds or start it. |
| **BlackHole 2ch** isn't listed in Audio MIDI Setup | Restart the Mac after `brew install blackhole-2ch`. |
| **`Cannot connect to the Docker daemon`** | Start Docker Desktop. |
| torch / faster-whisper fail to install | Recreate the venv with Python 3.12: `rm -rf venv && python3.12 -m venv venv`. |

---

## 10. Limitations

- **Spoofing:** Veracity checks the caller ID the network shows. It **cannot** reveal the real number behind a spoofed call or locate the caller. Only operators and police can, with legal process.
- **Not proof:** the AI-voice % is a calibrated estimate meant to warn the user. It is not legal proof.
- **Phone support varies:** whether call audio reaches scrcpy depends on the phone manufacturer.
- **Needs a laptop and cable today:** a normal Android app can't capture call audio without system privileges.

---

## 11. Further reading

| Document | What's in it |
|---|---|
| [CODEBASE_GUIDE.md](CODEBASE_GUIDE.md) | Every file explained, request flows, how phone detection works |
| `Claude outputs/Veracity_Design_System.pdf` | Colours, type, every screen and component |
| *Veracity Project Document v1.1* (shared by the team) | Full feature specs, thresholds, tech stack versions, pitch, team plan |
| [veracity-frontend/veracity/README.md](veracity-frontend/veracity/README.md) | Frontend-only notes |
