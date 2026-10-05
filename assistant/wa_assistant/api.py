"""HTTP API of the assistant. Authentication is delegated to the application backend: a bearer token is valid only if the backend accepts it,
and the same token is then used for every action. The assistant never stores or logs tokens."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from .backend import BackendClient
from .config import Settings
from .factory import Assistant, build_assistant
from .llm.openai_compat import OpenAICompatClient
from .pending import PendingError
from .rag.ingest import build_document
from .rag.store import DocumentStore
from .voice.adapters import ASR, read_wav_pcm16

DOC_ROLES = {"SUPER_ADMIN", "ADMIN", "PROJECT_MANAGER"}
MAX_DOC_BYTES = 20 * 1024 * 1024
DOC_SUFFIXES = (".pdf", ".md", ".txt", ".html", ".htm")


class AppState(BaseModel):
    page: Optional[str] = Field(None, max_length=60)
    project_id: Optional[str] = Field(None, max_length=64)
    filters: Optional[dict] = None


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: Optional[str] = Field(None, max_length=64)
    app_state: Optional[AppState] = None


class ActionIn(BaseModel):
    session_id: str = Field(max_length=64)
    pending_id: str = Field(max_length=64)


class FeedbackIn(BaseModel):
    turn_id: str = Field(max_length=64)
    rating: int = Field(ge=-1, le=1)
    comment: Optional[str] = Field(None, max_length=1000)
    correction: Optional[str] = Field(None, max_length=2000)


def create_app(assistant: Optional[Assistant] = None, settings: Optional[Settings] = None, asr: Optional[ASR] = None) -> FastAPI:
    s = settings or Settings()
    if assistant is None:
        backend = BackendClient(s.backend_url)
        assistant = build_assistant(OpenAICompatClient(s.llm_base_url, s.llm_model, s.llm_timeout_s), backend, s, DocumentStore(s.docs_dir))
    A = assistant
    app = FastAPI(title="Project Intelligence assistant", version="0.1")
    token_cache: dict[str, tuple[float, dict]] = {}

    async def current_user(request: Request) -> dict:
        auth = request.headers.get("authorization", "")
        if not auth.lower().startswith("bearer "):
            raise HTTPException(401, "Sign in first.")
        token = auth[7:].strip()
        key = hashlib.sha256(token.encode()).hexdigest()
        hit = token_cache.get(key)
        if hit and time.time() - hit[0] < 30:
            return {**hit[1], "token": token}
        r = await A.backend.request("GET", "/auth/me", token)
        if not r.ok:
            raise HTTPException(401 if r.status in (401, 403) else 503, "Your session is not valid." if r.status in (401, 403) else "The application is unavailable.")
        u = (r.data or {}).get("user") or {}
        info = {"id": u.get("id"), "role": u.get("role")}
        if not info["id"]:
            raise HTTPException(401, "Your session is not valid.")
        token_cache[key] = (time.time(), info)
        if len(token_cache) > 1000:
            token_cache.clear()
        return {**info, "token": token}

    def session_for(user: dict, session_id: Optional[str]):
        return A.sessions.get_or_create(session_id, user["id"], user["role"], user["token"])

    def result_json(res) -> dict:
        d = asdict(res)
        d["citations"] = [{k: c.get(k) for k in ("citation", "title", "authors", "year", "doi", "page", "section", "source_url")} for c in res.citations]
        return d

    @app.get("/health")
    async def health():
        llm_ok = "unknown"
        try:
            async with httpx.AsyncClient(timeout=3) as c:
                r = await c.get(s.llm_base_url.rstrip("/") + "/models")
                llm_ok = "reachable" if r.status_code < 500 else "error"
        except httpx.HTTPError:
            llm_ok = "unreachable"
        return {"status": "ok", "llm": llm_ok, "model": s.llm_model}

    @app.post("/assistant/chat")
    async def chat(body: ChatIn, user: dict = Depends(current_user)):
        sess = session_for(user, body.session_id)
        try:
            res = await A.agent.run_turn(sess, body.message, body.app_state.model_dump(exclude_none=True) if body.app_state else None)
        except httpx.HTTPError:
            raise HTTPException(503, "The language model is not reachable. Check that the local model server is running.")
        return result_json(res)

    @app.post("/assistant/voice")
    async def voice(file: UploadFile = File(...), session_id: Optional[str] = Form(None), language: Optional[str] = Form(None),
                    project_id: Optional[str] = Form(None), user: dict = Depends(current_user)):
        """Spoken input = another way to type. The transcript goes through the same agent and the same policy; there is NO spoken confirmation:
        sensitive actions still need the on-screen button, because a misheard 'yes' or a replayed recording must not execute anything."""
        if asr is None:
            raise HTTPException(501, "Voice input is not configured: no local speech model is installed.")
        data = await file.read(10 * 1024 * 1024 + 1)
        if len(data) > 10 * 1024 * 1024:
            raise HTTPException(413, "Recording too long (10 MB maximum).")
        try:
            pcm, rate = read_wav_pcm16(data)
        except ValueError as e:
            raise HTTPException(400, str(e))
        text = await __import__("asyncio").to_thread(asr.transcribe, pcm, rate, language)
        if not text.strip():
            return {"transcript": "", "reply": "I didn't catch that. Please try again.", "actions": [], "pending": [], "ui_events": [], "citations": [],
                    "sources": [], "issues": [], "session_id": session_id}
        sess = session_for(user, session_id)
        try:
            res = await A.agent.run_turn(sess, text[:4000], {"project_id": project_id} if project_id else None)
        except httpx.HTTPError:
            raise HTTPException(503, "The language model is not reachable. Check that the local model server is running.")
        out = result_json(res)
        out["transcript"] = text
        if res.pending:
            out["reply"] += "\n\nThis needs your confirmation: please press Confirm on the screen."
        return out

    @app.post("/assistant/confirm")
    async def confirm(body: ActionIn, user: dict = Depends(current_user)):
        sess = A.sessions.get(body.session_id, user["id"])
        if not sess:
            raise HTTPException(404, "Session not found.")
        sess.token, sess.role = user["token"], user["role"]
        return result_json(await A.agent.confirm(sess, body.pending_id))

    @app.post("/assistant/cancel")
    async def cancel(body: ActionIn, user: dict = Depends(current_user)):
        sess = A.sessions.get(body.session_id, user["id"])
        if not sess:
            raise HTTPException(404, "Session not found.")
        return result_json(A.agent.cancel(sess, body.pending_id))

    @app.get("/assistant/pending")
    async def pending(session_id: Optional[str] = None, user: dict = Depends(current_user)):
        return {"items": [{"id": p.id, "tool": p.tool, "preview": p.preview, "tainted": p.tainted, "session_id": p.session_id,
                           "expires_in_s": max(0, int(p.expires - time.time()))} for p in A.pending.list_pending(user["id"], session_id)]}

    @app.post("/assistant/feedback")
    async def feedback(body: FeedbackIn, user: dict = Depends(current_user)):
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()), "user_id": user["id"], **body.model_dump(), "status": "needs_review"}
        with open(s.feedback_file, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return {"ok": True}

    @app.get("/assistant/documents")
    async def list_documents(user: dict = Depends(current_user)):
        docs = A.documents.docs.values() if A.documents else []
        return {"items": [{"id": d.id, "title": d.title, "year": d.year, "scope": d.scope, "n_pages": d.n_pages, "authors": d.authors, "doi": d.doi, "tags": d.tags}
                          for d in docs if d.scope == "global"]}

    @app.post("/assistant/documents", status_code=201)
    async def upload_document(file: UploadFile = File(...), scope: str = Form("global"), title: Optional[str] = Form(None), authors: Optional[str] = Form(None),
                              year: Optional[int] = Form(None), doi: Optional[str] = Form(None), tags: Optional[str] = Form(None),
                              source_url: Optional[str] = Form(None), user: dict = Depends(current_user)):
        if A.documents is None:
            raise HTTPException(501, "Document storage is not configured.")
        if user["role"] not in DOC_ROLES:
            raise HTTPException(403, "Only admins and project managers can add documents.")
        if not (file.filename or "").lower().endswith(DOC_SUFFIXES):
            raise HTTPException(400, f"Supported file types: {', '.join(DOC_SUFFIXES)}")
        if scope != "global":
            r = await A.backend.request("GET", f"/projects/{scope}", user["token"])
            if not r.ok:
                raise HTTPException(404, "Project not found.")
        data = await file.read(MAX_DOC_BYTES + 1)
        if len(data) > MAX_DOC_BYTES:
            raise HTTPException(413, "File too large (20 MB maximum).")
        meta = {"title": title, "authors": [a.strip() for a in authors.split(";") if a.strip()] if authors else None, "year": year, "doi": doi}
        try:
            doc, chunks = build_document(data, file.filename, scope=scope, metadata=meta, uploaded_by=user["id"], source_url=source_url,
                                         tags=[t.strip() for t in (tags or "").split(",") if t.strip()])
        except (ValueError, RuntimeError) as e:
            raise HTTPException(422, str(e))
        added = A.documents.add(doc, chunks)
        A.audit.write("document_ingested", user_id=user["id"], session_id="-", doc_id=doc.id, scope=scope, chunks=len(chunks), new=added)
        return {"id": doc.id, "title": doc.title, "chunks": len(chunks), "already_present": not added}

    @app.delete("/assistant/documents/{doc_id}")
    async def delete_document(doc_id: str, user: dict = Depends(current_user)):
        if user["role"] not in ("SUPER_ADMIN", "ADMIN") or A.documents is None:
            raise HTTPException(403, "Only admins can remove documents from the assistant library.")
        if not A.documents.remove(doc_id):
            raise HTTPException(404, "Document not found.")
        A.audit.write("document_removed", user_id=user["id"], session_id="-", doc_id=doc_id)
        return {"ok": True}

    return app


def main():  # pragma: no cover
    import uvicorn
    uvicorn.run(create_app(), host="127.0.0.1", port=int(__import__("os").getenv("ASSISTANT_PORT", "8100")))
