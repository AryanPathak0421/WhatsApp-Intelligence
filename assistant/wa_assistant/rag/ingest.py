"""Document ingestion: parse -> sections -> metadata -> parent/child chunks.

Metadata that cannot be read reliably from the file (authors, DOI when absent, publication year when absent) stays EMPTY or is supplied by the
caller. Nothing is guessed, because the answer layer prints these fields as citations and a wrong citation is worse than a missing one.
"""
from __future__ import annotations

import hashlib
import html
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from typing import Optional

DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>\]\)]+)", re.I)
YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")
SECTION_NAMES = {"abstract", "introduction", "background", "related work", "method", "methods", "methodology", "approach", "experiments", "experimental setup",
                 "results", "discussion", "evaluation", "analysis", "conclusion", "conclusions", "limitations", "references", "acknowledgements",
                 "acknowledgments", "appendix", "overview", "summary"}
HEADING_NUM = re.compile(r"^(?:\d+(?:\.\d+){0,2}\.?|[A-Z]\.)\s+([A-Z][^\n]{2,90})$")
HEADING_MD = re.compile(r"^#{1,4}\s+(.+?)\s*#*$")
MAX_CHILD, OVERLAP_SENTENCES, MAX_PARENT = 520, 1, 3000


@dataclass
class Doc:
    id: str
    scope: str                                  # "global" (shared paper library) or a project id
    title: str
    authors: list[str] = field(default_factory=list)
    year: Optional[int] = None
    doi: Optional[str] = None
    abstract: str = ""
    source_url: Optional[str] = None
    language: str = "en"
    tags: list[str] = field(default_factory=list)
    content_hash: str = ""
    n_pages: Optional[int] = None
    uploaded_by: Optional[str] = None


@dataclass
class Chunk:
    id: str
    doc_id: str
    parent_id: str
    section: str
    page: Optional[int]
    text: str
    parent_text: str


class _Strip(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "footer"):
            self._skip += 1
        if tag in ("h1", "h2", "h3", "h4"):
            self.out.append("\n## ")
        elif tag in ("p", "div", "br", "li", "tr"):
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "footer"):
            self._skip = max(0, self._skip - 1)
        if tag in ("h1", "h2", "h3", "h4", "p"):
            self.out.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.out.append(data)


def parse_bytes(data: bytes, filename: str) -> list[tuple[Optional[int], str]]:
    """Return [(page or None, text)]. PDFs are read with poppler's pdftotext (must be on PATH)."""
    name = filename.lower()
    if name.endswith(".pdf"):
        exe = shutil.which("pdftotext")
        if not exe:
            raise RuntimeError("PDF ingestion needs poppler's `pdftotext` on PATH.")
        with tempfile.TemporaryDirectory() as tmp:                      # poppler/xpdf builds differ on stdin support; a temp file works everywhere
            src = os.path.join(tmp, "in.pdf")
            with open(src, "wb") as fh:
                fh.write(data)
            r = subprocess.run([exe, "-layout", "-enc", "UTF-8", src, "-"], capture_output=True, timeout=120)
        if r.returncode != 0:
            raise ValueError("The PDF could not be parsed (corrupt or encrypted).")
        pages = r.stdout.decode("utf-8", "replace").replace("\r\n", "\n").split("\f")
        return [(i + 1, p) for i, p in enumerate(pages) if p.strip()]
    text = data.decode("utf-8", "replace")
    if name.endswith((".html", ".htm")):
        p = _Strip()
        p.feed(text)
        text = html.unescape("".join(p.out))
    return [(None, text)]


def _heading(line: str) -> Optional[str]:
    s = line.strip()
    if not s or len(s) > 100:
        return None
    m = HEADING_MD.match(s)
    if m:
        return re.sub(r"^(?:\d+(?:\.\d+){0,2}\.?|[A-Z]\.)\s+", "", m.group(1).strip())
    if s.lower().rstrip(":") in SECTION_NAMES:
        return s.rstrip(":").title()
    m = HEADING_NUM.match(s)
    if m and not s.endswith((".", ",", ";")):
        return m.group(1).strip()
    return None


def split_sections(pages: list[tuple[Optional[int], str]]) -> list[tuple[str, Optional[int], str]]:
    """[(section title, first page, text)]."""
    out, title, page0, buf = [], "Front matter", pages[0][0] if pages else None, []
    for page, text in pages:
        for line in text.splitlines():
            h = _heading(line)
            if h:
                if "".join(buf).strip():
                    out.append((title, page0, "\n".join(buf).strip()))
                title, page0, buf = h, page, []
            else:
                buf.append(line.rstrip())
                if page0 is None:
                    page0 = page
    if "".join(buf).strip():
        out.append((title, page0, "\n".join(buf).strip()))
    return out


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"(\[])", re.sub(r"[ \t]+", " ", text))
    return [p.strip() for p in parts if p.strip()]


def child_chunks(text: str) -> list[str]:
    out, cur = [], []
    for s in _sentences(re.sub(r"\n(?!\n)", " ", text)):
        if cur and sum(len(x) for x in cur) + len(s) > MAX_CHILD:
            out.append(" ".join(cur))
            cur = cur[-OVERLAP_SENTENCES:] if OVERLAP_SENTENCES else []
        cur.append(s)
    if cur:
        out.append(" ".join(cur))
    return [c for c in out if len(c) > 25]


def extract_metadata(first_text: str, filename: str) -> dict:
    head = first_text[:3000]
    lines = [l.strip() for l in head.splitlines() if l.strip()]
    title = ""
    for l in lines[:8]:
        m = HEADING_MD.match(l)
        t = m.group(1) if m else l
        if 8 <= len(t) <= 200 and not t.lower().startswith(("abstract", "http", "arxiv", "doi")):
            title = t
            break
    doi = DOI_RE.search(head)
    year = next((int(y) for y in YEAR_RE.findall(head)), None)
    abstract = ""
    m = re.search(r"(?is)\babstract\b[:\s.\-]*(.{80,1800}?)(?:\n\s*\n|\b1\.?\s+introduction\b|\bintroduction\b)", head)
    if m:
        abstract = re.sub(r"\s+", " ", m.group(1)).strip()
    return {"title": title or filename.rsplit(".", 1)[0], "doi": doi.group(1).rstrip(".,;") if doi else None, "year": year, "abstract": abstract}


def build_document(data: bytes, filename: str, *, scope: str = "global", metadata: Optional[dict] = None, uploaded_by: Optional[str] = None,
                   source_url: Optional[str] = None, tags: Optional[list] = None) -> tuple[Doc, list[Chunk]]:
    pages = parse_bytes(data, filename)
    if not pages or not "".join(t for _, t in pages).strip():
        raise ValueError("No text could be extracted from the file.")
    meta = {**extract_metadata(pages[0][1], filename), **{k: v for k, v in (metadata or {}).items() if v not in (None, "", [])}}
    digest = hashlib.sha256(data).hexdigest()
    doc = Doc(id="d_" + digest[:12], scope=scope, title=meta["title"], authors=list(meta.get("authors") or []), year=meta.get("year"), doi=meta.get("doi"),
              abstract=meta.get("abstract", ""), source_url=source_url, tags=list(tags or []), content_hash=digest,
              n_pages=pages[-1][0], uploaded_by=uploaded_by)
    chunks: list[Chunk] = []
    for si, (section, page, text) in enumerate(split_sections(pages)):
        if section.lower() in ("references", "bibliography"):
            continue                                                   # citing a reference list as evidence is almost always wrong
        paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
        parents, cur = [], ""
        for p in paras:
            if cur and len(cur) + len(p) > MAX_PARENT:
                parents.append(cur)
                cur = ""
            cur += ("\n\n" if cur else "") + p
        if cur:
            parents.append(cur)
        for pi, parent in enumerate(parents):
            pid = f"{doc.id}:p{si}.{pi}"
            for cj, c in enumerate(child_chunks(parent)):
                chunks.append(Chunk(id=f"{pid}.c{cj}", doc_id=doc.id, parent_id=pid, section=section, page=page, text=c, parent_text=parent))
    if not chunks:
        raise ValueError("The document had no usable text sections.")
    return doc, chunks


def doc_to_dict(doc: Doc) -> dict:
    return asdict(doc)
