"""
pt-media-os — Review UI + Mission Control Server

Runs the FastAPI review interface with Mission Control dashboard.
Access at http://localhost:8000

Credentials: Use REVIEW_USERNAME and REVIEW_PASSWORD_HASH from .env
Default dev credentials: admin / changeme
"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "review:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
        proxy_headers=True,
    )
