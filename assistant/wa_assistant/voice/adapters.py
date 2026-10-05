"""Speech adapters. The interfaces are tested with doubles; the real engines are loaded lazily from LOCAL weights and are NOT exercised in this
repository's tests because no speech model is installed on the development machine. Their accuracy (WER, especially on Hinglish) is unmeasured
until the bake-off on real recordings.
"""
from __future__ import annotations

import io
import wave
from typing import Optional, Protocol


class ASR(Protocol):
    name: str

    def transcribe(self, pcm16: bytes, sample_rate: int = 16000, language: Optional[str] = None) -> str: ...


class TTS(Protocol):
    name: str

    def synthesize(self, text: str) -> bytes: ...             # WAV bytes


def read_wav_pcm16(data: bytes) -> tuple[bytes, int]:
    """Mono 16-bit PCM + sample rate from a WAV upload; other formats are rejected rather than guessed at."""
    try:
        with wave.open(io.BytesIO(data)) as w:
            if w.getsampwidth() != 2 or w.getnchannels() != 1:
                raise ValueError("Audio must be 16-bit mono WAV.")
            return w.readframes(w.getnframes()), w.getframerate()
    except (wave.Error, EOFError) as e:
        raise ValueError("Audio must be a valid WAV file.") from e


class FasterWhisperASR:
    """Whisper via CTranslate2 (faster-whisper). Requires `pip install faster-whisper` and a local model directory."""

    def __init__(self, model_dir: str, device: str = "auto", compute_type: str = "int8"):
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise RuntimeError("faster-whisper is not installed.") from e
        self.name = f"faster-whisper:{model_dir}"
        self._m = WhisperModel(model_dir, device=device, compute_type=compute_type, local_files_only=True)

    def transcribe(self, pcm16: bytes, sample_rate: int = 16000, language: Optional[str] = None) -> str:
        import numpy as np
        audio = np.frombuffer(pcm16, dtype=np.int16).astype("float32") / 32768.0
        segs, _ = self._m.transcribe(audio, language=language, vad_filter=True, beam_size=1)
        return " ".join(s.text.strip() for s in segs).strip()
