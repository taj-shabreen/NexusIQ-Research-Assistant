import { useCallback } from 'react'
import { useDocumentStore } from '../store/documentStore'
import { documentsApi } from '../services/api'

export function useDocuments() {
  const { documents, isLoading, error, setDocuments, setLoading, setError, addDocument, removeDocument } =
    useDocumentStore()

  const fetchDocuments = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await documentsApi.list()
      setDocuments(res.data.documents || [])
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [setDocuments, setLoading, setError])

  const uploadDocument = useCallback(async (file, onProgress) => {
    const form = new FormData()
    form.append('file', file)
    const res = await documentsApi.upload(form, (e) => {
      const pct = Math.round((e.loaded * 100) / (e.total || 1))
      onProgress?.(pct)
    })
    if (!res.data.duplicate) {
      addDocument({ filename: res.data.filename, chunks: res.data.chunks })
    }
    return res.data
  }, [addDocument])

  const deleteDocument = useCallback(async (filename) => {
    if (!filename) {
      throw new Error(
        'deleteDocument called without a filename — filename is the only ' +
        'identifier the backend accepts for DELETE /api/documents/{filename}.'
      )
    }
    await documentsApi.remove(filename)
    // Only update the store after the backend call succeeds — an optimistic
    // removal here would hide the doc in the UI even if the backend silently
    // matched zero chunks (e.g. wrong/stale filename) and deleted nothing.
    removeDocument(filename)
  }, [removeDocument])

  return { documents, isLoading, error, fetchDocuments, uploadDocument, deleteDocument }
}