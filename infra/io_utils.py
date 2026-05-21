"""
Input/Output Utilities Module.

This module provides generic tools for interacting with the user via the terminal.
It handles data collection, type conversion, and orchestration of input loops
based on configuration maps. It is agnostic to domain rules and relies on the
`verify` module for strict type safety at the public boundaries.
"""

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Callable, NotRequired, TypedDict

from inputimeout import TimeoutOccurred, inputimeout

from infra import verify
from settings import SYSTEM_TIMEOUT
from shared.exceptions import InactiveUserError, UserAbortError
from shared.validators import ValidatorCallback

IO_KEYS = {"info", "prompt", "value_type", "error_msg"}
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

                if k == "input_type" and not callable(v):
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
    verify.verify_instance(attr_value, (str, int, float, Decimal))
    verify.verify_instance(validation_mapper, dict)

    if attr_field not in validation_mapper:
        raise KeyError(
            f"{attr_field} not found in validation mapper: {validation_mapper}"
        )

    validation_func = validation_mapper[attr_field]
    result = validation_func(attr_value)
    return {"result": result}


def _get_user_input(field_config: InnerConfig, use_timeout: bool) -> InputType:
    """
    Collects user input, handles type conversion, and optionally checks for exit/timeout conditions.

    Acts as a secure, private worker method for input collection. It relies on the
    public orchestrator methods to have pre-validated the 'field_config' structure.
    If 'use_timeout' is active, it enforces the global SYSTEM_TIMEOUT inactivity limit.

    Args:
        field_config (InnerConfig): The validated dictionary configuration for a single field.
        use_timeout (bool): Flag indicating if the Kiosk inactivity timeout should be enforced.

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

    print(f"\n--- {info} ---\t>> 'S' para sair <<")

    while True:
        try:
            if use_timeout:
                user_in = inputimeout(prompt=prompt, timeout=SYSTEM_TIMEOUT).strip()
            else:
                user_in = input(prompt).strip()

            if user_in.upper() == EXIT_CMD:
                raise UserAbortError("Input aborted by user")

            return input_type(user_in)
        except (ValueError, InvalidOperation):
            print()
            print(error_msg)
            print(f"\nTente novamente ou digite {EXIT_CMD} para sair")
        except TimeoutOccurred as e:
            raise InactiveUserError from e


def config_loop(
    config_map: ConfigMap,
    callback_fn: Callable[[str, InputType], CallbackReturn],
    skip_fields: list[str | None] | None = None,
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

    user_inputs: dict[str, InputType] = {}

    for field, config_dict in config_map.items():
        if field in skip_fields:
            continue
        if None in skip_fields:
            break
        while True:
            user_in = _get_user_input(config_dict, use_timeout)

            callback_return = callback_fn(field, user_in)
            result = callback_return.get("result")
            skip = callback_return.get("skip_fields")

            if skip is not None:
                skip_fields.extend(skip)

            if result is True:
                user_inputs[field] = user_in
                break
            elif result is False:
                print(config_map[field]["error_msg"])
                continue

            raise RuntimeError(f"Unexpected callback return: {callback_return}")

    return user_inputs


def get_single_input(
    field_key: str,
    config_map: ConfigMap,
    callback_fn: Callable[[str, InputType], CallbackReturn],
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

    field_config = {field_key: config_map[field_key]}
    user_inputs = config_loop(field_config, callback_fn, use_timeout=use_timeout)
    return user_inputs[field_key]


def get_selected_inputs(
    target_fields: tuple[str, ...],
    config_map: ConfigMap,
    callback_fn: Callable[[str, InputType], CallbackReturn],
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

    sub_config = {k: config_map[k] for k in target_fields}
    user_in_dict = config_loop(sub_config, callback_fn, use_timeout=use_timeout)
    return user_in_dict
