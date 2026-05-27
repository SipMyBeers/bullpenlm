"""RAG keystone for BullpenLM.

Per-bullpen, per-buyer vector store on top of ChromaDB + Ollama
nomic-embed-text. Closer-facing pre-call research, AI-buyer roleplay
grounding, and the substrate for every NotebookLM-style game asset
(flashcards, quizzes, briefings, account maps, infographics, data
tables).

Architecture
============

  bullpens/<slug>/
    sources/<buyer-slug>/<n>__<original-name>.{md,pdf,txt,wav,url}
    rag/                          ← ChromaDB persistent dir for this bullpen
      chroma.sqlite3              ← internal Chroma metadata DB

  Collections inside the chroma client are namespaced by buyer slug:
    "buyer__accenture-mainframe"
    "buyer__allstate"
    ...

  Each chunk stored with metadata:
    {
      "source_id":   "stable-hash-of-source-content",
      "source_name": "Accenture-Q4-Earnings-Call.pdf",
      "source_kind": "pdf" | "url" | "text" | "audio",
      "source_url":  "https://...",
      "chunk_index": 0,
      "ingested_at": ISO8601,
      "actor":       rep who dropped this source
    }

Why ChromaDB (over sqlite-vss / numpy):
  - Real persistence + metadata filters out-of-the-box
  - Collection-level isolation (per-buyer scope)
  - Scales to ~10M chunks per bullpen without sweat
  - Embedded mode (PersistentClient) — no extra process to babysit
  - Can be lifted to client/server mode later if a bullpen grows huge

Why nomic-embed-text via Ollama:
  - Already on the operator's machine (Ollama is the LLM runtime)
  - 768-dim, free, local — no Anthropic / OpenAI dep
  - Industry-standard quality for sales/customer-data RAG
  - Fast (~50ms per chunk on M-series)

Game-mode integration (Phase B builds on this):
  - AI-buyer roleplay (existing): system prompt gets RAG context for the
    last user message appended before going to Gemma 2 9B.
  - Closer pre-call chat (new): same retrieval, but the model answers
    AS the closer's research assistant, not AS the buyer.
  - Flashcards / Quiz / Briefing / Mind Map / One-Sheeter: all generated
    by Gemma over a sweep of the buyer's full corpus + saved as
    artifacts in bullpens/<slug>/artifacts/<buyer>/<kind>/.

Public surface
==============

  ingest_text(bullpen, buyer, text, *, source_name, actor)
  ingest_pdf(bullpen, buyer, path, *, actor)
  ingest_url(bullpen, buyer, url, *, actor)
  ingest_audio(bullpen, buyer, path, *, actor)  # whisper → text → chunks

  search(bullpen, buyer, query, k=8) → list[{text, metadata, score}]
  context(bullpen, buyer, query, *, max_chars=2400) → str
  sources(bullpen, buyer) → list[dict]
  list_buyers(bullpen) → list[str]
  delete_source(bullpen, buyer, source_id)

  embed(text) → list[float]                          # raw embedding op
  chunk(text, *, size=1400, overlap=180) → list[str] # char-based chunker

Notes
=====
- Chunking is char-based, not token-based. 1400 char ≈ 350 tokens. Cheap,
  no tokenizer dep, fine for sales-document quality. Tune later if needed.
- Ollama embeddings endpoint: http://127.0.0.1:11434/api/embeddings.
  We retry once on connection error (Ollama can briefly hiccup during
  model load). If Ollama is down, ingestion + search both raise
  RagUnavailable — the caller surfaces this gracefully.
- All write ops emit audit events (kind=source_ingested / source_removed)
  so the firewall + XP system can see them. Per the two-ledger rules,
  source_ingested credits CLOUT-XP (volume of study), not money-XP.
"""
from __future__ import annotations
import datetime
import hashlib
import json
import re
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, Iterable

# Lazy imports for the heavyweight deps so module load doesn't crash
# in environments without them. The functions that need them raise
# RagUnavailable.
try:
    import chromadb
    from chromadb.config import Settings
    _HAVE_CHROMA = True
except Exception as e:
    _HAVE_CHROMA = False
    _CHROMA_IMPORT_ERR = str(e)

try:
    import pypdf
    _HAVE_PYPDF = True
except Exception as e:
    _HAVE_PYPDF = False

try:
    import trafilatura
    _HAVE_TRAFILATURA = True
except Exception:
    _HAVE_TRAFILATURA = False

REPO = Path(__file__).parent.parent
BULLPENS_ROOT = REPO / "bullpens"

OLLAMA_HOST = "http://127.0.0.1:11434"
EMBED_MODEL = "nomic-embed-text"


class RagUnavailable(RuntimeError):
    """Raised when the RAG stack (Chroma, Ollama, or a parser) can't run."""


# ── Storage layout ────────────────────────────────────────────────────────

def _bullpen_dir(bullpen: str) -> Path:
    d = BULLPENS_ROOT / bullpen
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sources_dir(bullpen: str, buyer: str) -> Path:
    d = _bullpen_dir(bullpen) / "sources" / buyer
    d.mkdir(parents=True, exist_ok=True)
    return d


def _rag_dir(bullpen: str) -> Path:
    d = _bullpen_dir(bullpen) / "rag"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Chroma client + collection management ─────────────────────────────────

_clients: dict[str, "chromadb.PersistentClient"] = {}  # noqa: F821


def _client(bullpen: str):
    if not _HAVE_CHROMA:
        raise RagUnavailable(f"chromadb not importable: {_CHROMA_IMPORT_ERR}")
    if bullpen not in _clients:
        _clients[bullpen] = chromadb.PersistentClient(
            path=str(_rag_dir(bullpen)),
            settings=Settings(anonymized_telemetry=False, allow_reset=False),
        )
    return _clients[bullpen]


def _collection(bullpen: str, buyer: str):
    """Return (creating if needed) the per-buyer collection."""
    name = f"buyer__{buyer}"
    c = _client(bullpen)
    return c.get_or_create_collection(
        name=name,
        metadata={"buyer_slug": buyer, "hnsw:space": "cosine"},
    )


# ── Embedding (via Ollama) ────────────────────────────────────────────────

def _ollama_embed(text: str) -> list[float]:
    """Single-text embedding via Ollama. Raises RagUnavailable on failure."""
    body = json.dumps({"model": EMBED_MODEL, "prompt": text}).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/embeddings",
        data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    last_err = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
                emb = data.get("embedding")
                if not emb:
                    raise RagUnavailable("Ollama returned no embedding")
                return emb
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            last_err = e
            if attempt == 0:
                continue
    raise RagUnavailable(f"Ollama embeddings unreachable: {last_err}")


def embed(text: str) -> list[float]:
    """Public single-text embed."""
    return _ollama_embed(text)


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a batch. Ollama's API is one-at-a-time today, so we sequence.
    Caller should chunk large batches sensibly."""
    return [_ollama_embed(t) for t in texts]


# ── Chunking ──────────────────────────────────────────────────────────────

def chunk(text: str, *, size: int = 1400, overlap: int = 180) -> list[str]:
    """Char-based chunker with sentence-boundary preference.

    Tries to break at \\n\\n (paragraph), then \\n, then ". ", else hard
    cut. Keeps `overlap` chars on either side. Filters chunks smaller
    than 80 chars (likely empty or noise).
    """
    text = text.replace("\r\n", "\n").strip()
    if len(text) <= size:
        return [text] if text else []

    chunks: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        end = min(i + size, n)
        if end < n:
            # Walk back to a clean break point
            window = text[i:end]
            for sep in ("\n\n", "\n", ". "):
                idx = window.rfind(sep)
                if idx > size * 0.5:
                    end = i + idx + len(sep)
                    break
        chunk_text = text[i:end].strip()
        if len(chunk_text) >= 80:
            chunks.append(chunk_text)
        if end >= n:
            break
        i = max(end - overlap, i + 1)
    return chunks


# ── Source loading ────────────────────────────────────────────────────────

def _load_pdf(path: Path) -> str:
    if not _HAVE_PYPDF:
        raise RagUnavailable("pypdf not installed")
    reader = pypdf.PdfReader(str(path))
    out: list[str] = []
    for page in reader.pages:
        try:
            t = page.extract_text() or ""
        except Exception:
            t = ""
        if t.strip():
            out.append(t.strip())
    return "\n\n".join(out)


def _load_url(url: str) -> tuple[str, str]:
    """Fetch a URL + return (clean_text, page_title). Uses trafilatura if
    available for clean article extraction; falls back to raw HTML."""
    if _HAVE_TRAFILATURA:
        downloaded = trafilatura.fetch_url(url, no_ssl=True)
        if downloaded:
            text = trafilatura.extract(
                downloaded, include_comments=False, include_tables=True,
                favor_recall=True,
            ) or ""
            meta = trafilatura.extract_metadata(downloaded)
            title = (meta.title if meta else None) or url
            if text.strip():
                return text.strip(), title
    # Fallback — plain HTTP fetch, strip tags
    req = urllib.request.Request(url, headers={"User-Agent": "BullpenLM-RAG/0.1"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    text = re.sub(r"<script.*?</script>", "", html, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", "", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text, url


def _load_audio_via_whisper(path: Path) -> str:
    """Transcribe via the existing call-transcription path."""
    try:
        from server import transcribe_wav  # type: ignore
    except Exception:
        raise RagUnavailable("transcribe_wav not importable from server.py")
    return transcribe_wav(path.read_bytes())


# ── Ingestion ─────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _source_id(text: str, name: str) -> str:
    """Stable id from content sha + name."""
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"{re.sub(r'[^a-zA-Z0-9_-]', '-', name)[:48]}__{h}"


def _audit(bullpen: str, actor: str, kind: str, payload: dict) -> None:
    try:
        from audit import append as audit_append
        audit_append(bullpen, actor, kind, target_type="rag", target_id=payload.get("source_id", ""), payload=payload)
    except Exception:
        pass


def _store_chunks(
    bullpen: str, buyer: str, *, chunks_text: list[str],
    base_metadata: dict, source_id: str,
) -> int:
    if not chunks_text:
        return 0
    embeddings = embed_batch(chunks_text)
    ids = [f"{source_id}__c{i:04d}" for i in range(len(chunks_text))]
    metadatas = [
        dict(base_metadata, chunk_index=i, source_id=source_id)
        for i in range(len(chunks_text))
    ]
    col = _collection(bullpen, buyer)
    # Idempotent: delete prior chunks for this source first (re-ingest case)
    try:
        col.delete(where={"source_id": source_id})
    except Exception:
        pass
    col.add(
        ids=ids, documents=chunks_text, embeddings=embeddings, metadatas=metadatas,
    )
    # ChromaDB's in-process HNSW index cache can lag behind disk after a
    # write — subsequent queries in the same process can hit
    # "Error creating hnsw segment reader: Nothing found on disk". Clear
    # the cached client so the next access reopens against fresh state.
    _clients.pop(bullpen, None)
    return len(chunks_text)


def ingest_text(
    bullpen: str, buyer: str, text: str,
    *, source_name: str = "pasted-text.md",
    actor: str = "operator",
    extra_metadata: Optional[dict] = None,
) -> dict:
    """Drop a blob of text/markdown as a source.

    Returns {source_id, source_name, chunks, ingested_at}.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("empty text")
    sid = _source_id(text, source_name)
    chunks_text = chunk(text)
    md = {
        "source_name": source_name,
        "source_kind": "text",
        "ingested_at": _now(),
        "actor": actor,
        **(extra_metadata or {}),
    }
    n = _store_chunks(bullpen, buyer, chunks_text=chunks_text, base_metadata=md, source_id=sid)
    # Mirror the raw text to disk for portability + re-ingest
    (_sources_dir(bullpen, buyer) / f"{sid}.md").write_text(text, encoding="utf-8")
    rec = {"source_id": sid, "source_name": source_name, "chunks": n,
           "ingested_at": md["ingested_at"], "source_kind": "text"}
    _audit(bullpen, actor, "source_ingested", {**rec, "buyer": buyer})
    return rec


def ingest_pdf(bullpen: str, buyer: str, path: Path | str, *, actor: str = "operator") -> dict:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    text = _load_pdf(path)
    if not text.strip():
        raise ValueError(f"no extractable text in {path.name}")
    sid = _source_id(text, path.name)
    chunks_text = chunk(text)
    md = {
        "source_name": path.name, "source_kind": "pdf",
        "ingested_at": _now(), "actor": actor,
    }
    n = _store_chunks(bullpen, buyer, chunks_text=chunks_text, base_metadata=md, source_id=sid)
    # Keep the original PDF too
    target = _sources_dir(bullpen, buyer) / f"{sid}.pdf"
    if str(path.resolve()) != str(target.resolve()):
        target.write_bytes(path.read_bytes())
    rec = {"source_id": sid, "source_name": path.name, "chunks": n,
           "ingested_at": md["ingested_at"], "source_kind": "pdf"}
    _audit(bullpen, actor, "source_ingested", {**rec, "buyer": buyer})
    return rec


def ingest_url(bullpen: str, buyer: str, url: str, *, actor: str = "operator") -> dict:
    text, title = _load_url(url)
    if not text.strip():
        raise ValueError(f"no extractable text at {url}")
    sid = _source_id(text, url)
    chunks_text = chunk(text)
    md = {
        "source_name": title, "source_kind": "url",
        "source_url": url, "ingested_at": _now(), "actor": actor,
    }
    n = _store_chunks(bullpen, buyer, chunks_text=chunks_text, base_metadata=md, source_id=sid)
    (_sources_dir(bullpen, buyer) / f"{sid}.url.txt").write_text(
        f"# {title}\n{url}\n\n{text}", encoding="utf-8"
    )
    rec = {"source_id": sid, "source_name": title, "source_url": url,
           "chunks": n, "ingested_at": md["ingested_at"], "source_kind": "url"}
    _audit(bullpen, actor, "source_ingested", {**rec, "buyer": buyer})
    return rec


def ingest_audio(bullpen: str, buyer: str, path: Path | str, *, actor: str = "operator") -> dict:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    transcript = _load_audio_via_whisper(path)
    if not transcript.strip():
        raise ValueError(f"empty transcript for {path.name}")
    sid = _source_id(transcript, path.name)
    chunks_text = chunk(transcript)
    md = {
        "source_name": path.name, "source_kind": "audio",
        "ingested_at": _now(), "actor": actor,
    }
    n = _store_chunks(bullpen, buyer, chunks_text=chunks_text, base_metadata=md, source_id=sid)
    # Preserve original audio + the transcript text
    target = _sources_dir(bullpen, buyer) / f"{sid}{path.suffix}"
    if str(path.resolve()) != str(target.resolve()):
        target.write_bytes(path.read_bytes())
    (_sources_dir(bullpen, buyer) / f"{sid}.transcript.txt").write_text(
        transcript, encoding="utf-8"
    )
    rec = {"source_id": sid, "source_name": path.name, "chunks": n,
           "ingested_at": md["ingested_at"], "source_kind": "audio"}
    _audit(bullpen, actor, "source_ingested", {**rec, "buyer": buyer})
    return rec


# ── Retrieval ─────────────────────────────────────────────────────────────

def search(bullpen: str, buyer: str, query: str, *, k: int = 8) -> list[dict]:
    """Semantic search across one buyer's corpus."""
    if not query.strip():
        return []
    try:
        col = _collection(bullpen, buyer)
    except Exception:
        return []
    if col.count() == 0:
        return []
    q_emb = _ollama_embed(query)
    res = col.query(query_embeddings=[q_emb], n_results=k)
    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]
    out = []
    for i, doc in enumerate(docs):
        out.append({
            "text": doc,
            "metadata": metas[i] if i < len(metas) else {},
            "score": (1.0 - float(dists[i])) if i < len(dists) else None,
        })
    return out


def context(bullpen: str, buyer: str, query: str, *, max_chars: int = 2400) -> str:
    """Build a context string for system-prompt injection. Returns a
    bulleted block of chunks under `max_chars`, with source attribution."""
    hits = search(bullpen, buyer, query, k=10)
    if not hits:
        return ""
    out: list[str] = ["[REFERENCE MATERIAL FROM THE BUYER'S DOSSIER]"]
    used = 0
    for h in hits:
        meta = h.get("metadata") or {}
        src = meta.get("source_name") or meta.get("source_kind") or "source"
        block = f'\n- (from "{src}") {h["text"]}'
        if used + len(block) > max_chars:
            break
        out.append(block)
        used += len(block)
    out.append("\n[/REFERENCE MATERIAL]")
    return "".join(out)


# ── Listing / management ──────────────────────────────────────────────────

def sources(bullpen: str, buyer: str) -> list[dict]:
    """List all unique sources for a buyer. Aggregates chunks → sources."""
    try:
        col = _collection(bullpen, buyer)
    except Exception:
        return []
    if col.count() == 0:
        return []
    res = col.get(include=["metadatas"])
    by_source: dict[str, dict] = {}
    for meta in (res.get("metadatas") or []):
        if not meta:
            continue
        sid = meta.get("source_id")
        if not sid:
            continue
        if sid in by_source:
            by_source[sid]["chunks"] += 1
        else:
            by_source[sid] = {
                "source_id": sid,
                "source_name": meta.get("source_name"),
                "source_kind": meta.get("source_kind"),
                "source_url": meta.get("source_url"),
                "ingested_at": meta.get("ingested_at"),
                "actor": meta.get("actor"),
                "chunks": 1,
            }
    out = list(by_source.values())
    out.sort(key=lambda r: r.get("ingested_at") or "", reverse=True)
    return out


def list_buyers(bullpen: str) -> list[dict]:
    """Every buyer that has any source ingested in this bullpen."""
    try:
        c = _client(bullpen)
        cols = c.list_collections()
    except Exception:
        return []
    out: list[dict] = []
    for col_obj in cols:
        col = c.get_collection(col_obj.name)
        slug = (col.metadata or {}).get("buyer_slug")
        if not slug:
            # Decode from name prefix
            if col.name.startswith("buyer__"):
                slug = col.name[len("buyer__"):]
            else:
                continue
        out.append({"buyer_slug": slug, "chunks": col.count()})
    out.sort(key=lambda r: -r["chunks"])
    return out


def delete_source(bullpen: str, buyer: str, source_id: str, *, actor: str = "operator") -> dict:
    col = _collection(bullpen, buyer)
    col.delete(where={"source_id": source_id})
    # Best-effort cleanup of mirrored files
    for ext in (".md", ".pdf", ".url.txt", ".transcript.txt"):
        f = _sources_dir(bullpen, buyer) / f"{source_id}{ext}"
        if f.exists():
            try: f.unlink()
            except Exception: pass
    _audit(bullpen, actor, "source_removed", {"source_id": source_id, "buyer": buyer})
    return {"ok": True, "source_id": source_id}


# ── Stats / health ────────────────────────────────────────────────────────

def stats(bullpen: str) -> dict:
    out = {
        "bullpen": bullpen,
        "chroma_available": _HAVE_CHROMA,
        "pypdf_available": _HAVE_PYPDF,
        "trafilatura_available": _HAVE_TRAFILATURA,
        "embed_model": EMBED_MODEL,
        "ollama_host": OLLAMA_HOST,
        "buyers": [],
        "total_chunks": 0,
    }
    if not _HAVE_CHROMA:
        out["error"] = _CHROMA_IMPORT_ERR
        return out
    # Probe ollama
    try:
        urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=2).read()
        out["ollama_reachable"] = True
    except Exception as e:
        out["ollama_reachable"] = False
        out["ollama_error"] = str(e)
    buyers = list_buyers(bullpen)
    out["buyers"] = buyers
    out["total_chunks"] = sum(b["chunks"] for b in buyers)
    return out


# ── CLI ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 server/rag.py stats <bullpen>")
        print("  python3 server/rag.py ingest-text <bullpen> <buyer> <name> < input.md")
        print("  python3 server/rag.py ingest-pdf  <bullpen> <buyer> <path>")
        print("  python3 server/rag.py ingest-url  <bullpen> <buyer> <url>")
        print("  python3 server/rag.py search <bullpen> <buyer> <query>")
        print("  python3 server/rag.py context <bullpen> <buyer> <query>")
        print("  python3 server/rag.py sources <bullpen> <buyer>")
        sys.exit(0)
    cmd = sys.argv[1]
    try:
        if cmd == "stats":
            print(json.dumps(stats(sys.argv[2]), indent=2))
        elif cmd == "ingest-text":
            bp, buyer, name = sys.argv[2], sys.argv[3], sys.argv[4]
            text = sys.stdin.read()
            print(json.dumps(ingest_text(bp, buyer, text, source_name=name, actor="cli"), indent=2))
        elif cmd == "ingest-pdf":
            print(json.dumps(ingest_pdf(sys.argv[2], sys.argv[3], sys.argv[4], actor="cli"), indent=2))
        elif cmd == "ingest-url":
            print(json.dumps(ingest_url(sys.argv[2], sys.argv[3], sys.argv[4], actor="cli"), indent=2))
        elif cmd == "search":
            print(json.dumps(search(sys.argv[2], sys.argv[3], " ".join(sys.argv[4:])), indent=2))
        elif cmd == "context":
            print(context(sys.argv[2], sys.argv[3], " ".join(sys.argv[4:])))
        elif cmd == "sources":
            print(json.dumps(sources(sys.argv[2], sys.argv[3]), indent=2))
        else:
            print(f"× unknown command: {cmd}", file=sys.stderr); sys.exit(1)
    except (RagUnavailable, ValueError, FileNotFoundError) as e:
        print(f"× {e}", file=sys.stderr); sys.exit(2)
