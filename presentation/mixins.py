from abc import ABC, abstractmethod
from functools import partial

from application import validators
from presentation.cli import io_utils
from presentation.types import ConfigMap


class SharedPromptsMixin(ABC):
    """Mixin providing reusable I/O workflows for common, sensitive data entry.

    Encapsulates standard terminal interactive routines like double-entry
    password validation and CPF gathering. Delegates prompt rendering and input
    parsing directly to `io_utils.get_user_input`.
    """

    _config_mapper: ConfigMap

    # --------------------------------------------------------------------------
    # Abstract methods
    # --------------------------------------------------------------------------
    @abstractmethod
    def _handle_info_ui(
        self,
        context_key: str,
        info_key: str,
        wait: bool = False,
        clean: bool = False,
        **kwargs,
    ) -> None:
        """Abstract contract to trigger contextual presentation outputs.

        Args:
            context_key (str): The category inside the message catalog (e.g., 'info').
            info_key (str): The specific lookup key for the UI template string.
            wait (bool, optional): If True, pauses execution until user input. Defaults to False.
            clean (bool, optional): If True, clears the terminal screen before output. Defaults to False.
            **kwargs: Dynamic placeholder values to format into the message template.
        """
        raise NotImplementedError

    # --------------------------------------------------------------------------
    # Protected methods
    # --------------------------------------------------------------------------
    def _prompt_new_password(self) -> str:
        """Handles the double-input loop for creating or updating a secure password.

        Prompts the user twice for a 6-digit password and ensures both inputs match
        before returning the validated credential string.

        Returns:
            str: The validated, matching 6-digit password string.
        """
        mapper = self._config_mapper["password"]

        while True:
            pwd_1 = io_utils.get_user_input(
                mapper,
                input_type=str,
                validation_fn=validators.validate_password,
                loop_header=partial(
                    self._handle_info_ui, context_key="info", info_key="pwd_input"
                ),
            )

            pwd_2 = io_utils.get_user_input(
                mapper,
                input_type=str,
                validation_fn=validators.validate_password,
                loop_header=partial(
                    self._handle_info_ui, context_key="info", info_key="pwd_confirm"
                ),
            )

            if pwd_1 == pwd_2:
                return pwd_1

            self._handle_info_ui("info", "pwd_error", wait=True)

    def _prompt_cpf(self) -> str:
        """Collects and validates a CPF identification string from terminal input.

        Returns:
            str: The 11-digit mathematical checksum-validated CPF string.
        """
        mapper = self._config_mapper["cpf"]
        return io_utils.get_user_input(
            mapper,
            input_type=str,
            validation_fn=validators.validate_cpf,
        )
