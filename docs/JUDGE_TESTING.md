# Veracity: 2-Minute Judge Runbook

Veracity hears scam calls as they happen. If the caller asks for money, PayPal holds it until the call checks out. This page is all you need to run and judge it.

## Why Local Docker (No Hosted URL)

Veracity's privacy guarantee keeps all call audio, transcripts and AI scoring on-device (only payment state touches PayPal's API), and live Android call capture requires local `adb` + `scrcpy` + `BlackHole`. The `judge` Docker profile lets you test the entire AI + PayPal Orders v2 / Payments v2 pipeline in one command, without an Android phone.

## Quick Start (One Command)

**You need** Docker Desktop (or Docker Engine with Compose 2.24 or newer) on amd64 or arm64, at least **6 GB of memory** for Docker (Docker Desktop → Settings → Resources) and about **10 GB of free disk**.

**1. Get the code and choose how PayPal runs.**

```bash
git clone https://github.com/YADUNANDAN-SINGH/Veracity.git && cd Veracity
cp .env.example .env
```

For live PayPal Sandbox checkout, paste a sandbox app's keys into `.env`. [PAYPAL_SETUP.md](PAYPAL_SETUP.md), steps 1 and 2, gets you keys and a buyer login in about 15 minutes.

```bash
PAYPAL_CLIENT_ID=...
PAYPAL_CLIENT_SECRET=...
```

No keys? Leave them empty, or skip this step entirely. A built-in in-memory stand-in lets you walk the whole flow:

| | Sandbox keys in `.env` | No keys: the built-in stand-in |
| --- | --- | --- |
| **Who answers** | PayPal's sandbox, `api-m.sandbox.paypal.com` | Local memory. Nothing reaches PayPal |
| **API calls** | Orders v2 and Payments v2 | The same calls, through the same client code |
| **To approve** | The PayPal button, then log in as the sandbox buyer (see the Devpost testing instructions) | **Approve with the PayPal stand-in**, with no pop-up or login |
| **Ids and `debug_id`s** | PayPal's own; look them up in the sandbox | Made up, and start with `STANDIN-` or `standin-` |

The stand-in labels itself on every screen and in the report (`paypal.environment: "standin"`). It shows how Veracity drives PayPal; only sandbox keys prove it against PayPal.

**2. Build and start.**

```bash
docker compose --profile judge up --build judge
```

The first build takes 8 to 12 minutes (measured on an Apple M5; a slower connection or CPU takes longer). There's nothing else to build or download: the dashboard, the Spectra-0 and Whisper *small* weights, ffmpeg and the sample audio are all in the image, and the build's last step proves the models run with the network off. Later starts are ready in under 30 seconds.

**3. Open <http://localhost:8000>.**

To stop: Ctrl+C, then `docker compose --profile judge down`.

## 3-Minute Evaluation Walkthrough (Step-by-Step)

Run the three tests in order. Each call takes under a minute.

### Test 1: Scam Call → PayPal `AUTHORIZE` → Held by Veracity → `VOID` (Cancelled)

| # | Click | What you see | API call |
| --- | --- | --- | --- |
| 1 | **Pick a sample call** → **"Grandma, it's me": a grandparent scam** → **Start the call** | The transcript and red flags build line by line | |
| 2 | In **Protected Send** (already filled in, $2,400): the PayPal button, or **Approve with the PayPal stand-in** | The money is authorized, not sent | `POST /v2/checkout/orders` with `intent: AUTHORIZE`, then `POST /v2/checkout/orders/{id}/authorize` |
| 3 | Scroll to the card at the top | **Held**, with the caller's words as timestamped quotes. It reads *likely scam* once the words match a known script | |
| 4 | **End call & build report**, then on the card **Jake didn't ask: cancel** | *"Cancelled. The money never left your account."* | `POST /v2/payments/authorizations/{id}/void` |
| 5 | **Details** on the card | Every API call with its HTTP status and `debug_id` | |

### Test 2: Legitimate Call → PayPal `AUTHORIZE` → `CAPTURE` (Released)

| # | Click | What you see | API call |
| --- | --- | --- | --- |
| 1 | **See report** → **Check another call** → **A real grandson asking for $50 for a birthday cake** → **Start the call** | No scam script: one mild flag ("right now"), script 8 / 100 | |
| 2 | In **Protected Send** ($50): pay as in Test 1 | **Held · call in progress**, like every payment made mid-call | `POST /v2/checkout/orders`, then `.../authorize` |
| 3 | Wait for "see you tonight", then **End call & build report** | Automatically **Released**, with no callback: low risk, 3 / 100 | `POST /v2/payments/authorizations/{id}/capture` |

### Test 3: AI Cloned Voice Detection (`Spectra-0` + `Whisper`)

**One click each, with your sound on.** End the call, then **See report** → **Check another call** → **Back**. The first screen replays two real recordings, so you can hear and compare them:

| Select | The recording | Expect |
| --- | --- | --- |
| **Replay ElevenLabs AI Scam Audio** | [`elevenlabs_scam_sample.mp3`](Audio/elevenlabs_scam_sample.mp3), 44 s: a voice we generated with ElevenLabs | Turns *Likely AI* at 0:05, and the headline holds its 99% peak even when the voice score dips. Script 100 / 100, with the red flags marked in the transcript |
| **Replay Real Voice (No Scam)** | [`Real_call_no_scam.mp3`](Audio/Real_call_no_scam.mp3), 66 s: a real person asking for $50 for gas | Stays *Likely human*, with a 13% peak and no scam alert. Script 8 / 100, from two mild urgency words |

To go from one to the other, end the call, then **See report** → **Check another call** → **Back**. The voice scores and transcripts in these replays are what the real models produced on these exact files, computed ahead of time so they play in real time. The scam rules run live.

**Run the models live, about 1 more minute.** Use the same file or your own `.wav` or `.mp3`, up to 2 minutes and 20 MB. Your own file's results are your own: newer generators and clips played from a speaker are harder ([`eval/voice_results.md`](../eval/voice_results.md)).

1. End the call, then **See report** → **Check another call** → **Upload a recording** → choose the file → **Start the call**. Spectra-0 and Whisper now run on your CPU: the 44 s sample reached its report in about 1 minute on an Apple M5, and a slower laptop takes longer.
2. When it says **Recording finished**, select **End call & build report** → **See report** → **Download JSON**.
3. In the JSON, check `voice.final_state`, `voice.smoothed_peak`, `script.red_flags`, `overall.risk_level` and `evidence.audio_saved` (`false`: the upload is deleted once decoded).

## Running the Test Suite

All 164 unit and integration tests run without a phone, models or PayPal account.

**Inside Docker**, with the image from step 2:

```bash
docker compose --profile judge run --rm judge pytest -q
```

**Outside Docker**, with Python 3.12 and ffmpeg:

```bash
cd veracity-backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements-judge.txt python-multipart pytest
python -m pytest -q
```

Outside Docker, one test that needs torch is skipped.

## What's Real

| | Real here | Not in Docker |
| --- | --- | --- |
| **Scam rules, risk fusion, payment gate, report** | Yes, in every test | |
| **Spectra-0 and Whisper** | Live on an upload; their pre-computed output on the two recorded replays; none on scripted calls, which show no voice score | Whisper large-v3-turbo (the phone build's) |
| **PayPal** | The real sandbox with keys; the labelled stand-in without | |
| **Live phone capture and the local LLM** | | Both need the phone build; see the [demo video](https://youtu.be/7DbctZZKWP8?si=1eyhgEVbLM1fektF) and the README's [real-call tests](../README.md#tested-on-real-phone-calls). Reports say `llm_used: false` |

## Troubleshooting

| Problem | Fix |
| --- | --- |
| Port 8000 is already in use | Stop whatever uses it (`docker compose --profile judge down`, or `lsof -nP -iTCP:8000 -sTCP:LISTEN` on macOS/Linux), then start again |
| The build or the container is killed, or an upload stops partway | Docker is short of memory: give it at least 6 GB in Docker Desktop → Settings → Resources |
| No sound on a recorded replay | Your browser blocked autoplay: press play on the player. The analysis is already running |
| A payment says *Held · waiting for PayPal* | The call checked out, but PayPal didn't complete the capture. No money has moved, and Veracity retries by itself; the card shows when |
| *The call didn't finish ending* | Select **End call again**. It's the same call, and any payment stays held until it finishes |
| **Upload a call recording** is greyed out | It says why. *Models still loading*: wait about 20 seconds. *Needs the full judge build*: start it with the command above, not the root `Dockerfile` |
| *Couldn't read this audio file* | ffmpeg couldn't decode it: export it as WAV or MP3 and try again |
| Compose complains about `env_file` or `required` | Update Docker Compose to 2.24 or newer |
| You added keys but it still says *PayPal stand-in* | Check `.env` is at the repo root, then run `docker compose --profile judge up --build judge` again |
| The PayPal button doesn't appear | An ad blocker may block PayPal's script; allow it on localhost |
