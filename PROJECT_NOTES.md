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
