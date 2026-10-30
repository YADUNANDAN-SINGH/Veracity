# Veracity — Codebase Guide

What every file does, why it lives where it does, and how a click on the dashboard turns into an answer. This describes the code **as of 27 Oct 2026** (commit `1466937`). Update it whenever you add a feature.

---

## 1. The big picture

There are two programs. They talk to each other over HTTP.

```
┌──────────────────────────┐   HTTP (JSON)    ┌───────────────────────────┐   shell commands   ┌──────────────┐
│  FRONTEND (React)        │ ───────────────► │  BACKEND (FastAPI/Python) │ ─────────────────► │ adb, scrcpy  │
│  veracity-frontend/      │ ◄─────────────── │  veracity-backend/        │ ◄───────────────── │ phonenumbers │
│  runs in your browser    │                  │  runs on port 8000        │                    │ (Mac tools)  │
└──────────────────────────┘                  └───────────────────────────┘                    └──────────────┘
        localhost:5173
```

- **Frontend**: only draws screens. It knows nothing about phones or numbers. It asks the backend and shows what comes back.
- **Backend**: does the real work. It runs `adb`, `scrcpy` and the phone-number library on the Mac, and replies with JSON.
- **The rule**: the browser never talks to the phone directly. Everything goes browser → backend → Mac tools.

### What's built so far

| Dashboard step | Frontend | Backend endpoint | Status |
|---|---|---|---|
| 1 · Check setup | `SetupPage` | `GET /api/health` | ✅ adb + scrcpy really checked · ⏳ audio and models hard-coded "not ready" |
| 2 · Check number | `NumberPage` | `POST /api/number/check` | ✅ libphonenumber facts · ⏳ no rule score / ML / community reports yet |
| 3 · Live call | placeholder (`ComingNext`) | — | ❌ not built (WebSocket, voice model, Whisper) |
| 4 · Report | placeholder | — | ❌ not built |

---

## 2. Folder map

```
Veracity/
├── README.md                    project overview + setup instructions
├── CODEBASE_GUIDE.md            this file
├── docker-compose.yml           starts backend + frontend containers together
│
├── veracity-backend/            ── PYTHON / FASTAPI ──
│   ├── main.py                  entry point: creates the app, plugs in the routes
│   ├── requirements.txt         Python packages (fastapi, uvicorn, phonenumbers)
│   ├── Dockerfile               how to build the backend container
│   ├── venv/                    your local Python environment (kept out of the Docker image)
│   └── app/
│       ├── routes/              "doors": one file per group of URLs
│       │   ├── health.py        GET  /api/health        → Step 1
│       │   └── number.py        POST /api/number/check  → Step 2
│       └── feature/             "brains": the actual logic, no web code
│           └── number_intelligence.py   phone-number lookup with libphonenumber
│
└── veracity-frontend/veracity/  ── REACT / VITE ──
    ├── index.html               the single HTML page; React mounts into <div id="root">
    ├── vite.config.js           dev server + proxy /api → backend
    ├── nginx.conf.template      Docker version of the same proxy
    ├── Dockerfile               dev / build / prod (nginx) images
    ├── package.json             JS dependencies and npm scripts
    └── src/
        ├── main.jsx             starts React, loads fonts + global CSS
        ├── App.jsx              which step is showing; holds shared state
        ├── api/                 talking to the backend (no React here)
        │   ├── client.js        fetch wrapper used by every API call
        │   ├── health.js        /api/health call + turns JSON into check rows
        │   └── number.js        /api/number/check call + turns JSON into fact rows
        ├── hooks/               React glue: loading / error / data state
        │   ├── useHealth.js
        │   └── useNumberCheck.js
        ├── pages/               one folder per full screen
        │   ├── SetupPage/       Step 1
        │   └── NumberPage/      Step 2
        ├── components/
        │   ├── layout/          AppHeader, FlowSteps (top bar + 1-2-3-4 progress)
        │   ├── setup/           SetupStep (one row of the system check)
        │   └── ui/              reusable building blocks: Button, Panel, AlertBanner, Toggle, Icon, Logo, CallStatus
        ├── constants/steps.js   the list of 4 steps
        └── styles/
            ├── tokens.css       every colour / size / spacing variable
            └── base.css         global element styles + type scale
```

### Why it's split this way

**Backend: `routes/` vs `feature/`**
- `routes/` holds web code only. It reads the request, calls a feature and turns errors into HTTP status codes.
- `feature/` holds pure Python logic. It has no FastAPI imports, so you can test it or reuse it (for example in the final report) without a web server.
- When you add the voice model, it goes in `app/feature/voice.py`, and its URL goes in `app/routes/session.py`.

**Frontend: `api/` → `hooks/` → `pages/` → `components/`**

| Layer | Knows about | Doesn't know about |
|---|---|---|
| `api/` | URLs, JSON shapes, how to turn JSON into display rows | React, screens |
| `hooks/` | React state (loading / error / data), cancelling old requests | URLs, layout |
| `pages/` | One whole screen: what to show, when to enable "Continue" | fetch, URLs |
| `components/` | How one piece looks (button, row, card) | where data comes from |

If the backend changes a field name, you only edit `api/`. If the design changes, you only edit `components/` and `styles/`.

---

## 3. How it knows your phone is connected (step by step)

This is the full path when you open the dashboard or click **Check again**:

```
 Browser                        Proxy                    Backend (Python)                    Mac / phone
 ───────                        ─────                    ────────────────                    ───────────
 App.jsx calls useHealth()
   └► useHealth.js: load()
        └► api/health.js: fetchHealth()
             └► api/client.js: fetch('/api/health')
                     │
                     ▼
              Vite (npm run dev)
              or nginx (Docker)
              forwards to :8000
                     │
                     ▼
                                       main.py → routes/health.py: health()
                                         1. shutil.which("adb")   ─────────────► is there an `adb` program on PATH?
                                                                                  (/opt/homebrew/bin/adb)
                                         2. _adb_device_count()
                                            runs `adb devices`    ─────────────► adb server (port 5037) asks USB:
                                                                                  "EIPNLJZXM7GIVKXG	device"
                                            counts lines ending in "\tdevice"
                                         3. shutil.which("scrcpy")
                                            + `scrcpy --version` → "5.0.1"
                                         4. returns JSON
                     ◄───────────────────────────────────────────
 {"adb_found": true, "adb_devices": 1, "scrcpy_found": true, ...}
        │
        ▼
 api/health.js: buildChecks()
   adb_found && adb_devices > 0  → row "Phone over adb" = ok ✓
   else if adb_found              → "No phone found…"   (fix: adb devices)
   else                           → "adb wasn't found…" (fix: brew install …)
        │
        ▼
 SetupPage.jsx renders one <SetupStep> per row
 "Continue" is enabled only if no blocking row is "fail" (or simulation mode is on)
```

### The key code

[`veracity-backend/app/routes/health.py`](veracity-backend/app/routes/health.py):

```python
def _adb_device_count() -> int:
    out = _run(["adb", "devices"]) or ""
    # Lines after the header look like "<serial>\tdevice"; skip "unauthorized" / "offline"
    return sum(1 for line in out.splitlines()[1:] if line.strip().endswith("\tdevice"))
```

`adb devices` prints something like:

```
List of devices attached          ← header, skipped by [1:]
EIPNLJZXM7GIVKXG	device         ← counted ✓
ABC123	unauthorized               ← NOT counted (you haven't tapped "Allow" on the phone)
```

So the dashboard's "phone connected" means exactly this: **`adb devices` on the machine running the backend lists at least one phone as `device`.**

### Why it showed "not connected" earlier

| What you saw | Real cause |
|---|---|
| "adb wasn't found" + "scrcpy wasn't found" | The backend was running **inside Docker**. The container is a small Linux box with no adb/scrcpy installed, and Docker on a Mac cannot see USB devices at all. |
| "No phone found" (adb found) | The backend was on the Mac, but `adb devices` was empty. The phone had dropped off USB (cable, USB mode set to "Charging only", or the debugging prompt not accepted). |

**Rule of thumb:** whenever the dashboard disagrees with you, run `adb devices` in a terminal on the Mac. The dashboard can never know more than that command does.

---

## 4. How a number check works (Step 2)

```
NumberPage.jsx  (user types "+91 98765 43210", presses "Check number")
  └► useNumberCheck.js: check(number)          sets loading=true, cancels any older check
       └► api/number.js: checkNumber()
            └► POST /api/number/check  {"number": "+91 98765 43210", "region": "IN"}
                 └► routes/number.py: check_number()
                      • Pydantic NumberCheckRequest validates the body (1–32 chars, 2-letter region)
                      └► feature/number_intelligence.py: get_number_details()
                           pn.parse()            → can't parse → InvalidNumberError → HTTP 422
                           pn.is_valid_number()  → valid?
                           number_type()         → "MOBILE", "FIXED_LINE", …
                           geocoder              → country, location ("India", circle/state)
                           carrier               → ORIGINAL operator (may have been ported since)
                           timezone              → ["Asia/Calcutta"]
                      • NumberCheckResponse checks the reply has exactly these fields
            ◄── JSON
       api/number.js: buildNumberRows() → label/value rows ("Line type: Mobile", …)
  NumberPage shows the rows; an invalid number gets a caution banner
```

Everything here is **offline**. `phonenumbers` ships Google's numbering-plan data inside the Python package, and nothing is looked up on the internet.

---

## 5. File-by-file reference

### Backend

| File | Role | Why it's here |
|---|---|---|
| `main.py` | Creates `app = FastAPI()`, adds CORS, registers the routers from `health.py` and `number.py`. `GET /` returns "Backend is ready!". | `uvicorn main:app` looks for `app` in `main.py`. This is the one place where all routes are plugged in. |
| `app/routes/health.py` | `GET /api/health`. Uses `shutil.which` to see if adb/scrcpy exist, runs `adb devices` and `scrcpy --version` with a 3-second timeout, and reports audio and models (hard-coded for now). | Powers Step 1. `_run()` swallows errors so a missing tool shows up as `false` instead of crashing the endpoint. |
| `app/routes/number.py` | `POST /api/number/check`. Pydantic models define the request and response shapes, and `InvalidNumberError` becomes HTTP 422. | Keeps the web code separate from the number logic. |
| `app/feature/number_intelligence.py` | `get_number_details(raw, region)` returns a dict of facts. The top of the file holds old test code in `'''` comments. | Pure logic, reusable by the future report builder. |
| `app/__init__.py`, `routes/__init__.py`, `feature/__init__.py` | Empty. | Tell Python these folders are packages, so `from app.routes import health` works. |
| `requirements.txt` | `fastapi`, `uvicorn[standard]`, `phonenumbers`. | `pip install -r requirements.txt` (venv and Docker). |
| `Dockerfile` | Python 3.12 image, installs requirements, runs uvicorn on 0.0.0.0:8000. | For teammates without a phone (simulation mode). **Cannot see USB**, so you can't use it for real calls. |
| `.dockerignore` | Keeps `venv/` and `__pycache__/` out of the image. | Smaller, cleaner builds. |

### Frontend — plumbing

| File | Role |
|---|---|
| `index.html` | The only HTML page. React fills `<div id="root">`. |
| `src/main.jsx` | Starts React, imports the fonts locally (works offline) and `base.css`. |
| `src/App.jsx` | Holds `step` (1–4), `saveAudio`, and the shared hooks `useHealth()` and `useNumberCheck()`. Picks which page to render. Steps 3–4 show `ComingNext`. |
| `vite.config.js` | Dev server on 5173. **Proxy**: `/api` and `/ws` go to `VITE_BACKEND_URL` or `http://localhost:8000`. |
| `nginx.conf.template` | The same proxy for the Docker (prod) image, using `${BACKEND_URL}`. Also serves the built files and falls back to `index.html`. |
| `Dockerfile` | Multi-stage: `deps` → `dev` (Vite hot reload) / `build` → `prod` (nginx on :80). |
| `package.json` | React 19, Vite 8, oxlint. Scripts: `dev`, `build`, `lint`, `preview`. |
| `.oxlintrc.json` | Lint rules (React hooks rules). |

**Why a proxy?** The page uses relative URLs like `/api/health`. The browser sends them to whoever served the page (Vite or nginx on :5173), and that forwards them to the backend. So the frontend never hard-codes the backend's address and there are no CORS problems. This is also why the Docker frontend can point at a Mac backend with only `BACKEND_URL=http://host.docker.internal:8000`.

### Frontend — `api/`

| File | Role |
|---|---|
| `client.js` | `apiRequest(path, options)`: a fetch with a 5-second timeout, cancel support, and a single `ApiError` type (`status: null` means the backend is unreachable). `wsUrl()` is ready for the Step 3 WebSocket. |
| `health.js` | `fetchHealth()`. `FIX_COMMANDS`: the exact commands shown in the "Fix this" chips. `buildChecks(health, {loading, error})`: **the decision logic** for each row's ok / fail / warn. The response shape is documented at the top. |
| `number.js` | `checkNumber()`. `TYPE_LABELS` turns "FIXED_LINE" into "Landline". `buildNumberRows()` turns the JSON into display rows and hides "Area" when it only repeats the country. |

### Frontend — `hooks/`

| File | Role |
|---|---|
| `useHealth.js` | Runs the health check on page load. `recheck()` is the "Check again" button. Uses an `AbortController` so a slow old response can't overwrite a newer one. |
| `useNumberCheck.js` | `check(number)` runs a lookup and cancels the previous one. It lives in `App`, so the result survives going back a step. |

### Frontend — `pages/` and `components/`

| File | Role |
|---|---|
| `pages/SetupPage/SetupPage.jsx` | Step 1 screen: the System check panel, the "No phone handy?" or simulation banner, the Privacy toggle, and Continue. Continue = not loading, no error, and (simulation **or** no failing blocking checks). |
| `pages/NumberPage/NumberPage.jsx` | Step 2 screen: the number form, error and invalid-number banners, the facts list, and Back / Continue (unlocked after any result, valid or not). |
| `components/setup/SetupStep.jsx` | One check row. Every status pairs a colour with a shape and a word ("OK", "Fix this"), for accessibility. |
| `components/layout/AppHeader.jsx` | Top bar: logo, steps, the SIMULATION MODE tag, "Offline", and the call status pill. |
| `components/layout/FlowSteps.jsx` | The 1-2-3-4 progress, driven by `constants/steps.js`. |
| `components/ui/*` | Design-system building blocks: `Button`, `Panel` (white card), `AlertBanner` (one per screen), `Toggle`, `Icon` (inline SVG paths), `Logo`, `CallStatus`. Each has a matching `.css` file. |
| `styles/tokens.css` | All colours, spacing and radii as CSS variables, including risk colours (`--risk-*`, `-soft`, `-fill`). Change the look here. |
| `styles/base.css` | Global resets and the type scale (`t-display`, `t-label`, `t-code`…). |

---

## 6. Ways to run it

| Setup | Commands | Phone detected? | Use it for |
|---|---|---|---|
| **Everything on the Mac** | `cd veracity-backend && source venv/bin/activate && uvicorn main:app --port 8000`<br>`cd veracity-frontend/veracity && npm run dev` | ✅ | Real phone work, debugging |
| **Mac backend + Docker frontend** | `cd veracity-backend && source venv/bin/activate && uvicorn main:app --host 0.0.0.0 --port 8000`<br>`BACKEND_URL=http://host.docker.internal:8000 docker compose up -d --no-deps frontend` | ✅ | Real phone, prod-style frontend |
| **All Docker** | `docker compose up --build` | ❌ (no USB in Docker) | Frontend work, simulation mode |

Only one backend and one frontend can run at a time, because they share ports **8000** and **5173**. If you see `address already in use`, run `lsof -nP -iTCP:5173 -sTCP:LISTEN` to find out what's holding the port.

---

## 7. Where new code should go

| Next feature (from the project doc) | Backend | Frontend |
|---|---|---|
| Detect BlackHole + sample rate | `health.py` (replace the TODO): `sounddevice.query_devices()` | nothing; `buildChecks` already handles `audio_device` |
| Model "ready" flags | `health.py` TODO: check the HF / faster-whisper caches, ping Ollama | nothing |
| Simulation mode | `app/feature/fakes.py`, switched on by `VERA_FAKE=1` | already reads `fake_mode` |
| Rule score + ML % for numbers | `app/feature/number_model.py`, `app/feature/reports_db.py` (SQLite) | add fields to `api/number.js` → `buildNumberRows` |
| Live call | `app/feature/audio_sources.py`, `voice.py`, `transcriber.py`, `scam_rules.py`, `scam_llm.py`; `app/routes/session.py` with `POST /api/session/start`, `/stop` and `WS /ws/live/{id}` | `api/session.js`, `hooks/useLiveSession.js`, `pages/LivePage/` |
| JSON report | `app/feature/report.py` (Pydantic schema + fusion) | `pages/ReportPage/` |

A pattern to keep: **logic in `feature/`, URL in `routes/`, register the router in `main.py`, JSON shape documented at the top of the matching `src/api/*.js`.**

---

## 8. Things to know / tidy up

- **The endpoint name differs from the project doc.** The doc says `POST /api/number/analyze`, but the code uses `/api/number/check`. Pick one before teammates build on it.
- **Python version.** The venv is 3.13 and Docker uses 3.12. The doc recommends 3.11 or 3.12 for torch / faster-whisper, so expect install trouble on 3.13.
- **Committed junk.** `__pycache__/*.pyc`, `.DS_Store` and `.idea/` are in git. Add them to `.gitignore` and `git rm --cached` them.
- **Commented-out code.** The top of `number_intelligence.py` has two `'''` blocks of old code that can be deleted.
- **CORS `allow_origins=["*"]`** in `main.py` is fine for a local-only demo. The proxy makes it mostly unnecessary anyway.
