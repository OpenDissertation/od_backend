"""Defines Pydantic schemas for session data structures and functions to process files."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import anyio
from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    import os

    from openai import AsyncOpenAI
    from openai.types import FileObject, VectorStore
    from openai.types.vector_stores import VectorStoreFile, VectorStoreFileBatch

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class UploadFilesRequest(BaseModel):
    """
    Stores the list of files to upload at the start of an OpenAI Chat session.

    Attributes
    ----------
    session_id: The OpenAI session ID.
    file_paths: The list of file paths to upload to the OpenAI client.

    """

    model_config = ConfigDict(frozen=True)

    session_id: str
    file_paths: list[str]


class ChatRequest(BaseModel):
    """
    Stores the request text data in an OpenAI Chat Session.

    Attributes
    ----------
    session_id: The OpenAI session ID.
    question: The question that the user is asking.

    """

    model_config = ConfigDict(frozen=True)

    session_id: str
    question: str


class ChatResponse(BaseModel):
    """
    Stores the response text data in an OpenAI Chat Session.

    Attributes
    ----------
    session_id: The OpenAI session ID.
    answer: The answer to the user's question from OpenAI.
    previous_response_id: The ID of the previous response from OpenAI.

    """

    model_config = ConfigDict(frozen=True)

    session_id: str
    answer: str
    previous_response_id: str


"""
In-memory session store. Replace with a Redis instance later.

Structure:
{
    session_id: {
        "uploaded_file_ids": list[str],
        "vector_store_id": str,
        "previous_response_id": str | None,
    }
}
"""
SESSION_DB: dict[str, dict[str, list[str] | str | None]] = {}


async def upload_files_to_openai(
    openai_client: AsyncOpenAI, file_paths: list[str]
) -> list[str]:
    """
    Read and upload a list of files to OpenAI. Max size is 50 MB per file.

    Max size is based on
    https://developers.openai.com/api/docs/guides/file-inputs#usage-considerations
    instead of
    https://developers.openai.com/api/reference/python/resources/files/methods/create.

    Attributes
    ----------
    openai_client: The AsyncOpenAI client to upload the file to.
    file_paths: A list of file paths to upload.

    Returns
    -------
    A list of IDs for files that were uploaded.

    Raises
    ------
    HTTPException if upload fails.

    """
    max_file_size_bytes: int = 50 * 1024 * 1024

    uploaded_file_ids: list[str] = []

    for file_path in file_paths:
        async_path = anyio.Path(file_path)

        if not await async_path.exists():
            logger.warning("Skip path %s, does not exist", file_path)
            continue

        if not await async_path.is_file():
            logger.warning("Skip path %s, which is not a file", file_path)
            continue

        file_stat: os.stat_result = await async_path.stat()
        if file_stat.st_size > max_file_size_bytes:
            logger.warning("Skip path %s larger than 50 MB", file_path)
            continue

        try:
            file_content: bytes = await async_path.read_bytes()
            uploaded_file: FileObject = await openai_client.files.create(
                file=file_content,
                purpose="assistants",
                expires_after={
                    "anchor": "created_at",
                    "seconds": 87000,
                },
            )
            logger.info(
                "File %s with ID %s uploaded successfully!",
                file_path,
                uploaded_file.id,
            )
            uploaded_file_ids.append(uploaded_file.id)
        except Exception as err:
            logger.exception("OpenAI upload failed for file %s", file_path)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"OpenAI File Upload failed: {err}",
            ) from err

    return uploaded_file_ids


async def create_vector_store(openai_client: AsyncOpenAI) -> str:
    """
    Create a vector store to store files/dissertations for searching.

    See https://developers.openai.com/api/docs/guides/tools-file-search

    Attributes
    ----------
    openai_client: The AsyncOpenAI client to create a vector store for.

    Returns
    -------
    The ID of the vector store that was created.

    Raises
    ------
    HTTPException if vector store creation fails.

    """
    try:
        file_vector_store: VectorStore = await openai_client.vector_stores.create(
            name="dissertation_knowledge_base",
            expires_after={
                "anchor": "last_active_at",
                "days": 1,
            },
        )
        logger.info(
            "Successfully created vector store with ID %s", file_vector_store.id
        )
    except Exception as err:
        logger.exception("OpenAI failed to create vector store")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OpenAI VectorStore creation failed: {err}",
        ) from err

    return file_vector_store.id


async def add_files_to_vector_store(
    openai_client: AsyncOpenAI,
    vector_store_id: str,
    uploaded_file_ids: list[str],
) -> None:
    """
    Add one or more files to the vector store.

    See https://developers.openai.com/api/reference/python/resources
        /vector_stores/subresources/files/methods/create
    and https://developers.openai.com/api/reference/python/resources
        /vector_stores/subresources/file_batches/methods/create.

    Attributes
    ----------
    openai_client: The AsyncOpenAI client owning the vector store to add files to.
    vector_store_id: The ID of the vector store to add file(s) to.
    uploaded_file_ids: A list of file IDs to add to the vector store.

    Returns
    -------
    None.

    Raises
    ------
    RuntimeError if uploaded_file_ids is empty.
    HTTPException if failed to add files to vector store.

    """
    if not uploaded_file_ids:
        raise RuntimeError("List of uploaded file IDs is empty")

    try:
        if len(uploaded_file_ids) == 1:
            single_file_result: VectorStoreFile = (
                await openai_client.vector_stores.files.create(
                    vector_store_id=vector_store_id,
                    file_id=uploaded_file_ids[0],
                )
            )
            logger.info(
                "Successfully added file ID %s with usage_bytes %d "
                "to vector store ID %s with VectorStoreFile ID %s",
                uploaded_file_ids[0],
                single_file_result.usage_bytes,
                vector_store_id,
                single_file_result.id,
            )
        else:
            multi_file_result: VectorStoreFileBatch = (
                await openai_client.vector_stores.file_batches.create(
                    vector_store_id=vector_store_id,
                    file_ids=uploaded_file_ids,
                )
            )
            logger.info(
                "Added file IDs to vector store ID %s with Batch ID %s. "
                "total: %d, completed: %d, in_progress: %d, failed: %d, cancelled %d.",
                vector_store_id,
                multi_file_result.id,
                multi_file_result.file_counts.total,
                multi_file_result.file_counts.completed,
                multi_file_result.file_counts.in_progress,
                multi_file_result.file_counts.failed,
                multi_file_result.file_counts.cancelled,
            )
    except Exception as err:
        logger.exception(
            "OpenAI failed to add %d file(s) to vector store ID %s",
            len(uploaded_file_ids),
            vector_store_id,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OpenAI failed to add files to vector store: {err}",
        ) from err


def add(lhs: int, rhs: int) -> int:
    """
    Test function that adds two integers.

    Args
    ----
    lhs: The left-hand int to add.
    rhs: The right-hand int to add.

    Returns
    -------
    The sum of lhs and rhs.

    """
    return lhs + rhs
