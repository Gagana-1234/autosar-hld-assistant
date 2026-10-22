# AUTOSAR HLD Document Analysis Assistant

> A secure, locally-hosted AI assistant for reviewing AUTOSAR High-Level Design documents. **Engineers decide — AI assists. Nothing auto-approves.**

---

## Architecture

```
FastAPI Backend (port 8000)
│
├── app/api/          — REST routers (auth, projects, documents, query, extraction, ...)
├── app/core/         — Security, RBAC, audit logging, config, exceptions
├── app/db/           — SQLAlchemy models, CRUD helpers, session factory (SQLite)
├── app/ingestion/    — PDF extraction (PyMuPDF + pdfplumber + OCR), chunking pipeline
├── app/rag/          — Embeddings (sentence-transformers), ChromaDB, LLM (Ollama), retriever
├── app/extraction/   — Entity extraction from chunks (SWC, Interface, Signal, ...)
├── app/validation/   — Cross-document consistency rules
└── app/ui/           — Streamlit web UI (port 8501)
```

---

## Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure environment
```bash
cp .env.example .env
# Edit .env — at minimum change SECRET_KEY
```

### 3. Start Ollama (optional — for LLM features)
```bash
ollama serve
ollama pull llama3
```

### 4. Start the API server
```bash
uvicorn app.api.main:app --reload --host 0.0.0.0 --port 8000
```

### 5. Start the Streamlit UI
```bash
streamlit run app/ui/streamlit_app.py
```

Open **http://localhost:8501** — default login: `admin` / `admin123`

---

## Running Tests
```bash
pytest tests/ -v
```

**Current coverage:** 111 tests — all passing.

---

## Features

| Feature | Status |
|---|---|
| JWT Authentication & RBAC (6 roles) | ✅ Complete |
| Project & user management | ✅ Complete |
| PDF ingestion (text + tables + OCR) | ✅ Complete |
| Section-aware chunking with overlap | ✅ Complete |
| Semantic search (ChromaDB + BGE embeddings) | ✅ Complete |
| MMR re-ranking for diversity | ✅ Complete |
| RAG Q&A with citations (Ollama LLM) | ✅ Complete |
| Entity extraction (SWC, Interface, Signal, Dependency, DataFlow) | ✅ Complete |
| LLM-powered + regex-fallback extraction | ✅ Complete |
| Human review queue (low-confidence entities) | ✅ Complete |
| Consistency validation (5 rules) | ✅ Complete |
| Revision comparison (chunk-level diff) | ✅ Complete |
| Export (CSV / Excel / Markdown) | ✅ Complete |
| Full audit trail | ✅ Complete |
| Streamlit UI (all features) | ✅ Complete |

---

## RBAC Permissions

| Action | Admin | Architect | Developer | Tester | Manager | Viewer |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Create/delete project | ✓ | | | | | |
| Create/delete user | ✓ | | | | | |
| Upload document | ✓ | ✓ | ✓ | | | |
| Approve document | ✓ | ✓ | | | | |
| Run query | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Review entity | ✓ | ✓ | ✓ | ✓ | | |
| Approve entity | ✓ | ✓ | | | | |
| Export | ✓ | ✓ | ✓ | ✓ | ✓ | |
| View audit log | ✓ | | | | ✓ | |
| Compare revisions | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

---

## API Documentation

Once the server is running, visit:
- Swagger UI: http://localhost:8000/api/docs
- ReDoc: http://localhost:8000/api/redoc

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | (change in prod) | JWT signing key |
| `SQLITE_DB_PATH` | `./data/sqlite/autosar_hld.db` | SQLite database path |
| `CHROMA_PERSIST_DIR` | `./data/chroma` | ChromaDB persistence directory |
| `LLM_PROVIDER` | `ollama` | `ollama` or `stub` |
| `OLLAMA_MODEL` | `llama3` | Ollama model name |
| `EMBEDDING_MODEL` | `BAAI/bge-base-en-v1.5` | Sentence-transformers model |
| `EMBEDDING_BATCH_SIZE` | `32` | Embedding batch size |
| `MIN_CONFIDENCE_AUTO_APPROVE` | `0.8` | Confidence threshold for auto-accept |
| `LOW_CONFIDENCE_THRESHOLD` | `0.6` | Confidence threshold for review queue |
| `RETRIEVAL_TOP_K` | `6` | Number of chunks to retrieve for RAG |

---

## Project Structure

```
TCS/
├── app/
│   ├── api/
│   │   ├── main.py          # App factory & router registration
│   │   ├── auth.py          # Login, register, JWT
│   │   ├── projects.py      # Project CRUD + membership
│   │   ├── documents.py     # Upload, approve, list
│   │   ├── query.py         # RAG Q&A endpoint
│   │   ├── extraction.py    # Entity extraction & review
│   │   ├── review.py        # Review queue management
│   │   ├── consistency.py   # Consistency check runner
│   │   ├── comparison.py    # Revision diff
│   │   ├── export.py        # CSV / Excel / Markdown export
│   │   └── admin.py         # Audit log & user deactivation
│   ├── core/
│   │   ├── config.py        # Pydantic settings
│   │   ├── security.py      # RBAC, JWT, bcrypt
│   │   ├── audit.py         # Audit log writer
│   │   └── exceptions.py    # HTTP exception hierarchy
│   ├── db/
│   │   ├── models.py        # SQLAlchemy ORM models
│   │   ├── crud.py          # DB helper functions
│   │   └── database.py      # Engine, session factory
│   ├── ingestion/
│   │   ├── extractor.py     # PDF → text/tables/headings
│   │   ├── chunker.py       # Section-aware chunker
│   │   ├── pipeline.py      # Full ingestion orchestrator
│   │   └── validator.py     # Upload validation
│   ├── rag/
│   │   ├── embedder.py      # Sentence-transformers embedder
│   │   ├── vector_store.py  # ChromaDB abstraction
│   │   ├── retriever.py     # Retrieve + MMR re-rank
│   │   ├── llm_provider.py  # Ollama + stub LLM
│   │   └── pipeline.py      # RAG orchestrator
│   ├── extraction/
│   │   ├── schemas.py       # Pydantic entity schemas
│   │   └── entity_extractor.py  # LLM + regex extraction
│   ├── validation/
│   │   └── consistency.py   # Consistency rules (5 checks)
│   └── ui/
│       └── streamlit_app.py # Full Streamlit UI
├── tests/
│   ├── conftest.py          # Shared fixtures
│   ├── test_rbac.py         # Auth & RBAC (36 tests)
│   ├── test_chunker.py      # Chunker (19 tests)
│   ├── test_rag.py          # RAG pipeline (17 tests)
│   ├── test_extraction.py   # Entity extraction (16 tests)
│   ├── test_consistency.py  # Consistency rules (10 tests)
│   └── test_api_endpoints.py # API integration (13 tests)
├── data/
│   ├── sqlite/              # SQLite database
│   └── chroma/              # ChromaDB vector store
├── .env                     # Environment variables
├── requirements.txt         # Python dependencies
└── pytest.ini               # Test configuration
```
