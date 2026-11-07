# Testing Veracity

Veracity runs on your own machine with Docker, with the real models. There's no hosted demo.

## What you need

- **Docker**: Docker Desktop on macOS or Windows, or Docker Engine with Docker Compose 2.24 or newer on Linux. amd64 or arm64 (Apple Silicon) both work.
- **At least 6 GB of memory for Docker** (Docker Desktop → Settings → Resources). The container used up to 4.4 GB in our tests.
- **About 10 GB of free disk.** The image is 6.2 GB.
- An internet connection for the first build, and for the PayPal sandbox.

## Run it

```bash
git clone https://github.com/YADUNANDAN-SINGH/Veracity.git && cd Veracity
cp .env.example .env        # optional: add PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET from a PayPal sandbox app
docker compose --profile judge up --build judge
```

Open <http://localhost:8000>.

- **First build:** 8 min 27 s on an Apple M5 (10 CPUs), 4 min 48 s of it downloading the models into the image. A slower connection or CPU takes longer.
- **Later starts:** ready in 9 to 21 seconds. **Upload a call recording** turns on once the models have loaded.
- **Without PayPal keys,** everything runs and Protected Send says PayPal isn't set up. Getting sandbox keys takes about 15 minutes: [docs/PAYPAL_SETUP.md](PAYPAL_SETUP.md), steps 1 and 2.
- **PayPal sandbox buyer login** (to log in to the PayPal pop-up): see the credentials in the Devpost testing instructions. It's a sandbox test account with test money.
- **To stop:** Ctrl+C, then `docker compose --profile judge down`.

## Test 1: a sample call (scripted)

1. Select **Pick a sample call**, choose **"Grandma, it's me": a grandparent scam**, then **Start the call**.
2. When "Jake" asks for $2,400, Protected Send is already filled in. Pay with the PayPal button as the sandbox buyer. PayPal authorizes it and Veracity **holds** it, quoting the caller's words.
3. Select **End call & build report**, then **Jake didn't ask: cancel**. Veracity voids the authorization at PayPal. **Details** shows each PayPal call with its HTTP status and `debug_id`.
4. Try **A real grandson asking for concert money**: the $40 is held during the call and released (captured) when it ends.

A sample call is a scripted transcript through the real scam rules, risk fusion, payment gate and PayPal sandbox. It has no audio, so it has no voice score.

## Test 2: upload a call recording (the real models)

1. Select **Upload a call recording**. Choose a file (wav, mp3, m4a, ogg, flac or webm; up to 2 minutes and 20 MB), add a caller's number if you like, and select **Start the call**. The repo's `samples/` folder has clips to try.
2. Watch the voice meter (Spectra-0), the transcript (Whisper), the red flags and the risk update as the recording plays.
3. While it plays, make a **Protected Send** payment: an amount, a recipient, then the PayPal button as the sandbox buyer. Veracity **holds** it while the call is on.
4. When it says **Recording finished**, select **End call & build report**. The payment is decided with the final report, then open the report.

- **Upload the audio file itself.** A clip played from a speaker across a room is the hardest case for the voice model.
- **Uploads run slower than real time.** Docker has no GPU. A 60-second recording took 2.0 to 2.4 minutes to reach its report on an Apple M5. A slower laptop takes longer, but the result is the same.
- **No local LLM in Docker.** The scam rules run alone, and the report says so (`llm_used: false`).
- **The live phone capture** (an Android call through scrcpy and BlackHole) is in the video and the README's real-call tests.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| Port 8000 is already in use | Stop whatever uses it (`docker compose --profile judge down`, or `lsof -nP -iTCP:8000 -sTCP:LISTEN` on macOS/Linux), then start again |
| The build or the container is killed, or an upload stops partway | Docker is short of memory: give it at least 6 GB in Docker Desktop → Settings → Resources |
| **Upload a call recording** is greyed out | It says why. *Models still loading*: wait about 20 seconds. *Needs the full judge build*: start it with the command above, not the root `Dockerfile` |
| *Couldn't read this audio file* | ffmpeg couldn't decode it: export it as WAV or MP3 and try again |
| Compose complains about `env_file` or `required` | Update Docker Compose to 2.24 or newer (Docker Desktop updates include it) |
| Protected Send says PayPal isn't set up | Put sandbox `PAYPAL_CLIENT_ID` and `PAYPAL_CLIENT_SECRET` in `.env`, then run `docker compose --profile judge up --build judge` again |
| The PayPal button doesn't appear | An ad blocker may block PayPal's script; allow it on localhost |
