"""Optional FastAPI interface. Install with: pip install -e '.[api]'"""
from __future__ import annotations
import os
from pathlib import Path
try:
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel, Field
except ImportError as exc:
    raise RuntimeError("Install the API extra: pip install -e '.[api]'") from exc
from repoatlas.analyzer import analyze_repository
from repoatlas.qa import answer_question
from repoatlas.search import search_repository

app = FastAPI(title="RepoAtlas AI", version="0.1.0",
              description="Read-only, evidence-grounded repository intelligence")
ALLOWED_ROOT = Path(os.environ.get("REPOATLAS_ROOT", ".")).resolve()

class AskRequest(BaseModel):
    path: str = "."
    question: str = Field(min_length=2, max_length=2000)
    top_k: int = Field(default=6, ge=1, le=20)

class SearchRequest(BaseModel):
    path: str = "."
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=8, ge=1, le=50)

def resolve_project_path(raw: str) -> Path:
    try:
        candidate = (ALLOWED_ROOT / raw).resolve(strict=True)
    except OSError as exc:
        raise HTTPException(status_code=400, detail="Repository path does not exist or cannot be accessed") from exc
    try:
        candidate.relative_to(ALLOWED_ROOT)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Repository path escapes configured root") from exc
    if not candidate.is_dir():
        raise HTTPException(status_code=400, detail="Repository path must be a directory")
    return candidate

@app.get("/health")
def health():
    return {"status": "ok", "service": "repoatlas-ai", "mode": "read-only"}

@app.post("/v1/scan")
def scan(payload: dict):
    path = resolve_project_path(str(payload.get("path", ".")))
    try:
        return analyze_repository(path).to_dict()
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@app.post("/v1/search")
def search(payload: SearchRequest):
    path = resolve_project_path(payload.path)
    try:
        hits = search_repository(path, payload.query, top_k=payload.top_k)
        return {"query": payload.query, "results": [{
            "path": hit.path, "start_line": hit.start_line, "end_line": hit.end_line,
            "score": hit.score, "excerpt": hit.excerpt, "reason": hit.reason,
        } for hit in hits]}
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@app.post("/v1/ask")
def ask(payload: AskRequest):
    path = resolve_project_path(payload.path)
    try:
        return answer_question(path, payload.question, top_k=payload.top_k)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
