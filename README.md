# Dyanphil

Dyanphil is a local-first, privacy-first personal search assistant. It empowers you to index and search across your personal documents, notes, and local files directly on your own machine. Your data never leaves your computer by default.

---

## Architecture & Directory Structure

```text
Dyanphil/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI application entry point
│   │   ├── config.py            # Settings loaded via pydantic-settings
│   │   ├── connectors/          # Data source connectors
│   │   ├── ingestion/           # Document ingestion & processing
│   │   ├── search/              # Search & retrieval engines
│   │   └── api/                 # API endpoints & route handlers
│   ├── tests/
│   │   ├── __init__.py
│   │   └── test_health.py       # Health check test suite
│   ├── requirements.txt         # Core backend dependencies
│   ├── .env.example             # Environment variable template
│   └── .venv/                   # Python virtual environment (ignored by git)
├── ui/                          # Frontend user interface (future step)
├── docs/                        # Project documentation
├── PROJECT_NOTES.md             # Running architectural log & design constraints
├── README.md                    # Setup and execution guide
└── .gitignore                   # Git ignore rules
```

---

## Prerequisites

- **OS**: Windows 10/11 with PowerShell
- **Python**: Python 3.11+ installed and available on `PATH`

---

## Installation & Setup (Windows PowerShell)

Run all commands from the repository root (`D:\prompteng`):

### 1. Create the Virtual Environment
Create an isolated virtual environment inside `backend\.venv`:

```powershell
python -m venv backend\.venv
```

### 2. Activate the Virtual Environment
Activate the environment in your PowerShell terminal:

```powershell
.\backend\.venv\Scripts\Activate.ps1
```

> **Note**: If PowerShell displays an execution policy error, enable script execution for the current process:
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process
> ```

### 3. Install Dependencies
Install the required packages using pip:

```powershell
pip install -r backend\requirements.txt
```

---

## Running Tests

Ensure your virtual environment is active, then run `pytest` pointing to the `backend` directory:

```powershell
pytest backend
```

Or change into the `backend` folder and run `pytest`:

```powershell
cd backend
pytest
cd ..
```

---

## Starting the Backend Server

Start the FastAPI application with Uvicorn:

```powershell
uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

Alternatively, from inside the `backend` directory:

```powershell
cd backend
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### Endpoints
- **Health Check**: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health) - returns `{"status":"ok"}`
- **Interactive API Docs (Swagger UI)**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **Alternative Docs (ReDoc)**: [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)
