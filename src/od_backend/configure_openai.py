"""Process config.toml if present and initialize the OpenAI client."""

import logging
import os
import tomllib

from openai import AsyncOpenAI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Define the OpenAI model to use.
OPENAI_MODEL: str = "gpt-5.6-luna"


def _initialize_credentials() -> None:
    """
    Maybe read CONFIG_TOML_FILE to define OPENAI_API_KEY as an env variable.

    Raises
    ------
    RuntimeError if OPENAI_API_KEY is not available as an environment variable.

    """
    # If CONFIG_TOML_FILE environment variable is defined, read from it.
    if "OPENAI_API_KEY" not in os.environ:
        if "CONFIG_TOML_FILE" in os.environ:
            with open(os.environ["CONFIG_TOML_FILE"], "rb") as toml_file:
                try:
                    cfg = tomllib.load(toml_file)

                    if "OPENAI_DEV" in cfg:
                        # Write credentials from CONFIG_TOML_FILE to the environment.
                        os.environ["OPENAI_API_KEY"] = cfg["OPENAI_DEV"][
                            "OPENAI_API_KEY"
                        ]
                    else:
                        raise RuntimeError("OPENAI_DEV section not in config.toml")
                except tomllib.TOMLDecodeError:
                    logger.exception("config.toml is invalid")
                    raise
        else:
            raise RuntimeError("Unable to access OPENAI_API_KEY environment variable")


def initialize_openai() -> AsyncOpenAI:
    """
    Initialize the OpenAI client.

    Raises
    ------
    RuntimeError or TOMLDecodeError when OPENAI_API_KEY isn't available.

    """
    _initialize_credentials()

    # Initialize the asynchronous OpenAI client, which reads OPENAI_API_KEY.
    return AsyncOpenAI()
