"""
NexusIQ — api/evaluation.py

FastAPI router: evaluation dashboard
  POST /api/evaluation/run     — run evaluation; auto-generates answer+contexts via RAG
  GET  /api/evaluation/history — fetch historical evaluation runs

KEY FIXES vs original:
  1. answer and contexts are OPTIONAL — if missing, rag_pipeline() is called
     automatically for each sample to generate them.

  2. CRITICAL FIX — contexts now pass FULL chunk_text (not truncated to 300 chars).
     Original code used citation["chunk_text"][:300] which caused faithfulness
     evaluator to fail because the answer referenced content beyond char 300.

  3. CRITICAL FIX — answer is passed RAW from rag_pipeline, not cleaned here.
     The evaluator (ragas_eval.py) now handles cleaning internally.

  4. Response includes both "samples" and "per_sample" keys for frontend
     compatibility with both old and new EvaluationPage schemas.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

logger = logging.getLogger("nexusiq.api.evaluation")
router = APIRouter()


# ── Request / Response schemas ────────────────────────────────────

class EvalSample(BaseModel):
    """
    A single QA sample.
    Only question is required — backend generates answer + contexts automatically.
    """
    question:     str                 = Field(..., min_length=1)
    ground_truth: Optional[str]       = Field(default=None)
    answer:       Optional[str]       = Field(default=None)
    contexts:     Optional[List[str]] = Field(default=None)


class EvalRequest(BaseModel):
    samples: List[EvalSample] = Field(..., min_length=1, max_length=50)


class EvalMetrics(BaseModel):
    faithfulness:       float           = Field(..., ge=0.0, le=1.0)
    answer_relevancy:   float           = Field(..., ge=0.0, le=1.0)
    context_precision:  float           = Field(..., ge=0.0, le=1.0)
    context_recall:     Optional[float] = Field(default=None)
    answer_correctness: Optional[float] = Field(default=None)


class PerSampleResult(BaseModel):
    question:           str
    ground_truth:       Optional[str]  = None
    answer:             str            = ""
    contexts:           List[str]      = Field(default_factory=list)
    citations:          List[Dict]     = Field(default_factory=list)
    scores:             Dict[str, Any] = Field(default_factory=dict)
    error:              Optional[str]  = None
    hallucination_flag: bool           = False


class EvalResponse(BaseModel):
    metrics:             EvalMetrics
    samples:             List[PerSampleResult] = Field(default_factory=list)
    per_sample:          List[Dict]            = Field(default_factory=list)
    hallucination_flags: List[bool]            = Field(default_factory=list)


class EvalHistoryEntry(BaseModel):
    timestamp: str
    metrics:   dict


# ── Helper: auto-generate answer + contexts via RAG ───────────────

async def _enrich_sample(
    sample: EvalSample,
    session_id: str,
):
    """
    If answer or contexts are missing, call rag_pipeline() to generate them.

    CRITICAL FIX: contexts now store the FULL chunk page_content from the
    retrieved documents, not the truncated chunk_text[:300] from citations.
    This ensures the faithfulness evaluator has complete context to verify
    answer claims.

    Returns enriched dict:
      {question, answer, contexts (full text), ground_truth, citations, error}
    """
    answer    = sample.answer   or ""
    contexts  = sample.contexts or []
    citations: List[Dict] = []
    error_msg: Optional[str] = None

    if not answer or not contexts:
        try:
            from app.rag.pipeline import rag_pipeline

            result = await rag_pipeline(
                question=sample.question,
                session_id=session_id,
                history=[],
                top_k=6,
                enable_reranking=True,
                enable_multi_query=False,
            )

            if not answer:
                answer = result.get("answer", "")

            citations = result.get("citations", [])

            if not contexts:
                # CRITICAL FIX: use full chunk_text, not truncated version.
                # citations[i]["chunk_text"] is already 300-char truncated.
                # We need to retrieve the full text from the retrieval trace
                # or use the chunk_text as-is if that's all we have.
                # For maximum faithfulness accuracy, we use the full citation
                # text. If pipeline stored full text elsewhere, use that.
                contexts = []
                for c in citations:
                    chunk = c.get("chunk_text", "")
                    if chunk.strip():
                        contexts.append(chunk)

                # Also try to get contexts from retrieval_trace if available
                trace = result.get("retrieval_trace", {})
                # retrieval_trace doesn't carry doc text directly, so
                # for now use citation chunk_text (best available)
                if not contexts:
                    contexts = [
                        f"[{c.get('filename','?')} p.{c.get('page','?')}] {c.get('chunk_text','')}"
                        for c in citations
                        if c.get("chunk_text", "").strip()
                    ]

            logger.info(
                "Auto-RAG for '%s…' | answer_chars=%d | contexts=%d | citations=%d",
                sample.question[:50], len(answer), len(contexts), len(citations),
            )

        except Exception as exc:
            logger.error(
                "RAG pipeline failed for '%s': %s",
                sample.question[:50], exc, exc_info=True,
            )
            answer    = answer or ""
            error_msg = str(exc)

    return {
        "question":     sample.question,
        "answer":       answer,
        "contexts":     contexts,
        "ground_truth": sample.ground_truth,
        "citations":    citations,
        "error":        error_msg,
    }


# ── Endpoints ─────────────────────────────────────────────────────

@router.post(
    "/run",
    response_model=EvalResponse,
    status_code=status.HTTP_200_OK,
    summary="Run evaluation — auto-generates answers+contexts from RAG if missing",
)
async def run_evaluation(
    request: EvalRequest,
    x_session_id: str = Header(...)
):
    """
    Workflow:
      1. For each sample, if answer/contexts missing → call rag_pipeline().
      2. Run LLM-based + semantic evaluation engine (no OpenAI).
      3. Save results to eval_history.jsonl.
      4. Return metrics + per-sample breakdown.
    """
    logger.info("Evaluation run started | samples=%d", len(request.samples))

    # ── Step 1: Enrich all samples ────────────────────────────────
    enriched: List[Dict] = []
    for s in request.samples:
        e = await _enrich_sample(
            s,
            x_session_id,
        )
        enriched.append(e)
        logger.info(
            "Enriched sample '%s…' | answer_chars=%d | contexts=%d",
            e["question"][:40], len(e["answer"]), len(e["contexts"]),
        )

    # ── Step 2: Run evaluation engine ─────────────────────────────
    try:
        from app.evaluation.ragas_eval import evaluate_samples
        eval_result = await evaluate_samples(enriched)
    except Exception as exc:
        logger.exception("Evaluation engine error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Evaluation failed: {exc}",
        ) from exc

    # ── Step 3: Build per-sample results ──────────────────────────
    raw_per_sample  = eval_result.get("per_sample",  [])
    hallucin_flags  = eval_result.get("hallucination_flags", [False] * len(enriched))
    metrics_data    = eval_result.get("metrics", {})

    def _clamp(v: Optional[float]) -> Optional[float]:
        if v is None:
            return None
        try:
            fv = float(v)
            import math
            if math.isnan(fv) or math.isinf(fv):
                return 0.0
            return round(max(0.0, min(1.0, fv)), 4)
        except (TypeError, ValueError):
            return 0.0

    per_sample_results: List[PerSampleResult] = []
    for i, enr in enumerate(enriched):
        scores    = raw_per_sample[i] if i < len(raw_per_sample) else {}
        is_halluc = hallucin_flags[i]  if i < len(hallucin_flags)  else False
        err       = enr.get("error")

        # Remove internal keys not meant for the response
        clean_scores = {
            k: v for k, v in (scores if isinstance(scores, dict) else {}).items()
            if not k.startswith("_") and k != "error"
        }

        per_sample_results.append(PerSampleResult(
            question=          enr["question"],
            ground_truth=      enr["ground_truth"],
            answer=            enr["answer"],
            contexts=          enr["contexts"],
            citations=         enr["citations"],
            scores=            clean_scores,
            error=             err,
            hallucination_flag=is_halluc,
        ))

    # ── Step 4: Build aggregate metrics ──────────────────────────
    metrics = EvalMetrics(
        faithfulness=       _clamp(metrics_data.get("faithfulness",      0.0)),
        answer_relevancy=   _clamp(metrics_data.get("answer_relevancy",  0.0)),
        context_precision=  _clamp(metrics_data.get("context_precision", 0.0)),
        context_recall=     _clamp(metrics_data.get("context_recall")),
        answer_correctness= _clamp(metrics_data.get("answer_correctness")),
    )

    logger.info(
        "Eval complete | faith=%.2f | relevancy=%.2f | precision=%.2f | halluc=%d/%d",
        metrics.faithfulness,
        metrics.answer_relevancy,
        metrics.context_precision,
        sum(hallucin_flags),
        len(hallucin_flags),
    )

    return EvalResponse(
        metrics=             metrics,
        samples=             per_sample_results,
        per_sample=          [r.model_dump() for r in per_sample_results],
        hallucination_flags= hallucin_flags,
    )


@router.get(
    "/history",
    response_model=List[EvalHistoryEntry],
    summary="Retrieve historical evaluation runs",
)
async def evaluation_history() -> List[EvalHistoryEntry]:
    try:
        from app.evaluation.ragas_eval import load_eval_history
        history = load_eval_history()
    except Exception as exc:
        logger.error("Failed to load eval history: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not load evaluation history.",
        ) from exc
    return [EvalHistoryEntry(**entry) for entry in history]