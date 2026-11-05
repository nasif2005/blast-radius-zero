
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from agent import execute_request


# --------------------------------------------------
# 1. Initialize FastAPI
# --------------------------------------------------

app = FastAPI(
    title="Blast Radius Zero",
    description="AI-generated Python execution with Docker isolation",
    version="0.2.0",
)


# --------------------------------------------------
# 2. Frontend directory
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"


# --------------------------------------------------
# 3. Request model
# --------------------------------------------------

class ExecuteRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)


# --------------------------------------------------
# 4. Homepage
# --------------------------------------------------

@app.get("/", include_in_schema=False)
def homepage():
    """Serve the Blast Radius Zero web interface."""

    index_file = FRONTEND_DIR / "index.html"

    if not index_file.is_file():
        raise HTTPException(
            status_code=404,
            detail="Frontend index.html not found"
        )

    return FileResponse(index_file)


# --------------------------------------------------
# 5. Health endpoint
# --------------------------------------------------

@app.get("/health")
def health():
    """Check whether the FastAPI application is running."""

    return {"status": "ok"}


# --------------------------------------------------
# 6. AI code generation and sandbox execution
# --------------------------------------------------

@app.post("/execute")
def execute(request: ExecuteRequest):
    """
    1. Receive natural-language programming request.
    2. Generate Python code using Vultr Serverless Inference.
    3. Execute generated code in the Docker sandbox.
    4. Return generated code and execution results.
    """

    try:
        return execute_request(request.prompt)

    except Exception as exc:
        # Avoid exposing API keys or internal errors to clients.
        print(f"Execution error: {type(exc).__name__}")

        raise HTTPException(
            status_code=500,
            detail="Request processing failed"
        ) from exc
