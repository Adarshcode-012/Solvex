
import os

import uvicorn

RELOAD_INCLUDES = ["*.py", ".env"]
RELOAD_EXCLUDES = [
    "memory",
    "venv",
    "*.sqlite*",
    "*.db",
    "__pycache__",
]


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=int(os.getenv("BACKEND_PORT", "8000")),
        reload=True,
        reload_includes=RELOAD_INCLUDES,
        reload_excludes=RELOAD_EXCLUDES,
    )
