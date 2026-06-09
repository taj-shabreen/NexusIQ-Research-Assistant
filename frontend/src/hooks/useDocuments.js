/**
 * NexusIQ — hooks/useDocuments.js
 * Custom hook: fetch & manage the document list from the backend.
 */

import { useCallback, useEffect } from 'react'
import { documentsApi } from '../services/api'
import { useDocumentStore } from '../store/documentStore'

export function useDocuments() {
  const {
    documents,
    isFetching,
    uploadError,
    setDocuments,
    setFetching,
    removeDocument: storeRemove,
  } = useDocumentStore()

  // ── Fetch document list ─────────────────────────────────────────
  const fetchDocuments = useCallback(async () => {
    setFetching(true)
    try {
      const res = await documentsApi.list()
      // Normalise: backend returns { id, filename, chunks, status }
      setDocuments(res.data ?? [])
    } catch (err) {
      console.error('[useDocuments] fetch error:', err.message)
    } finally {
      setFetching(false)
    }
  }, [setDocuments, setFetching])

  // ── Delete a document ───────────────────────────────────────────
  const deleteDocument = useCallback(async (documentId) => {
    try {
      await documentsApi.remove(documentId)
      storeRemove(documentId)
    } catch (err) {
      console.error('[useDocuments] delete error:', err.message)
      throw err // let caller handle UI feedback
    }
  }, [storeRemove])

  // ── Load on mount ───────────────────────────────────────────────
  useEffect(() => {
    fetchDocuments()
  }, [fetchDocuments])

  return {
    documents,
    isFetching,
    uploadError,
    fetchDocuments,
    deleteDocument,
  }
}