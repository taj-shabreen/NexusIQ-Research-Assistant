import React, { useCallback, useState } from 'react'
import { useDropzone } from 'react-dropzone'
import { Upload, CheckCircle2, AlertCircle, Loader2, FilePlus, Clock } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { useDocumentStore } from '../store/documentStore'
import { documentsApi } from '../services/api'
import { useBackend } from './Layout'

export default function DocumentUpload({ onUploaded }) {
  const {
    addDocuments,
    isUploading,
    setUploading,
    setUploadError,
    uploadError,
  } = useDocumentStore()

  const [justDone,  setJustDone]  = useState(false)
  const [progress,  setProgress]  = useState(0)   // 0-100
  const [retryMsg,  setRetryMsg]  = useState(null) // shown during retry

  /* ── Gate on backend readiness ──────────────────────────────── */
  const { backendReady, backendStatus } = useBackend()
  const blocked = !backendReady

  const onDrop = useCallback(async (accepted) => {
    if (!accepted.length) return

    if (blocked) {
      setUploadError('Backend is not ready yet. Please wait and retry.')
      setTimeout(() => setUploadError(null), 4000)
      return
    }

    setUploading(true)
    setJustDone(false)
    setProgress(0)
    setRetryMsg(null)

    try {
      for (const file of accepted) {
        const form = new FormData()
        form.append('file', file)

        const res = await documentsApi.upload(form, (evt) => {
         if (evt.total) {
          const pct = Math.round((evt.loaded / evt.total) * 100)
          setProgress(pct)

          if (pct >= 100) {
            setRetryMsg(`Indexing ${file.name}...`)
          }
        }
      })

     addDocuments([
        {
          filename: res.data.filename,
          chunks: res.data.chunks,
        },
     ])
   }

   setJustDone(true)
   setProgress(0)
   setRetryMsg(null)

   setTimeout(() => setJustDone(false), 4000)

   onUploaded?.()
 } catch (err) {
     setProgress(0)
     setRetryMsg(null)

    let msg = err.message || 'Upload failed'

    if (msg.includes('not ready') || msg.includes('503')) {
      msg =
        'Backend is still initialising. Please wait a moment and try again.'
    } else if (msg.includes('timed out')) {
      msg =
        'Upload timed out — the PDF may be very large. Try a smaller file first.'
    } else if (msg.includes('Cannot reach')) {
      msg =
        'Cannot reach backend. Make sure the server is running on port 8000.'
    }

    setUploadError(msg)
    setTimeout(() => setUploadError(null), 6000)
  } finally {
    setUploading(false)
  }
}, [
  addDocuments,
  setUploading,
  setUploadError,
  onUploaded,
  blocked,
])
const { getRootProps, getInputProps, isDragActive } = useDropzone({
  onDrop,
  accept: { 'application/pdf': ['.pdf'] },
  multiple: true,
  disabled: isUploading || blocked,
})

  /* ── Visual states ──────────────────────────────────────────── */
  const isDisabled = isUploading || blocked

  const borderColor = isDragActive
    ? 'rgba(74,144,226,.75)'
    : uploadError
    ? 'rgba(226,92,106,.5)'
    : blocked
    ? 'rgba(255,255,255,.07)'
    : 'rgba(255,255,255,.14)'

  const bgColor = isDragActive
    ? 'rgba(74,144,226,.07)'
    : blocked
    ? 'rgba(8,12,20,.3)'
    : 'rgba(8,12,20,.55)'

  return (
    <div className="space-y-2">
      {/* Drop zone */}
      <div
        {...getRootProps()}
        className="relative overflow-hidden rounded-xl transition-all duration-200"
        style={{
          border:  `1.5px dashed ${borderColor}`,
          background: bgColor,
          boxShadow:  isDragActive ? '0 0 0 3px rgba(74,144,226,.12)' : 'none',
          padding:    '20px 16px',
          cursor:     isDisabled ? 'not-allowed' : 'pointer',
          opacity:    blocked ? 0.55 : 1,
        }}
      >
        <input {...getInputProps()} />

        <div className="flex flex-col items-center gap-3 text-center">
          {/* Icon */}
          <motion.div
            animate={isDragActive ? { scale: 1.14, y: -3 } : { scale: 1, y: 0 }}
            transition={{ duration: .2 }}
            className="w-11 h-11 rounded-xl flex items-center justify-center"
            style={{
              background: isDragActive ? 'rgba(74,144,226,.2)' : 'rgba(255,255,255,.05)',
              border: `1px solid ${isDragActive ? 'rgba(74,144,226,.5)' : 'rgba(255,255,255,.09)'}`,
              boxShadow: isDragActive ? '0 0 20px rgba(74,144,226,.28)' : 'none',
            }}
          >
            {isUploading
              ? <Loader2 size={18} className="animate-spin" style={{ color: '#8bbef7' }} />
              : blocked
              ? <Clock size={17} style={{ color: 'var(--text-dim)' }} />
              : isDragActive
              ? <FilePlus size={18} style={{ color: '#8bbef7' }} />
              : <Upload size={17} style={{ color: 'var(--text-muted)' }} />
            }
          </motion.div>

          {/* Text */}
          <div>
            <p
              className="text-sm font-medium"
              style={{
                color: blocked
                  ? 'var(--text-dim)'
                  : isDragActive
                  ? '#8bbef7'
                  : 'var(--text-secondary)',
                fontFamily: 'var(--font-sans)',
              }}
            >
              {isUploading && retryMsg
                ? retryMsg
                : isUploading
                ? progress > 0 && progress < 100
                  ? `Uploading… ${progress}%`
                  : 'Processing…'
                : blocked
                ? 'Waiting for backend…'
                : isDragActive
                ? 'Release to upload'
                : 'Drop PDFs or click to browse'
              }
            </p>
            <p className="text-xs mt-1"
              style={{ color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>
              {blocked
                ? `Backend ${backendStatus === 'checking' ? 'connecting' : backendStatus}…`
                : 'PDF only · up to 50 MB · multi-file'
              }
            </p>
          </div>

          {/* Upload progress bar */}
          {isUploading && progress > 0 && progress < 100 && (
            <div
              className="w-full rounded-full overflow-hidden"
              style={{ height: 3, background: 'rgba(255,255,255,.08)' }}
            >
              <motion.div
                initial={{ width: 0 }}
                animate={{ width: `${progress}%` }}
                className="h-full rounded-full"
                style={{ background: 'var(--sapphire)', boxShadow: '0 0 6px rgba(74,144,226,.5)' }}
              />
            </div>
          )}
        </div>
      </div>

      {/* Status feedback */}
      <AnimatePresence>
        {justDone && (
          <motion.div
            key="done"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: .2 }}
            className="flex items-center gap-2 px-3 py-2.5 rounded-lg overflow-hidden"
            style={{ background: 'rgba(62,207,142,.07)', border: '1px solid rgba(62,207,142,.22)' }}
          >
            <CheckCircle2 size={13} style={{ color: 'var(--emerald)', flexShrink: 0 }} />
            <span className="text-xs" style={{ color: 'var(--emerald)', fontFamily: 'var(--font-mono)' }}>
              Upload complete — document indexed ✓
            </span>
          </motion.div>
        )}

        {uploadError && (
          <motion.div
            key="error"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: .2 }}
            className="flex items-start gap-2 px-3 py-2.5 rounded-lg overflow-hidden"
            style={{ background: 'rgba(226,92,106,.07)', border: '1px solid rgba(226,92,106,.22)' }}
          >
            <AlertCircle size={13} style={{ color: 'var(--rose)', flexShrink: 0, marginTop: 2 }} />
            <span className="text-xs leading-relaxed"
              style={{ color: 'var(--rose)', fontFamily: 'var(--font-mono)' }}>
              {uploadError}
            </span>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}