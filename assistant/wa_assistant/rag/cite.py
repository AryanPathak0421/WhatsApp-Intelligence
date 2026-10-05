"""Grounding and citation checking. Citations are produced by THIS code from chunk metadata, never by the model.

The model is told to mark claims with [C1], [C2]... (the numbers of the passages it was given). After generation:
  * markers that do not exist in the retrieved set are removed;
  * long quotations must appear verbatim in a cited passage, otherwise the quote marks are removed and the issue is reported;
  * DOIs / URLs in the answer that are not in the retrieved metadata are removed (a model invents these);
  * the reference list is built from stored metadata (authors not recorded are shown as such, not guessed);
  * an answer that uses retrieved material but cites nothing is labelled unverified.
Abstention happens BEFORE generation when the best reranked relevance is below the threshold.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

MARK = re.compile(r"\[(C\d+(?:\s*,\s*C\d+)*)\]")
QUOTE = re.compile(r"[\"“]([^\"”]{25,400})[\"”]")
DOI = re.compile(r"\b10\.\d{4,9}/[^\s\"<>\]\)]+", re.I)
URL = re.compile(r"https?://[^\s\"<>\])]+")
ABSTAIN = "I don't have enough verified information to answer that confidently."


@dataclass
class FinalAnswer:
    text: str
    citations: list[dict] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    abstained: bool = False


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", s.lower())).strip()


def context_block(results: list[dict]) -> str:
    """Passages for the model: numbered, wrapped as untrusted data (closing tag neutralised so a document cannot break out of the wrapper)."""
    blocks = []
    for r in results:
        body = r["text"].replace("</passage>", "<\\/passage>")
        blocks.append(f"<passage id=\"{r['citation']}\" doc=\"{r['title'][:120]}\" year=\"{r['year'] or 'n/a'}\" page=\"{r['page'] or 'n/a'}\">{body}</passage>")
    return "\n".join(blocks)


def _reference(r: dict) -> str:
    authors = ", ".join(r["authors"]) if r["authors"] else "authors not recorded"
    bits = [f"[{r['citation']}] {r['title']} - {authors}" + (f" ({r['year']})" if r["year"] else "")]
    if r.get("doi"):
        bits.append(f"DOI: {r['doi']}")
    if r.get("source_url"):
        bits.append(r["source_url"])
    if r.get("page"):
        bits.append(f"p. {r['page']}")
    return ", ".join(bits)


def finalize(answer: str, results: list[dict]) -> FinalAnswer:
    by_id = {r["citation"]: r for r in results}
    issues: list[str] = []
    used: list[str] = []

    def fix_marker(m):
        ids = [x.strip() for x in m.group(1).split(",")]
        good = [i for i in ids if i in by_id]
        bad = [i for i in ids if i not in by_id]
        if bad:
            issues.append(f"removed citation(s) {', '.join(bad)} that do not exist in the retrieved passages")
        used.extend(good)
        return f"[{', '.join(good)}]" if good else ""

    text = MARK.sub(fix_marker, answer)
    used = list(dict.fromkeys(used))
    cited_text = _norm(" ".join(by_id[i]["text"] + " " + by_id[i]["context"] for i in used))

    def check_quote(m):
        if _norm(m.group(1)) in cited_text:
            return m.group(0)
        issues.append("a quotation that does not appear in the cited passages was un-quoted")
        return m.group(1)

    text = QUOTE.sub(check_quote, text)
    known_dois = {(r["doi"] or "").lower() for r in results}
    known_urls = {r["source_url"] for r in results if r.get("source_url")}
    if DOI.search(text) or URL.search(text):
        def drop_doi(m):
            if m.group(0).lower().rstrip(".,;") in known_dois:
                return m.group(0)
            issues.append("removed a DOI that is not in the stored metadata")
            return "[unverified DOI removed]"

        def drop_url(m):
            if m.group(0) in known_urls:
                return m.group(0)
            issues.append("removed a URL that is not in the stored metadata")
            return "[unverified link removed]"
        text = URL.sub(drop_url, DOI.sub(drop_doi, text))
    if results and not used and text.strip():
        text += "\n\n(Unverified: this answer is not tied to any retrieved passage.)"
        issues.append("no citation supports the answer")
    refs = [_reference(by_id[i]) for i in used]
    if refs:
        text += "\n\nReferences:\n" + "\n".join(refs)
    return FinalAnswer(text=text.strip(), citations=[by_id[i] for i in used], issues=list(dict.fromkeys(issues)))


def should_abstain(results: list[dict], threshold: float) -> bool:
    return not results or max(r["relevance"] for r in results) < threshold
