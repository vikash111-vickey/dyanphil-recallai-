# Dyanphil - Project Notes & Architectural Decisions

This document maintains a running log of foundational decisions, architectural principles, and constraints governing the Dyanphil project.

---

## Core Principles

1. **Local-First & Privacy-First**:
   - Dyanphil is designed from the ground up as a personal search assistant operating entirely on the user's local machine.
   - User data, files, indices, and personal metadata never leave the machine by default.
   - Network calls to third-party endpoints are never made automatically or implicitly. Any external connection must be explicitly enabled and configured by the user.

2. **Disk Space & Resource Constraints**:
   - The primary development and deployment environments have strict disk space limitations (e.g. constrained C: drive storage, keeping all dependencies, virtual environments, and data local to the project workspace).
   - **Memory Constraint (8 GB RAM Host)**:
     - The host machine has 8 GB of RAM.
     - Embedding batch size is strictly capped at 16 chunks.
     - The embedding model is loaded into memory only once (as a lazy singleton) and kept alive.
     - Full file texts are never loaded into memory all at once: content is streamed from SQLite row by row (file by file), releasing references immediately to avoid heap bloating.
   - **Do NOT install or depend on heavyweight frameworks or runtimes**:
     - Do NOT use Ollama.
     - Do NOT use PyTorch (`torch`), CUDA, or large machine learning dependencies.
     - Do NOT use `sentence-transformers` (which pulls in PyTorch and heavy HuggingFace dependencies).
     - Do NOT download or bundle any model larger than 500 MB.
   - All runtime dependencies, caches, and storage must stay lean and strictly isolated within the project directory.

3. **Embeddings & Vector Search**:
   - Embeddings will be powered by `fastembed` (leveraging lightweight, CPU-optimized ONNX runtime) rather than heavy PyTorch-based libraries.
   - Embeddings must be implemented behind a swappable, modular interface to decouple model providers from retrieval and indexing pipelines.
   - Models used must be compact (under 500 MB) and run efficiently on CPU without specialized hardware.

4. **Pluggable LLM Provider**:
   - The Large Language Model (LLM) component is designed as a pluggable, modular provider.
   - Architecture starts with **cloud opt-in first** (user explicitly supplies their own API keys if they wish to use LLM features), with an option for lightweight local models in later stages.
   - No cloud LLM requests are dispatched without deliberate, opt-in user consent.

5. **LLM-Independent Search**:
   - **Search must work fully without any LLM**:
     - Fast keyword, lexical, BM25, and metadata-based retrieval must function completely standalone.
     - Users can index documents, query, filter, and review search results without needing any LLM configured, running, or online.
     - LLM capabilities (e.g., summarization, synthesis, answer generation) serve purely as optional enhancement layers on top of the search engine, never as a hard prerequisite for finding information.

---

## Log of Architectural Decisions

| Date | Topic | Decision | Rationale |
|------|-------|----------|-----------|
| 2026-11-16 | Project Foundation | FastAPI backend with Pydantic Settings, modular directory structure (`connectors`, `ingestion`, `search`, `api`). | Lightweight, standard Python async framework with low overhead and strict type validation. |
| 2026-11-16 | Model & Framework Ban | No PyTorch, no Ollama, no sentence-transformers, no models > 500 MB. | Severe host disk constraints; prioritize small footprint, fast boot times, and CPU execution. |
| 2026-11-16 | Embeddings | FastEmbed (ONNX) behind an abstract swappable interface. | Sub-500 MB footprint, CPU optimized, no PyTorch dependency. |
| 2026-11-16 | LLM Strategy | Pluggable interface; cloud opt-in first; search fully operational without LLM. | Ensures privacy-first guarantee while providing resilience against missing API keys or lack of local GPU/disk. |
| 2026-11-16 | File Indexer & Storage | SQLite with FTS5 (`unicode61 remove_diacritics 2`), automated sync triggers, and pure-Python extractors (`pypdf`, `python-docx`, `openpyxl` read-only). | Lean disk usage, zero external server overhead, zero network dependency, automated cascading consistency. |
| 2026-11-21 | Memory & Streaming | Embedding batch size of 16, load model once, stream file text from SQLite. | Host has 8 GB RAM; prevents OOM and keeps memory footprint minimal. |
| 2026-11-22 | Document Classification & Facts | Rule/regex-based categorization (12 categories) and privacy-preserving fact extraction (ISO dates, amounts, IDs, masked Aadhaar/PAN/cards). | Zero LLM requirement, lightweight CPU execution, privacy compliance, supports natural fact querying and expiring document tracking. |
| 2026-11-22 | UI Expiring Documents & Facts | Added "Expiring soon" button under MorphOrb calling `GET /expiring?days=60`, displaying doc_type badge and up to 3 fact chips on result cards. | Native dark theme consistency, seamless transition between search queries and expiring document reviews without modifying MorphOrb. |
| 2026-11-22 | Emergency Vault & PIN Lock | SQLite `vault` & `settings` tables, salted `hashlib.scrypt` PIN (4-8 digits), 10-minute in-memory session tokens (`X-Vault-Token`), 5 wrong attempt lockout for 60 seconds. | Secure zero-leak local vault for sensitive IDs/insurance without external auth dependencies. |
| 2026-11-22 | Follow-up Session Commands | In-memory session store (last 10 messages, last search results) supporting English & Hinglish rule-based commands ("open it", "kholo", "the older one", "show more", "aur dikhao"). | Natural conversational interaction calling unified file opener and tone-adapted composer without LLM overhead. |
| 2026-11-22 | Emergency Prioritization & Safeguards | High-urgency queries matching pinned vault files prioritize them first without leaking secrets; fact answers explicitly cite source files; no fact guessing; never dump full file text. | High user safety, privacy compliance, and reliable emergency assistance. |
| 2026-11-22 | Auto-Indexing, Watchdog & Single-Port UI | Background single-thread worker with watchdog observer, 10s debounce, folder settings validation (rejecting system folders/root drives), single-file sequential pipeline (extract -> classify -> facts -> chunk -> embed), UI mounted at `/` from `ui/dist`, and `start.bat`/`stop.bat` scripts. | Continuous background synchronization with low memory footprint (8 GB RAM), robust file change handling, and seamless unified production serving on port 8000. |
| 2026-11-22 | Quality Pass, Faithfulness & Vector Cache | Verification in `verify.py` against facts and stored text; automated evaluation CLI (`eval`) with 100% recall@5 and 0.84 MRR; in-memory float32 vector matrix caching (<50ms `/ask`); English/Hinglish query cleaning; resilient fallback on model failure or locked DB. | Zero hallucinations in factual replies, ultra-fast vector retrieval on CPU, robust query understanding across multilingual idioms, and resilience against transient runtime faults. |
| 2026-11-22 | Read-Only Gmail Connector | OAuth2 InstalledAppFlow (gmail.readonly scope only), Windows Credential Manager token storage via keyring (never logged or saved in plain files), incremental sync in batches of 25 with exponential backoff, in-memory attachment text extraction (pdf, docx, xlsx, txt <= 10MB, never written to disk), body cleaning (BS4, reply/sig trimming), integrated into single heavy job worker lock, and search query filters ("gmail", "email", "inbox", "from <name>"). | Local-first offline search over emails without third-party cloud leakage, unified classification/fact/vector pipelines, and strict memory limits for 8 GB RAM host. |

---

## Planned Later Features

1. **Gmail Connector Enhancements**:
   - Background periodic auto-sync scheduler with configurable sync intervals and notification badges on unread indexed emails.
2. **Expiry Reminders**:
   - Automated background scheduler checking upcoming expiration dates on insurance, passports, warranties, and driver's licences, sending desktop toast notifications.
3. **Phone Version (Companion App)**:
   - Lightweight mobile companion client (PWA or Android client) connecting over local Wi-Fi to query desktop indices and access the Emergency Vault on the go.



