"""
Input/Output Utilities Module.

This module provides generic tools for interacting with the user via the terminal.
It handles data collection, type conversion, and orchestration of input loops
based on configuration maps. It is agnostic to domain rules.
"""

from decimal import Decimal, InvalidOperation
from typing import Callable, NotRequired, Type, TypedDict

from shared.exceptions import UserAbortError
from shared.validators import ValidatorCallback

from .config import ConfigMap, InnerConfig


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


type InputType = str | int | float | Decimal

EXIT_CMD = "S"


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
        attr_field (str):
            The name of the field currently being processed.
        attr_value (InputType):
            The value entered by the user.
        validation_mapper (dict[str, ValidatorCallback]):
            A dictionary mapping field names to their corresponding validation functions.

    Returns:
        CallbackReturn:
            A dictionary containing the validation result ('result': bool).
            If the field is not found in the mapper, returns {'result': True} by default.
    """
    if not isinstance(validation_mapper, dict):
        raise TypeError(
            f"validation_mapper must be a dict, got {type(validation_mapper).__name__}"
        )

    if not isinstance(attr_field, str):
        raise TypeError(f"attr_field must be a string, got {type(attr_field).__name__}")

    if not isinstance(attr_value, (str, int, float, Decimal)):
        raise TypeError(
            f"attr_value must be a string, int, float or Decimal, got {type(attr_value).__name__}"
        )

    if attr_field not in validation_mapper:
        return {"result": True}

    validation_func = validation_mapper[attr_field]
    result = validation_func(attr_value)
    return {"result": result}


def get_user_input(field_config: InnerConfig) -> InputType:
    """
    Collects user input, handles type conversion, and checks for exit commands.

    Args:
        field_config (InnerConfig):
            Dictionary containing 'prompt', 'value_type', etc., for a single field.

    Returns:
        InputType:
            The user input value cast to the specified type.

    Raises:
        UserAbortError:
            If the user enters the EXIT_CMD (e.g., 'S') to abort the operation.
        ValueError:
            If the configuration is missing 'prompt' or 'value_type'.
        TypeError:
            If the specified 'value_type' is not supported (must be str, int, float, or Decimal).
    """
    info: str = field_config.get("info", "Coletando dados...")
    prompt: str = field_config.get("prompt")
    value_type: Type | str = field_config.get("value_type", str)
    error_msg: str = field_config.get("error_msg", "Ocorreu um erro. Tente novamente")

    if not prompt or not value_type:
        raise ValueError("I/O configuration has no value_type or prompt")

    if value_type not in (str, int, float, Decimal):
        raise TypeError("Invalid type specified for I/O utils methods")

    print(f"\n--- {info} ---\t>> 'S' para sair <<")
    while True:
        try:
            value: str | int | float = input(prompt).strip()

            if value.upper() == EXIT_CMD:
                raise UserAbortError("Input aborted by user")

            return value_type(value)
        except (ValueError, InvalidOperation):
            print()
            print(error_msg)
            print(f"\nTente novamente ou digite {EXIT_CMD} para sair")


def config_loop(
    config_map: ConfigMap,
    callback_fn: Callable[[str, InputType], CallbackReturn],
    skip_fields: list[str | None] | None = None,
) -> dict[str, InputType]:
    """
    Iterates over a configuration dictionary, collecting and validating data using a contextual callback.

    Args:
        config_map (ConfigMap):
            The configuration map containing the keys and the InnerConfig for the required data fields.

        callback_fn (Callable[[str, InputType], CallbackReturn]):
            A validation function called for each collected input.
            It receives two arguments:
                1. field_key (str): The key of the field being processed (e.g., 'cpf', 'password').
                2. user_input (InputType): The value collected from the user.

            It MUST return a dictionary (CallbackReturn) with:
            - 'result' (bool):
                - True: Data is valid, store it, and proceed to the next field.
                - False: Data is invalid, print error_msg, and prompt again for the same field.

            - 'skip_fields' (tuple[str | None], optional):
                - An immutable tuple of keys to skip for the current and future iterations.
                - If the tuple contains None, the loop will terminate immediately.

        skip_fields (list[str | None], optional):
            A mutable list of accumulated skip keys. This list is extended with the values
            returned by the callback's 'skip_fields' tuple. Defaults to an empty list.

    Returns:
        dict[str, InputType]:
            A dictionary with the validated input fields and their values.

    Raises:
        UserAbortError:
            Propagated from 'get_user_input' if the user chooses to abort.
        ValueError:
            If any key in 'skip_fields' is provided but not found in 'config_map'.
        TypeError:
            If 'callback_fn' is not callable or 'skip_fields' is not a list.
        UtilsModuleError:
            For unexpected return values from the callback.
    """
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
            user_in = get_user_input(config_dict)

            callback_return: CallbackReturn = callback_fn(field, user_in)
            result: bool = callback_return.get("result")
            skip: tuple[str | None] | None = callback_return.get("skip_fields")

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
) -> InputType:
    """
    Retrieves and validates a single input field based on a configuration map.

    This function acts as a convenience wrapper around 'config_loop', isolating
    a specific field configuration to prompt the user for a single value.
    It simplifies the process when only one piece of data is needed, avoiding
    the need to manually construct single-item dictionaries.

    Args:
        field_key (str):
            The key of the specific field within the config_map to be retrieved.
        config_map (ConfigMap):
            The full configuration dictionary containing the field's settings.
        callback_fn (Callable[[str, InputType], CallbackReturn]):
            The validation callback function (usually a partial) to be used by the loop.

    Returns:
        InputType:
            The validated value entered by the user.

    Raises:
        KeyError:
            If 'field_key' is not present in 'config_map'.
        UserAbortError:
            If the user cancels the operation via the exit command.
        UtilsModuleError:
            If an error occurs during the generic loop execution.
    """
    if not isinstance(field_key, str):
        raise TypeError(f"field_key must be a string, got {type(field_key).__name__}")

    if not isinstance(config_map, dict):
        raise TypeError(f"config_map must be a dict, got {type(config_map).__name__}")

    if field_key not in config_map:
        raise KeyError(f"Field '{field_key}' not found in the provided configuration.")

    if not callable(callback_fn):
        raise TypeError(
            f"callback_fn expects a callable, got {type(callback_fn).__name__}"
        )

    field_config = {field_key: config_map[field_key]}
    user_inputs = config_loop(field_config, callback_fn)
    return user_inputs[field_key]


def get_selected_inputs(
    target_fields: tuple[str, ...],
    config_map: ConfigMap,
    callback_fn: Callable[[str, InputType], CallbackReturn],
) -> dict[str, InputType]:
    """
    Retrieves and validates a specific subset of input fields based on a configuration map.

    This function acts as a dynamic wrapper around 'config_loop'. It safely extracts
    only the requested fields into a sub-configuration, keeping the domain controllers
    clean and free from dictionary manipulation logic.

    Args:
        target_fields (tuple[str, ...]):
            A tuple containing the exact keys of the fields to be prompted.
        config_map (ConfigMap):
            The full configuration dictionary containing the fields' settings.
        callback_fn (Callable[[str, InputType], CallbackReturn]):
            The contextual validation callback function to process the user inputs.

    Returns:
        dict[str, InputType]:
            A dictionary containing only the requested fields mapped to their
            validated input values.

    Raises:
        TypeError:
            If 'target_fields', 'config_map', or 'callback_fn' receive invalid types.
        KeyError:
            If any key inside 'target_fields' is not present in the 'config_map'.
        UserAbortError:
            Propagated from 'config_loop' if the user cancels the operation.
    """

    if not isinstance(target_fields, tuple):
        raise TypeError(
            f"target_fields must be a tuple, got {type(target_fields).__name__}"
        )

    if not isinstance(config_map, dict):
        raise TypeError(f"config_map must be a dict, got {type(config_map).__name__}")

    if not set(target_fields).issubset(config_map):
        raise KeyError("One or more target field(s) not found in config_map")

    if not callable(callback_fn):
        raise TypeError(
            f"callback_fn expects a callable, got {type(callback_fn).__name__}"
        )

    sub_config = {k: config_map[k] for k in target_fields}
    user_in_dict = config_loop(sub_config, callback_fn)
    return user_in_dict
