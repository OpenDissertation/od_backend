"""Defines endpoints for file processing and chatting with OpenAI Chat-GPT."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from od_backend.configure_openai import initialize_openai
from openai import AsyncOpenAI

from . import __version__

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """
    Initialize FastAPI with a lifespan event to manage the async HTTP client.

    Attributes
    ----------
    app: The FastAPI object to initialize.

    """
    # Initialize the global async HTTPX client on startup
    app.state.http_client = httpx.AsyncClient()
    yield

    # Clean up the client on shutdown
    await app.state.http_client.aclose()


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

# Initialize the asynchronous OpenAI client
openai_client: AsyncOpenAI = initialize_openai()


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
