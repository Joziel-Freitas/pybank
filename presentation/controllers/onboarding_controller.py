from datetime import date
from typing import Any

import settings
from application import validators
from application.dtos import AccountDataDTO, CheckDataDTO, NewAccountDTO
from application.services.onboarding_service import OnboardingService
from application.types import NewAccountType
from presentation.cli import config, io_utils, ui_messages
from presentation.controllers.base_controller import BaseController
from presentation.controllers.mixins import SharedPromptsMixin
from presentation.types import AccountTypeMenu
from shared.exceptions import (
    AccountHolderNotFoundError,
    ControllerRegisterError,
    DuplicatedAccountError,
    DuplicatedAccountHolderError,
    UserAbortError,
)

# =====================================================================
# Onboarding Controller
# =====================================================================


class OnboardingController(BaseController[OnboardingService], SharedPromptsMixin):
    """Controller responsible for the registration of new clients and accounts.

    Guides the user through terminal I/O data collection loops, builds required
    transfer payloads (DTOs), and interacts directly with the `OnboardingService`
    to persist new account holders and accounts.
    """

    # --------------------------------------------------------------------------
    # Constructor
    # --------------------------------------------------------------------------
    def __init__(
        self,
        service: OnboardingService,
        branch_code: str = settings.BRANCH_CODE,
    ):
        """Initializes the onboarding controller with required application services and UI configs.

        Args:
            service (OnboardingService): The concrete application service for client onboarding.
            branch_code (str, optional): The home branch code for new accounts. Defaults to settings.BRANCH_CODE.
        """
        super().__init__(service)

        self._branch_code = branch_code
        self._ui_message_map = ui_messages.ONBOARDING_MESSAGES
        self._config_mapper = (
            config.auth_config
            | config.identification_config
            | config.new_account_config
        )

    # --------------------------------------------------------------------------
    # Public API
    # --------------------------------------------------------------------------
    def run_controller(self) -> None:
        """Orchestrates the client registration and account onboarding lifecycle.

        Guides the applicant through terminal input collection loops to capture identity
        and account data, enforces secure double-entry password creation, constructs
        `NewAccountDTO` payloads, and dispatches registration to the application service.

        Raises:
            ControllerRegisterError: If the proposed account already exists or registration fails.
            RuntimeError: If an unexpected application logic failure occurs.
        """
        try:
            cpf = self._prompt_cpf()
            name_date_tuple = self._handle_account_holder_data(cpf)
            account_dict = self._handle_account_data()
            account_dict["holder_cpf"] = cpf
            account_dict["password"] = self._prompt_new_password()
            self._handle_info_ui("info", "pwd_ok")

            if name_date_tuple:
                account_dict["holder_name"], account_dict["holder_birth_date"] = (
                    name_date_tuple
                )

            self._service.register_account(NewAccountDTO(**account_dict))
            self._handle_info_ui("info", "register_ok", wait=True)
        except UserAbortError:
            self._handle_info_ui("info", "user_cancel", wait=True)
        except DuplicatedAccountError as e:
            self._handle_exception_ui("errors", e)
            raise ControllerRegisterError from e
        except (
            DuplicatedAccountHolderError,
            AccountHolderNotFoundError,
        ):
            raise RuntimeError("Critical error internal logic")

    # --------------------------------------------------------------------------
    # Protected methods
    # --------------------------------------------------------------------------
    def _handle_account_holder_data(self, cpf: str) -> tuple[str, date] | None:
        """Handles the account holder data gathering workflow.

        Queries the application service to check if the CPF is already registered. If found,
        notifies the user and skips identity prompts. Otherwise, prompts for name and birth date.

        Args:
            cpf (str): The validated 11-digit CPF string.

        Returns:
            tuple[str, date] | None: A tuple containing (name, birth_date) if the holder is new,
                or None if the holder already exists in persistence.
        """
        is_holder = self._service.check_data_exists(CheckDataDTO(holder_cpf=cpf))

        if is_holder:
            self._handle_info_ui(
                "info", "already_account_holder", wait=True, clean=True
            )
            return None

        self._handle_info_ui("info", "new_account_holder", wait=True, clean=True)

        name = io_utils.get_user_input(
            self._config_mapper["name"], str, validators.validate_holder_name
        )
        birth_date = io_utils.get_user_input(
            self._config_mapper["birth_date"],
            io_utils.parse_input_date,
            validators.validate_birth_date,
        )

        return (name, birth_date)

    def _handle_account_data(self) -> dict[str, Any]:
        """Orchestrates the collection of account-specific configurations.

        Prompts the user to select the account type and account number via the
        I/O engine, performing preventative existence checks against persistence.

        Returns:
            dict[str, Any]: A dictionary containing key parameters (account_type,
                branch_code, account_num) ready to populate the `NewAccountDTO`.

        Raises:
            ControllerRegisterError: If the proposed account coordinates collide
                with an existing registered account.
        """
        acc_type_mapper = {
            AccountTypeMenu.CHECKING: NewAccountType.CHECKING_ACCOUNT,
            AccountTypeMenu.SAVINGS: NewAccountType.SAVINGS_ACCOUNT,
        }
        acc_type_menu = io_utils.get_user_input(
            self._config_mapper["account_type"], int, AccountTypeMenu
        )
        acc_type = acc_type_mapper[acc_type_menu]
        acc_num = io_utils.get_user_input(
            self._config_mapper["account_num"], str, validators.validate_account_num
        )

        acc_exists = self._service.check_data_exists(
            CheckDataDTO(
                account=AccountDataDTO(
                    branch_code=self._branch_code, account_num=acc_num
                )
            )
        )

        if acc_exists:
            self._handle_info_ui("errors", "acc_duplicated", wait=True, clean=True)
            raise ControllerRegisterError

        return {
            "account_type": acc_type,
            "branch_code": self._branch_code,
            "account_num": acc_num,
        }
