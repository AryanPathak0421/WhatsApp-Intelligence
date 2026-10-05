"""Voice activity detection + utterance endpointing + barge-in, as a pure state machine over 16-bit PCM frames (no models, fully testable).

This is the energy-based fallback. A neural VAD (Silero) can replace `is_speech` without touching the state machine. Thresholds adapt to the
room: the noise floor is tracked while nobody speaks, and speech must exceed it by a margin, which copes with steady background noise
(fans, street) but NOT with several people talking, which needs a neural VAD and is out of scope for this fallback.
"""
from __future__ import annotations

import array
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterator, Optional


def rms(frame: bytes) -> float:
    a = array.array("h")
    a.frombytes(frame[: len(frame) - len(frame) % 2])
    return math.sqrt(sum(x * x for x in a) / len(a)) if len(a) else 0.0


@dataclass
class Event:
    kind: str                   # speech_start | speech_end | interrupt
    audio: bytes = b""          # speech_end: the utterance (16-bit mono PCM)
    duration_ms: int = 0


class VoiceTurnState(str, Enum):
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


@dataclass
class Endpointer:
    sample_rate: int = 16000
    frame_ms: int = 30
    min_speech_ms: int = 240          # shorter bursts (clicks, coughs) are ignored
    end_silence_ms: int = 700         # this much silence ends the utterance
    max_utterance_ms: int = 20000
    margin: float = 3.0               # speech must exceed margin x noise floor
    min_floor: float = 60.0           # absolute floor (digital silence must not make everything "speech")
    preroll_ms: int = 150             # audio kept from just before speech was detected
    state: VoiceTurnState = VoiceTurnState.LISTENING
    _floor: float = field(default=200.0, init=False)
    _speaking: bool = field(default=False, init=False)
    _voiced_ms: int = field(default=0, init=False)
    _silence_ms: int = field(default=0, init=False)
    _buf: list = field(default_factory=list, init=False)
    _preroll: list = field(default_factory=list, init=False)

    def is_speech(self, frame: bytes) -> bool:
        e = rms(frame)
        speech = e > max(self.min_floor, self._floor * self.margin)
        if not speech:                                              # track the noise floor only while it is quiet
            self._floor = 0.95 * self._floor + 0.05 * max(e, 1.0)
        return speech

    def feed(self, frame: bytes) -> Iterator[Event]:
        speech = self.is_speech(frame)
        if not self._speaking:
            self._preroll.append(frame)
            self._preroll = self._preroll[-max(1, (self.min_speech_ms + self.preroll_ms) // self.frame_ms):]     # detection lags speech onset by min_speech_ms
            self._voiced_ms = self._voiced_ms + self.frame_ms if speech else 0
            if self._voiced_ms >= self.min_speech_ms:
                self._speaking, self._silence_ms = True, 0
                self._buf = list(self._preroll)
                if self.state == VoiceTurnState.SPEAKING:           # the user talked over the assistant: stop playback, start listening
                    self.state = VoiceTurnState.LISTENING
                    yield Event("interrupt")
                yield Event("speech_start")
            return
        self._buf.append(frame)
        self._silence_ms = 0 if speech else self._silence_ms + self.frame_ms
        total = len(self._buf) * self.frame_ms
        if self._silence_ms >= self.end_silence_ms or total >= self.max_utterance_ms:
            audio = b"".join(self._buf)
            self._speaking, self._voiced_ms, self._buf, self._preroll = False, 0, [], []
            self.state = VoiceTurnState.THINKING
            yield Event("speech_end", audio, total - self._silence_ms)

    def assistant_started_speaking(self):
        self.state = VoiceTurnState.SPEAKING

    def assistant_finished(self):
        if self.state != VoiceTurnState.LISTENING:
            self.state = VoiceTurnState.LISTENING
