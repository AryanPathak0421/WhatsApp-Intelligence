"""FastAPI entrypoint. Phase 2 exposes parse + annotation endpoints."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.annotation.core import AnnotationIn, AnnotationStore, build_queue
from app.intelligence.pipeline import analyze
from app.intelligence.types import Msg
from app.labels import ACTIVE_CATEGORIES, CATEGORIES, ENTITY_TYPES, TASK_STATUSES
from app.parsers.whatsapp import (UnsupportedFormatError, WhatsAppParser,
                                  chat_fingerprint)

MAX_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", 200 * 1024 * 1024))
ANNOTATION_FILE = os.getenv("ANNOTATION_FILE", "data/annotated/annotations.jsonl")

app = FastAPI(title="WA Intelligence Engine", version="0.3.0")


@app.middleware("http")
async def service_token(request, call_next):
    """Internal service auth: when AI_ENGINE_TOKEN is set every /ai/* call must carry it."""
    token = os.getenv("AI_ENGINE_TOKEN")
    if token and request.url.path.startswith("/ai/"):
        import hmac
        if not hmac.compare_digest(request.headers.get("x-service-token", ""), token):
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return await call_next(request)
store = AnnotationStore(ANNOTATION_FILE)
_STATIC = Path(__file__).parent / "static"


def _msg_json(m):
    return {"messageId": m.message_id, "index": m.index, "timestamp": m.timestamp.isoformat(),
            "senderName": m.sender_name, "senderPhone": m.sender_phone, "message": m.text,
            "rawText": m.raw_text, "messageType": m.message_type, "isSystemMessage": m.is_system,
            "isMedia": m.is_media, "mediaKind": m.media_kind, "isDeleted": m.is_deleted,
            "isEdited": m.is_edited, "isForwarded": m.is_forwarded, "urls": m.urls,
            "replyContext": m.reply_context}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ai/parse")
async def parse(file: UploadFile = File(...), limit: int = 0):
    """Parse an export. ``limit`` > 0 returns only the first N messages (preview)."""
    if not (file.filename or "").lower().endswith(".txt"):
        raise HTTPException(415, "Only WhatsApp .txt exports are supported.")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as tmp:
        size = 0
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > MAX_BYTES:
                os.unlink(tmp.name)
                raise HTTPException(413, "File too large.")
            tmp.write(chunk)
    try:
        parser = WhatsAppParser()
        msgs = []
        for m in parser.parse_file(tmp.name):
            msgs.append(_msg_json(m))
            if limit and len(msgs) >= limit:
                break
        r = parser.report
        return {"fingerprint": chat_fingerprint(tmp.name), "messages": msgs,
                "report": {"messages": r.messages, "dateOrder": r.date_order,
                           "dateOrderAmbiguous": r.date_order_ambiguous, "clock": r.clock,
                           "headerStyle": r.header_style, "warnings": r.warnings[:20],
                           "senders": dict(r.senders)}}
    except UnsupportedFormatError as e:
        raise HTTPException(422, str(e))
    finally:
        os.unlink(tmp.name)  # temporary upload cleanup


_clf_cache: dict = {}


def _classifier():
    """Production classifier from the model registry (MODEL_REGISTRY_DIR) or an explicit CLASSIFIER_PATH; none = rules only."""
    path = os.getenv("CLASSIFIER_PATH") or None
    if path is None:
        from app.training.registry import production_path
        path = production_path("classifier")
    if not path:
        return None
    if _clf_cache.get("path") != path:   # reload when a promotion / rollback changes the pointer
        from app.classifiers.baseline import MessageClassifier
        _clf_cache.update(path=path, model=MessageClassifier.load(path))
    return _clf_cache["model"]


def _prediction_logger():
    p = os.getenv("PREDICTION_LOG")
    if not p:
        return None
    from app.monitoring.drift import PredictionLogger
    return PredictionLogger(p)


@app.get("/ai/model")
def model_info():
    """Which model versions are serving (for audit; every prediction also carries its model_version)."""
    clf = _classifier()
    return {"classifier": clf.version if clf else None, "rules": "rules_v0.1", "embedding": os.getenv("EMBED_MODEL", "intfloat/multilingual-e5-small")}


@app.post("/ai/analyze")
async def analyze_chat(file: UploadFile = File(...)):
    """Parse + run all Phase-5 engines. Every object carries confidence, evidence ids and model version."""
    if not (file.filename or "").lower().endswith(".txt"):
        raise HTTPException(415, "Only WhatsApp .txt exports are supported.")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as tmp:
        size = 0
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > MAX_BYTES:
                os.unlink(tmp.name)
                raise HTTPException(413, "File too large.")
            tmp.write(chunk)
    try:
        msgs = [Msg.from_parsed(m) for m in WhatsAppParser().parse_file(tmp.name)]
        return analyze(msgs, classifier=_classifier())
    except UnsupportedFormatError as e:
        raise HTTPException(422, str(e))
    finally:
        os.unlink(tmp.name)


_embedder = None
_projects: dict = {}  # project_id -> ProjectSearch (worker-side cache; persistent copy lives in pgvector)


def get_embedder():
    global _embedder
    if _embedder is None:
        from app.embeddings.embedder import HashingEmbedder, HFEmbedder
        name = os.getenv("EMBED_MODEL", "intfloat/multilingual-e5-small")
        _embedder = HashingEmbedder() if name == "hashing" else HFEmbedder(name)
    return _embedder


class IndexMsg(BaseModel):
    id: str
    text: str
    sender: Optional[str] = None
    ts: datetime
    index: int = 0


class IndexReq(BaseModel):
    project_id: str
    messages: list[IndexMsg]


class SearchReq(BaseModel):
    project_id: str
    query: str
    k: int = 8
    mode: str = "hybrid"
    sender: Optional[str] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None


@app.post("/ai/embeddings")
def embeddings(texts: list[str]):
    e = get_embedder()
    return {"model": e.name, "dim": e.dim, "vectors": e.encode(texts).tolist()}


@app.post("/ai/index")
def index_messages(req: IndexReq):
    from app.search.semantic import ProjectSearch
    ps = _projects.setdefault(req.project_id, ProjectSearch(req.project_id, get_embedder()))
    added = ps.add_messages([Msg(id=m.id, ts=m.ts, sender=m.sender, text=m.text, index=m.index) for m in req.messages])
    if added:
        ps._lex()   # build the keyword index now so the first search is not slow
    return {"project_id": req.project_id, "added": added, "total": len(ps.msgs)}


@app.delete("/ai/index/{project_id}")
def drop_index(project_id: str):
    """Forget a project's search index (retention purge / erasure). Idempotent."""
    existed = _projects.pop(project_id, None) is not None
    return {"project_id": project_id, "dropped": existed}


@app.post("/ai/search")
def search(req: SearchReq):
    ps = _projects.get(req.project_id)
    if ps is None:
        raise HTTPException(404, "Project is not indexed yet.")
    if req.mode not in ("hybrid", "semantic", "lexical"):
        raise HTTPException(422, "mode must be hybrid, semantic or lexical")
    return {"model": ps.emb.name, "hits": ps.search(req.query, req.k, req.mode, req.sender, req.date_from, req.date_to)}


@app.post("/ai/graph")
async def graph(file: UploadFile = File(...)):
    from app.knowledge_graph.graph import build_graph, to_node_link
    msgs = [Msg.from_parsed(m) for m in WhatsAppParser().parse_text((await file.read()).decode("utf-8", "replace"))]
    result = analyze(msgs)
    return {"graph": to_node_link(build_graph(result, msgs)), "insights": result["insights"],
            "next_actions": result["next_actions"]}


async def _read_chat(file: UploadFile) -> list:
    if not (file.filename or "").lower().endswith(".txt"):
        raise HTTPException(415, "Only WhatsApp .txt exports are supported.")
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "File too large.")
    try:
        return [Msg.from_parsed(m) for m in WhatsAppParser().parse_text(data.decode("utf-8-sig", "replace"))]
    except UnsupportedFormatError as e:
        raise HTTPException(422, str(e))


@app.post("/ai/summarize")
async def summarize(file: UploadFile = File(...), k: int = 8):
    """Evidence-bound executive summary + extractive key messages (no external LLM)."""
    from app.summarization.executive import build_summary, verify_summary
    from app.summarization.extractive import summarize_messages
    msgs = await _read_chat(file)
    result = analyze(msgs)
    summary = build_summary(result)
    return {"summary": summary, "problems": verify_summary(summary, result), "key_messages": summarize_messages(msgs, k=k)}


@app.post("/ai/report")
async def report(file: UploadFile = File(...), format: str = "json", project: str = "Project", client: str = "",
                 company: str = "", manager: str = "", section: str = "Tasks"):
    from fastapi.responses import Response
    from app.reports import export
    from app.reports.builder import full_report
    if format not in ("json", "pdf", "xlsx", "csv"):
        raise HTTPException(422, "format must be json, pdf, xlsx or csv")
    msgs = await _read_chat(file)
    rep = full_report(analyze(msgs), msgs, {"name": project, "client": client, "company": company, "manager": manager})
    if format == "pdf":
        return Response(export.to_pdf(rep), media_type="application/pdf")
    if format == "xlsx":
        return Response(export.to_xlsx(rep), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    if format == "csv":
        if section not in export.tables(rep):
            raise HTTPException(422, "unknown section")
        return Response(export.to_csv(rep, section), media_type="text/csv")
    return Response(export.to_json(rep), media_type="application/json")


class AnalyzeReq(BaseModel):
    messages: list[IndexMsg]
    role_overrides: dict[str, str] = {}
    project_start: Optional[datetime] = None
    expected_delivery: Optional[datetime] = None
    as_of: Optional[datetime] = None
    meta: dict = {}
    project_id: str = ""
    use_semantic_linker: bool = False


def _analysis(req: AnalyzeReq):
    msgs = sorted((Msg(id=m.id, ts=m.ts, sender=m.sender, text=m.text, index=m.index) for m in req.messages),
                  key=lambda m: (m.ts, m.index))
    linker = None
    if req.use_semantic_linker:
        from app.embeddings.linker import SemanticLinker
        linker = SemanticLinker(get_embedder())
    return msgs, analyze(msgs, role_overrides=req.role_overrides, classifier=_classifier(), as_of=req.as_of,
                         project_start=req.project_start, expected_delivery=req.expected_delivery, linker=linker,
                         prediction_logger=_prediction_logger(), project_id=req.project_id)


@app.post("/ai/analyze-messages")
def analyze_messages(req: AnalyzeReq):
    """Analysis over already-parsed messages (incremental import / re-analysis / role overrides)."""
    if not req.messages:
        raise HTTPException(422, "No messages to analyze.")
    from app.reports.builder import build_timeline
    from app.summarization.executive import build_summary
    msgs, result = _analysis(req)
    result["summary"] = build_summary(result)
    result["timeline"] = build_timeline(result, msgs)
    return result


@app.post("/ai/report-messages")
def report_messages(req: AnalyzeReq):
    from app.reports.builder import full_report
    if not req.messages:
        raise HTTPException(422, "No messages to analyze.")
    msgs, result = _analysis(req)
    return full_report(result, msgs, req.meta)


class ExportReq(BaseModel):
    report: dict
    format: str = "pdf"
    section: str = "Tasks"


@app.post("/ai/export")
def export_report(req: ExportReq):
    from fastapi.responses import Response
    from app.reports import export
    try:
        if req.format == "pdf":
            return Response(export.to_pdf(req.report), media_type="application/pdf")
        if req.format == "xlsx":
            return Response(export.to_xlsx(req.report), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        if req.format == "csv":
            return Response(export.to_csv(req.report, req.section), media_type="text/csv")
        if req.format == "json":
            return Response(export.to_json(req.report), media_type="application/json")
    except KeyError:
        raise HTTPException(422, "Unknown report section.")
    raise HTTPException(422, "format must be json, pdf, xlsx or csv")


@app.get("/ai/annotation/schema")
def schema():
    return {"categories": ACTIVE_CATEGORIES, "entityTypes": ENTITY_TYPES, "statuses": TASK_STATUSES}


@app.post("/ai/annotation")
def save_annotation(a: AnnotationIn):
    return store.save(a)


@app.get("/ai/annotation")
def list_annotations(project_id: str | None = None):
    rows = list(store.latest().values())
    return [r for r in rows if project_id in (None, r["project_id"])]


_BATCH_NAME = __import__("re").compile(r"^[\w.-]{1,120}\.json$")


def _batch_dir():
    d = os.getenv("ANNOTATION_BATCH_DIR")
    return Path(d).resolve() if d else None


@app.get("/ai/annotation/batches")
def list_batches():
    """Pre-labelled batches available on the server (ANNOTATION_BATCH_DIR), so annotators pick one instead of uploading a file."""
    d = _batch_dir()
    return {"items": sorted(p.name for p in d.glob("*.json")) if d and d.is_dir() else []}


@app.get("/ai/annotation/batches/{name}")
def get_batch(name: str):
    d = _batch_dir()
    if not d or not _BATCH_NAME.match(name):      # whitelist: plain file names only, no path separators / traversal
        raise HTTPException(404, "Batch not found.")
    p = (d / name).resolve()
    if p.parent != d or not p.is_file():
        raise HTTPException(404, "Batch not found.")
    from fastapi.responses import Response
    return Response(p.read_bytes(), media_type="application/json")


@app.get("/ai/annotation/export")
def annotation_export(reviewer: str, project_id: str | None = None):
    """One reviewer's labels as JSON lines text (save as a file and feed `python -m app.evaluation.agreement a.jsonl b.jsonl`)."""
    import json as _json
    from fastapi.responses import PlainTextResponse
    lines = [_json.dumps(r, ensure_ascii=False) for r in store.latest_by(reviewer, project_id)]
    return PlainTextResponse("".join(line + chr(10) for line in lines), media_type="application/x-ndjson")


@app.get("/ai/annotation/stats")
def annotation_stats_endpoint(project_id: str | None = None):
    """How often annotators accept the pre-label, overall / per category / per confidence band."""
    from app.annotation.prelabel import annotation_stats
    return annotation_stats([r for r in store.latest().values() if project_id in (None, r["project_id"])])


@app.post("/ai/annotation/queue")
def queue(predictions: list[dict], limit: int = 200):
    return build_queue(predictions, set(store.latest().keys()), limit)


@app.get("/annotate")
def ui():
    return FileResponse(_STATIC / "annotate.html")
