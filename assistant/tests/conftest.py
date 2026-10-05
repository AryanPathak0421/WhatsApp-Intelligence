import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wa_assistant.backend import BackendClient          # noqa: E402
from wa_assistant.config import Settings                # noqa: E402
from wa_assistant.eval.fake_backend import create_app, standard_world   # noqa: E402
from wa_assistant.factory import build_assistant        # noqa: E402


@pytest.fixture(params=["asyncio"])
def anyio_backend(request):
    return request.param


class Env:
    def __init__(self, tmp_path, llm, documents=None, **settings):
        self.world, self.ids = standard_world()
        self.backend = BackendClient("http://fake", transport=httpx.ASGITransport(app=create_app(self.world)))
        self.a = build_assistant(llm, self.backend, Settings(**{"audit_file": str(tmp_path / "audit.jsonl"), **settings}), documents,
                                 audit_path=str(tmp_path / "audit.jsonl"))

    def session(self, who="pm"):
        u = self.world.users[self.ids[who]]
        return self.a.sessions.get_or_create(None, u["id"], u["role"], self.ids[f"tok_{who}"])

    async def say(self, session, text, **kw):
        return await self.a.agent.run_turn(session, text, **kw)


@pytest.fixture
def make_env(tmp_path):
    def make(llm, documents=None, **settings):
        return Env(tmp_path, llm, documents, **settings)
    return make
