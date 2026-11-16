from fastapi import FastAPI

app = FastAPI(
    title="Dyanphil",
    description="Local-first, privacy-first personal search assistant backend",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
