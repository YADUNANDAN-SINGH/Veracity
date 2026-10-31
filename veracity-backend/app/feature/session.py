# One monitored call (Project Document §3.2). Three threads:
#   audio       BlackHole blocks → level events, a voice score every second,
#               and 6–12 s chunks, cut at pauses, for the transcriber
#   transcriber Whisper on each chunk → transcript, rule flags; every 2nd chunk
#               the LLM (on its own thread, so a slow answer doesn't hold it up)
#   llm         Ollama verdicts → extra flags whose quotes are in the transcript
# Every result is published as a WebSocket event (shapes in
# veracity-frontend/veracity/src/api/session.js); late joiners get the history.

import asyncio
import hashlib
import logging
import queue
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from app.feature import reports_db, scam_llm, scam_rules, transcriber, voice
from app.feature.audio_capture import (
    AUDIO_DEVICE, CAPTURE_METHOD, TARGET_SR, LiveCapture, default_output_name, rms_dbfs, start_scrcpy,
    stop_scrcpy, to_mono_16k,
)
from app.feature.number_intelligence import InvalidNumberError, analyse_number
from app.feature.report import build_report

log = logging.getLogger("veracity.session")

# Audio per transcription: at least 6 s, cut at the next pause so no word is split
# between chunks, and at most 12 s if the caller never pauses
CHUNK_MIN_S = 6.0
CHUNK_MAX_S = 12.0
PAUSE_DB = 25.0  # a 0.1 s block this far below the chunk's loudest block counts as a pause
LLM_EVERY = 2  # chunks between LLM checks (~16 s)
SCRIPT_ALERT = 80
FLAGS_PER_CATEGORY = 3  # a category can be flagged again for different words, up to this many times
LLM_MIN_CONFIDENCE = 0.6
AUDIO_DIR = Path(__file__).resolve().parent.parent / "data" / "audio"

VOICE_ALERT = "The voice sounds AI-generated. Hang up, then call back on a number you have saved."
SCRIPT_ALERT_MESSAGE = (
    "Hang up, then call back on a number you have saved. This call matches a known scam script."
)
NO_AUDIO_S = 6.0  # this long without a single sample from BlackHole means the routing is wrong


def no_audio_message() -> str:
    output = default_output_name()
    # A Multi-Output Device may already include BlackHole, so only name a plain output
    routed = output is None or "multi" in output.lower() or output == AUDIO_DEVICE
    where = "" if routed else f"The Mac plays sound to “{output}”, so it never reaches {AUDIO_DEVICE}. "
    return (
        f"Nothing is reaching {AUDIO_DEVICE}. {where}Set the Mac's sound output to a Multi-Output Device "
        f"with your speakers or headphones and {AUDIO_DEVICE} ticked, and check the call is connected."
    )


class Session:
    def __init__(self, caller_number: str | None, save_audio: bool, loop: asyncio.AbstractEventLoop):
        self.id = uuid.uuid4().hex
        self.caller_number = caller_number
        self.save_audio = save_audio
        self.loop = loop
        self.started_at = datetime.now(timezone.utc).replace(microsecond=0)
        self.ended_at: datetime | None = None

        # Published events; touched only on the event loop's thread
        self.history: list[dict] = []
        self.subscribers: list[asyncio.Queue] = []

        self.capture = LiveCapture()
        self.scrcpy = None
        self.smoother = voice.VerdictSmoother()
        self.windows: list[dict] = []  # every scored window, for the report
        self.transcript: list[dict] = []  # { t, text }
        self.flags: list[dict] = []
        self.categories: set[str] = set()
        self.scam_type: str | None = None
        self.alerted: set[str] = set()
        self.recorded: list[np.ndarray] = []  # only if save_audio

        self._flag_lock = threading.Lock()
        self._stop = threading.Event()
        self._chunks: queue.Queue = queue.Queue()
        self._llm = ThreadPoolExecutor(max_workers=1, thread_name_prefix="llm")
        self._llm_job: Future | None = None
        self._audio_thread = threading.Thread(target=self._run_audio, name="audio", daemon=True)
        self._text_thread = threading.Thread(target=self._run_transcriber, name="transcriber", daemon=True)
        self.report: dict | None = None

    # ----- lifecycle -----

    def start(self) -> None:
        """Blocking (starts scrcpy); call from a worker thread."""
        self.scrcpy = start_scrcpy()
        self.capture.start()
        self._audio_thread.start()
        self._text_thread.start()

    def stop(self) -> dict:
        """End the call: finish the last transcript chunk, then build and publish the report."""
        if self.report is not None:
            return self.report
        self._stop.set()
        self._audio_thread.join(timeout=5)
        self._text_thread.join(timeout=20)  # the last chunk may still be transcribing
        self._llm.shutdown(wait=False, cancel_futures=True)
        stop_scrcpy(self.scrcpy)
        self.ended_at = datetime.now(timezone.utc).replace(microsecond=0)
        self.report = self._build_report()
        self._publish({"type": "report", "report": self.report})
        self._publish({"type": "ended"})
        return self.report

    @property
    def active(self) -> bool:
        return self.report is None

    # ----- events -----

    def _publish(self, event: dict) -> None:
        """Thread-safe: hands the event to the event loop, which fans it out."""
        self.loop.call_soon_threadsafe(self._deliver, event)

    def _deliver(self, event: dict) -> None:
        self.history.append(event)
        for q in self.subscribers:
            q.put_nowait(event)

    def subscribe(self) -> asyncio.Queue:
        """A queue that gets the history so far, then every new event. Call on the event loop."""
        q: asyncio.Queue = asyncio.Queue()
        for event in self.history:
            q.put_nowait(event)
        self.subscribers.append(q)
        return q

    # ----- audio thread -----

    def _run_audio(self) -> None:
        sr = self.capture.sample_rate
        window = np.zeros(0, dtype=np.float32)
        chunk: list[np.ndarray] = []
        chunk_start = 0.0
        chunk_peak = -120.0  # loudest block so far in this chunk, dBFS
        samples = 0
        blocks = 0
        heard = False
        try:
            while not self._stop.is_set():
                block = self.capture.read(timeout=0.5)
                if block is None:
                    continue
                x = to_mono_16k(block, sr)
                samples += len(x)
                blocks += 1
                t = round(samples / TARGET_SR, 1)
                dbfs = rms_dbfs(x)
                self._publish({"type": "level", "t": t, "dbfs": round(dbfs, 1)})

                # BlackHole sends exact zeros while nothing plays into it, unlike a quiet call
                heard = heard or bool(block.any())
                if not heard and t >= NO_AUDIO_S and "audio" not in self.alerted:
                    self.alerted.add("audio")
                    self._publish({"type": "alert", "kind": "audio", "message": no_audio_message()})

                window = np.concatenate([window, x])[-int(voice.WINDOW_S * TARGET_SR):]
                chunk.append(x)
                if self.save_audio:
                    self.recorded.append(x)
                if blocks % 10 == 0:  # once a second
                    self._score_voice(round(t), window)
                chunk_peak = max(chunk_peak, dbfs)
                chunk_s = sum(len(c) for c in chunk) / TARGET_SR
                pause = dbfs < voice.SILENCE_DBFS or dbfs < chunk_peak - PAUSE_DB
                if chunk_s >= CHUNK_MAX_S or (chunk_s >= CHUNK_MIN_S and pause):
                    self._chunks.put((chunk_start, np.concatenate(chunk)))
                    chunk, chunk_start, chunk_peak = [], t, -120.0
        except Exception:
            log.exception("audio loop failed")
        finally:
            self.capture.close()
            if sum(len(c) for c in chunk) >= TARGET_SR:  # the last second or more still counts
                self._chunks.put((chunk_start, np.concatenate(chunk)))
            self._chunks.put(None)

    def _score_voice(self, t: int, window: np.ndarray) -> None:
        detector = voice.detector_if_ready()
        speech = len(window) >= TARGET_SR and rms_dbfs(window) >= voice.SILENCE_DBFS
        if not speech or detector is None:
            vs = self.smoother.update(None)
            self._publish({"type": "voice", "t": t, "p_ai": None, "smoothed": vs.smoothed, "state": vs.state, "speech": False})
            return

        p = round(voice.calibrate(detector.p_fake(window)), 4)
        vs = self.smoother.update(p)
        self.windows.append({"t_start": round(max(0.0, t - len(window) / TARGET_SR), 1), "t_end": float(t), "p_ai": p})
        self._publish({"type": "voice", "t": t, "p_ai": p, "smoothed": vs.smoothed, "state": vs.state, "speech": True})
        if vs.state == "LIKELY_AI" and "voice" not in self.alerted:
            self.alerted.add("voice")
            self._publish({"type": "alert", "kind": "voice", "message": VOICE_ALERT})

    # ----- transcriber thread -----

    def _run_transcriber(self) -> None:
        done = 0
        while (item := self._chunks.get()) is not None:
            start_t, audio = item
            if rms_dbfs(audio) < voice.SILENCE_DBFS:
                continue
            try:
                text = transcriber.transcribe(audio)
            except Exception:
                log.exception("transcription failed")
                continue
            if not text:
                continue
            t = round(start_t, 1)
            self.transcript.append({"t": t, "text": text})
            self._publish({"type": "transcript", "t": t, "text": text})
            for hit in scam_rules.scan(text):
                self._add_flag(hit["category"], hit["evidence"], t, "rule")

            done += 1
            if done % LLM_EVERY == 0 and not self._stop.is_set() and (self._llm_job is None or self._llm_job.done()):
                full = " ".join(line["text"] for line in self.transcript)
                self._llm_job = self._llm.submit(self._run_llm, full)

    def _run_llm(self, full_transcript: str) -> None:
        verdict = scam_llm.analyse(full_transcript)
        # On garbled transcripts the LLM guesses; only a confident "this is a scam" adds flags
        if verdict is None or not verdict.scam_likely or verdict.confidence < LLM_MIN_CONFIDENCE:
            return
        if verdict.scam_type != "none":
            self.scam_type = verdict.scam_type
        for flag in verdict.red_flags:
            quote = flag.evidence_quote.strip()
            # The quote must be inside one line, which also gives the flag its time
            line = next((l for l in self.transcript if quote.lower() in l["text"].lower()), None)
            if line:
                self._add_flag(flag.category, quote, line["t"], "llm")

    def _add_flag(self, category: str, evidence: str, t: float, source: str) -> None:
        """Record a red flag; each quote counts once, and a new category updates the script score."""
        with self._flag_lock:
            key = evidence.lower()
            if any(key in f["evidence"].lower() or f["evidence"].lower() in key for f in self.flags):
                return  # the same words can't be evidence twice (the LLM tried several labels for one line)
            if sum(f["category"] == category for f in self.flags) >= FLAGS_PER_CATEGORY:
                return
            new_category = category not in self.categories
            self.categories.add(category)
            flag = {"category": category, "severity": scam_rules.SEVERITY[category], "evidence": evidence, "t": t, "source": source}
            self.flags.append(flag)
            self._publish({"type": "flag", **flag})
            if not new_category:
                return
            score = scam_rules.script_score(self.categories)
            self._publish({"type": "script", "score": score})
            if score >= SCRIPT_ALERT and "script" not in self.alerted:
                self.alerted.add("script")
                self._publish({"type": "alert", "kind": "script", "message": SCRIPT_ALERT_MESSAGE})

    # ----- report -----

    def _build_report(self) -> dict:
        """The §1.7 report (app/feature/report.py), with the number's rule score as of now."""
        number = None
        if self.caller_number:
            try:
                number = analyse_number(self.caller_number)
            except InvalidNumberError:
                pass  # e.g. a hidden or garbled caller ID; the report just has no number section

        report = build_report(
            report_id=self.id,
            caller_number=self.caller_number,
            started_at=self.started_at,
            ended_at=self.ended_at,
            capture_method=CAPTURE_METHOD,
            audio_device=AUDIO_DEVICE,
            number=number,
            model_id=voice.VOICE_MODEL,
            calibration_t=voice.CALIBRATION_T,
            threshold=voice.T_AI,
            windows=self.windows,
            final_state=self.smoother.state,
            red_flags=self.flags,
            script_score=scam_rules.script_score(self.categories),
            scam_type=self.scam_type,
            transcript=" ".join(line["text"] for line in self.transcript),
            audio_sha256=self._save_audio() if self.save_audio else None,
        ).model_dump(mode="json")
        reports_db.save_report(report)  # for GET /api/report/{id}
        return report

    def _save_audio(self) -> str | None:
        """Write the call as 16 kHz WAV and return its SHA-256, so the file can be checked later."""
        if not self.recorded:
            return None
        from scipy.io import wavfile

        AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        path = AUDIO_DIR / f"{self.id}.wav"
        pcm = (np.clip(np.concatenate(self.recorded), -1, 1) * 32767).astype(np.int16)
        wavfile.write(path, TARGET_SR, pcm)
        return hashlib.sha256(path.read_bytes()).hexdigest()


def warm_models() -> None:
    """Load the voice model and Whisper in the background at start-up, so the first call scores at once."""
    for name, load in (("voice model", voice.load_detector), ("whisper", transcriber.load_model)):
        try:
            load()
        except Exception:
            log.exception("couldn't load the %s", name)
