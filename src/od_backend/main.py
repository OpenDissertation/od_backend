"""Defines endpoints for file processing and chatting with OpenAI Chat-GPT."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__

app = FastAPI(
    title="OpenDissertation",
    description="OpenDissertation API enables OpenAI processing of dissertations.",
    summary="OpenDissertation Back-end Python API",
    version=f"{__version__}",
    contact={
        "name": "OpenDissertation",
        "url": "https://opendissertation.com/api/v1/contact",
        "email": "info@opendissertation.com",
    },
    license_info={
        "name": "Apache 2.0",
        "identifier": "MIT",
    },
)


# Needed so FastAPI server can accept forwarded requests in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/v1/contact")
async def contact() -> dict[str, str]:
    """
    Get contact info for OpenDissertation.

    Returns
    -------
    Dict containting the contact names and GitHub URL.

    """
    return {
        "name": "Jeffry Lew and Seong Oh",
        "GitHub": "https://github.com/OpenDissertation",
    }
