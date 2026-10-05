# Voice (microphone) pipeline

## Target
`microphone -> voice activity detection -> noise handling -> speech-to-text -> assistant -> response -> text-to-speech`, with barge-in (user speaks, current speech stops).

## What is built (`assistant/wa_assistant/voice/`)
| Piece | State |
|---|---|
| `endpointing.py`: energy-based VAD, adaptive noise floor, utterance start/end detection, pre-roll, maximum length, **barge-in** (`interrupt` event when the user speaks while the assistant is "speaking"), turn states LISTENING / THINKING / SPEAKING | Done, 5 unit tests on synthetic audio (one utterance with pre-roll, clicks and steady loud noise ignored, two utterances separated, barge-in, length limit) |
| `adapters.py`: `ASR` / `TTS` protocols, strict WAV reader (16-bit mono only), `FasterWhisperASR` (lazy, local weights only) | Interface tested with doubles; **the real ASR class has never run** (no model, no `faster-whisper` installed) |
| `POST /assistant/voice` (WAV upload -> transcript -> same agent and policy as text) | Done; returns 501 until an ASR is configured; 400 for non-WAV; 413 over 10 MB |
| Browser microphone capture, streaming ASR, TTS playback, UI states (IDLE / LISTENING / PROCESSING / EXECUTING / SPEAKING / ERROR) | **Not built** |

## Safety rules for voice
- A spoken request goes through the same policy as typed text; it gets no extra trust.
- **Voice cannot confirm a sensitive action.** The reply says "please press Confirm on the screen". A misheard "yes" or a replayed recording must not execute anything (tested).
- Speaker identification is not used for authorization.
- Raw audio is not stored.

## Why no ASR/TTS yet
Nothing is installed or downloaded for speech; models need your approval (name, source, size) and a real measurement on your recordings first. Candidates and criteria: Whisper-family via faster-whisper
(WER/CER on English, Hindi, Hinglish, Indian accents, noise), Piper-class TTS (naturalness, latency, streaming, licence). **No WER, latency or accuracy figure exists for this system.**
On this CPU-only laptop (15.7 GB RAM) real-time conversational voice with a 7B LLM will be slow regardless; expect seconds per step.

## Next steps (in order)
1. Choose and download an ASR (e.g. a small multilingual Whisper) with your approval; record 100+ real utterances (Hindi/Hinglish/English) and measure WER.
2. Browser capture (AudioWorklet to 16 kHz mono PCM) + WebSocket/chunked upload using `Endpointer`; show the six UI states.
3. TTS and barge-in playback control; measure end-to-end latency.
