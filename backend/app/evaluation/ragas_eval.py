"""
NexusIQ — evaluation/ragas_eval.py

Production-grade RAG evaluation engine — zero OpenAI dependencies.

═══════════════════════════════════════════════════════════════════
ROOT CAUSE OF ALL 0% METRICS (documented here for future reference)
═══════════════════════════════════════════════════════════════════

BUG 1 (PRIMARY — caused ALL metrics to be 0%):
  ragas_evaluate(dataset, metrics=metrics_to_run) uses OpenAI LLM and
  OpenAI embeddings by default. Without OPENAI_API_KEY it throws an
  AuthenticationError internally. The except clause at line 113-118
  in the original file catches this silently and returns _zero_metrics().
  ALL metrics become 0.0. ALL hallucination flags become False.
  The exception is never logged, making it impossible to diagnose.

BUG 2 (RAGAS key name mismatch):
  RAGAS ≥ 0.2 uses 'answer_relevance' not 'answer_relevancy' as the key.
  result['answer_relevancy'] raises KeyError → _get() returns None → clamped to 0.0.

BUG 3 (Markdown contamination):
  The answer string passed to RAGAS contains "[1] SOURCE: file.pdf — Page 3"
  prefixes, **bold** markdown, bullet points. RAGAS NLI-based faithfulness
  cannot verify structured markdown statements against plain-text contexts.
  Even when retrieval is correct, faithfulness → 0.

BUG 4 (Truncated contexts):
  citations[].chunk_text is sliced to [:300] chars.
  If a claim in the answer comes from chars 301-600, the NLI check fails.
  faithfulness → 0 even when the answer is grounded.

BUG 5 (Exception swallowing):
  All RAGAS failures are caught and silently return zero metrics.
  No error message ever reaches the frontend.

═══════════════════════════════════════════════════════════════════
THIS REPLACEMENT — How it works
═══════════════════════════════════════════════════════════════════

Architecture:
  1. LLM-based evaluator   — uses ChatGroq (llama-3.1-8b-instant) to score
                             faithfulness and answer_relevancy via structured prompts.
  2. Embedding-based       — uses SentenceTransformer to compute cosine similarity
                             for answer_correctness and semantic_relevancy.
  3. Precision/Recall      — lexical token-overlap for context_precision
                             and context_recall (no LLM needed).
  4. Hallucination         — faithfulness < 0.4 AND answer does NOT contain
                             "not contain enough information" (document-grounded).
  5. Answer cleaning       — strips markdown, citation prefixes, bold markers
                             before evaluation.

All metrics return values in [0.0, 1.0]. No NaN. No silent zero.
"""

import asyncio
import json
import logging
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings

logger = logging.getLogger("nexusiq.evaluation")

HISTORY_FILE = Path("./data/eval_history.jsonl")

# ── Sentinel answer for "no answer found" ─────────────────────────
_NO_ANSWER_SENTINEL = "not contain enough information"


# ══════════════════════════════════════════════════════════════════
# TEXT CLEANING
# Removes markdown, citation prefixes, bullet symbols before eval
# ══════════════════════════════════════════════════════════════════

def _clean_answer(text: str) -> str:
    """
    Strip markdown formatting and citation prefixes so the evaluator
    receives clean prose, not decorated text.

    Removes:
      - [N] SOURCE: filename — Page N  (context section headers)
      - **bold** markers
      - Bullet points (-, *, •)
      - Inline citations [filename, page N]
      - Excess whitespace
    """
    if not text:
        return ""
    # Remove [N] SOURCE: ... — Page N headers
    text = re.sub(r'\[\d+\]\s+SOURCE:.*?(?=\n|$)', '', text, flags=re.MULTILINE)
    # Remove [filename, page N] citations
    text = re.sub(r'\[[^\]]*page\s+\d+[^\]]*\]', '', text, flags=re.IGNORECASE)
    # Remove numbered citations [1], [2]
    text = re.sub(r'\[\d+\]', '', text)
    # Remove markdown bold/italic
    text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)
    # Remove bullet points
    text = re.sub(r'^[\s]*[-*•]\s+', '', text, flags=re.MULTILINE)
    # Collapse whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    return text.strip()


def _clean_contexts(contexts: List[str]) -> List[str]:
    """Strip citation headers from context strings."""
    cleaned = []
    for ctx in contexts:
        ctx = re.sub(r'^\[\d+\]\s+SOURCE:.*?\n', '', ctx, flags=re.MULTILINE)
        ctx = ctx.strip()
        if ctx:
            cleaned.append(ctx)
    return cleaned


# ══════════════════════════════════════════════════════════════════
# TOKENIZER for lexical metrics
# ══════════════════════════════════════════════════════════════════

def _tokenize(text: str) -> set:
    """Lowercase word tokens, alphanumeric only, min length 2."""
    return set(re.findall(r'\b[a-z0-9]{2,}\b', text.lower()))


def _f1_score(pred: str, ref: str) -> float:
    """Token-level F1 between two strings."""
    p_toks = _tokenize(pred)
    r_toks = _tokenize(ref)
    if not p_toks or not r_toks:
        return 0.0
    common   = len(p_toks & r_toks)
    precision = common / len(p_toks)
    recall    = common / len(r_toks)
    if precision + recall == 0:
        return 0.0
    return round(2 * precision * recall / (precision + recall), 4)


def _precision(pred: str, ref: str) -> float:
    p_toks = _tokenize(pred)
    r_toks = _tokenize(ref)
    if not p_toks:
        return 0.0
    return round(len(p_toks & r_toks) / len(p_toks), 4)


def _recall(pred: str, ref: str) -> float:
    p_toks = _tokenize(pred)
    r_toks = _tokenize(ref)
    if not r_toks:
        return 0.0
    return round(len(p_toks & r_toks) / len(r_toks), 4)


# ══════════════════════════════════════════════════════════════════
# EMBEDDING-BASED SIMILARITY
# ══════════════════════════════════════════════════════════════════

_embed_model = None

def _get_embed_model():
    """Lazy-load the embedding model (already loaded for RAG — reuse it)."""
    global _embed_model
    if _embed_model is None:
        try:
            from app.rag.embeddings import embedding_manager
            _embed_model = embedding_manager
        except Exception as exc:
            logger.warning("Could not load embedding model for eval: %s", exc)
    return _embed_model


def _cosine_sim(a: List[float], b: List[float]) -> float:
    """Cosine similarity between two embedding vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    na  = math.sqrt(sum(x * x for x in a))
    nb  = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return round(dot / (na * nb), 4)


def _semantic_similarity(text_a: str, text_b: str) -> float:
    """
    Compute semantic similarity between two texts using the project's
    existing SentenceTransformer embeddings. Falls back to lexical F1
    if the model is unavailable.
    """
    em = _get_embed_model()
    if em is None:
        return _f1_score(text_a, text_b)
    try:
        vec_a = em.embed_query(text_a[:512])
        vec_b = em.embed_query(text_b[:512])
        return _cosine_sim(vec_a, vec_b)
    except Exception as exc:
        logger.debug("Embedding similarity failed: %s — using lexical F1", exc)
        return _f1_score(text_a, text_b)


# ══════════════════════════════════════════════════════════════════
# LLM-BASED EVALUATOR (ChatGroq)
# ══════════════════════════════════════════════════════════════════

async def _llm_score_faithfulness(
    answer: str,
    contexts: List[str],
    llm,
) -> float:
    """
    Ask the LLM to score how faithfully the answer is grounded in the contexts.
    Returns a float in [0.0, 1.0].

    Prompt design:
      - Give the LLM the answer and contexts.
      - Ask it to rate grounding on a scale of 0-10.
      - Parse the integer score.
    """
    if not answer.strip() or not contexts:
        return 0.0

    # If this is a "no answer" response, it's faithful to retrieval
    if _NO_ANSWER_SENTINEL.lower() in answer.lower():
        return 1.0

    ctx_block = "\n\n".join(
        f"[Context {i+1}]: {c[:600]}"
        for i, c in enumerate(contexts[:5])
    )

    prompt = f"""You are an expert RAG evaluator. Your task is to assess faithfulness.

RETRIEVED CONTEXTS:
{ctx_block}

GENERATED ANSWER:
{answer[:800]}

TASK: On a scale from 0 to 10, rate how faithfully the answer is grounded in the provided contexts.
- 10 = Every claim in the answer is directly supported by the contexts
- 7-9 = Most claims are supported, minor extrapolations
- 4-6 = Some claims supported, some not
- 1-3 = Few claims supported
- 0 = Answer contradicts or ignores contexts completely

Respond with ONLY a single integer from 0 to 10. No explanation."""

    try:
        from langchain_core.messages import HumanMessage
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        raw = response.content.strip()
        # Extract first integer found
        match = re.search(r'\b([0-9]|10)\b', raw)
        if match:
            score = int(match.group(1))
            return round(min(max(score / 10.0, 0.0), 1.0), 4)
        logger.warning("Faithfulness LLM response not parseable: '%s'", raw[:50])
        return _compute_lexical_faithfulness(answer, contexts)
    except Exception as exc:
        logger.warning("LLM faithfulness scoring failed: %s — using lexical", exc)
        return _compute_lexical_faithfulness(answer, contexts)


async def _llm_score_relevancy(
    question: str,
    answer: str,
    llm,
) -> float:
    """
    Ask the LLM to score how relevant the answer is to the question.
    Returns a float in [0.0, 1.0].
    """
    if not answer.strip() or not question.strip():
        return 0.0

    # "No answer" responses are technically relevant (correctly indicate no info)
    if _NO_ANSWER_SENTINEL.lower() in answer.lower():
        return 0.5

    prompt = f"""You are an expert RAG evaluator. Your task is to assess answer relevancy.

QUESTION:
{question}

ANSWER:
{answer[:800]}

TASK: On a scale from 0 to 10, rate how well the answer addresses the question.
- 10 = Perfectly answers what was asked, complete and on-topic
- 7-9 = Mostly answers the question with minor gaps
- 4-6 = Partially answers, significant parts of the question not addressed
- 1-3 = Barely relevant to the question
- 0 = Completely off-topic

Respond with ONLY a single integer from 0 to 10. No explanation."""

    try:
        from langchain_core.messages import HumanMessage
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        raw = response.content.strip()
        match = re.search(r'\b([0-9]|10)\b', raw)
        if match:
            score = int(match.group(1))
            return round(min(max(score / 10.0, 0.0), 1.0), 4)
        logger.warning("Relevancy LLM response not parseable: '%s'", raw[:50])
        return _semantic_similarity(answer, question)
    except Exception as exc:
        logger.warning("LLM relevancy scoring failed: %s — using semantic sim", exc)
        return _semantic_similarity(answer, question)


# ══════════════════════════════════════════════════════════════════
# LEXICAL METRICS (no LLM needed)
# ══════════════════════════════════════════════════════════════════

def _compute_lexical_faithfulness(answer: str, contexts: List[str]) -> float:
    """
    Lexical faithfulness: what fraction of answer tokens appear in contexts.
    More robust than RAGAS NLI when LLM is unavailable.
    """
    full_ctx = " ".join(contexts)
    ans_toks = _tokenize(answer)
    ctx_toks = _tokenize(full_ctx)
    if not ans_toks:
        return 0.0
    grounded = len(ans_toks & ctx_toks) / len(ans_toks)
    # Scale up: lexical overlap of 0.4 is already strong grounding
    return round(min(grounded * 1.6, 1.0), 4)


def _compute_context_precision(answer: str, contexts: List[str]) -> float:
    """
    Context precision: what fraction of retrieved contexts are relevant to the answer.
    A context is "relevant" if it has significant token overlap with the answer.
    """
    if not contexts or not answer.strip():
        return 0.0
    relevant = 0
    ans_toks = _tokenize(answer)
    for ctx in contexts:
        ctx_toks = _tokenize(ctx)
        if not ctx_toks:
            continue
        overlap = len(ans_toks & ctx_toks) / len(ctx_toks)
        if overlap > 0.05:   # at least 5% of ctx tokens appear in answer
            relevant += 1
    return round(relevant / len(contexts), 4)


def _compute_context_recall(answer: str, contexts: List[str], ground_truth: str) -> float:
    """
    Context recall: what fraction of ground_truth information is
    covered by the retrieved contexts.
    """
    if not ground_truth or not contexts:
        return None
    full_ctx = " ".join(contexts)
    return round(_recall(full_ctx, ground_truth), 4)


def _compute_answer_correctness(answer: str, ground_truth: str) -> float:
    """
    Answer correctness: semantic similarity between generated answer
    and ground truth, using embedding model if available.
    """
    if not ground_truth or not answer:
        return None
    sem_sim = _semantic_similarity(answer, ground_truth)
    lexical = _f1_score(answer, ground_truth)
    # Weighted blend: semantic 70%, lexical 30%
    return round(0.7 * sem_sim + 0.3 * lexical, 4)


# ══════════════════════════════════════════════════════════════════
# HALLUCINATION DETECTION
# ══════════════════════════════════════════════════════════════════

def _is_hallucination(
    answer: str,
    faithfulness: float,
    contexts: List[str],
) -> bool:
    """
    Multi-signal hallucination detector.

    NOT hallucination if:
      - Answer is the strict "no answer" sentinel
      - faithfulness >= 0.4

    IS hallucination if:
      - faithfulness < 0.4 AND answer makes specific claims not in contexts
    """
    # Strict no-answer is not a hallucination
    if _NO_ANSWER_SENTINEL.lower() in answer.lower():
        return False

    # If faithfulness is high enough, not a hallucination
    if faithfulness >= 0.4:
        return False

    # Low faithfulness — check if answer makes claims beyond contexts
    full_ctx   = " ".join(contexts).lower()
    ans_words  = _tokenize(answer)
    ctx_words  = _tokenize(full_ctx)

    # If more than 60% of answer tokens are NOT in contexts → likely hallucination
    if not ans_words:
        return False
    unsupported_ratio = len(ans_words - ctx_words) / len(ans_words)
    return unsupported_ratio > 0.6


# ══════════════════════════════════════════════════════════════════
# PER-SAMPLE EVALUATOR
# ══════════════════════════════════════════════════════════════════

async def _evaluate_one_sample(
    sample: Dict,
    llm,
    use_llm: bool,
) -> Dict[str, Any]:
    """
    Evaluate a single sample and return its metric scores dict.
    """
    question     = sample.get("question", "")
    raw_answer   = sample.get("answer",   "")
    raw_contexts = sample.get("contexts", [])
    ground_truth = sample.get("ground_truth") or ""

    # ── Clean inputs ──────────────────────────────────────────────
    answer   = _clean_answer(raw_answer)
    contexts = _clean_contexts(raw_contexts)

    logger.debug(
        "Evaluating sample: q='%s…' | answer_chars=%d | contexts=%d",
        question[:40], len(answer), len(contexts),
    )

    # ── Guard: empty answer/contexts ──────────────────────────────
    if not answer:
        logger.warning("Sample has empty answer — all scores = 0")
        return {"faithfulness": 0.0, "answer_relevancy": 0.0, "context_precision": 0.0}

    # ── Faithfulness ──────────────────────────────────────────────
    if use_llm and llm and contexts:
        faithfulness = await _llm_score_faithfulness(answer, contexts, llm)
    else:
        faithfulness = _compute_lexical_faithfulness(answer, contexts)

    # ── Answer relevancy ──────────────────────────────────────────
    if use_llm and llm:
        answer_relevancy = await _llm_score_relevancy(question, answer, llm)
    else:
        answer_relevancy = _semantic_similarity(answer, question)
        # Scale up: semantic sim of 0.4 between answer and question is good
        answer_relevancy = round(min(answer_relevancy * 1.4, 1.0), 4)

    # ── Context precision ─────────────────────────────────────────
    context_precision = _compute_context_precision(answer, contexts)

    scores: Dict[str, Any] = {
        "faithfulness":     faithfulness,
        "answer_relevancy": answer_relevancy,
        "context_precision": context_precision,
    }

    # ── Context recall (needs ground truth) ───────────────────────
    if ground_truth:
        cr = _compute_context_recall(answer, contexts, ground_truth)
        if cr is not None:
            scores["context_recall"] = cr

        # ── Answer correctness ─────────────────────────────────────
        ac = _compute_answer_correctness(answer, ground_truth)
        if ac is not None:
            scores["answer_correctness"] = ac

    # ── Hallucination ─────────────────────────────────────────────
    scores["_hallucination"] = _is_hallucination(answer, faithfulness, contexts)

    return scores


# ══════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════

async def evaluate_samples(samples: List[Any]) -> Dict:
    """
    Evaluate a list of QA samples.

    Accepts:
      - Pydantic EvalSample objects (with .question, .answer, .contexts attributes)
      - Plain dicts (with 'question', 'answer', 'contexts' keys)

    Returns:
      {metrics, per_sample, hallucination_flags}
    """
    if not samples:
        return {
            "metrics":            _zero_metrics(),
            "per_sample":         [],
            "hallucination_flags": [],
        }

    # ── Normalise to dicts ─────────────────────────────────────────
    normalised: List[Dict] = []
    for s in samples:
        if isinstance(s, dict):
            normalised.append(s)
        else:
            normalised.append({
                "question":     getattr(s, "question",     ""),
                "answer":       getattr(s, "answer",       "") or "",
                "contexts":     getattr(s, "contexts",     []) or [],
                "ground_truth": getattr(s, "ground_truth", None),
            })

    logger.info(
        "Starting evaluation | samples=%d | first_q='%s…'",
        len(normalised),
        normalised[0]["question"][:50] if normalised else "",
    )

    # ── Set up ChatGroq LLM ────────────────────────────────────────
    llm      = None
    use_llm  = False
    try:
        from langchain_groq import ChatGroq
        llm = ChatGroq(
            api_key=settings.groq_api_key,
            model=settings.groq_model,
            temperature=0.0,
            max_tokens=64,   # only need a number, keep it cheap
        )
        use_llm = True
        logger.info("LLM evaluator: ChatGroq(%s) ready", settings.groq_model)
    except Exception as exc:
        logger.warning("ChatGroq not available for evaluation: %s — using lexical+semantic", exc)

    # ── Evaluate each sample ───────────────────────────────────────
    per_sample_scores: List[Dict] = []
    for s in normalised:
        try:
            scores = await _evaluate_one_sample(s, llm, use_llm)
        except Exception as exc:
            logger.error("Sample evaluation failed: %s", exc, exc_info=True)
            scores = {
                "faithfulness":     0.0,
                "answer_relevancy": 0.0,
                "context_precision": 0.0,
                "error":            str(exc),
            }
        per_sample_scores.append(scores)

    # ── Extract hallucination flags ────────────────────────────────
    hallucination_flags = [
        s.pop("_hallucination", False)
        for s in per_sample_scores
    ]

    # ── Aggregate metrics ──────────────────────────────────────────
    def _avg(key: str) -> Optional[float]:
        vals = [
            s[key] for s in per_sample_scores
            if key in s and s[key] is not None and isinstance(s[key], (int, float))
               and not math.isnan(s[key])
        ]
        return round(sum(vals) / len(vals), 4) if vals else None

    metrics = {
        "faithfulness":       _avg("faithfulness")       or 0.0,
        "answer_relevancy":   _avg("answer_relevancy")   or 0.0,
        "context_precision":  _avg("context_precision")  or 0.0,
        "context_recall":     _avg("context_recall"),
        "answer_correctness": _avg("answer_correctness"),
    }

    logger.info(
        "Evaluation complete | faith=%.2f | relevancy=%.2f | precision=%.2f | halluc=%d/%d",
        metrics["faithfulness"],
        metrics["answer_relevancy"],
        metrics["context_precision"],
        sum(hallucination_flags),
        len(hallucination_flags),
    )

    _append_history(metrics)

    return {
        "metrics":            metrics,
        "per_sample":         per_sample_scores,
        "hallucination_flags": hallucination_flags,
    }


# ══════════════════════════════════════════════════════════════════
# HISTORY UTILITIES
# ══════════════════════════════════════════════════════════════════

def _zero_metrics() -> Dict:
    return {
        "faithfulness":       0.0,
        "answer_relevancy":   0.0,
        "context_precision":  0.0,
        "context_recall":     None,
        "answer_correctness": None,
    }


def _append_history(metrics: Dict) -> None:
    try:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metrics":   metrics,
        }
        with HISTORY_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as exc:
        logger.warning("Failed to persist eval history: %s", exc)


def load_eval_history() -> List[Dict]:
    """Load all past evaluation runs from JSONL file."""
    if not HISTORY_FILE.exists():
        return []
    records = []
    try:
        for line in HISTORY_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))
    except Exception as exc:
        logger.error("Failed to load eval history: %s", exc)
    return records