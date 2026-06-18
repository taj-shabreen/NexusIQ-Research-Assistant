/**
 * NexusIQ — store/documentStore.js
 *
 * Production fixes:
 *   1. uploadedFilenames Set — prevents duplicate uploads of same filename
 *   2. uploadProgress 0-100 — used by DocumentUpload progress bar
 *   3. isDeleting Set — tracks which doc_ids are being deleted
 *   4. fetchError — separate from uploadError for better UX
 */

import { create } from 'zustand'

export const useDocumentStore = create((set, get) => ({
  // ── State ────────────────────────────────────────────────────────
  documents:        [],
  isUploading:      false,
  uploadProgress:   0,
  uploadError:      null,
  isFetching:       false,
  fetchError:       null,
  selectedDocId:    null,
  deletingIds:      new Set(),       // set of document_ids currently being deleted
  uploadedFilenames: new Set(),      // set of filenames already indexed (duplicate guard)

  // ── Document actions ─────────────────────────────────────────────

  setDocuments(docs) {
    // Rebuild uploadedFilenames from fresh list
    const names = new Set(docs.map((d) => d.filename).filter(Boolean))
    set({ documents: docs, uploadedFilenames: names })
  },

  addDocuments(newDocs) {
    set((s) => {
      const existingIds   = new Set(s.documents.map((d) => d.document_id ?? d.id))
      const existingNames = new Set(s.documents.map((d) => d.filename))
      const docs = Array.isArray(newDocs)
         ? newDocs
         : [newDocs]

      const fresh = docs.filter(
         (d) => !existingIds.has(d.document_id ?? d.id)
      )
      const merged        = [...s.documents, ...fresh]
      // Update filename set
      fresh.forEach((d) => { if (d.filename) existingNames.add(d.filename) })
      return {
        documents:         merged,
        uploadedFilenames: existingNames,
      }
    })
  },

  removeDocument(documentId) {
    set((s) => {
      const doc    = s.documents.find((d) => (d.document_id ?? d.id) === documentId)
      const names  = new Set(s.uploadedFilenames)
      if (doc?.filename) names.delete(doc.filename)
      return {
        documents:         s.documents.filter((d) => (d.document_id ?? d.id) !== documentId),
        selectedDocId:     s.selectedDocId === documentId ? null : s.selectedDocId,
        uploadedFilenames: names,
      }
    })
  },

  /** Returns true if filename is already indexed. */
  isFilenameUploaded(filename) {
    return get().uploadedFilenames.has(filename)
  },

  // ── Upload state ─────────────────────────────────────────────────

  setUploading(val) {
    set({
      isUploading:    val,
      uploadProgress: val ? 0 : get().uploadProgress,
      uploadError:    val ? null : get().uploadError,
    })
  },

  setUploadProgress(pct) {
    set({ uploadProgress: Math.min(Math.max(0, pct), 100) })
  },

  setUploadError(err) {
    set({ uploadError: err, isUploading: false, uploadProgress: 0 })
  },

  // ── Fetch state ──────────────────────────────────────────────────

  setFetching(val) {
    set({ isFetching: val, fetchError: val ? null : get().fetchError })
  },

  setFetchError(err) {
    set({ fetchError: err, isFetching: false })
  },

  // ── Delete state ─────────────────────────────────────────────────

  setDeleting(documentId, isDeleting) {
    set((s) => {
      const ids = new Set(s.deletingIds)
      isDeleting ? ids.add(documentId) : ids.delete(documentId)
      return { deletingIds: ids }
    })
  },

  isDocumentDeleting(documentId) {
    return get().deletingIds.has(documentId)
  },

  // ── Misc ─────────────────────────────────────────────────────────

  selectDoc(id) {
    set({ selectedDocId: id })
  },
}))