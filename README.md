# NexusIQ — Advanced Multi-Document Research RAG Assistant

> Production-grade conversational RAG system with hybrid retrieval, citation-aware answers,
> hallucination detection, and RAGAS-powered evaluation.

## Tech Stack

| Layer          | Technology                                      |
|----------------|-------------------------------------------------|
| Frontend       | React + Vite + TailwindCSS + Zustand + Framer  |
| Backend        | FastAPI (async) + Pydantic v2                   |
| LLM            | Groq — llama3-8b-8192                           |
| Embeddings     | HuggingFace BAAI/bge-small-en                   |
| Vector Store   | ChromaDB (persistent)                           |
| Retrieval      | BM25 + Semantic + Cross-encoder reranking       |
| Orchestration  | LangChain + LlamaIndex                          |
| Evaluation     | RAGAS                                           |
| Observability  | LangSmith                                       |

## Quick Start

### Backend
```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env .env        # fill in GROQ_API_KEY
uvicorn app.main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

## Features
- 📄 Multi-document PDF upload & intelligent chunking
- 🔍 Hybrid BM25 + semantic retrieval with cross-encoder reranking
- 💬 Conversational RAG with multi-query expansion & query rewriting
- 📌 Citation-aware answers with chunk-level provenance
- 📊 RAGAS evaluation dashboard with hallucination flags
- 🔬 Retrieval debugger for chunk inspection
- 🔭 LangSmith tracing & observability