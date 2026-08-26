"""Module containing the AccountManagementController.

Orchestrates administrative account lifecycle workflows, including security credential updates,
frozen account recovery via secondary identity validation, and zero-balance account closure.
"""

from application import validators
from application.dtos import UnfreezeAccountDTO, UpdatePasswordDTO
from application.services.account_management_service import AccountManagementService
from presentation.cli import config, io_utils
from presentation.controllers.base_controller import BaseController
from presentation.controllers.mixins import SharedPromptsMixin
from presentation.types import OperationMenuType, RestrictedMenuType
from shared.credentials import AccessToken, AuthToken
from shared.exceptions import (
    AccessDeniedError,
    AccountAlreadyActiveError,
    AuthenticationError,
    ControllerCredentialsError,
    ControllerOperationError,
    DeniedOperationError,
)
from shared.projections import SummaryProjectionDTO


class AccountManagementController(
    BaseController[AccountManagementService], SharedPromptsMixin
):
    """Controller responsible for administrative account operations and lifecycle management.

    Handles account unfreezing, password updates, and account closure. Ensures that operations
    enforce required security clearance levels (AuthToken for recovery, AccessToken for sensitive mutations).
    """

    # --------------------------------------------------------------------------
    # Constructor
    # --------------------------------------------------------------------------
    def __init__(
        self,
        service: AccountManagementService,
        token: AccessToken | AuthToken,
        operation: OperationMenuType | RestrictedMenuType,
    ) -> None:
        """Initializes the AccountManagementController with target service, active token, and operation.

        Args:
            service (AccountManagementService): The application service handling account administration.
            token (AccessToken | AuthToken): Active security token required for authorization.
            operation (OperationMenuType | RestrictedMenuType): The target operation to execute.
        """
        super().__init__(service)

        self._token = token
        self._operation = operation
        self._config_mapper = config.identification_config

    # --------------------------------------------------------------------------
    # Dunder methods
    # --------------------------------------------------------------------------
    def __repr__(self) -> str:
        """Returns the controller's runtime state and target administrative operation.

        Returns:
            str: Diagnostic string capturing the underlying service, token type, and operation name.
        """
        class_name = type(self).__name__
        op_name = getattr(self._operation, "name", str(self._operation))

        return f"{class_name}(service={self._service!r}, operation={op_name!r}, token={self._token!r})"

    # --------------------------------------------------------------------------
    # Public API (Orchestrators)
    # --------------------------------------------------------------------------
    def run_controller(self) -> None:
        """Routes execution to the requested administrative workflow based on operational context.

        Raises:
            TypeError: If the requested operation type is unmapped.
        """
        match self._operation:
            case RestrictedMenuType.UNFREEZE_ACCOUNT:
                self._unfreeze_account()
            case OperationMenuType.CHANGE_PASSWORD:
                self._update_password()
            case OperationMenuType.CLOSE_ACCOUNT:
                self._close_account()
            case _:
                raise TypeError("Unmapped operation type")

    # --------------------------------------------------------------------------
    # Protected methods (Administrative Workflows)
    # --------------------------------------------------------------------------
    def _unfreeze_account(self) -> None:
        """Provides the specialized workflow for recovering a blocked account.

        Coordinates the collection of the account holder's registered birth date
        for identity verification. Once verified, prompts for password creation,
        resets failed authentication counters, and restores the account's operational state.

        Raises:
            TypeError: If the operational token is not an AuthToken instance.
            ControllerCredentialsError: Triggers an immediate session reset upon successful recovery.
            ControllerOperationError: If identity verification fails or the account is already active.
        """
        if not isinstance(self._token, AuthToken):
            raise TypeError("AuthToken is required to unfreeze an account")

        birth_date = io_utils.get_user_input(
            self._config_mapper["birth_date"],
            io_utils.parse_input_date,
            validators.validate_birth_date,
        )
        new_password = self._prompt_new_password()

        try:
            self._service.unfreeze_account(
                UnfreezeAccountDTO(
                    auth_token=self._token,
                    birth_date=birth_date,
                    new_password=new_password,
                )
            )
            self._handle_info_ui("info", "unfreeze_acc_ok", wait=True, clean=True)
            raise ControllerCredentialsError
        except (AuthenticationError, AccountAlreadyActiveError) as e:
            self._handle_exception_ui("errors", e)
            raise ControllerOperationError

    def _update_password(self) -> None:
        """Handles the workflow for modifying an account's security password.

        Prompts the user for a new matching password sequence and delegates the
        cryptographic hashing and update operation to the Application service.
        Forcefully triggers a session reset to invalidate active credentials upon success.

        Raises:
            TypeError: If the operational token is not an AccessToken instance.
            RuntimeError: If the account is frozen, indicating an invalid operational state.
            ControllerCredentialsError: Triggers session reset after password mutation.
        """
        if not isinstance(self._token, AccessToken):
            raise TypeError("AccessToken is required to update password")

        new_password = self._prompt_new_password()
        try:
            self._service.update_password(UpdatePasswordDTO(self._token, new_password))
            self._handle_info_ui("info", "pwd_update_ok", wait=True)
            raise ControllerCredentialsError
        except AccessDeniedError as e:
            raise RuntimeError("Critical routing failure: Account is frozen") from e

    def _close_account(self) -> None:
        """Handles the complete account termination workflow.

        Enforces strict domain constraints, most notably an absolute zero-balance
        policy prior to deletion. If the account is not empty, it dynamically
        fetches the live adjusted 'balance' (disregarding credit limit inflation)
        to precisely inform the client of the exact settlement amount required
        before closure can proceed.

        Raises:
            TypeError: If the operational token is not an AccessToken instance.
            RuntimeError: If the account is frozen, blocking termination.
            ControllerCredentialsError: Triggers session reset upon successful account deletion.
            ControllerOperationError: If underlying non-zero balances prevent closure.
        """
        if not isinstance(self._token, AccessToken):
            raise TypeError("AccessToken is required to close an account")

        try:
            self._service.close_account(self._token)
            self._handle_info_ui("info", "close_acc_ok", wait=True, clean=True)
            raise ControllerCredentialsError
        except DeniedOperationError:
            account_summary = self._service.get_account_summary(
                self._token, request_financial=True
            )
            self._not_empty_notification(account_summary)
            raise ControllerOperationError
        except AccessDeniedError as e:
            raise RuntimeError("Critical routing failure: Account is frozen.") from e

    def _not_empty_notification(self, account_summary: SummaryProjectionDTO) -> None:
        """Evaluates and flashes specialized UI alerts for non-zero liquidation barriers.

        Args:
            account_summary (SummaryProjectionDTO): Financial summary projection of target account.
        """
        financial_info = account_summary.unwrap_financial()
        key = (
            "close_acc_positive" if financial_info.balance > 0 else "close_acc_negative"
        )
        self._handle_info_ui(
            "info", key, wait=True, clean=True, balance=financial_info.balance
        )
