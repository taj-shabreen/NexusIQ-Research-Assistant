import React, { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { debugApi } from '../services/api'
import {
  RefreshCw, Terminal, Cpu, Database, Search, Loader2,
  AlertCircle, CheckCircle2, XCircle, ChevronDown, ChevronUp,
  Layers, Hash, FileText, Activity,
} from 'lucide-react'

/* ─────────────────────────────────────────────────────────────────
   CONSTANTS
───────────────────────────────────────────────────────────────── */
const TOP_K_OPTIONS = [3, 6, 10, 15]
const METHOD_OPTIONS = ['hybrid', 'semantic', 'bm25']

/* ─────────────────────────────────────────────────────────────────
   STATUS INDICATOR
───────────────────────────────────────────────────────────────── */
function StatusDot({ ok }) {
  return (
    <span
      className="inline-block w-2 h-2 rounded-full"
      style={{
        background: ok ? 'var(--emerald)' : 'var(--rose)',
        boxShadow: ok
          ? '0 0 6px rgba(62,207,142,.7)'
          : '0 0 6px rgba(226,92,106,.7)',
      }}
    />
  )
}

/* ─────────────────────────────────────────────────────────────────
   INFO ROW — label / value pair
───────────────────────────────────────────────────────────────── */
function InfoRow({ label, value, valueColor }) {
  return (
    <div className="flex items-center justify-between py-2"
      style={{ borderBottom: '1px solid var(--border)' }}>
      <span className="text-xs uppercase tracking-widest"
        style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
        {label}
      </span>
      <span className="text-sm font-medium tabular-nums"
        style={{ color: valueColor ?? 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
        {value ?? '—'}
      </span>
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────
   CHUNK CARD — collapsible retrieved chunk
───────────────────────────────────────────────────────────────── */
function ChunkCard({ chunk, index }) {
  const [open, setOpen] = useState(false)

  const scoreColor =
    chunk.score == null    ? 'var(--text-muted)'
    : chunk.score > 3      ? 'var(--emerald)'
    : chunk.score > 0      ? 'var(--amber)'
    : 'var(--rose)'

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: .18, delay: index * .04 }}
      className="rounded-xl overflow-hidden"
      style={{
        background: 'linear-gradient(145deg, rgba(14,21,38,.9) 0%, rgba(10,15,28,.95) 100%)',
        border: '1px solid var(--border)',
      }}
    >
      {/* Header row */}
      <div
        className="flex items-center gap-3 px-4 py-3 cursor-pointer select-none hover:bg-white/[.02] transition-colors"
        onClick={() => setOpen(v => !v)}
      >
        {/* Rank */}
        <div
          className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 text-xs font-bold"
          style={{
            background: 'rgba(74,144,226,.1)',
            border: '1px solid rgba(74,144,226,.22)',
            color: '#8bbef7',
            fontFamily: 'var(--font-mono)',
          }}
        >
          {chunk.rank}
        </div>

        {/* Source info */}
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium truncate"
            style={{ color: 'var(--text-primary)' }}>
            {chunk.source ?? 'unknown'}
          </p>
          <p className="text-xs mt-0.5"
            style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
            Page {chunk.page ?? '?'}
          </p>
        </div>

        {/* Score */}
        {chunk.score != null && (
          <div
            className="flex-shrink-0 px-2.5 py-1 rounded-lg text-xs tabular-nums"
            style={{
              background: `${scoreColor}14`,
              border: `1px solid ${scoreColor}35`,
              color: scoreColor,
              fontFamily: 'var(--font-mono)',
            }}
          >
            score {chunk.score.toFixed(3)}
          </div>
        )}

        {open
          ? <ChevronUp size={13} style={{ color: 'var(--text-muted)', flexShrink: 0 }} />
          : <ChevronDown size={13} style={{ color: 'var(--text-muted)', flexShrink: 0 }} />
        }
      </div>

      {/* Preview text */}
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: .2 }}
            className="overflow-hidden"
          >
            <div className="px-4 pb-4">
              <div className="divider mb-3" />
              <p
                className="text-sm leading-relaxed"
                style={{
                  color: 'var(--text-secondary)',
                  fontFamily: 'var(--font-mono)',
                  whiteSpace: 'pre-wrap',
                }}
              >
                {chunk.preview || '(no preview available)'}
              </p>
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
export default function DebugPage() {

  /* ── Health state ───────────────────────────────────────────── */
  const [health, setHealth]           = useState(null)
  const [healthLoading, setHLoading]  = useState(true)
  const [healthError, setHError]      = useState(null)

  /* ── Stats state ────────────────────────────────────────────── */
  const [stats, setStats]             = useState(null)
  const [statsLoading, setSLoading]   = useState(true)
  const [statsError, setSError]       = useState(null)

  /* ── Retrieval state ────────────────────────────────────────── */
  const [query, setQuery]             = useState('')
  const [topK, setTopK]               = useState(6)
  const [method, setMethod]           = useState('hybrid')
  const [retrieving, setRetrieving]   = useState(false)
  const [retrieveResult, setResult]   = useState(null)
  const [retrieveError, setRError]    = useState(null)

  /* ── Load health + stats on mount ───────────────────────────── */
  const loadHealth = async () => {
    setHLoading(true)
    setHError(null)
    try {
      const { data } = await debugApi.health()
      setHealth(data)
    } catch (err) {
      setHError(err.message || 'Failed to load health')
    } finally {
      setHLoading(false)
    }
  }

  const loadStats = async () => {
    setSLoading(true)
    setSError(null)
    try {
      const { data } = await debugApi.stats()
      setStats(data)
    } catch (err) {
      setSError(err.message || 'Failed to load stats')
    } finally {
      setSLoading(false)
    }
  }

  const refreshAll = () => {
    loadHealth()
    loadStats()
  }

  useEffect(() => {
    loadHealth()
    loadStats()
  }, [])

  /* ── Retrieval tester ───────────────────────────────────────── */
  const runRetrieve = async () => {
    if (!query.trim()) return
    setRetrieving(true)
    setRError(null)
    setResult(null)
    try {
      const { data } = await debugApi.retrieve({
        query: query.trim(),
        top_k: topK,
        method,
      })
      setResult(data)
    } catch (err) {
      setRError(err.message || 'Retrieval failed')
    } finally {
      setRetrieving(false)
    }
  }

  /* ─────────────────────────────────────────────────────────────
     RENDER
  ───────────────────────────────────────────────────────────── */
  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-4xl mx-auto px-6 py-8 space-y-7">

        {/* ── Page header ──────────────────────────────────────── */}
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <div className="flex items-center gap-3 mb-1">
              <div
                className="w-9 h-9 rounded-xl flex items-center justify-center"
                style={{
                  background: 'rgba(62,207,142,.12)',
                  border: '1px solid rgba(62,207,142,.22)',
                }}
              >
                <Terminal size={16} style={{ color: 'var(--emerald)' }} />
              </div>
              <h1 className="text-xl font-semibold"
                style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-serif)' }}>
                Debug Console
              </h1>
            </div>
            <p className="text-xs ml-12"
              style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
              Inspect backend health · vector DB stats · test retrieval pipeline
            </p>
          </div>
          <motion.button
            whileHover={{ scale: 1.04 }} whileTap={{ scale: .95 }}
            onClick={refreshAll}
            disabled={healthLoading || statsLoading}
            className="btn btn-ghost gap-2"
          >
            <RefreshCw
              size={14}
              className={(healthLoading || statsLoading) ? 'animate-spin' : ''}
            />
            Refresh
          </motion.button>
        </div>

        {/* ── Top row: Health + Stats cards side by side ────────── */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">

          {/* Health card */}
          <div
            className="rounded-2xl p-5"
            style={{
              background: 'linear-gradient(145deg, rgba(16,24,42,.92) 0%, rgba(12,18,34,.95) 100%)',
              border: '1px solid var(--border-md)',
              boxShadow: 'var(--shadow-card)',
            }}
          >
            <div className="flex items-center gap-2.5 mb-4">
              <div className="w-7 h-7 rounded-lg flex items-center justify-center"
                style={{ background: 'rgba(74,144,226,.12)', border: '1px solid rgba(74,144,226,.22)' }}>
                <Cpu size={13} style={{ color: '#8bbef7' }} />
              </div>
              <h2 className="text-sm font-semibold"
                style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-serif)' }}>
                Backend Health
              </h2>
              {!healthLoading && health && (
                <StatusDot ok={health.status === 'ok'} />
              )}
              {healthLoading && (
                <Loader2 size={12} className="animate-spin ml-auto"
                  style={{ color: 'var(--text-dim)' }} />
              )}
            </div>

            {healthError && (
              <div className="flex items-center gap-2 px-3 py-2 rounded-lg mb-3"
                style={{ background: 'rgba(226,92,106,.07)', border: '1px solid rgba(226,92,106,.22)' }}>
                <AlertCircle size={12} style={{ color: 'var(--rose)' }} />
                <p className="text-xs" style={{ color: 'var(--rose)', fontFamily: 'var(--font-mono)' }}>
                  {healthError}
                </p>
              </div>
            )}

            {healthLoading && !health && (
              <div className="space-y-2">
                {[0, 1, 2, 3].map(i => (
                  <div key={i} className="skeleton h-7 rounded-lg" />
                ))}
              </div>
            )}

            {health && (
              <div>
                <InfoRow label="Status"    value={health.status}    valueColor="var(--emerald)" />
                <InfoRow label="LLM Model" value={health.model} />
                <InfoRow label="Embed Model" value={health.embed_model} />
                <InfoRow
                  label="Groq Key"
                  value={health.groq_key_set ? 'Configured ✓' : 'Missing ✗'}
                  valueColor={health.groq_key_set ? 'var(--emerald)' : 'var(--rose)'}
                />
                <InfoRow label="Collection" value={health.chroma_collection} />
                <InfoRow
                  label="Chunks in DB"
                  value={health.chunks_stored >= 0 ? health.chunks_stored.toString() : 'Error'}
                  valueColor={health.chunks_stored > 0 ? 'var(--sapphire)' : 'var(--amber)'}
                />
                <InfoRow label="Environment" value={health.env} />
              </div>
            )}
          </div>

          {/* Stats card */}
          <div
            className="rounded-2xl p-5"
            style={{
              background: 'linear-gradient(145deg, rgba(16,24,42,.92) 0%, rgba(12,18,34,.95) 100%)',
              border: '1px solid var(--border-md)',
              boxShadow: 'var(--shadow-card)',
            }}
          >
            <div className="flex items-center gap-2.5 mb-4">
              <div className="w-7 h-7 rounded-lg flex items-center justify-center"
                style={{ background: 'rgba(155,135,245,.12)', border: '1px solid rgba(155,135,245,.22)' }}>
                <Database size={13} style={{ color: 'var(--lavender)' }} />
              </div>
              <h2 className="text-sm font-semibold"
                style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-serif)' }}>
                Vector DB Stats
              </h2>
              {statsLoading && (
                <Loader2 size={12} className="animate-spin ml-auto"
                  style={{ color: 'var(--text-dim)' }} />
              )}
            </div>

            {statsError && (
              <div className="flex items-center gap-2 px-3 py-2 rounded-lg mb-3"
                style={{ background: 'rgba(226,92,106,.07)', border: '1px solid rgba(226,92,106,.22)' }}>
                <AlertCircle size={12} style={{ color: 'var(--rose)' }} />
                <p className="text-xs" style={{ color: 'var(--rose)', fontFamily: 'var(--font-mono)' }}>
                  {statsError}
                </p>
              </div>
            )}

            {statsLoading && !stats && (
              <div className="space-y-2">
                {[0, 1, 2, 3].map(i => (
                  <div key={i} className="skeleton h-7 rounded-lg" />
                ))}
              </div>
            )}

            {stats && (
              <div>
                <InfoRow
                  label="Total Chunks"
                  value={stats.total_chunks?.toString()}
                  valueColor={stats.total_chunks > 0 ? 'var(--sapphire)' : 'var(--amber)'}
                />
                <InfoRow
                  label="Total Documents"
                  value={stats.total_documents?.toString()}
                  valueColor={stats.total_documents > 0 ? 'var(--emerald)' : 'var(--amber)'}
                />
                <InfoRow label="Collection"   value={stats.collection_name} />
                <InfoRow label="Persist Dir"  value={stats.persist_dir} />
                <InfoRow label="Embed Model"  value={stats.embed_model} />
              </div>
            )}

            {/* Tip if no chunks */}
            {stats && stats.total_chunks === 0 && (
              <div className="mt-3 px-3 py-2 rounded-lg"
                style={{ background: 'rgba(224,156,67,.07)', border: '1px solid rgba(224,156,67,.22)' }}>
                <p className="text-xs" style={{ color: 'var(--amber)', fontFamily: 'var(--font-mono)' }}>
                  No documents indexed. Upload a PDF on the Research page first.
                </p>
              </div>
            )}
          </div>
        </div>

        {/* ── Retrieval Tester ──────────────────────────────────── */}
        <div
          className="rounded-2xl p-6 space-y-4"
          style={{
            background: 'linear-gradient(145deg, rgba(16,24,42,.92) 0%, rgba(12,18,34,.95) 100%)',
            border: '1px solid var(--border-md)',
            boxShadow: 'var(--shadow-card)',
          }}
        >
          <div className="flex items-center gap-2.5 mb-1">
            <div className="w-7 h-7 rounded-lg flex items-center justify-center"
              style={{ background: 'rgba(62,207,142,.12)', border: '1px solid rgba(62,207,142,.22)' }}>
              <Search size={13} style={{ color: 'var(--emerald)' }} />
            </div>
            <h2 className="text-sm font-semibold"
              style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-serif)' }}>
              Retrieval Tester
            </h2>
          </div>

          <p className="text-xs" style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
            Test the hybrid retrieval pipeline. Returns ranked chunks from your indexed documents
            with source file, page number, reranker score, and text preview.
          </p>

          {/* Query input */}
          <div className="flex gap-3">
            <input
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && runRetrieve()}
              placeholder="e.g. What is inversion count?"
              className="nx-input flex-1"
            />
            <motion.button
              whileHover={{ scale: 1.03 }} whileTap={{ scale: .95 }}
              onClick={runRetrieve}
              disabled={retrieving || !query.trim()}
              className="btn btn-primary flex-shrink-0 px-5"
            >
              {retrieving
                ? <Loader2 size={15} className="animate-spin" />
                : <><Search size={14} />Search</>
              }
            </motion.button>
          </div>

          {/* Method + Top-K selectors */}
          <div className="flex items-center justify-between gap-4 flex-wrap">
            {/* Method */}
            <div className="flex items-center gap-2">
              <span className="text-xs uppercase tracking-widest"
                style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', marginRight: 4 }}>
                Method
              </span>
              {METHOD_OPTIONS.map(m => (
                <button
                  key={m}
                  onClick={() => setMethod(m)}
                  className="text-xs uppercase px-3 py-1.5 rounded-lg transition-all"
                  style={{
                    fontFamily: 'var(--font-mono)',
                    ...(method === m ? {
                      background: 'rgba(74,144,226,.12)',
                      color: '#8bbef7',
                      border: '1px solid rgba(74,144,226,.38)',
                      boxShadow: '0 0 8px rgba(74,144,226,.2)',
                    } : {
                      background: 'transparent',
                      color: 'var(--text-muted)',
                      border: '1px solid var(--border)',
                    }),
                  }}
                >
                  {m}
                </button>
              ))}
            </div>

            {/* Top-K */}
            <div className="flex items-center gap-2">
              <span className="text-xs uppercase tracking-widest"
                style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', marginRight: 4 }}>
                Top-K
              </span>
              {TOP_K_OPTIONS.map(k => (
                <button
                  key={k}
                  onClick={() => setTopK(k)}
                  className="text-xs w-9 h-9 rounded-lg transition-all tabular-nums"
                  style={{
                    fontFamily: 'var(--font-mono)',
                    ...(topK === k ? {
                      background: 'rgba(155,135,245,.12)',
                      color: 'var(--lavender)',
                      border: '1px solid rgba(155,135,245,.38)',
                    } : {
                      background: 'transparent',
                      color: 'var(--text-muted)',
                      border: '1px solid var(--border)',
                    }),
                  }}
                >
                  {k}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* ── Retrieve error ────────────────────────────────────── */}
        <AnimatePresence>
          {retrieveError && (
            <motion.div
              initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
              className="flex items-center gap-3 px-4 py-3 rounded-xl"
              style={{ background: 'rgba(226,92,106,.07)', border: '1px solid rgba(226,92,106,.28)' }}
            >
              <AlertCircle size={14} style={{ color: 'var(--rose)', flexShrink: 0 }} />
              <p className="text-sm" style={{ color: 'var(--rose)', fontFamily: 'var(--font-mono)' }}>
                {retrieveError}
              </p>
            </motion.div>
          )}
        </AnimatePresence>

        {/* ── Retrieve results ──────────────────────────────────── */}
        <AnimatePresence>
          {retrieveResult && (
            <motion.div
              initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}
              transition={{ duration: .3 }}
              className="space-y-4"
            >
              {/* Stats bar */}
              <div className="grid grid-cols-3 gap-3">
                {[
                  {
                    icon: Layers,
                    label: 'Chunks returned',
                    value: retrieveResult.total_returned,
                    color: '#4a90e2',
                  },
                  {
                    icon: Activity,
                    label: 'Method',
                    value: retrieveResult.method?.toUpperCase(),
                    color: 'var(--lavender)',
                  },
                  {
                    icon: Hash,
                    label: 'Query',
                    value: `"${retrieveResult.query?.slice(0, 24)}…"`,
                    color: 'var(--emerald)',
                  },
                ].map(({ icon: Icon, label, value, color }) => (
                  <div key={label}
                    className="rounded-xl px-4 py-3.5 flex items-center gap-3"
                    style={{ background: 'rgba(14,20,36,.8)', border: '1px solid var(--border)' }}>
                    <div className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0"
                      style={{ background: `${color}16`, border: `1px solid ${color}30` }}>
                      <Icon size={13} style={{ color }} />
                    </div>
                    <div>
                      <p className="text-xs uppercase tracking-widest"
                        style={{ color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>
                        {label}
                      </p>
                      <p className="text-sm font-semibold mt-0.5" style={{ color }}>
                        {value}
                      </p>
                    </div>
                  </div>
                ))}
              </div>

              {/* Chunk cards */}
              {retrieveResult.chunks?.length > 0 ? (
                <div className="space-y-2">
                  {retrieveResult.chunks.map((chunk, i) => (
                    <ChunkCard key={i} chunk={chunk} index={i} />
                  ))}
                </div>
              ) : (
                <div
                  className="flex flex-col items-center justify-center py-12 rounded-2xl gap-3"
                  style={{ border: '1px dashed rgba(255,255,255,.1)' }}
                >
                  <FileText size={24} style={{ color: 'var(--text-dim)' }} />
                  <p className="text-sm" style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                    No chunks retrieved for this query.
                  </p>
                  <p className="text-xs" style={{ color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>
                    Make sure you have uploaded and indexed at least one PDF document.
                  </p>
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>

        {/* ── Loading skeletons (retrieval) ─────────────────────── */}
        {retrieving && (
          <div className="space-y-2">
            {[0, 1, 2, 3].map(i => (
              <div key={i} className="skeleton h-16 rounded-xl" />
            ))}
          </div>
        )}

        {/* ── Footer ─────────────────────────────────────────────── */}
        <div className="pt-4 pb-2 text-center"
          style={{ borderTop: '1px solid var(--border)' }}>
          <p className="text-xs italic"
            style={{ color: 'var(--text-dim)', fontFamily: 'var(--font-serif)' }}>
            Developed by{' '}
            <a
              href="https://github.com/taj-shabreen"
              target="_blank"
              rel="noopener noreferrer"
              style={{ color: 'var(--gold-light)', textDecoration: 'none' }}
              onMouseEnter={e => { e.currentTarget.style.color = '#fff' }}
              onMouseLeave={e => { e.currentTarget.style.color = 'var(--gold-light)' }}
            >
              Shabreen Taj
            </a>
          </p>
        </div>

      </div>
    </div>
  )
}