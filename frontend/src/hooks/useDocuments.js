import { useCallback } from 'react'
import { useDocumentStore } from '../store/documentStore'
import { documentsApi } from '../services/api'

export function useDocuments() {
  const {
    documents,
    isFetching,
    fetchError,
    setDocuments,
    setFetching,
    setFetchError,
    addDocuments,
    removeDocument,
  } = useDocumentStore()

  const fetchDocuments = useCallback(async () => {
    setFetching(true)
    setFetchError(null)

    try {
      const res = await documentsApi.list()
      setDocuments(res.data.documents || [])
    } catch (err) {
      setFetchError(err.message)
    } finally {
      setFetching(false)
    }
  }, [setDocuments, setFetching, setFetchError])

  const uploadDocument = useCallback(async (file, onProgress) => {
    const form = new FormData()
    form.append('file', file)

    const res = await documentsApi.upload(form, (e) => {
      const pct = Math.round((e.loaded * 100) / (e.total || 1))
      onProgress?.(pct)
    })

    if (!res.data.duplicate) {
      addDocuments([
        {
          filename: res.data.filename,
          chunks: res.data.chunks,
        },
      ])
    }

    return res.data
  }, [addDocuments])

  const deleteDocument = useCallback(async (filename) => {
    if (!filename) {
      throw new Error(
        'deleteDocument called without a filename — filename is the only identifier the backend accepts.'
      )
    }

    await documentsApi.remove(filename)
    removeDocument(filename)
  }, [removeDocument])

  return {
    documents,
    isFetching,
    fetchError,
    fetchDocuments,
    uploadDocument,
    deleteDocument,
  }
}