"""Defines endpoints for file processing and chatting with OpenAI Chat-GPT."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx
from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware

from od_backend.configure_openai import initialize_openai
from od_backend.session_data import (
    SESSION_DB,
    UploadFilesRequest,
    add_files_to_vector_store,
    create_vector_store,
    upload_files_to_openai,
)

from . import __version__

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from openai import AsyncOpenAI

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


@app.post("/api/v1/session/init", status_code=status.HTTP_201_CREATED)
async def initialize_vector_store(
    payload: UploadFilesRequest,
) -> dict[str, str | list[str]]:
    """
    Upload files to OpenAI file storage and initialize the vector store.

    Attributes
    ----------
    payload: An UploadFilesRequest containing the session_id and file_paths.

    Returns
    -------
    A dict containing the status, session_id, and openai_file_ids.

    """
    # Upload files to OpenAI file storage
    uploaded_file_ids: list[str] = await upload_files_to_openai(
        openai_client, payload.file_paths
    )

    # Create vector store
    vector_store_id: str = await create_vector_store(openai_client)

    # Add files to vector store to augment model's knowledge (RAG)
    await add_files_to_vector_store(
        openai_client,
        vector_store_id,
        uploaded_file_ids,
    )

    # Commit active tracker state map to database cache
    SESSION_DB[payload.session_id] = {
        "file_ids": uploaded_file_ids,
        "previous_response_id": None,
    }

    logger.info(
        "Initialize vector store ID %s with %d files for session ID %s",
        vector_store_id,
        len(uploaded_file_ids),
        payload.session_id,
    )

    return {
        "status": "success",
        "session_id": payload.session_id,
        "openai_file_ids": uploaded_file_ids,
    }
