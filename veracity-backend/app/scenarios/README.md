# Replay scenarios

A scenario is a call that can be replayed without a phone (judge mode, or `VERA_FAKE=1`).
The transcript is replayed at its real times and **the real scam rules run on every line**,
exactly as in a live call. Each file is `<id>.json`, where `<id>` is lowercase letters, digits and `_`.

```jsonc
{
  "title": "Shown in the scenario picker",
  "description": "One or two sentences: who calls and what they want",
  "region": "US",                 // next steps and number checks follow this region
  "order": 1,                     // position in the picker
  "source": "scripted",           // "scripted" (hand-written lines) or "recorded" (a real recording)
  "caller_number": "+12025550143",// fictional 555-01xx numbers only; null for a hidden caller ID
  "lines": [ { "t": 3, "text": "What the caller says at 3 s" } ],
  "voice": {                      // only for "recorded": the real model's output on that recording
    "model_id": "lab260/spectra_0",
    "recording_sha256": "…",
    "windows": [ { "t": 4, "p_ai": 0.91 } ],   // one calibrated score per second of speech
    "levels": [ { "t": 0.1, "dbfs": -38.5 } ]  // input level every 0.1 s
  },
  "payment": {                    // what Protected Send is pre-filled with; null for no PayPal step
    "amount": "2400.00", "currency": "USD",
    "recipient_name": "Jake (grandson)", "contact_name": "Jake",
    "contact_number": "+12025550172", "note": "Bail money"
  }
}
```

Scripted scenarios have **no voice score**: the UI says so instead of inventing one.
To replay a real recording with the real model's voice scores, record a call with
*Save audio* on, then on the Mac run:

```bash
cd veracity-backend
python scripts/build_replay.py app/data/audio/<session>.wav --base grandparent_us --out app/scenarios/grandparent_us_recorded.json
```

It runs the deepfake model and Whisper on the recording, the same way a live call does, and writes
their output into a copy of the `--base` scenario (its region, caller number and payment), with the
recording's SHA-256, so anyone can check which file the scores came from. Whisper's language follows
the base scenario's region (`en` for US, `hi` for India); pass `--language` to change it. Then replay
it with `VERA_SCENARIO=grandparent_us_recorded`, or pick it in Step 2.

Only record voices you have consent for: your own, or a clone of your own voice that you made.
