# Dyanphil

Dyanphil is a local-first, privacy-first personal search assistant designed for laptop and desktop Windows machines (optimized for 8 GB RAM). It indexes and searches across your local files, documents, receipts, certificates, and notes directly on your own computer. Your data never leaves your machine.

---

## What the App Does

- **Local Hybrid Search**: Combines BM25 full-text keyword search (SQLite FTS5) with semantic vector search (`fastembed` ONNX sub-500MB model running on CPU).
- **In-Memory Vector Matrix Caching**: Caches normalized float32 vector embeddings in RAM, delivering warm `/ask` search latency under 50 ms.
- **Rule-Based Document Classification**: Categorizes files into 12 document types (ID documents, insurance, medical, financial, tickets, warranties, contracts, certificates, education, resume, code/notes, other) using fast keyword scoring in English and Hinglish—no LLM required.
- **Privacy-Preserving Fact Extraction**: Automatically extracts expiry dates, amounts, policy/ID numbers, emails, and phone numbers. Automatically masks Aadhaar numbers, PAN numbers, and payment cards (retaining only the last 4 digits). Passwords and OTPs are never stored.
- **Faithfulness Verification**: Before returning any factual claim (dates, amounts, policy/ID numbers, names), claims are validated against the extracted facts and stored file contents. If unconfirmed, the assistant states: *"I couldn't confirm this from your files"*, while still showing the matching document cards.
- **Emergency Vault**: Secure PIN-protected vault (`hashlib.scrypt` with 10-minute in-memory session tokens) for pinning critical emergency documents. High-urgency queries ("mera passport jaldi", "URGENT ticket") automatically prioritize vault documents.
- **Conversational Follow-ups**: Context-aware follow-up actions ("open it", "kholo", "the older one", "show more", "aur dikhao") work seamlessly across sessions.
- **Auto-Indexing & Live File Watcher**: A lightweight background worker with `watchdog` watches configured folders, debounces changes by 10s, and processes files one by one to stay under 8 GB RAM.
- **Single-Port Production Serving**: Both the FastAPI backend and the compiled React UI are served together from `http://127.0.0.1:8000`.

---

## System Requirements

- **OS**: Windows 10 or 11
- **RAM**: 8 GB RAM (optimized with sequential file processing and 16-chunk batch limits)
- **Python**: Python 3.11+
- **Node.js**: Node.js 18+ (only needed if building the UI from source)

---

## Quick Start

### 1. Start the Application
Double-click or run `start.bat` from the repository root (`D:\prompteng`):

```cmd
D:\prompteng\start.bat
```

What `start.bat` does:
1. Activates the Python virtual environment (`backend\.venv`).
2. Starts the backend server on `http://127.0.0.1:8000` with `--app-dir backend`.
3. Serves the production UI directly from `ui/dist`.
4. Automatically opens your default web browser to `http://127.0.0.1:8000`.

### 2. Stop the Application
To cleanly shut down the server:

```cmd
D:\prompteng\stop.bat
```
Or press `Ctrl+C` in the terminal where `start.bat` is running.

---

## Adding Folders to Index

### Via the Web UI (Recommended)
1. In the browser (`http://127.0.0.1:8000`), click the **Settings** button below the central orb.
2. Under **Indexed Folders**, enter the full folder path (e.g. `D:\MyDocuments` or `C:\Users\username\Documents`).
3. Click **Add**.
4. The auto-indexer will immediately scan the folder and register a live file watcher (`watchdog`) for any future additions, edits, or deletions.

> *Note: For security and stability, root drive roots (e.g. `C:\`) and Windows system folders (`C:\Windows`, `Program Files`) cannot be added.*

### Via the Command Line
Run the CLI indexer from the repository root:

```powershell
.\backend\.venv\Scripts\python.exe -m app.cli index "D:\MyDocuments" "D:\Invoices"
```

---

## Running Indexing, OCR, and Embeddings

You can trigger indexing and processing either through the UI or via the CLI:

### Through the UI
- Open **Settings** under the central orb.
- Click **Index now** to perform a full incremental scan of all configured folders.
- Click **Process scanned files (OCR)** to run optical character recognition on pending scanned images and PDFs.
- The status bar polls every 3 seconds while Settings is open, showing current task, total indexed files, and pending OCR count.

### Through the CLI
From `D:\prompteng`:

```powershell
# 1. Full incremental scan and index of folders
.\backend\.venv\Scripts\python.exe -m app.cli index "D:\MyDocuments"

# 2. Extract classification and facts for newly indexed files
.\backend\.venv\Scripts\python.exe -m app.cli classify

# 3. Generate semantic vector embeddings
.\backend\.venv\Scripts\python.exe -m app.cli embed

# 4. Run OCR on files marked 'needs_ocr' (scanned PDFs / images)
.\backend\.venv\Scripts\python.exe -m app.cli ocr --limit 20

# 5. List files with expiring dates (warranties, IDs, insurance)
.\backend\.venv\Scripts\python.exe -m app.cli expiring --days 60

# 6. Test search via terminal
.\backend\.venv\Scripts\python.exe -m app.cli search "passport renewal date" --mode hybrid

# 7. Run automated retrieval evaluation (recall@5 and MRR)
.\backend\.venv\Scripts\python.exe -m app.cli eval
```

---

## Backing Up Your Data

All index databases, classifications, extracted facts, vault credentials, and configuration settings are stored locally inside the `D:\prompteng\data` directory:

```text
D:\prompteng\data/
├── recall.db            # SQLite database (FTS5, chunks, facts, vault, classifications)
├── settings.json        # Configured indexed folders and application settings
├── last_search.json     # Last CLI search cache for quick 'open' commands
└── eval_report.txt      # Latest automated evaluation benchmark report
```

### To Back Up:
1. Stop the application with `stop.bat`.
2. Copy the `D:\prompteng\data` folder to your backup drive or cloud storage.
3. Your original document files are never modified or relocated.

### To Restore:
1. Stop the application.
2. Replace `D:\prompteng\data` with your backed-up copy.
3. Start the application with `start.bat`.

---

## Deleting All Data

If you wish to reset the application and wipe all indexed data, vector embeddings, facts, and vault items:

### Via the Web UI:
1. Click **Settings** under the orb.
2. Scroll to the **Privacy** section.
3. Click the red **Delete all my data** button.
4. A confirmation dialog will appear. Type `DELETE` in the box, enter your Vault PIN (if configured), and click **Confirm Delete**.
5. All indexed database records, chunks, facts, and vault pins are permanently erased. Your original files on disk remain completely untouched.

### Via the API:
```bash
curl -X POST http://127.0.0.1:8000/data/delete-all \
  -H "Content-Type: application/json" \
  -H "X-Vault-Token: <token-if-pin-is-set>" \
  -d "{\"confirm\": \"DELETE\"}"
```

### Manually:
1. Run `stop.bat`.
2. Delete `D:\prompteng\data\recall.db`.
3. Restart `start.bat`. A clean database schema will be initialized automatically.

---

## Data Locations on `D:`

| Path | Description |
|------|-------------|
| `D:\prompteng\` | Application workspace root |
| `D:\prompteng\backend\` | Python FastAPI backend, virtual environment, and pipelines |
| `D:\prompteng\ui\` | React + Tailwind + Vite frontend source code |
| `D:\prompteng\ui\dist\` | Compiled production frontend bundle served at `http://127.0.0.1:8000` |
| `D:\prompteng\data\` | SQLite database (`recall.db`), settings, and search caches |
| `D:\prompteng\.pytest_temp\` | Isolated test temporary directory (keeps C: drive empty) |
| `D:\cache\models\` | FastEmbed ONNX embedding models directory |

---

## Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| **"The database is currently busy with background tasks"** | An indexing or OCR job is currently writing to `recall.db`. | SQLite is locked during transaction writes. Wait a few moments and try your query again; the backend handles concurrency gracefully and retries. |
| **Port 8000 is already in use** | A previous instance of the backend is still running in the background. | Run `D:\prompteng\stop.bat` to terminate orphaned processes on port 8000, or run `netstat -aon \| findstr :8000` and kill the PID with `taskkill /F /PID <PID>`. |
| **Scanned files not appearing in text search** | Scanned PDFs or image files contain no digital text and require OCR. | Scanned documents are marked `needs_ocr` to prevent CPU throttling. Run OCR via the UI Settings ("Process scanned files") or execute `python -m app.cli ocr`. |
| **File permission warning (`icacls`) on startup** | Windows user permissions restriction could not be modified. | Dyanphil attempts to restrict `D:\prompteng\data` to the current user via `icacls`. On non-NTFS drives (exFAT/FAT32) or standard non-admin accounts, a warning is logged. The application runs normally. |
| **Embedding model fails to load** | FastEmbed ONNX runtime binary is missing or downloading. | Dyanphil automatically falls back to keyword BM25 search without showing technical errors to the user. Search continues to function normally. |
| **UI shows "Session expired" or 401 Unauthorized** | The browser cookie was cleared or the server was restarted. | Refresh the page (`F5`) to obtain a fresh HttpOnly session token. |
| **Cannot add root drive or system directory** | Security validation rejected a restricted path. | For privacy and performance, drive roots (e.g. `C:\`) and system paths (`C:\Windows`, `Program Files`) are forbidden. Choose specific user directories (e.g. `D:\Documents`). |

---

## Possible Later Features

1. **Gmail Connector**:
   - Local-first email connector allowing users to authenticate via OAuth (`gmail.readonly` scope) to download, index, and search personal Gmail threads and attachments locally without sending emails to third-party servers.
   - Attachments (PDF, DOCX, XLSX, TXT) downloaded and parsed in-memory without saving to disk.

2. **Expiry Reminders**:
   - Automated background check notifying users about upcoming document expiration dates (driver's licence, passport, insurance renewals, warranty coverage) via desktop toast notifications or email digests.

3. **Phone Version (Companion App)**:
   - Lightweight mobile companion interface (PWA or Android client) connecting over local Wi-Fi to search desktop indices and securely retrieve Emergency Vault documents on the go.

---

## Development & Testing

Run all unit and integration tests (148 tests):

```powershell
.\backend\.venv\Scripts\pytest.exe backend/tests
```

Rebuild the frontend UI:

```powershell
cd ui
npm run build
cd ..
```
