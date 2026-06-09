import React, { useEffect, useState } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
} from 'recharts'
import { motion, AnimatePresence } from 'framer-motion'
import { evaluationApi } from '../services/api'
import {
  RefreshCw, BarChart2, TrendingUp, AlertCircle, Activity, Award,
  Plus, Trash2, Play, BookOpen, ChevronDown, ChevronUp,
  CheckCircle2, Loader2, XCircle,
} from 'lucide-react'

/* ─────────────────────────────────────────────────────────────────
   CONSTANTS
───────────────────────────────────────────────────────────────── */
const METRIC_CFG = {
  faithfulness:       { label: 'Faithfulness',       color: '#4a90e2' },
  answer_relevancy:   { label: 'Answer Relevancy',   color: '#9b87f5' },
  context_precision:  { label: 'Context Precision',  color: '#3ecf8e' },
  context_recall:     { label: 'Context Recall',     color: '#e09c43' },
  answer_correctness: { label: 'Answer Correctness', color: '#e25c6a' },
}
const CHART_COLORS = ['#4a90e2', '#9b87f5', '#3ecf8e', '#e09c43', '#e25c6a']

const EXAMPLE_SAMPLES = [
  {
    question:     'Is merge sort stable?',
    ground_truth: 'Yes, merge sort is stable because it preserves the relative order of equal elements during the merge step.',
  },
  {
    question:     'What mistake causes overflow in binary search?',
    ground_truth: 'Using mid = (low + high) / 2 can cause integer overflow. The correct approach is mid = low + (high - low) / 2.',
  },
  {
    question:     'Why can quick sort become O(n²)?',
    ground_truth: 'Quick sort becomes O(n²) when pivot selection creates highly unbalanced partitions, such as always picking the smallest or largest element.',
  },
]

/* ─────────────────────────────────────────────────────────────────
   METRIC CARD
───────────────────────────────────────────────────────────────── */
function MetricCard({ label, value, color, delay = 0 }) {
  const pct = value != null ? Math.round(value * 100) : null
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: .3, delay }}
      className="relative overflow-hidden rounded-2xl p-5"
      style={{
        background: 'linear-gradient(145deg, rgba(16,24,42,.92) 0%, rgba(12,18,34,.95) 100%)',
        border: '1px solid var(--border-md)',
        boxShadow: 'var(--shadow-card)',
      }}
    >
      <div
        className="absolute inset-0 opacity-40 pointer-events-none"
        style={{ background: `radial-gradient(ellipse 80% 60% at 85% 20%, ${color}15 0%, transparent 60%)` }}
      />
      <div className="relative z-10">
        <p className="text-xs uppercase tracking-widest mb-3"
          style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
          {label}
        </p>
        {pct != null ? (
          <>
            <p className="font-bold leading-none mb-4"
              style={{ color, fontFamily: 'var(--font-serif)', fontSize: '2rem' }}>
              {pct}
              <span className="text-sm font-normal ml-1" style={{ color: 'var(--text-dim)' }}>%</span>
            </p>
            <div className="rounded-full overflow-hidden" style={{ height: 4, background: 'rgba(255,255,255,.07)' }}>
              <motion.div
                initial={{ width: 0 }}
                animate={{ width: `${pct}%` }}
                transition={{ duration: .9, ease: 'easeOut', delay: delay + .2 }}
                className="h-full rounded-full"
                style={{ background: color, boxShadow: `0 0 9px ${color}65` }}
              />
            </div>
          </>
        ) : (
          <p className="text-sm" style={{ color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>N/A</p>
        )}
      </div>
    </motion.div>
  )
}

/* ─────────────────────────────────────────────────────────────────
   CHART TOOLTIP
───────────────────────────────────────────────────────────────── */
function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div className="px-4 py-3 rounded-xl"
      style={{
        background: 'rgba(10,16,30,.97)',
        border: '1px solid var(--border-md)',
        backdropFilter: 'blur(16px)',
        boxShadow: '0 8px 32px rgba(0,0,0,.5)',
      }}>
      <p className="text-xs mb-1" style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{label}</p>
      <p className="text-lg font-bold" style={{ color: payload[0].fill, fontFamily: 'var(--font-serif)' }}>
        {payload[0].value}%
      </p>
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────
   PER-SAMPLE RESULT CARD
───────────────────────────────────────────────────────────────── */
function SampleResultCard({ result, index }) {
  const [open, setOpen] = useState(false)
  const isHalluc = result.hallucination_flag

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: .2, delay: index * .05 }}
      className="rounded-xl overflow-hidden"
      style={{
        background: 'linear-gradient(145deg, rgba(14,21,38,.9) 0%, rgba(10,15,28,.95) 100%)',
        border: `1px solid ${isHalluc ? 'rgba(226,92,106,.3)' : 'var(--border)'}`,
      }}
    >
      {/* Header */}
      <div
        className="flex items-start gap-3 px-4 py-3.5 cursor-pointer select-none hover:bg-white/[.02] transition-colors"
        onClick={() => setOpen(v => !v)}
      >
        <div
          className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 text-xs font-bold tabular-nums mt-0.5"
          style={{
            background: isHalluc ? 'rgba(226,92,106,.1)' : 'rgba(74,144,226,.1)',
            border: `1px solid ${isHalluc ? 'rgba(226,92,106,.3)' : 'rgba(74,144,226,.22)'}`,
            color: isHalluc ? 'var(--rose)' : '#8bbef7',
            fontFamily: 'var(--font-mono)',
          }}
        >
          {index + 1}
        </div>

        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>
            {result.question}
          </p>
          {result.error && (
            <p className="text-xs mt-1" style={{ color: 'var(--rose)', fontFamily: 'var(--font-mono)' }}>
              ⚠ {result.error}
            </p>
          )}
        </div>

        <div className="flex items-center gap-1.5 flex-shrink-0">
          {Object.entries(result.scores || {}).slice(0, 3).map(([k, v]) => {
            if (v == null || typeof v !== 'number') return null
            const cfg = METRIC_CFG[k]
            if (!cfg) return null
            return (
              <span key={k} className="text-xs px-2 py-0.5 rounded-full tabular-nums"
                style={{
                  color: cfg.color,
                  background: `${cfg.color}14`,
                  border: `1px solid ${cfg.color}35`,
                  fontFamily: 'var(--font-mono)',
                }}>
                {Math.round(v * 100)}%
              </span>
            )
          })}
          {isHalluc && <span className="badge badge-rose">hallucination</span>}
        </div>

        {open
          ? <ChevronUp size={14} style={{ color: 'var(--text-muted)', flexShrink: 0, marginTop: 2 }} />
          : <ChevronDown size={14} style={{ color: 'var(--text-muted)', flexShrink: 0, marginTop: 2 }} />
        }
      </div>

      {/* Expanded detail */}
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: .22 }}
            className="overflow-hidden"
          >
            <div className="px-4 pb-4 space-y-3">
              <div className="divider" />

              {result.answer && (
                <div>
                  <p className="text-xs uppercase tracking-widest mb-1.5"
                    style={{ color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>
                    Generated Answer
                  </p>
                  <p className="text-sm leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                    {result.answer}
                  </p>
                </div>
              )}

              {result.ground_truth && (
                <div>
                  <p className="text-xs uppercase tracking-widest mb-1.5"
                    style={{ color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>
                    Ground Truth
                  </p>
                  <p className="text-sm leading-relaxed" style={{ color: 'var(--emerald)' }}>
                    {result.ground_truth}
                  </p>
                </div>
              )}

              {result.contexts?.length > 0 && (
                <div>
                  <p className="text-xs uppercase tracking-widest mb-1.5"
                    style={{ color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>
                    Retrieved Contexts ({result.contexts.length})
                  </p>
                  <div className="space-y-1.5">
                    {result.contexts.map((ctx, ci) => (
                      <div key={ci}
                        className="px-3 py-2 rounded-lg text-xs leading-relaxed clamp-4"
                        style={{
                          background: 'rgba(255,255,255,.03)',
                          border: '1px solid var(--border)',
                          color: 'var(--text-muted)',
                          fontFamily: 'var(--font-mono)',
                        }}>
                        [{ci + 1}] {ctx}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {result.scores && Object.keys(result.scores).length > 0 && (
                <div>
                  <p className="text-xs uppercase tracking-widest mb-2"
                    style={{ color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>
                    All Metric Scores
                  </p>
                  <div className="grid grid-cols-3 gap-2">
                    {Object.entries(result.scores).map(([k, v]) => {
                      if (v == null || typeof v !== 'number') return null
                      const cfg = METRIC_CFG[k]
                      if (!cfg) return null
                      return (
                        <div key={k} className="px-3 py-2 rounded-lg text-center"
                          style={{ background: 'rgba(255,255,255,.03)', border: '1px solid var(--border)' }}>
                          <p className="text-xs mb-1"
                            style={{ color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>
                            {cfg.label}
                          </p>
                          <p className="text-base font-bold"
                            style={{ color: cfg.color, fontFamily: 'var(--font-serif)' }}>
                            {Math.round(v * 100)}%
                          </p>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}

/* ─────────────────────────────────────────────────────────────────
   MAIN PAGE
───────────────────────────────────────────────────────────────── */
export default function EvaluationPage() {
  /* ── History state ──────────────────────────────────────────── */
  const [history, setHistory]         = useState([])
  const [histLoading, setHistLoading] = useState(true)
  const [histError, setHistError]     = useState(null)

  /* ── Form state ─────────────────────────────────────────────── */
  const [samples, setSamples]               = useState([{ id: 1, question: '', ground_truth: '' }])
  const [validationErrors, setValidationErrors] = useState({})

  /* ── Run state ──────────────────────────────────────────────── */
  const [running, setRunning]       = useState(false)
  const [runError, setRunError]     = useState(null)
  const [evalResult, setEvalResult] = useState(null)

  /* ── Load history ───────────────────────────────────────────── */
  const loadHistory = async () => {
    setHistLoading(true)
    setHistError(null)
    try {
      const r = await evaluationApi.history()
      setHistory(r.data ?? [])
    } catch (err) {
      setHistError(err.message || 'Failed to load history')
    } finally {
      setHistLoading(false)
    }
  }

  useEffect(() => { loadHistory() }, [])

  /* ── Bar chart data ─────────────────────────────────────────── */
  const displayMetrics = evalResult?.metrics ?? history[history.length - 1]?.metrics
  const barData = displayMetrics
    ? Object.entries(displayMetrics)
        .filter(([, v]) => v != null)
        .map(([k, v], i) => ({
          name:  METRIC_CFG[k]?.label ?? k.replace(/_/g, ' '),
          value: +(v * 100).toFixed(1),
          color: CHART_COLORS[i % CHART_COLORS.length],
        }))
    : []

  /* ── Sample form helpers ────────────────────────────────────── */
  const addSample = () =>
    setSamples(prev => [...prev, { id: Date.now(), question: '', ground_truth: '' }])

  const removeSample = (id) => {
    if (samples.length === 1) return
    setSamples(prev => prev.filter(s => s.id !== id))
    setValidationErrors(prev => { const n = { ...prev }; delete n[id]; return n })
  }

  const updateSample = (id, field, value) => {
    setSamples(prev => prev.map(s => s.id === id ? { ...s, [field]: value } : s))
    if (validationErrors[id]?.[field]) {
      setValidationErrors(prev => ({
        ...prev,
        [id]: { ...prev[id], [field]: undefined },
      }))
    }
  }

  const loadExamples = () => {
    setSamples(EXAMPLE_SAMPLES.map((s, i) => ({ ...s, id: Date.now() + i })))
    setValidationErrors({})
    setEvalResult(null)
    setRunError(null)
  }

  /* ── Validation ─────────────────────────────────────────────── */
  const validate = () => {
    const errors = {}
    samples.forEach(s => {
      const e = {}
      if (!s.question.trim())     e.question     = 'Required'
      if (!s.ground_truth.trim()) e.ground_truth = 'Required'
      if (Object.keys(e).length)  errors[s.id] = e
    })
    setValidationErrors(errors)
    return Object.keys(errors).length === 0
  }

  /* ── Run evaluation ─────────────────────────────────────────── */
  const runEvaluation = async () => {
    if (!validate()) return
    setRunning(true)
    setRunError(null)
    setEvalResult(null)

    try {
      const payload = {
        samples: samples.map(s => ({
          question:     s.question.trim(),
          ground_truth: s.ground_truth.trim() || undefined,
        })),
      }
      const { data } = await evaluationApi.run(payload)
      setEvalResult(data)
      await loadHistory()
    } catch (err) {
      setRunError(err.message || 'Evaluation failed — check backend logs.')
    } finally {
      setRunning(false)
    }
  }

  /* ── Result samples — prefer 'samples' field, fall back to 'per_sample' */
  const resultSamples = evalResult?.samples ?? evalResult?.per_sample ?? []

  /* ─────────────────────────────────────────────────────────────
     RENDER
  ───────────────────────────────────────────────────────────── */
  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-5xl mx-auto px-6 py-8 space-y-8">

        {/* ── Header ─────────────────────────────────────────── */}
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <h1 className="text-xl font-semibold"
              style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-serif)' }}>
              Evaluation Lab
            </h1>
            <p className="text-xs mt-1"
              style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
              Enter questions · backend runs RAG + computes metrics · no manual answers needed
            </p>
          </div>
          <motion.button
            whileHover={{ scale: 1.04 }} whileTap={{ scale: .95 }}
            onClick={loadHistory} disabled={histLoading}
            className="btn btn-ghost gap-2"
          >
            <RefreshCw size={14} className={histLoading ? 'animate-spin' : ''} />
            Refresh History
          </motion.button>
        </div>

        {/* ── QA Form ──────────────────────────────────────────── */}
        <div className="rounded-2xl p-6 space-y-5"
          style={{
            background: 'linear-gradient(145deg, rgba(16,24,42,.92) 0%, rgba(12,18,34,.95) 100%)',
            border: '1px solid var(--border-md)',
            boxShadow: 'var(--shadow-card)',
          }}>

          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg flex items-center justify-center"
              style={{ background: 'rgba(62,207,142,.12)', border: '1px solid rgba(62,207,142,.22)' }}>
              <BookOpen size={15} style={{ color: 'var(--emerald)' }} />
            </div>
            <h2 className="text-base font-semibold"
              style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-serif)' }}>
              Evaluation Samples
            </h2>
            <span className="badge badge-muted ml-auto">
              {samples.length} sample{samples.length !== 1 ? 's' : ''}
            </span>
          </div>

          <p className="text-xs" style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
            Enter a question and expected ground truth answer. The backend will automatically
            query your uploaded PDFs, generate a RAG answer, retrieve source chunks,
            and compute evaluation metrics — no manual answer needed.
          </p>

          {/* Sample rows */}
          <div className="space-y-3">
            <AnimatePresence>
              {samples.map((sample, idx) => (
                <motion.div
                  key={sample.id}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, height: 0, overflow: 'hidden' }}
                  transition={{ duration: .18 }}
                  className="rounded-xl p-4 space-y-3"
                  style={{ background: 'rgba(8,12,20,.5)', border: '1px solid var(--border)' }}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-medium"
                      style={{ color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>
                      Sample #{idx + 1}
                    </span>
                    {samples.length > 1 && (
                      <motion.button
                        whileHover={{ scale: 1.1 }} whileTap={{ scale: .9 }}
                        onClick={() => removeSample(sample.id)}
                        className="p-1.5 rounded-lg"
                        style={{ color: 'var(--rose)' }}
                      >
                        <Trash2 size={13} />
                      </motion.button>
                    )}
                  </div>

                  {/* Question */}
                  <div>
                    <label className="text-xs uppercase tracking-widest mb-1.5 block"
                      style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                      Question *
                    </label>
                    <input
                      type="text"
                      value={sample.question}
                      onChange={e => updateSample(sample.id, 'question', e.target.value)}
                      placeholder="e.g. Is merge sort stable?"
                      className="nx-input"
                      style={{
                        borderColor: validationErrors[sample.id]?.question
                          ? 'rgba(226,92,106,.55)' : undefined,
                      }}
                    />
                    {validationErrors[sample.id]?.question && (
                      <p className="text-xs mt-1" style={{ color: 'var(--rose)', fontFamily: 'var(--font-mono)' }}>
                        {validationErrors[sample.id].question}
                      </p>
                    )}
                  </div>

                  {/* Ground truth */}
                  <div>
                    <label className="text-xs uppercase tracking-widest mb-1.5 block"
                      style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                      Ground Truth Answer *
                    </label>
                    <textarea
                      value={sample.ground_truth}
                      onChange={e => updateSample(sample.id, 'ground_truth', e.target.value)}
                      placeholder="e.g. Yes, merge sort is stable because it preserves the relative order of equal elements."
                      rows={2}
                      className="nx-input resize-none"
                      style={{
                        lineHeight: '1.6',
                        borderColor: validationErrors[sample.id]?.ground_truth
                          ? 'rgba(226,92,106,.55)' : undefined,
                      }}
                    />
                    {validationErrors[sample.id]?.ground_truth && (
                      <p className="text-xs mt-1" style={{ color: 'var(--rose)', fontFamily: 'var(--font-mono)' }}>
                        {validationErrors[sample.id].ground_truth}
                      </p>
                    )}
                  </div>
                </motion.div>
              ))}
            </AnimatePresence>
          </div>

          {/* Action buttons */}
          <div className="flex items-center gap-3 flex-wrap pt-1">
            <motion.button
              whileHover={{ scale: 1.03 }} whileTap={{ scale: .95 }}
              onClick={addSample} className="btn btn-ghost gap-2">
              <Plus size={14} /> Add Sample
            </motion.button>
            <motion.button
              whileHover={{ scale: 1.03 }} whileTap={{ scale: .95 }}
              onClick={loadExamples} className="btn btn-ghost gap-2">
              <BookOpen size={14} /> Load Examples
            </motion.button>
            <div className="flex-1" />
            <motion.button
              whileHover={{ scale: 1.03 }} whileTap={{ scale: .95 }}
              onClick={runEvaluation}
              disabled={running}
              className="btn btn-primary gap-2"
              style={{ minWidth: 168 }}
            >
              {running
                ? <><Loader2 size={15} className="animate-spin" />Running…</>
                : <><Play size={15} />Run Evaluation</>
              }
            </motion.button>
          </div>
        </div>

        {/* ── Run error ─────────────────────────────────────────── */}
        <AnimatePresence>
          {runError && (
            <motion.div
              initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
              className="flex items-start gap-3 px-4 py-3 rounded-xl"
              style={{ background: 'rgba(226,92,106,.07)', border: '1px solid rgba(226,92,106,.25)' }}
            >
              <AlertCircle size={14} style={{ color: 'var(--rose)', flexShrink: 0, marginTop: 2 }} />
              <div>
                <p className="text-sm font-medium" style={{ color: 'var(--rose)' }}>Evaluation failed</p>
                <p className="text-xs mt-0.5"
                  style={{ color: 'var(--rose)', fontFamily: 'var(--font-mono)', opacity: .8 }}>
                  {runError}
                </p>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* ── Results ───────────────────────────────────────────── */}
        <AnimatePresence>
          {evalResult && (
            <motion.div
              initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}
              transition={{ duration: .35 }}
              className="space-y-6"
            >
              {/* Metric cards */}
              <div>
                <div className="flex items-center gap-2 mb-4">
                  <CheckCircle2 size={16} style={{ color: 'var(--emerald)' }} />
                  <h2 className="text-base font-semibold"
                    style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-serif)' }}>
                    Latest Run Results
                  </h2>
                  <span className="badge badge-emerald ml-auto">
                    {resultSamples.length} sample{resultSamples.length !== 1 ? 's' : ''} evaluated
                  </span>
                </div>
                <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                  {Object.entries(METRIC_CFG).map(([key, { label, color }], i) => (
                    <MetricCard
                      key={key} label={label}
                      value={evalResult.metrics[key]}
                      color={color} delay={i * .07}
                    />
                  ))}
                </div>
              </div>

              {/* Per-sample breakdown */}
              {resultSamples.length > 0 && (
                <div>
                  <h2 className="text-base font-semibold mb-3"
                    style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-serif)' }}>
                    Per-Sample Breakdown
                  </h2>
                  <div className="space-y-2">
                    {resultSamples.map((result, i) => (
                      <SampleResultCard
                        key={i}
                        result={{
                          ...result,
                          hallucination_flag: evalResult.hallucination_flags?.[i] ?? false,
                        }}
                        index={i}
                      />
                    ))}
                  </div>
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>

        {/* ── Bar chart ─────────────────────────────────────────── */}
        {barData.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}
            transition={{ duration: .4, delay: .1 }}
            className="rounded-2xl p-6"
            style={{
              background: 'linear-gradient(145deg, rgba(16,24,42,.92) 0%, rgba(12,18,34,.95) 100%)',
              border: '1px solid var(--border-md)',
              boxShadow: 'var(--shadow-card)',
            }}
          >
            <div className="flex items-center gap-3 mb-6">
              <div className="w-8 h-8 rounded-lg flex items-center justify-center"
                style={{ background: 'rgba(74,144,226,.12)', border: '1px solid rgba(74,144,226,.22)' }}>
                <BarChart2 size={15} style={{ color: '#8bbef7' }} />
              </div>
              <h2 className="text-base font-semibold"
                style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-serif)' }}>
                {evalResult ? 'Current Run Metrics' : 'Latest Saved Metrics'}
              </h2>
              <span className="badge badge-muted ml-auto">Run #{history.length}</span>
            </div>
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={barData} barSize={28}>
                <XAxis dataKey="name"
                  tick={{ fill: 'var(--text-muted)', fontSize: 11, fontFamily: 'var(--font-mono)' }}
                  axisLine={{ stroke: 'var(--border)' }} tickLine={false} />
                <YAxis domain={[0, 100]}
                  tick={{ fill: 'var(--text-muted)', fontSize: 11, fontFamily: 'var(--font-mono)' }}
                  axisLine={false} tickLine={false}
                  tickFormatter={v => `${v}%`} />
                <Tooltip content={<ChartTooltip />} cursor={{ fill: 'rgba(255,255,255,.03)' }} />
                <Bar dataKey="value" radius={[6, 6, 0, 0]}>
                  {barData.map((entry, i) => (
                    <Cell key={i} fill={entry.color}
                      style={{ filter: `drop-shadow(0 0 6px ${entry.color}60)` }} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </motion.div>
        )}

        {/* ── History table ──────────────────────────────────────── */}
        {!histLoading && history.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}
            transition={{ duration: .4, delay: .2 }}
            className="rounded-2xl p-6"
            style={{
              background: 'linear-gradient(145deg, rgba(16,24,42,.92) 0%, rgba(12,18,34,.95) 100%)',
              border: '1px solid var(--border-md)',
              boxShadow: 'var(--shadow-card)',
            }}
          >
            <div className="flex items-center gap-3 mb-5">
              <div className="w-8 h-8 rounded-lg flex items-center justify-center"
                style={{ background: 'rgba(155,135,245,.12)', border: '1px solid rgba(155,135,245,.22)' }}>
                <TrendingUp size={15} style={{ color: 'var(--lavender)' }} />
              </div>
              <h2 className="text-base font-semibold"
                style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-serif)' }}>
                Run History
              </h2>
              <span className="badge badge-muted ml-auto">{history.length} runs</span>
            </div>
            <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
              {[...history].reverse().map((entry, i) => (
                <div key={i} className="flex items-center gap-3 px-4 py-3 rounded-xl"
                  style={{ background: 'rgba(255,255,255,.025)', border: '1px solid var(--border)' }}>
                  <Activity size={12} style={{ color: 'var(--text-dim)', flexShrink: 0 }} />
                  <span className="text-xs flex-1"
                    style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                    {new Date(entry.timestamp).toLocaleString([], {
                      month: 'short', day: '2-digit',
                      hour: '2-digit', minute: '2-digit',
                    })}
                  </span>
                  <div className="flex gap-1.5">
                    {['faithfulness', 'answer_relevancy', 'context_precision'].map(k =>
                      entry.metrics[k] != null && (
                        <span key={k} className="text-xs px-2 py-0.5 rounded"
                          style={{
                            background: 'rgba(74,144,226,.08)',
                            color: '#8bbef7',
                            border: '1px solid rgba(74,144,226,.18)',
                            fontFamily: 'var(--font-mono)',
                          }}>
                          {Math.round(entry.metrics[k] * 100)}%
                        </span>
                      )
                    )}
                  </div>
                </div>
              ))}
            </div>
          </motion.div>
        )}

        {/* ── Loading skeleton ───────────────────────────────────── */}
        {histLoading && (
          <div className="grid grid-cols-3 gap-4">
            {[0, 1, 2].map(i => <div key={i} className="skeleton h-32 rounded-2xl" />)}
          </div>
        )}

        {/* ── History error ──────────────────────────────────────── */}
        {histError && (
          <div className="flex items-center gap-3 px-4 py-3 rounded-xl"
            style={{ background: 'rgba(226,92,106,.07)', border: '1px solid rgba(226,92,106,.25)' }}>
            <AlertCircle size={14} style={{ color: 'var(--rose)' }} />
            <p className="text-sm" style={{ color: 'var(--rose)', fontFamily: 'var(--font-mono)' }}>
              {histError}
            </p>
          </div>
        )}

        {/* ── Empty state ────────────────────────────────────────── */}
        {!histLoading && !evalResult && history.length === 0 && !histError && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}
            className="flex flex-col items-center justify-center py-16 gap-6 text-center rounded-2xl"
            style={{ border: '1px dashed rgba(255,255,255,.1)' }}>
            <div className="w-16 h-16 rounded-2xl flex items-center justify-center"
              style={{ background: 'rgba(255,255,255,.03)', border: '1px solid rgba(255,255,255,.08)' }}>
              <Award size={26} style={{ color: 'var(--text-dim)' }} />
            </div>
            <div>
              <p className="text-base font-semibold mb-1"
                style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-serif)' }}>
                No evaluations run yet
              </p>
              <p className="text-xs" style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                Fill in the form above and click "Run Evaluation" to begin
              </p>
            </div>
          </motion.div>
        )}

        {/* ── Footer ─────────────────────────────────────────────── */}
        <div className="pt-4 pb-2 text-center" style={{ borderTop: '1px solid var(--border)' }}>
          <p className="text-xs italic"
            style={{ color: 'var(--text-dim)', fontFamily: 'var(--font-serif)' }}>
            Developed by{' '}
            <a href="https://github.com/taj-shabreen" target="_blank" rel="noopener noreferrer"
              style={{ color: 'var(--gold-light)', textDecoration: 'none' }}
              onMouseEnter={e => { e.currentTarget.style.color = '#fff' }}
              onMouseLeave={e => { e.currentTarget.style.color = 'var(--gold-light)' }}>
              Shabreen Taj
            </a>
          </p>
        </div>

      </div>
    </div>
  )
}