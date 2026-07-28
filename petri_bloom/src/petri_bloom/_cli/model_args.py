"""Shared `-M` model argument handling for the CLI commands."""

import click
from dotenv import load_dotenv
from inspect_ai._cli.util import (
    parse_cli_args,  # pyright: ignore[reportPrivateImportUsage]
)
from inspect_ai.model import Model, get_model

model_args_option = click.option(
    "-M",
    "model_args",
    multiple=True,
    metavar="ARG=VALUE",
    help=(
        "Model argument passed through to the provider, e.g. "
        "-M reasoning_enabled=false. Repeatable."
    ),
)


def resolve_model_args(model: str, model_args: tuple[str, ...]) -> str | Model:
    """Build a `Model` when `-M` arguments are supplied.

    Returns the model name unchanged when there are no arguments, so the stage
    keeps its own resolution behavior.

    Args:
        model: Model name from `--model-role`.
        model_args: Raw `key=value` strings collected from `-M`.

    Returns:
        The model name, or a `Model` constructed with the parsed arguments.
    """
    if not model_args:
        return model
    # The stages load .env themselves, but constructing the client here happens
    # first, so provider credentials must be present before get_model.
    load_dotenv()
    return get_model(model, **parse_cli_args(model_args))
