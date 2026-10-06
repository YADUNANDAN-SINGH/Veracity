# Veracity

**Live AI-voice & scam-call detection for normal phone calls.**

Veracity is a real-time, fully offline pipeline that listens to an active cellular call on an Android phone and instantly evaluates the likelihood of AI-generated audio, known scam-script patterns, and caller ID risk. It equips users with a live dashboard and generates a ready-to-file JSON evidence report for authorities (1930 / cybercrime.gov.in / Chakshu). 

Built for **Hackathon 2026**.

## 🚀 Key Features

1. **Number Intelligence** 
   Cross-references the caller's number against numbering-plan rules (e.g., India's 1600 regulated and 140 telemarketing series), community reports, and an explainable scikit-learn logistic regression model to flag high-risk numbers.
2. **Live AI-Voice Detection** 
   Captures downlink call audio via USB and scores 4-second windows through a calibrated `wav2vec2` deepfake detection model. The dashboard updates every second, applying an exponential moving average to prevent false alarms before shifting to a `LIKELY_AI` state.
3. **Scam-Script Detection** 
   Transcribes the call locally using `faster-whisper`. The text is routed through a dual-layer engine: a deterministic rule engine for high-risk keywords (English, Hinglish, Devanagari) and a local `llama3.1:8b` LLM generating structured JSON outputs to identify pressure tactics (e.g., "digital arrest").
4. **Actionable Evidence Reporting** 
   Generates a structured JSON red-flag report containing timestamped quotes, model confidence scores, and raw metadata to streamline official cybercrime reporting.

## 🛠 Tech Stack

**Privacy First:** Veracity is entirely offline at runtime. No cloud APIs are pinged during a call, and audio is processed in memory without being saved to disk (unless explicitly enabled by the user).

*   **Frontend:** React, Vite, Recharts, Tailwind CSS
*   **Backend:** Python, FastAPI, WebSockets, SQLite
*   **Audio Pipeline:** `scrcpy` (Android USB audio capture), BlackHole 2ch (virtual routing), `sounddevice`
*   **Machine Learning / AI:**
    *   `faster-whisper` (Speech-to-text, int8 CPU)
    *   `transformers` / `mo-thecreator/Deepfake-audio-detection` (94.6M param wav2vec2)
    *   `Ollama` running `llama3.1:8b` (Structured JSON generation)
    *   `scikit-learn` (Logistic regression for number scoring)
    *   `libphonenumber` (Telecom metadata)

## 🏗 Architecture Overview

1. An Android 11+ phone routes call audio (downlink only) to the host machine via `scrcpy` over an ADB USB connection.
2. A macOS Multi-Output Device splits the audio to the speakers (for the user to hear) and a virtual cable (BlackHole 2ch).
3. The Python backend reads the virtual cable at 48 kHz, resamples to 16 kHz, and runs continuous parallel pipelines for voice analysis and transcription.
4. FastAPI pushes live metrics, transcriptions, and alerts to the React dashboard via WebSockets.

## 💻 Getting Started

### Prerequisites

Install these first:

*   [Git](https://git-scm.com/downloads)
*   [Node.js](https://nodejs.org/) 20.19+ (includes `npm`)
*   [Python](https://www.python.org/downloads/) 3.10+ (on Windows, tick **"Add Python to PATH"** during install)

### 1. Clone the repository

**macOS (Terminal) / Windows (PowerShell or Command Prompt):**

```bash
git clone https://github.com/YADUNANDAN-SINGH/Veracity.git
cd Veracity
```

The project layout:

```text
Veracity/
├── veracity-backend/        # FastAPI server (main.py)
└── veracity-frontend/
    └── veracity/            # React + Vite app (package.json lives here)
```

### 2. Run the backend

Open a terminal in the `Veracity` folder.

**macOS:**

```bash
cd veracity-backend
python3 -m venv venv
source venv/bin/activate
pip install fastapi uvicorn
uvicorn main:app --reload
```

**Windows (PowerShell):**

```powershell
cd veracity-backend
python -m venv venv
venv\Scripts\Activate.ps1
pip install fastapi uvicorn
uvicorn main:app --reload
```

> If PowerShell says running scripts is disabled, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, then try activating again. In Command Prompt, use `venv\Scripts\activate.bat` instead.

The backend runs at **<http://localhost:8000>**. Opening it should return `{"message": "Backend is ready!"}`.

On later runs, you only need to activate the virtual environment and run `uvicorn main:app --reload`.

### 3. Run the frontend

Open a **second** terminal in the `Veracity` folder and leave the backend running.

**macOS / Windows (same commands):**

```bash
cd veracity-frontend/veracity
npm install
npm run dev
```

The frontend runs at **<http://localhost:5173>**. It should show the welcome text and the message from the backend.

On later runs, you only need `npm run dev` from inside `veracity-frontend/veracity`.

### Troubleshooting

*   **`npm error Missing script: "dev"`**: you are in the wrong folder. `npm` commands must be run inside `veracity-frontend/veracity`, the folder that contains `package.json`.
*   **Blank page or no backend message**: make sure the backend is running on port 8000, then open the browser DevTools Console to see the error.
*   **`uvicorn: command not found`**: the virtual environment isn't active. Activate it (step 2) and try again.
*   **Port already in use**: another copy of the server is already running. Stop it with `Ctrl + C` in its terminal.

## ⚠️ Limitations & Scope
*   **Spoofing:** Veracity evaluates the caller ID presented by the telecom network. It cannot unmask the "true" number behind a spoofed call, nor can it track physical location.
*   **Not Proof:** The AI-voice percentage is a calibrated machine learning estimate designed to protect users, not definitive legal proof.
