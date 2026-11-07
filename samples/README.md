# Sample recordings

Short clips to try **Upload a call recording** in the Docker judge build (`docker compose --profile judge up --build judge`). Every clip here was generated or recorded by the Veracity team. None comes from YouTube, films, the news or anyone else.

| File | What it is | Length |
| --- | --- | --- |
| `ai-voice-grandparent-scam.mp3` | An **AI voice** reading a grandparent-scam script | 25 s |
| `ai-voice-normal-message.mp3` | An **AI voice** saying an ordinary message, with no scam words | 16 s |

## How they were made

Both AI clips were generated on a Mac with macOS text-to-speech (`say`), then converted with ffmpeg to mono 16 kHz MP3 at 48 kbps:

```bash
say -v Samantha -f scam.txt -o scam.aiff                  # the grandparent scam
say -v "Reed (English (US))" -f normal.txt -o normal.aiff  # the normal message
ffmpeg -i scam.aiff -ac 1 -ar 16000 -b:a 48k ai-voice-grandparent-scam.mp3
ffmpeg -i normal.aiff -ac 1 -ar 16000 -b:a 48k ai-voice-normal-message.mp3
```

The scam script (Samantha):

> Grandma? Hi, it's me, Jake. Please don't freak out. I was in a car accident, and the police arrested me. I'm in jail right now, and I need two thousand four hundred dollars for bail. Please don't tell Mom and Dad. My lawyer says you have to send it today, right now, or I stay here all weekend. Can you send it on PayPal? I'll pay you back, I promise. Please hurry, and don't call anyone else.

The normal message (Reed):

> Hi, it's me. Just calling to say I'll be home late tonight. The meeting is running over, and then there's traffic. No need to call back. There's leftover pasta in the fridge if you get hungry. See you around nine. Love you, bye.

## Measured results

Each file was uploaded to the Docker judge build (Spectra-0, Whisper *small*, the scam rules, no local LLM) on 8 November 2026, on an Apple M5. No caller number was given, so the number adds nothing to the risk. Each file was run twice, and both runs gave the same result.

| File | Voice verdict | Voice peak (smoothed / highest window) | *Likely AI* from | Script score | Risk |
| --- | --- | --- | --- | --- | --- |
| `ai-voice-grandparent-scam.mp3` | *Likely AI* | 97% / 100% | 5 s | 100 (12 red flags) | **HIGH**, 100 |
| `ai-voice-normal-message.mp3` | *Likely AI* | 100% / 100% | 5 s | 8 (only "it's me") | **HIGH**, 100 |

- **The grandparent scam** is caught twice over: by the voice and by the words. The red flags are police, arrested, jail, lawyer, a car accident, bail, "need $2,400", "send it on PayPal", "don't tell Mom", "right now", "hurry" and "it's me".
- **The normal message** shows the voice model working on its own: there are no scam words, yet the call is *high risk* because the voice is synthetic. Whisper missed one word ("traffic").
- **The smoothed peak** is what the risk score uses. The report's Voice card shows the highest single window.
- **macOS voices are an easy case.** They are older text-to-speech, and in [`eval/voice_results.md`](../eval/voice_results.md) Spectra-0 caught 17 of 17 macOS clips as recorded. Newer generators and a clip played from a speaker across a room are harder; see that file for the numbers.
