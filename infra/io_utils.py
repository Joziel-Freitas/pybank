"""
Input/Output Utilities Module.

This module provides generic tools for interacting with the user via the terminal.
It handles data collection, type conversion, and orchestration of input loops
based on configuration maps. It is agnostic to domain rules and relies on the
`verify` module for strict type safety at the public boundaries.
"""

import os
import sys
import time
from collections.abc import Callable
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import NotRequired, TypedDict

from infra import verify, views
from settings import SYSTEM_TIMEOUT
from shared.exceptions import UserAbortError
from shared.validators import ValidatorCallback

try:
    import msvcrt
except ImportError:
    msvcrt = None

try:
    import select
    import termios
    import tty
except ImportError:
    select = termios = tty = None

IS_WINDOWS = sys.platform == "win32"
IO_KEYS = {"info", "prompt", "input_type", "error_msg"}
EXIT_CMD = "S"

type InputType = str | int | float | Decimal | date
type ConfigMap = dict[str, InnerConfig]


class InnerConfig(TypedDict):
    """
    Typed dictionary that defines the structure of a configuration entry.

    Attributes:
        info (str): Short description or label for the configuration option.
        prompt (str): Text shown to the user when input is required.
        input_type (Callable[[str], InputType]): A callable (like a built-in type
            or a custom parser) that casts the raw string input into the expected Python type.
        error_msg (str): Error message displayed when the input does not match
            the expected type or format.
    """

    info: str
    prompt: str
    input_type: Callable[[str], InputType]
    error_msg: str


class CallbackReturn(TypedDict):
    """
    Return structure for validation callbacks.

    Attributes:
        result (bool):
            True if input is valid, False otherwise.
        skip_fields (tuple[str | None], optional):
            Fields to skip in the current loop.
            - If the tuple contains None, the loop terminates immediately.
    """

    result: bool
    skip_fields: NotRequired[tuple[str | None]]


if IS_WINDOWS:

    def _get_char_windows() -> str | None:
        """Reads a single character on Windows via `msvcrt` without blocking execution.

        Captures raw keyboard input using `msvcrt.getwch()`. Consumes 2-byte
        extended keys (such as arrow and function keys) without polluting the system
        input buffer. Relieves CPU usage with a short sleep when the buffer is idle.

        Returns:
            str | None: The decoded character read from the Windows console, or
            `None` if no key is pressed or if an extended key sequence is discarded.

        Raises:
            NotImplementedError: If the `msvcrt` module is not available.
        """
        if msvcrt is None:
            raise NotImplementedError(
                "_get_char_windows cannot be implemented without msvcrt lib"
            )

        # If no key is in the buffer, sleep 50ms to reduce CPU usage
        if not msvcrt.kbhit():  # type: ignore
            time.sleep(0.05)
            return None

        ch = msvcrt.getwch()  # type: ignore

        # Discard the 2nd byte of extended keys (Arrows, F1-F12, etc.)
        if ch in ("\x00", "\xe0"):
            msvcrt.getwch()  # type: ignore
            return None

        return ch

else:

    def _get_char_posix() -> str | None:
        """Reads a single character on POSIX/Linux systems via non-blocking I/O
        directly from the kernel (`os.read`).

        Uses `select.select` and the `os.read` system call directly on the stdin
        file descriptor (`fd`). This bypasses Python's internal I/O buffer,
        ensuring immediate capture and purging of multi-byte ANSI escape
        sequences (e.g., arrow keys `\\x1b[D`).

        Returns:
            str | None: The normalized character (`\\r` for Enter, `\\x08` for Backspace),
            or `None` if no key is pressed or if an escape sequence is discarded.

        Raises:
            NotImplementedError: If `select`, `termios`, or `tty` are unavailable.
        """
        if select is None or termios is None or tty is None:
            raise NotImplementedError(
                "_get_char_posix cannot be implemented without libs select, termios and tty"
            )

        fd = sys.stdin.fileno()
        r_list, _, _ = select.select([fd], [], [], 0.05)

        if r_list:
            # Raw (unbuffered) read from File Descriptor to avoid misguiding select
            ch_bytes = os.read(fd, 1)

            if not ch_bytes:
                return None

            ch = ch_bytes.decode("utf-8", errors="ignore")

            # Purge ANSI escape sequences (Arrows/Functions) from the kernel buffer
            if ch == "\x1b":
                while select.select([fd], [], [], 0)[0]:
                    os.read(fd, 1)
                return None

            # POSIX key normalization
            if ch == "\n":
                return "\r"

            if ch == "\x7f":
                return "\x08"

            return ch
        return None


def custom_input(
    prompt: str = "",
    inactive_timeout: float | None = None,
    total_timeout: float | None = None,
    only_alphanumeric: bool = True,
):
    """Prompts for and captures a line of text character-by-character with custom filtering
    and dual-timeout support.

    Switches POSIX terminals to cbreak mode during execution and guarantees
    restoration of original settings in a `finally` block. Supports real-time echo,
    visual character deletion (Backspace), optional alphanumeric restriction, and
    both inactivity and total session timeouts.

    Args:
        prompt (str, optional): Instruction text displayed to the user.
            Defaults to "".
        inactive_timeout (float | None, optional): Maximum allowed user inactivity time
            between keypresses in seconds. `None` disables this limit. Defaults to None.
        total_timeout (float | None, optional): Maximum total allowed duration for the
            entire input session in seconds. `None` disables this limit. Defaults to None.
        only_alphanumeric (bool, optional): If True, restricts character input to letters,
            digits, and spaces. Defaults to True.

    Returns:
        str: The string containing the input typed by the user up to the Enter key.

    Raises:
        TimeoutError: If either `inactive_timeout` or `total_timeout` is exceeded.
    """
    if IS_WINDOWS:
        _get_char_fn = _get_char_windows
    else:
        _get_char_fn = _get_char_posix
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)  # type: ignore
        tty.setcbreak(fd)  # type: ignore

    buffer: list[str] = []
    start_time = time.time()
    last_activity = time.time()

    sys.stdout.write(prompt)
    sys.stdout.flush()

    try:
        while True:
            inactivity_exceeded = False
            timeout_exceeded = False
            timeout_msg = None
            char = _get_char_fn()
            now = time.time()

            if inactive_timeout:
                if char:
                    last_activity = time.time()

                inactivity_exceeded = (now - last_activity) > inactive_timeout
                if inactivity_exceeded:
                    timeout_msg = "Inactive timeout exceeded"

            if total_timeout:
                timeout_exceeded = (now - start_time) > total_timeout
                if timeout_exceeded:
                    timeout_msg = "Total timeout exceeded"

            if inactivity_exceeded or timeout_exceeded:
                sys.stdout.write("\n")
                sys.stdout.flush()
                raise TimeoutError(timeout_msg)

            if not char:
                continue

            # Enter key (Finalize input)
            if char == "\r":
                sys.stdout.write("\n")
                sys.stdout.flush()
                return "".join(buffer)

            # Backspace key (Remove from buffer and screen)
            elif char == "\x08":
                if buffer:
                    buffer.pop()
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()

            # Character echo and filtering
            elif char.isprintable():
                if only_alphanumeric and not (char.isalnum() or char == " "):
                    continue
                buffer.append(char)
                sys.stdout.write(char)
                sys.stdout.flush()
    finally:
        # Ensure POSIX terminal restoration even if exceptions or timeouts occur
        if not IS_WINDOWS:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)  # type: ignore


def parse_input_date(str_date: str) -> date:
    """Casts a Brazilian formatted date string into a native date object."""
    return date.strptime(str_date, "%d/%m/%Y")


def verify_config_map(obj_config: ConfigMap) -> None:
    """
    Verifies if the configuration map follows the expected nested dictionary structure.

    Ensures that the provided map is a dictionary where each key is a string,
    and its value is an inner dictionary. It validates that within the inner
    dictionary, the 'input_type' key holds a Callable, while all other keys
    hold string values.

    Args:
        obj_config (ConfigMap):
            The configuration map to be verified.

    Raises:
        TypeError:
            If the structure does not match the expected InnerConfig schema.
    """
    try:
        verify.verify_instance(obj_config, dict)

        for key, inner_dict in obj_config.items():
            verify.verify_instance(key, str)
            verify.verify_instance(inner_dict, dict)

            if inner_dict.keys() != IO_KEYS:
                raise TypeError

            for k, v in inner_dict.items():
                verify.verify_instance(k, str)

                if k == "input_type":
                    if callable(v):
                        continue
                    raise TypeError("The key 'input_type' expects a callable")

                verify.verify_instance(v, str)
    except TypeError as e:
        raise TypeError(
            "obj_config must follow the InnerConfig schema strictly."
        ) from e


def validate_entry(
    attr_field: str,
    attr_value: InputType,
    validation_mapper: dict[str, ValidatorCallback],
) -> CallbackReturn:
    """
    Generic dispatcher that validates an input value against a mapper of validators.

    This function serves as a bridge between the generic 'config_loop' and specific
    domain validation logic.

    NOTE: 'validation_mapper' is placed last to accommodate 'functools.partial' usage,
    allowing 'attr_field' and 'attr_value' to be passed as positional arguments
    by the configuration loop.

    Args:
        attr_field (str): The name of the field currently being processed.
        attr_value (InputType): The value entered by the user.
        validation_mapper (dict[str, ValidatorCallback]): A dictionary mapping field
            names to their corresponding validation functions.

    Returns:
        CallbackReturn: A dictionary containing the validation result ('result': bool).
            If the field is not found in the mapper, returns {'result': True} by default.

    Raises:
        TypeError: If any of the arguments fail strict type verification.
        KeyError: If the field is not found within the provided validation mapper.
    """
    verify.verify_instance(attr_field, str)
    verify.verify_instance(attr_value, (str, int, float, date, Decimal))
    verify.verify_instance(validation_mapper, dict)

    if attr_field not in validation_mapper:
        raise KeyError(
            f"{attr_field} not found in validation mapper: {validation_mapper}"
        )

    validation_func = validation_mapper[attr_field]
    result = validation_func(attr_value)
    return {"result": result}


def _get_user_input(
    field_config: InnerConfig,
    use_timeout: bool,
    loop_header: Callable[[], None] | None = None,
) -> InputType:
    """
    Collects user input, handles type conversion, and optionally checks for exit/timeout conditions.

    Acts as a secure, private worker method for input collection. It relies on the
    public orchestrator methods to have pre-validated the 'field_config' structure.
    If 'use_timeout' is active, it enforces the global SYSTEM_TIMEOUT inactivity limit.

    Args:
        field_config (InnerConfig): The validated dictionary configuration for a single field.
        use_timeout (bool): Flag indicating if the Kiosk inactivity timeout should be enforced.
        loop_header (Callable[[], None], optional):
            A parameterless callback function executed at the beginning of each
            input retry cycle. Used to redraw persistent visual contexts (such as
            menus, tables, or selection lists) after a terminal screen clear.
            Defaults to None.

    Returns:
        InputType: The user input value cast to the type specified by 'input_type'.

    Raises:
        UserAbortError: If the user enters the EXIT_CMD (e.g., 'S') to abort the operation.
        InactiveUserError: If 'use_timeout' is True and the user exceeds the system time limit.
        ValueError | InvalidOperation: If the raw input cannot be cast by the provided callable.
    """
    info = field_config["info"]
    prompt = field_config["prompt"]
    input_type = field_config["input_type"]
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
                user_in = custom_input(
                    prompt=prompt,
                    inactive_timeout=SYSTEM_TIMEOUT,
                    only_alphanumeric=True,
                ).strip()
            else:
                user_in = custom_input(prompt=prompt)

            if user_in == "":
                continue

            if user_in.upper() == EXIT_CMD:
                raise UserAbortError("Input aborted by user")

            return input_type(user_in)
        except (ValueError, InvalidOperation):
            views.system_output(error_msg, wait=True)
            views.system_output(f"Tente novamente ou digite {EXIT_CMD} para sair")


def config_loop(
    config_map: ConfigMap,
    callback_fn: Callable[[str, InputType], CallbackReturn],
    skip_fields: list[str | None] | None = None,
    loop_header: Callable[[], None] | None = None,
    use_timeout: bool = True,
) -> dict[str, InputType]:
    """
    Iterates over a configuration dictionary, collecting and validating data using a contextual callback.

    Args:
        config_map (ConfigMap): The configuration map containing the required fields.
        callback_fn (Callable[[str, InputType], CallbackReturn]): A validation function
            called for each collected input.
        skip_fields (list[str | None], optional): A mutable list of accumulated skip keys.
            Defaults to an empty list.
        loop_header (Callable[[], None], optional):
            A parameterless callback function executed at the beginning of each
            input retry cycle. Used to redraw persistent visual contexts (such as
            menus, tables, or selection lists) after a terminal screen clear.
            Defaults to None.
        use_timeout (bool, optional): Flag to activate inactivity tracking. Defaults to True.

    Returns:
        dict[str, InputType]: A dictionary with the validated input fields and their values.

    Raises:
        UserAbortError: Propagated if the user chooses to abort.
        InactiveUserError: Propagated if the session times out.
        ValueError: If skip keys are invalid or missing from the map.
        TypeError: If structural verification of the config map or arguments fails.
    """
    verify.verify_instance(use_timeout, bool)
    verify_config_map(config_map)

    if skip_fields is None:
        skip_fields = []
    elif not isinstance(skip_fields, list):
        raise TypeError(
            f"'skip_fields' must be a list, not {type(skip_fields).__name__}"
        )

    skip_fields_set = set(skip_fields) - {None}
    config_map_set = set(config_map)

    if not skip_fields_set.issubset(config_map_set):
        raise ValueError("Fields to skip not found in config map fields.")

    if not callable(callback_fn):
        raise TypeError(
            f"callback_fn expects a callable, got {type(callback_fn).__name__}"
        )

    if loop_header and not callable(loop_header):
        raise TypeError(
            f"loop_header expects a callable, got {type(loop_header).__name__}"
        )

    user_inputs: dict[str, InputType] = {}

    for field, config_dict in config_map.items():
        if field in skip_fields:
            continue
        if None in skip_fields:
            break
        while True:
            user_in = _get_user_input(
                config_dict, use_timeout=use_timeout, loop_header=loop_header
            )

            callback_return = callback_fn(field, user_in)
            result = callback_return.get("result")
            skip = callback_return.get("skip_fields")

            if skip is not None:
                skip_fields.extend(skip)

            if result is True:
                user_inputs[field] = user_in
                break
            elif result is False:
                msg = config_dict["error_msg"]
                views.system_output(msg, wait=True)
                continue

            raise RuntimeError(f"Unexpected callback return: {callback_return}")

    return user_inputs


def get_single_input(
    field_key: str,
    config_map: ConfigMap,
    callback_fn: Callable[[str, InputType], CallbackReturn],
    loop_header: Callable[[], None] | None = None,
    use_timeout: bool = True,
) -> InputType:
    """
    Retrieves and validates a single input field based on a configuration map.

    This function acts as a convenience wrapper around 'config_loop', isolating
    a specific field configuration to prompt the user for a single value.

    Args:
        field_key (str): The key of the specific field within the config_map to be retrieved.
        config_map (ConfigMap): The full configuration dictionary containing the field's settings.
        callback_fn (Callable[[str, InputType], CallbackReturn]): The validation callback function.
        loop_header (Callable[[], None], optional):
            A parameterless callback function executed at the beginning of each
            input retry cycle. Used to redraw persistent visual contexts (such as
            menus, tables, or selection lists) after a terminal screen clear.
            Defaults to None.
        use_timeout (bool, optional): Flag to activate inactivity tracking. Defaults to True.

    Returns:
        InputType: The validated value entered by the user.

    Raises:
        KeyError: If 'field_key' is not present in 'config_map'.
        UserAbortError: If the user cancels the operation via the exit command.
        InactiveUserError: If the session times out.
        TypeError: If argument types fail verification.
    """
    verify.verify_instance(field_key, str)
    verify.verify_instance(use_timeout, bool)
    verify_config_map(config_map)

    if not callable(callback_fn):
        raise TypeError(
            f"callback_fn expects a callable, got {type(callback_fn).__name__}"
        )

    if loop_header and not callable(loop_header):
        raise TypeError(
            f"loop_header expects a callable, got {type(loop_header).__name__}"
        )

    field_config = {field_key: config_map[field_key]}
    user_inputs = config_loop(
        field_config, callback_fn, use_timeout=use_timeout, loop_header=loop_header
    )
    return user_inputs[field_key]


def get_selected_inputs(
    target_fields: tuple[str, ...],
    config_map: ConfigMap,
    callback_fn: Callable[[str, InputType], CallbackReturn],
    loop_header: Callable[[], None] | None = None,
    use_timeout: bool = True,
) -> dict[str, InputType]:
    """
    Retrieves and validates a specific subset of input fields based on a configuration map.

    This function acts as a dynamic wrapper around 'config_loop', safely extracting
    only the requested fields into a sub-configuration.

    Args:
        target_fields (tuple[str, ...]): The exact keys of the fields to be prompted.
        config_map (ConfigMap): The full configuration dictionary containing the fields' settings.
        callback_fn (Callable[[str, InputType], CallbackReturn]): The contextual validation callback.
        loop_header (Callable[[], None], optional):
            A parameterless callback function executed at the beginning of each
            input retry cycle. Used to redraw persistent visual contexts (such as
            menus, tables, or selection lists) after a terminal screen clear.
            Defaults to None.
        use_timeout (bool, optional): Flag to activate inactivity tracking. Defaults to True.


    Returns:
        dict[str, InputType]: A dictionary containing only the requested fields mapped
            to their validated input values.

    Raises:
        KeyError: If any key inside 'target_fields' is not present in the 'config_map'.
        UserAbortError: Propagated if the user cancels the operation.
        InactiveUserError: Propagated if the session times out.
        TypeError: If argument types fail verification.
    """
    verify.verify_instance(target_fields, tuple)
    verify.verify_instance(use_timeout, bool)
    verify_config_map(config_map)

    if not set(target_fields).issubset(config_map):
        raise KeyError("One or more target field(s) not found in config_map")

    if not callable(callback_fn):
        raise TypeError(
            f"callback_fn expects a callable, got {type(callback_fn).__name__}"
        )

    if loop_header and not callable(loop_header):
        raise TypeError(
            f"loop_header expects a callable, got {type(loop_header).__name__}"
        )

    sub_config = {k: config_map[k] for k in target_fields}
    user_in_dict = config_loop(
        sub_config, callback_fn, use_timeout=use_timeout, loop_header=loop_header
    )
    return user_in_dict
