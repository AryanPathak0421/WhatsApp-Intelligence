import io
import math
import struct
import wave

import httpx
import pytest

from wa_assistant.api import create_app
from wa_assistant.llm.base import LLMOutput
from wa_assistant.llm.scripted import ScriptedLLM, call
from wa_assistant.voice.adapters import read_wav_pcm16
from wa_assistant.voice.endpointing import Endpointer, VoiceTurnState

pytestmark = pytest.mark.anyio
SR, FRAME = 16000, 480            # 30 ms


def tone(ms, amp=8000, hz=220):
    n = SR * ms // 1000
    return b"".join(struct.pack("<h", int(amp * math.sin(2 * math.pi * hz * i / SR))) for i in range(n))


def noise(ms, amp=40):
    import random
    r = random.Random(1)
    return b"".join(struct.pack("<h", r.randint(-amp, amp)) for _ in range(SR * ms // 1000))


def frames(pcm):
    return [pcm[i:i + FRAME * 2] for i in range(0, len(pcm) - FRAME * 2 + 1, FRAME * 2)]


def run(ep, pcm):
    ev = []
    for f in frames(pcm):
        ev += list(ep.feed(f))
    return ev


def test_detects_one_utterance_with_preroll_and_ends_on_silence():
    ep = Endpointer()
    ev = run(ep, noise(600) + tone(900) + noise(1000))
    kinds = [e.kind for e in ev]
    assert kinds == ["speech_start", "speech_end"]
    end = ev[1]
    assert 850 <= end.duration_ms <= 1300 and len(end.audio) > SR * 2 * 0.9
    assert ep.state == VoiceTurnState.THINKING


def test_short_clicks_and_steady_background_noise_are_ignored():
    ep = Endpointer()
    assert run(ep, noise(1500) + tone(90) + noise(800)) == []
    loud_room = Endpointer()
    assert run(loud_room, noise(3000, amp=600)) == []                  # steady loud noise raises the floor instead of triggering


def test_two_utterances_are_separated():
    ep = Endpointer()
    pcm = noise(400) + tone(600) + noise(1000) + tone(500) + noise(1000)
    ev = run(ep, pcm)
    assert [e.kind for e in ev].count("speech_end") == 2


def test_barge_in_interrupts_assistant_speech():
    ep = Endpointer()
    run(ep, noise(500))
    ep.assistant_started_speaking()
    ev = run(ep, tone(600))
    assert [e.kind for e in ev][:2] == ["interrupt", "speech_start"] and ep.state == VoiceTurnState.LISTENING


def test_very_long_speech_is_cut_at_the_limit():
    ep = Endpointer(max_utterance_ms=2000)
    ev = run(ep, noise(300) + tone(5000))
    assert any(e.kind == "speech_end" for e in ev)


def wav(pcm=b"\x00\x00" * 1600, rate=16000, ch=1):
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return b.getvalue()


def test_wav_reader_rejects_other_formats():
    assert read_wav_pcm16(wav())[1] == 16000
    with pytest.raises(ValueError):
        read_wav_pcm16(wav(ch=2))
    with pytest.raises(ValueError):
        read_wav_pcm16(b"not a wav")


class FakeASR:
    name = "fake"

    def __init__(self, text):
        self.text = text

    def transcribe(self, pcm16, sample_rate=16000, language=None):
        return self.text


def H(env, who):
    return {"Authorization": f"Bearer {env.ids['tok_' + who]}"}


async def test_voice_endpoint_needs_a_configured_model(make_env):
    env = make_env(ScriptedLLM([]))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(env.a, env.a.settings)), base_url="http://a") as c:
        r = await c.post("/assistant/voice", files={"file": ("a.wav", wav(), "audio/wav")}, headers=H(env, "pm"))
        assert r.status_code == 501


async def test_spoken_sensitive_action_still_needs_the_on_screen_confirmation(make_env):
    alpha = "11111111-aaaa-4aaa-8aaa-111111111111"
    env = make_env(ScriptedLLM([LLMOutput(tool_calls=[call("list_projects")]), LLMOutput(tool_calls=[call("list_tasks", project_id=alpha)]), LLMOutput(text="x")]))
    env.a.agent.llm.outputs.insert(2, LLMOutput(tool_calls=[call("complete_task", task_id=env.ids["t_login"])]))
    asr = FakeASR("yes yes confirm and mark the login task as completed right now")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(env.a, env.a.settings, asr=asr)), base_url="http://a") as c:
        r = (await c.post("/assistant/voice", files={"file": ("a.wav", wav(), "audio/wav")}, headers=H(env, "pm"))).json()
        assert r["transcript"].startswith("yes yes confirm") and r["pending"] and "press Confirm" in r["reply"]
        assert env.world.tasks[env.ids["t_login"]]["status"] == "TODO"
        assert (await c.post("/assistant/voice", files={"file": ("a.mp3", b"ID3", "audio/mpeg")}, headers=H(env, "pm"))).status_code == 400
