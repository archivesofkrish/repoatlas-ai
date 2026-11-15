"""Optional FastAPI interface for a local, read-only RepoAtlas workspace."""

from __future__ import annotations

import os
from pathlib import Path

try:
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel, Field
except ImportError as exc:
    raise RuntimeError("Install the API extra: pip install -e '.[api]'") from exc

from repoatlas.analyzer import analyze_repository
from repoatlas.graph import build_graph, impact_analysis
from repoatlas.qa import answer_question
from repoatlas.search import search_repository
from repoatlas.hybrid import hybrid_search_repository
from repoatlas.llm import ProviderError, generate_grounded_answer
from repoatlas.api_validation import resolve_workspace_path

app = FastAPI(
    title="RepoAtlas AI",
    version="0.5.0",
    description="Read-only repository intelligence with lexical and graph-aware evidence retrieval",
)
ALLOWED_ROOT = Path(os.environ.get("REPOATLAS_ROOT", ".")).resolve()


class RepositoryRequest(BaseModel):
    path: str = Field(default=".", min_length=1, max_length=1000)


class AskRequest(RepositoryRequest):
    question: str = Field(min_length=2, max_length=2000)
    top_k: int = Field(default=6, ge=1, le=20)


class SearchRequest(RepositoryRequest):
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=8, ge=1, le=50)


class HybridSearchRequest(SearchRequest):
    graph_depth: int = Field(default=2, ge=1, le=3, allow_inf_nan=False)
    lexical_weight: float = Field(default=0.65, ge=0.1, le=0.9, allow_inf_nan=False)


class ImpactRequest(RepositoryRequest):
    target: str = Field(min_length=1, max_length=500)
    max_depth: int = Field(default=5, ge=1, le=20)


def resolve_project_path(raw: str) -> Path:
    """Resolve a project directory strictly below the configured workspace root."""
    return resolve_workspace_path(ALLOWED_ROOT, raw)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "repoatlas-ai", "mode": "read-only"}


@app.post("/v1/scan")
def scan(payload: RepositoryRequest) -> dict:
    try:
        return analyze_repository(resolve_project_path(payload.path)).to_dict()
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/search")
def search(payload: SearchRequest) -> dict:
    try:
        hits = search_repository(
            resolve_project_path(payload.path),
            payload.query,
            top_k=payload.top_k,
        )
        return {
            "query": payload.query,
            "results": [
                {
                    "path": hit.path,
                    "start_line": hit.start_line,
                    "end_line": hit.end_line,
                    "score": hit.score,
                    "excerpt": hit.excerpt,
                    "reason": hit.reason,
                    "sha256": hit.sha256,
                    "snapshot_id": hit.snapshot_id,
                    "revision": hit.revision,
                }
                for hit in hits
            ],
        }
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/hybrid-search")
def hybrid_search_endpoint(payload: HybridSearchRequest) -> dict:
    try:
        hits = hybrid_search_repository(
            resolve_project_path(payload.path),
            payload.query,
            top_k=payload.top_k,
            graph_depth=payload.graph_depth,
            lexical_weight=payload.lexical_weight,
        )
        return {
            "retrieval": "lexical+graph",
            "query": payload.query,
            "results": [
                {
                    "path": hit.path,
                    "start_line": hit.start_line,
                    "end_line": hit.end_line,
                    "score": hit.score,
                    "excerpt": hit.excerpt,
                    "reason": hit.reason,
                    "sha256": hit.sha256,
                    "snapshot_id": hit.snapshot_id,
                    "revision": hit.revision,
                }
                for hit in hits
            ],
        }
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/ask")
def ask(payload: AskRequest) -> dict:
    try:
        return answer_question(
            resolve_project_path(payload.path),
            payload.question,
            top_k=payload.top_k,
        )
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/answer")
def answer_endpoint(payload: AskRequest) -> dict:
    try:
        return generate_grounded_answer(
            resolve_project_path(payload.path),
            payload.question,
            top_k=payload.top_k,
        )
    except ProviderError as exc:
        status_code = 503 if (
            "No model provider is configured" in str(exc)
            or "Install the optional model dependency" in str(exc)
        ) else 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/graph")
def graph_endpoint(payload: RepositoryRequest) -> dict:
    try:
        report = analyze_repository(resolve_project_path(payload.path))
        return build_graph(report)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/impact")
def impact_endpoint(payload: ImpactRequest) -> dict:
    try:
        report = analyze_repository(resolve_project_path(payload.path))
        return impact_analysis(
            build_graph(report),
            payload.target,
            max_depth=payload.max_depth,
        )
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
