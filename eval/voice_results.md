# AI-voice detection: what failed, what changed, and how well it works now

## What failed on 7 November 2026

The tester played the demo video's narration into a phone call. The narration is AI speech: the clips carry Google's C2PA credential *"Created by Google Generative AI"* (Veo) and a SynthID watermark. Veracity said **Likely human** the whole call, at 7–22% per window. Two things were wrong:

1. **The model.** `Gustking/wav2vec2-large-xlsr-deepfake-audio-classification` gives the same narration 0.07–0.13 per window even as clean audio, which is what it gives real people. It misses most of today's generators (table below).
2. **The live pipeline.** Each 0.1 s block from BlackHole was resampled from 48 kHz to 16 kHz on its own, padding it with zeros. That put a click at every block edge, 27 times the normal resampling error. On the same narration, a model that scores 37% of windows ≥ 0.75 on the recording scored 3% through the old pipeline.

## What changed

| | Before | Now |
| --- | --- | --- |
| Model | wav2vec2 classifier (Gustking) | [Spectra-0](https://huggingface.co/lab260/spectra_0): XLS-R 300M + ECAPA-TDNN anti-spoofing network (MIT), weights pinned to one revision, network vendored in [`app/feature/spectra0.py`](../veracity-backend/app/feature/spectra0.py) |
| Resampling | block by block | one continuous stream ([`StreamResampler`](../veracity-backend/app/feature/audio_capture.py)); identical to resampling the whole call at once |
| First score | 1 s into the call (1 s repeated to fill the model's 4 s, which sounds synthetic to it: 8% of real callers' first windows ≥ 0.75) | 3 s into the call (1%) |
| Verdict | the smoother's state when the call ends | stays *Likely AI* once the voice was *Likely AI*, even if a real person speaks afterwards; the payment gate and the report use it |
| Risk | a confirmed AI voice could still show *Low risk* (smoothed peak under 85) | *Likely AI* is high risk on its own (at least 70) |
| Screen | a later scam-script alert replaced the AI-voice alert in the banner | the banner names every alert; the voice panel says when an AI voice was heard |

The rule is unchanged: a 4 s window every second, *Likely AI* after 3 windows in a row ≥ 0.75.

## The demo narration as one call (2 min), through the live pipeline

Run through `Session`'s own audio thread (resampling, windows, model, smoother, report), with the phone and BlackHole replaced by the file. On 7 November the old app said *Likely human* for the whole call; how the clip reached the calling phone wasn't recorded.

| How the call carried it | Now |
| --- | --- |
| As recorded | *Likely AI* from 16 s, risk 98 |
| Narrowband call (8 kHz G.711, then scrcpy's AAC) | *Likely AI* from 42 s, risk 89 |
| Wideband call (16 kbit/s Opus, then AAC; close to VoLTE) | *Likely AI* from 75 s, risk 83 |
| Played from a speaker with the phone close to it (mostly direct sound), then wideband | *Likely AI* from 12, 41 and 75 s (3 placements) |
| Played from a speaker across a room (reverberant), then wideband | **missed**: *Likely human* in 3 of 3 rooms |

## Every source, before and after

Calls (files) that turned *Likely AI* / calls, for each channel. Old · new, on the files both models scored (human sets: 20 per source).

| Source | As recorded | Narrowband | Wideband | Speaker in a room |
| --- | ---: | ---: | ---: | ---: |
| ElevenLabs v4, English | 12 · **26** of 26 | 4 · **25** of 26 | 9 · **23** of 26 | 1 · 7 of 26 |
| ElevenLabs v4, German/French/Dutch/Spanish | 12 · **24** of 24 | 5 · **24** of 24 | 11 · **23** of 24 | 1 · 2 of 24 |
| Two-host AI podcast | 15 · **18** of 18 | 0 · **18** of 18 | 15 · **18** of 18 | 0 · 3 of 18 |
| macOS text-to-speech | 17 · 17 of 17 | 16 · 17 of 17 | 17 · 17 of 17 | 6 · 10 of 17 |
| Veo 3, 19 other voices | 2 · **18** of 19 | 1 · **14** of 19 | 3 · **13** of 19 | 0 · 1 of 19 |
| Veo, the demo narrator, 10 s clips | 0 · 3 of 11 | 0 · 1 of 11 | 0 · 0 of 11 | 0 · 0 of 11 |
| Veo, Hindi skits | 1 · 3 of 4 | 1 · 0 of 4 | 1 · 1 of 4 | 0 · 0 of 4 |
| *Real people:* audiobooks (LibriSpeech) | 8 · **0** of 20 | 0 · 0 of 20 | 12 · **1** of 20 | 0 · 0 of 20 |
| Read speech, Hindi (FLEURS) | 0 · 0 of 20 | 0 · 0 of 20 | 0 · 1 of 20 | 0 · 1 of 20 |
| Phone calls, US / UK / Australian English (MInDS-14) | 0 · 1 of 59 | 0 · 0 of 59 | 0 · 1 of 59 | 0 · 2 of 60 |

On every file (new model only; about 12 hours scored, counting each channel and the 30 s calls). On the files both models scored, the old model caught 39% of AI calls over a phone line, the new one 85%.

| | Over a phone line | Speaker in a room |
| --- | ---: | ---: |
| AI voices turned *Likely AI* | **309 of 363 calls (85%)** | 23 of 120 (19%) |
| Real people turned *Likely AI* (false alarms) | **21 of 1,902 calls (1.1%)** | 10 of 575 (1.7%) |

The false-alarm rate held across languages: Tamil read speech 0 of 192, French phone calls 0 of 188, Spanish 1 of 188, German 5 of 192 (4 of them through the speaker).

## What we tried and didn't ship

A logistic-regression head on Spectra-0's features, trained on these sources, caught far more on sources held out of training: 11 of 12 demo-narrator calls as recorded, and after a speaker in a room 10 of 11 narrator clips, 15 of 19 other Veo voices and every ElevenLabs, podcast and macOS file. But held out by **whole dataset**, as a new user's phone and room would be, it flagged up to **43% of real people's calls** (US phone calls 19 of 69, Hindi read speech 23 of 72, as recorded): it had learned what each dataset's recordings sound like, not what synthesis sounds like. Holding a real grandson's payment one call in four is worse than the miss, so the head was dropped.

## Limits

- **A speaker across a room hides most AI voices**, from this model and the old one (19% caught). Audio sent into the call directly (a VoIP app, a voice changer, a cable) is the case it handles. For a demo, play the clip into the calling phone over a cable, or hold the phone against the speaker in a quiet room.
- **Clean, studio-like voiceovers are the hardest generator here.** The demo narrator's 10 s clips are mostly missed; the 2-minute call is caught because it gives the model more chances.
- **Small and partly synthetic.** Phone channels are simulated with ffmpeg (G.711, Opus, AAC), not AMR-WB or EVS on a real network; rooms are synthetic. Veo, ElevenLabs, one AI podcast and macOS voices are not every generator, and new ones will evade it. Real phone-line recordings of a consented clone (Save audio on) are the next measurement.
- **Not proof.** *Likely AI* is a warning; the report says so.

## The test set

Per channel, 121 minutes of distinct audio; each file at the same speech level (−24 dBFS) so loudness can't give the answer away, then through each channel.

| Source | What | Files | Licence |
| --- | --- | ---: | --- |
| Veo, demo narrator | The 11 clips of the demo video (Google Veo, C2PA-verified), and all 11 back to back as one call | 11 + 1 | the user's |
| Veo, Hindi skits; Veo, fitness coach | The user's other Veo clips | 4 + 1 | the user's |
| Veo 3, other voices | [34data/gen-videos-veo3](https://huggingface.co/datasets/34data/gen-videos-veo3): the 19 English clips with speech, all C2PA-verified | 19 | none stated; scored only, not redistributed |
| Two-host AI podcast | A 6-minute AI-generated audio overview, in 20 s pieces | 18 | the user's |
| ElevenLabs v4 | [laion/elevenlabs-v4-five-language-voice-acting](https://huggingface.co/datasets/laion/elevenlabs-v4-five-language-voice-acting), shard 0: every English clip and 6 each in de/fr/nl/es, up to 40 s | 50 | CC BY 4.0 |
| macOS text-to-speech | `say`: 8 English voices (US, UK, Indian, Australian, Irish) and Hindi, scam scripts | 17 | generated locally |
| Phone calls, 6 locales | [PolyAI/minds14](https://huggingface.co/datasets/PolyAI/minds14): real calls to a bank's phone line (8 kHz), en-US/GB/AU, de, fr, es, and 30 s calls made of them | 276 + 53 | CC BY 4.0 |
| Read speech | [google/fleurs](https://huggingface.co/datasets/google/fleurs): Hindi (dev and test), Tamil, US English, and 30 s calls made of them | 180 + 36 | CC BY 4.0 |
| Audiobooks | `hf-internal-testing/librispeech_asr_dummy` (LibriSpeech), and 30 s calls made of them | 73 + 16 | CC BY 4.0 |

To measure any model on your own recordings, the way a call scores them and through the same channels:

```bash
cd veracity-backend && source venv/bin/activate
python ../eval/voice_eval.py --real recordings/me --ai recordings/my_clone recordings/veo \
    --channels clean,phone_nb,phone_wb,replay
```

Set `VERA_VOICE_MODEL=Gustking/wav2vec2-large-xlsr-deepfake-audio-classification` to score the old model the same way.
