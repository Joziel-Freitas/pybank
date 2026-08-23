"""Input/Output Utilities Module.

This module provides streamlined CLI tools for interacting with the user via
the terminal. It handles raw string collection, type parsing, and validation
loops based on field configuration entries.
"""

from collections.abc import Callable
from datetime import date
from decimal import InvalidOperation

from infra import terminal_input
from presentation.cli import views
from presentation.types import InnerConfig, InputType, PresentationT
from settings import ADMIN_EXIT_CODE, INACTIVITY_TIMEOUT, TOTAL_TIMEOUT
from shared.exceptions import (
    AdminExitError,
    InactiveUserError,
    InvalidDataError,
    UserAbortError,
)

EXIT_CMD = "S"


def parse_input_date(str_date: str) -> date:
    """Casts a Brazilian formatted date string into a native date object."""
    return date.strptime(str_date, "%d/%m/%Y")


def get_user_input[In_T: InputType, Out_T: PresentationT](
    field_config: InnerConfig,
    input_type: Callable[[str], In_T],
    validation_fn: Callable[[In_T], Out_T],
    loop_header: Callable[[], None] | None = None,
    use_timeout: bool = True,
) -> Out_T:
    """Collects user input from the terminal, parses types, and applies validation.

    Renders screen prompts, captures raw terminal input, converts it via the specified
    parser, and executes domain or presentation validators in an interactive loop.
    Enforces inactivity timeouts and handles abort signals.

    Args:
        field_config (InnerConfig[In_T, Out_T]): Schema definition containing field labels,
            prompts, parser functions, and error feedback messages.
        use_timeout (bool): If True, enforces global Kiosk inactivity and total session limits.
        loop_header (Callable[[], None] | None): Optional parameterless view renderer called
            at the start of each retry iteration to restore persistent screen layouts.
        callback_fn (Callable[[In_T], Out_T] | None): Optional dynamic validator override.
            If provided, takes precedence over the default 'validation_fn' in field_config.

    Returns:
        Out_T: The strongly-typed, fully validated value ready for presentation or DTO construction.

    Raises:
        UserAbortError: Raised when the user inputs the standard exit trigger ('S').
        AdminExitError: Raised when the secure admin shutdown code is supplied.
        InactiveUserError: Raised when user input exceeds configured inactivity timeouts.
    """
    info = field_config["info"]
    prompt = field_config["prompt"]
    error_msg = field_config["error_msg"]

    while True:
        print("\033[2J\033[3J\033[H", end="", flush=True)

        if loop_header:
            loop_header()

        print()
        print(f"{info:^45}")
        print(f"{">> 'S' para sair <<":^45}")
        print("-" * 45)

        try:
            if use_timeout:
                user_in = terminal_input.custom_input(
                    prompt=prompt,
                    inactive_timeout=INACTIVITY_TIMEOUT,
                    total_timeout=TOTAL_TIMEOUT,
                    only_alphanumeric=False,
                ).strip()
            else:
                user_in = terminal_input.custom_input(prompt=prompt)

            if user_in == "":
                continue

            if user_in.upper() == EXIT_CMD:
                raise UserAbortError("Input aborted by user")

            if user_in == ADMIN_EXIT_CODE:
                raise AdminExitError(
                    "admin exit code detected: Shutting down the system"
                )
            parsed_in = input_type(user_in)
            return validation_fn(parsed_in)
        except (InvalidDataError, InvalidOperation, ValueError):
            views.system_output(error_msg, wait=True)
            views.system_output(f"Tente novamente ou digite {EXIT_CMD} para sair")
        except TimeoutError as e:
            raise InactiveUserError from e
