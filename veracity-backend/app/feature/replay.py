# A replayed call: the same WebSocket events as a live Session, played from a
# scenario file instead of the phone. Judge mode (VERA_MODE=judge) and
# VERA_FAKE=1 use it, so the whole flow runs on a server with no phone, no
# audio input and no models.
#
# What is real and what is replayed:
#   transcript   the scenario's lines at their times: a scripted call, or Whisper's
#                output on a real recording (scripts/build_replay.py)
#   red flags    the real scam rules (and the local LLM, if it's running) on each line, live
#   AI voice     only when the scenario holds scores the real model produced on a
#                recording (scripts/build_replay.py); a scripted call has no voice score
#   audio        a recorded scenario can name its file (audio_file): the dashboard plays
#                it along with the replay, from GET /api/session/scenarios/{id}/audio
#   say()        a line the user types, treated as if the caller had just said it
#
# Scenario files live in app/scenarios/<id>.json (format: app/scenarios/README.md).

import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from app.feature.session import Session, voice_event

SCENARIO_DIR = Path(__file__).resolve().parent.parent / "scenarios"
# The recordings: docs/Audio in the repo, a folder of its own in the judge images
SAMPLE_AUDIO_DIR = Path(os.environ.get("VERA_SAMPLE_AUDIO_DIR") or Path(__file__).resolve().parents[3] / "docs" / "Audio")
TICK_S = 0.1
SPEED = float(os.environ.get("VERA_REPLAY_SPEED", "1"))  # 2 plays a call twice as fast; the tests use more
_ID = re.compile(r"^[a-z0-9_]{1,40}$")


class ScenarioNotFound(LookupError):
    pass


def load_scenario(scenario_id: str) -> dict:
    if not _ID.match(scenario_id or ""):
        raise ScenarioNotFound(scenario_id)
    path = SCENARIO_DIR / f"{scenario_id}.json"
    if not path.is_file():
        raise ScenarioNotFound(scenario_id)
    scenario = json.loads(path.read_text(encoding="utf-8"))
    scenario["id"] = scenario_id
    return scenario


def audio_path(scenario: dict) -> Path | None:
    """The scenario's recording, if it names one and this build has it."""
    name = scenario.get("audio_file")
    path = SAMPLE_AUDIO_DIR / Path(name).name if name else None  # .name: only ever a file in that folder
    return path if path is not None and path.is_file() else None


def audio_type(path: Path) -> str:
    """From the file's first bytes, not its name: a phone's recording can be M4A (AAC in MP4) called .mp3."""
    with path.open("rb") as f:
        return "audio/mp4" if f.read(12)[4:8] == b"ftyp" else "audio/mpeg"


def audio_url(scenario: dict) -> str | None:
    return f"/api/session/scenarios/{scenario['id']}/audio" if audio_path(scenario) else None


def duration_s(scenario: dict) -> float:
    recorded = (scenario.get("voice") or {}).get("recording_seconds")
    return recorded or max((line["t"] for line in scenario["lines"]), default=0)


def list_scenarios(region: str | None = None) -> list[dict]:
    """Every scenario (or one region's), described for the scenario picker."""
    out = []
    for path in sorted(SCENARIO_DIR.glob("*.json")):
        s = load_scenario(path.stem)
        if region and s.get("region") != region:
            continue
        out.append({
            "id": s["id"],
            "title": s["title"],
            "description": s.get("description", ""),
            "region": s.get("region"),
            "caller_number": s.get("caller_number"),
            "source": s.get("source", "scripted"),
            "voice_scored": bool((s.get("voice") or {}).get("windows")),
            "audio_url": audio_url(s),
            "duration_s": duration_s(s),
            "payment": s.get("payment"),
            "order": s.get("order", 99),
        })
    return sorted(out, key=lambda s: (s["order"], s["id"]))


class ReplaySession(Session):
    def __init__(self, scenario: dict, loop, caller_number: str | None = None):
        super().__init__(caller_number or scenario.get("caller_number"), save_audio=False, loop=loop)
        self.scenario = scenario
        self.capture_method = f"replay_{scenario.get('source', 'scripted')}"
        self.audio_device = None
        self.region = scenario.get("region", self.region)

        voice = scenario.get("voice") or {}
        self._voice = {int(round(w["t"])): float(w["p_ai"]) for w in voice.get("windows", [])}
        self._levels = sorted(voice.get("levels", []), key=lambda lv: lv["t"])
        self._lines = sorted(scenario["lines"], key=lambda line: line["t"])
        self._t0: float | None = None
        self._speed = SPEED
        self._replay = threading.Thread(target=self._run_replay, name="replay", daemon=True)

    def start(self) -> None:
        self._t0 = time.monotonic()
        self._publish({
            "type": "mode", "replay": True, "scenario": self.scenario["id"], "title": self.scenario["title"],
            "source": self.scenario.get("source", "scripted"), "voice_scored": bool(self._voice),
            "audio_url": audio_url(self.scenario), "duration_s": duration_s(self.scenario), "region": self.region,
        })
        self._replay.start()

    def elapsed(self) -> float:
        """Seconds into the call (call time, not wall time, when SPEED isn't 1)."""
        return round((time.monotonic() - self._t0) * self._speed, 1) if self._t0 else 0.0

    def say(self, text: str) -> None:
        """A line the user typed in, heard as the caller's words right now."""
        self._on_text(self.elapsed(), text.strip())

    def _run_replay(self) -> None:
        tick = line_i = level_i = 0
        last = max([line["t"] for line in self._lines] + [lv["t"] for lv in self._levels] + list(self._voice), default=0)
        recording_over = not self._voice  # a scripted call has no recording to run out
        while not self._stop.is_set():
            tick += 1
            t = round(tick * TICK_S, 1)
            while level_i < len(self._levels) and self._levels[level_i]["t"] <= t:
                lv = self._levels[level_i]
                self._publish({"type": "level", "t": lv["t"], "dbfs": lv["dbfs"]})
                level_i += 1
            if self._voice and tick % round(1 / TICK_S) == 0 and int(t) <= last:
                second = int(t)
                if second in self._voice:
                    self._record_voice(second, self._voice[second])
                else:  # a pause in the recording: keep the verdict, draw a gap
                    self._publish(voice_event(second, None, self.smoother.update(None)))
            while line_i < len(self._lines) and self._lines[line_i]["t"] <= t:
                line = self._lines[line_i]
                self._on_text(float(line["t"]), line["text"])
                line_i += 1
            if not recording_over and t > last:  # the same event as an uploaded recording that has played out
                recording_over = True
                self._publish({"type": "audio_done", "t": last})
            # Sleep to the next tick on the clock, so the replay doesn't drift
            time.sleep(max(0.0, self._t0 + (t + TICK_S) / self._speed - time.monotonic()))

    def stop(self) -> dict:
        if self.report is not None:
            return self.report
        self._stop.set()
        self._replay.join(timeout=2)
        self._llm.shutdown(wait=False, cancel_futures=True)
        self.ended_at = datetime.now(timezone.utc).replace(microsecond=0)
        self.report = self._build_report()
        self._publish({"type": "report", "report": self.report})
        self._publish({"type": "ended"})
        return self.report
