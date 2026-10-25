# Veracity dashboard (frontend)

React + Vite dashboard for Veracity. It follows the *Veracity Design System & Front-end Spec v1* and the API in *Project Document v1.1 §1.8*.

## Folder structure

```text
veracity/
├── Dockerfile               # multi-stage: dev (hot reload) · build · prod (nginx)
├── nginx.conf.template      # prod: serves dist/, proxies /api + /ws to FastAPI
├── vite.config.js           # dev: proxies /api + /ws to FastAPI (:8000)
├── index.html
├── public/favicon.svg       # the Veracity mark
└── src/
    ├── main.jsx             # entry: fonts + global styles + <App/>
    ├── App.jsx              # shell: current step, shared state, header + page
    ├── api/                 # one module per backend area; no React in here
    │   ├── client.js        # fetch wrapper (timeouts, ApiError), wsUrl()
    │   └── health.js        # GET /api/health + buildChecks() + fix commands
    ├── hooks/
    │   └── useHealth.js     # loads health, "Check again"
    ├── constants/
    │   └── steps.js         # the four flow steps
    ├── styles/
    │   ├── tokens.css       # colours, type, spacing, radii (design system §2)
    │   └── base.css         # resets, type scale classes, focus ring
    ├── components/
    │   ├── layout/          # AppHeader, FlowSteps
    │   ├── ui/              # Button, Panel, AlertBanner, Toggle, Icon, Logo, CallStatus
    │   └── setup/           # SetupStep
    └── pages/
        └── SetupPage/       # Step 1 · Check setup (home page)
```

Planned next, in the same pattern:

```text
src/api/number.js, session.js, report.js
src/hooks/useLiveSession.js           # WebSocket /ws/live/{id} → screen state
src/components/number/   NumberCard, RiskBadge
src/components/live/     ScoreMeter, ScoreTimeline (Recharts), LevelMeter, Transcript, RedFlag
src/components/report/   RiskSummary
src/pages/NumberPage/ · LivePage/ · ReportPage/
src/utils/phone.js                    # +917045618823 → +91 70456 18823
```

Each component keeps its CSS next to it, and every value comes from `styles/tokens.css`.

## Run locally

```bash
npm install
npm run dev        # http://localhost:5173, proxies /api and /ws to localhost:8000
npm run build      # production bundle in dist/
npm run lint
```

You don't need a phone to work on the UI. Start the backend in simulation mode with `VERA_FAKE=1 uvicorn app.main:app --port 8000`.

## Docker

Run these from the repo root:

```bash
# Production-style: nginx on http://localhost:5173
docker compose up --build

# Hot reload while editing src/: http://localhost:5174
docker compose --profile dev up --build backend frontend-dev
```

The app only calls relative URLs (`/api/...`, `/ws/...`). In dev the Vite proxy forwards them, and in Docker nginx does, so you never need to bake a backend URL into the bundle. To point at a different backend, change `BACKEND_URL` (prod) or `VITE_BACKEND_URL` (dev) in `docker-compose.yml`.

Note: real call capture needs USB, scrcpy and BlackHole on the Mac itself, so a Dockerised backend is only useful in simulation mode.

## API contract: `GET /api/health`

This is what the Step 1 page expects. Field names follow Project Document §3.1.

```json
{
  "status": "ok",
  "fake_mode": false,
  "port": 8000,
  "adb_found": true,
  "adb_devices": 1,
  "scrcpy_found": true,
  "scrcpy_version": "4.1",
  "audio_device": "BlackHole 2ch",
  "audio_sample_rate": 48000,
  "models": {
    "voice":   { "id": "mo-thecreator/Deepfake-audio-detection", "ready": true },
    "whisper": { "id": "small", "ready": true },
    "llm":     { "id": "llama3.1:8b", "ready": true }
  }
}
```

- "Continue" unlocks when the backend, adb, scrcpy, audio, voice model and Whisper checks all pass, or when `fake_mode` is `true`.
- A missing LLM shows as a warning, not a blocker, because the rule engine still works without it.
- If the response shape changes, update `buildChecks()` in `src/api/health.js`. That is the only place that reads it.
