/**
 * NexusIQ — VisitorModal.jsx
 *
 * Visitor onboarding modal — shown once on first visit.
 * Collects name + optional email.
 * Saves to localStorage (no repeat shows) + POSTs to /api/visitors/register.
 *
 * Usage: Add <VisitorModal /> to App.jsx inside BrowserRouter.
 */

import React, { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Brain, X, ArrowRight, Loader2 } from 'lucide-react'
import { http } from '../services/api'

const STORAGE_KEY = 'nexusiq_visitor'

function getStoredVisitor() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

function storeVisitor(data) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(data))
  } catch {
    // storage not available — silent fail
  }
}

export function useVisitorId() {
  const stored = getStoredVisitor()
  return stored?.visitor_id ?? null
}

export default function VisitorModal() {
  const [show,     setShow]     = useState(false)
  const [name,     setName]     = useState('')
  const [email,    setEmail]    = useState('')
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState(null)
  const [nameErr,  setNameErr]  = useState(null)

  // Show modal if visitor has not registered before
  useEffect(() => {
    const stored = getStoredVisitor()
    if (!stored?.visitor_id) {
      // Short delay so page renders first
      const t = setTimeout(() => setShow(true), 1200)
      return () => clearTimeout(t)
    }
  }, [])

  const validate = () => {
    if (!name.trim()) {
      setNameErr('Please enter your name.')
      return false
    }
    setNameErr(null)
    return true
  }

  const handleSubmit = async () => {
    if (!validate()) return
    setLoading(true)
    setError(null)

    try {
      const { data } = await http.post('/visitors/register', {
        name:  name.trim(),
        email: email.trim() || undefined,
      })

      storeVisitor({
        visitor_id: data.visitor_id,
        name:       name.trim(),
        registered: new Date().toISOString(),
      })

      setShow(false)
    } catch (err) {
      // Don't block the user — save locally and close
      storeVisitor({
        visitor_id: `local_${Date.now()}`,
        name:       name.trim(),
        registered: new Date().toISOString(),
      })
      setShow(false)
    } finally {
      setLoading(false)
    }
  }

  const handleSkip = () => {
    storeVisitor({
      visitor_id: `skip_${Date.now()}`,
      name:       'Guest',
      registered: new Date().toISOString(),
    })
    setShow(false)
  }

  return (
    <AnimatePresence>
      {show && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50"
            style={{ background: 'rgba(0,0,0,.65)', backdropFilter: 'blur(6px)' }}
            onClick={handleSkip}
          />

          {/* Modal */}
          <motion.div
            initial={{ opacity: 0, scale: .92, y: 20 }}
            animate={{ opacity: 1, scale: 1,   y: 0  }}
            exit={  { opacity: 0, scale: .95,  y: 10 }}
            transition={{ duration: .25, ease: [0.34, 1.56, 0.64, 1] }}
            className="fixed inset-0 z-50 flex items-center justify-center px-4 pointer-events-none"
          >
            <div
              className="pointer-events-auto w-full max-w-md rounded-2xl p-8 relative"
              style={{
                background: 'linear-gradient(145deg, rgba(16,24,44,.98) 0%, rgba(10,16,32,.99) 100%)',
                border:     '1px solid var(--border-md)',
                boxShadow:  '0 24px 80px rgba(0,0,0,.7), 0 0 0 1px rgba(74,144,226,.12)',
              }}
              onClick={e => e.stopPropagation()}
            >
              {/* Close */}
              <button
                onClick={handleSkip}
                className="absolute top-4 right-4 p-1.5 rounded-lg opacity-50 hover:opacity-100 transition-opacity"
                style={{ color: 'var(--text-muted)' }}
              >
                <X size={15} />
              </button>

              {/* Logo */}
              <div className="flex items-center gap-3 mb-6">
                <div
                  className="w-10 h-10 rounded-xl flex items-center justify-center"
                  style={{
                    background: 'linear-gradient(135deg, rgba(74,144,226,.32) 0%, rgba(155,135,245,.28) 100%)',
                    border:     '1px solid rgba(74,144,226,.32)',
                    boxShadow:  '0 0 20px rgba(74,144,226,.2)',
                  }}
                >
                  <Brain size={19} style={{ color: '#8bbef7' }} />
                </div>
                <div>
                  <h1
                    className="text-lg font-semibold leading-none"
                    style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-serif)' }}
                  >
                    Welcome to NexusIQ
                  </h1>
                  <p className="text-xs mt-0.5"
                    style={{ color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>
                    AI-Powered Research Assistant
                  </p>
                </div>
              </div>

              <p className="text-sm mb-6"
                style={{ color: 'var(--text-muted)', lineHeight: 1.7 }}>
                Upload your PDFs and ask questions — NexusIQ retrieves cited,
                grounded answers using hybrid RAG retrieval.
                <br /><br />
                Please introduce yourself to personalise your experience.
              </p>

              {/* Name field */}
              <div className="mb-4">
                <label
                  className="text-xs uppercase tracking-widest block mb-1.5"
                  style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}
                >
                  Your Name *
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={e => { setName(e.target.value); setNameErr(null) }}
                  onKeyDown={e => e.key === 'Enter' && handleSubmit()}
                  placeholder="e.g. Shabreen"
                  className="nx-input"
                  autoFocus
                  style={{ borderColor: nameErr ? 'rgba(226,92,106,.55)' : undefined }}
                />
                {nameErr && (
                  <p className="text-xs mt-1" style={{ color: 'var(--rose)', fontFamily: 'var(--font-mono)' }}>
                    {nameErr}
                  </p>
                )}
              </div>

              {/* Email field */}
              <div className="mb-6">
                <label
                  className="text-xs uppercase tracking-widest block mb-1.5"
                  style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}
                >
                  Email <span style={{ color: 'var(--text-dim)' }}>(optional)</span>
                </label>
                <input
                  type="email"
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleSubmit()}
                  placeholder="you@example.com"
                  className="nx-input"
                />
              </div>

              {/* Error */}
              {error && (
                <p className="text-xs mb-4 px-3 py-2 rounded-lg"
                  style={{
                    color:      'var(--rose)',
                    background: 'rgba(226,92,106,.07)',
                    border:     '1px solid rgba(226,92,106,.22)',
                    fontFamily: 'var(--font-mono)',
                  }}>
                  {error}
                </p>
              )}

              {/* Actions */}
              <div className="flex items-center justify-between gap-3">
                <button
                  onClick={handleSkip}
                  className="text-sm"
                  style={{ color: 'var(--text-dim)', background: 'none', border: 'none', cursor: 'pointer' }}
                >
                  Skip for now
                </button>
                <motion.button
                  whileHover={{ scale: 1.03 }}
                  whileTap={{ scale: .96 }}
                  onClick={handleSubmit}
                  disabled={loading}
                  className="btn btn-primary gap-2"
                  style={{ minWidth: 140 }}
                >
                  {loading
                    ? <><Loader2 size={15} className="animate-spin" />Saving…</>
                    : <><ArrowRight size={15} />Get Started</>
                  }
                </motion.button>
              </div>

              {/* Privacy note */}
              <p className="text-xs mt-4 text-center"
                style={{ color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>
                Your data is stored only on this server and never shared.
              </p>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}