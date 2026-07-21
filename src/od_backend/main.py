"""Defines endpoints for file processing and chatting with OpenAI Chat-GPT."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import anyio
import httpx
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from od_backend.configure_openai import OPENAI_MODEL, initialize_openai
from od_backend.dissertation_downloads import (
    DownloadDissertationsRequest,
    DownloadedDissertation,
    download_dissertation,
    normalize_institution,
)
from od_backend.session_data import (
    SESSION_DB,
    ChatRequest,
    ChatResponse,
    UploadFilesRequest,
    add_files_to_vector_store,
    create_vector_store,
    delete_files_from_openai,
    delete_vector_store,
    upload_files_to_openai,
)

from . import __version__

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from openai import AsyncOpenAI
    from openai.types.responses import Response

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
    A dict containing the status, session_id, uploaded_file_ids, and vector_store_id.

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
        "vector_store_id": vector_store_id,
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
        "uploaded_file_ids": uploaded_file_ids,
        "vector_store_id": vector_store_id,
    }


@app.post("/api/v1/dissertations/download", status_code=status.HTTP_200_OK)
async def download_dissertations(
    payload: DownloadDissertationsRequest,
) -> dict[str, list[DownloadedDissertation]]:
    """
    Download one PhD dissertation per requested author to /tmp.

    Attributes
    ----------
    payload: A request containing dissertation authors and institutions.

    Returns
    -------
    A dict containing one download result per requested author.

    """
    for dissertation in payload.dissertations:
        try:
            normalize_institution(dissertation.institution)
        except ValueError as err:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{err} Author: {dissertation.author}",
            ) from err

    results = [
        await anyio.to_thread.run_sync(download_dissertation, dissertation)
        for dissertation in payload.dissertations
    ]
    return {"results": results}


@app.post("/api/v1/chat", response_model=ChatResponse)
async def chat_turn(payload: ChatRequest) -> ChatResponse:
    """
    Process a multi-turn chat request leveraging the active session's context.

    Attributes
    ----------
    payload: A ChatRequest containing the session_id and the user's question.

    Returns
    -------
    A ChatResponse containing the session_id, answer, and previous_response_id.

    """
    session: dict[str, list[str] | str | None] | None = SESSION_DB.get(
        payload.session_id
    )
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Active session context not found. Call initialization route first.",
        )

    # Structure payload params dynamically depending on conversation turn depth
    # See https://developers.openai.com/api/docs/guides/tools-file-search
    api_kwargs: dict[str, str | list[str] | list[dict[str, int | str | list[str]]]] = {
        "model": OPENAI_MODEL,
        "input": payload.question,
        "tools": [  # type: ignore[dict-item]
            {
                "type": "file_search",
                "vector_store_ids": [session["vector_store_id"]],
                "max_num_results": 2,
            },
        ],
        "include": ["file_search_call.results"],
    }

    if session["previous_response_id"] is not None:
        # Link history natively via the previous ID pointer
        api_kwargs["previous_response_id"] = session["previous_response_id"]

    try:
        # Execute asynchronous context completion
        api_response: Response = await openai_client.responses.create(**api_kwargs)  # type: ignore[call-overload]

        logger.info(
            "Completed API response ID %s with output %s",
            api_response.id,
            api_response.output_text,
        )
    except Exception as err:
        logger.exception("OpenAI execution interrupted")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"OpenAI Execution Interrupted: {err}",
        ) from err

    # Mutate localized storage pointer reference to match newest message tail
    session["previous_response_id"] = api_response.id

    return ChatResponse(
        session_id=payload.session_id,
        answer=api_response.output_text,
        previous_response_id=api_response.id,
    )


@app.delete("/api/v1/session/{session_id}", status_code=status.HTTP_200_OK)
async def terminate_session(session_id: str) -> dict[str, str]:
    """
    Delete the session context and destroy remote OpenAI storage artifacts.

    Attributes
    ----------
    session_id: The OpenAI session ID to terminate.

    Returns
    -------
    A dict containing the status and detail.

    """
    session: dict[str, list[str] | str | None] | None = SESSION_DB.pop(session_id, None)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session ID target missing or already cleared.",
        )

    try:
        # Unlink structural backend storage assets
        await delete_vector_store(openai_client, session["vector_store_id"])  # type: ignore[arg-type]
        await delete_files_from_openai(openai_client, session["uploaded_file_ids"])  # type: ignore[arg-type]
    except Exception as err:
        logger.exception("Failed to delete remote OpenAI assets")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Session wiped but remote OpenAI asset deletion failed: {err}",
        ) from err

    return {
        "status": "success",
        "detail": f"Session {session_id} destroyed cleanly.",
    }
