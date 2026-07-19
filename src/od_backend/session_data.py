"""Defines Pydantic schemas for session data structures."""

from pydantic import BaseModel, ConfigDict, HttpUrl


class InitSessionRequest(BaseModel):
    """
    Stores the list of files needed to initialize an OpenAI Chat session.

    Attributes
    ----------
    session_id: The OpenAI session ID.
    file_urls: The list of file URLs to retrieve.

    """

    model_config = ConfigDict(frozen=True)

    session_id: str
    file_urls: list[HttpUrl]


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
    question: str
    previous_response_id: str


"""
In-memory session store. Replace with a Redis instance later.

Structure:
{
    session_id: {
        "file_ids": list[str],
        "previous_response_id": str | None,
    }
}
"""
SESSION_DB: dict[str, dict[str, list[str] | str | None]] = {}


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
