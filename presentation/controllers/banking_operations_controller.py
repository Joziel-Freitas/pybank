"""Module containing the BankingOperationsController.

Orchestrates monetary operations (Deposits, Withdrawals, and Account Statements)
by bridging terminal user input and presentation views with the BankingOperationsService.
"""

from dataclasses import asdict
from datetime import date, timedelta
from decimal import Decimal
from functools import partial
from typing import Any

from application import validators
from application.dtos import AccountDataDTO, DepositDTO, StatementDTO, WithdrawalDTO
from application.services.banking_operations_service import BankingOperationsService
from presentation.cli import config, io_utils, ui_messages, views
from presentation.controllers.base_controller import BaseController
from presentation.types import StatementPeriodType, TransactionMenuType, UserConfirmType
from shared import clock, verify
from shared.credentials import AccessToken, AuthToken
from shared.exceptions import (
    AccessDeniedError,
    AccountNotFoundError,
    ControllerOperationError,
    DeniedOperationError,
    UserAbortError,
)
from shared.projections import DepositTargetProjectionDTO, SummaryProjectionDTO


class BankingOperationsController(BaseController[BankingOperationsService]):
    """Controller responsible for executing banking transactions (Deposit, Withdrawal, Statement).

    Operates in a hybrid state model based on the provided token:
    - Public Mode (None): Executes anonymous third-party deposits.
    - Lobby Mode (AuthToken): Executes authenticated deposits, bypassing target account identification.
    - Vault Mode (AccessToken): Executes highly secure, stateful operations (withdrawals
      and statements) requiring full cryptographic clearance.
    """

    # --------------------------------------------------------------------------
    # Constructor
    # --------------------------------------------------------------------------
    def __init__(
        self,
        service: BankingOperationsService,
        transaction_type: TransactionMenuType,
        token: AuthToken | AccessToken | None = None,
    ) -> None:
        """Initializes the banking operations controller for a specific operational context.

        Delegates base application service binding to the BaseController.

        Args:
            service (BankingOperationsService): The concrete financial operations application service.
            transaction_type (TransactionMenuType): The specific monetary operation to execute.
            token (AuthToken | AccessToken | None, optional): The session token determining clearance level.
                Must be an AccessToken for vault-level operations (Withdrawal, Statement). Defaults to None.

        Raises:
            RuntimeError: If a vault-level operation is requested without an AccessToken.
        """
        super().__init__(service)

        verify.verify_instance(transaction_type, TransactionMenuType)

        if token is not None:
            verify.verify_instance(token, (AuthToken, AccessToken))

        if transaction_type is not TransactionMenuType.DEPOSIT and not isinstance(
            token, AccessToken
        ):
            raise RuntimeError(
                "AccessToken is required to perform the requested operation"
            )

        self._transaction_type = transaction_type
        self._token = token
        self._config_mapper = config.auth_config | config.transaction_config
        self._ui_message_map = ui_messages.TRANSACTION_MESSAGES

    # --------------------------------------------------------------------------
    # Dunder methods
    # --------------------------------------------------------------------------
    def __repr__(self) -> str:
        """Returns the controller's runtime state, indicating the access level and account.

        Returns:
            str: Diagnostic representation containing clearance level and active account metrics.
        """
        class_name = type(self).__name__
        access_status = "Not Authorized"

        if isinstance(self._token, AuthToken):
            access_status = "Authenticated"
        elif isinstance(self._token, AccessToken):
            access_status = "Authorized"

        account_accessed = self._token.account_num if self._token else None

        return (
            f"{class_name}("
            f"service={self._service!r}, "
            f"access_status={access_status!r}, "
            f"account_accessed={account_accessed!r}"
            f")"
        )

    # --------------------------------------------------------------------------
    # Properties
    # --------------------------------------------------------------------------
    @property
    def _active_access_token(self) -> AccessToken:
        """Guard clause for Vault operations (withdrawal, Statement).

        Guarantees that the internal session token is specifically an AccessToken.

        Returns:
            AccessToken: The verified cryptographic session token.

        Raises:
            TypeError: If the internal session token is not an AccessToken instance.
        """
        if not isinstance(self._token, AccessToken):
            raise TypeError(
                f"_token must be an AccessToken, not {type(self._token).__name__}."
            )
        return self._token

    # --------------------------------------------------------------------------
    # Public API (Orchestrators)
    # --------------------------------------------------------------------------
    def run_controller(self) -> None:
        """Routes execution to the correct private transaction handler.

        Evaluates the runtime transaction context parameter and dispatches handling
        to specialized handlers inside the boundary.
        """
        match self._transaction_type:
            case TransactionMenuType.DEPOSIT:
                self._handle_deposit()
            case TransactionMenuType.WITHDRAWAL:
                self._handle_withdrawal()
            case TransactionMenuType.STATEMENT:
                self._handle_balance_statement()
            case _:
                raise RuntimeError("Unmapped TransactionType")

    # --------------------------------------------------------------------------
    # Protected methods (Helpers ordered by high-to-low abstraction)
    # --------------------------------------------------------------------------
    def _handle_deposit(self) -> None:
        """Orchestrates the public-facing and smart deposit transaction flow.

        Coordinates target coordinate resolution, pulls pre-sanitized confirmation
        metadata records from the application service, and triggers the parameterized
        confirmation loop before committing the ledger deposit transaction.

        Raises:
            ControllerOperationError: If the destination target account coordinates
                do not resolve, if the target is blocked, or if database mutations fail.
        """
        target_account = self._get_target_account()
        branch_code, account_num = target_account

        amount = self._get_transaction_value()

        try:
            target_info = self._service.get_deposit_target(
                AccountDataDTO(branch_code=branch_code, account_num=account_num)
            )
        except AccountNotFoundError as e:
            self._handle_exception_ui("deposit_errors", e)
            raise ControllerOperationError from e

        self._confirm_deposit(target_info, amount)

        try:
            self._service.execute_deposit(
                DepositDTO(
                    branch_code=branch_code, account_num=account_num, amount=amount
                )
            )
            self._handle_info_ui("info", "deposit_ok", wait=True)
        except (AccountNotFoundError, AccessDeniedError) as e:
            self._handle_exception_ui("deposit_errors", e)
            raise ControllerOperationError from e

    def _handle_withdrawal(self) -> None:
        """Manages the complete stateful withdrawal workflow using a pessimistic lock.

        Requests financial transaction magnitudes and initiates an isolated transaction context.
        Evaluates domain authorization parameters immediately; if the transaction is flagged
        as unauthorized (e.g., exceeding total combined limits), execution is aborted to prevent
        UI drift. If credit lines are required and valid, it holds the critical database lock,
        pauses execution threads, and prompts the client for explicit overdraft terms approval.

        Raises:
            ControllerOperationError: If underlying balances or total credit limits are
                insufficient, if session validation fails, or if infrastructural errors emerge.
            UserAbortError: If credit limit approval is explicitly declined by the user.
        """
        amount = self._get_transaction_value()

        try:
            with self._service.execute_withdrawal(
                WithdrawalDTO(self._active_access_token, amount)
            ) as simulation:

                if not simulation.authorized:
                    self._handle_info_ui("withdrawal_errors", "value", wait=True)
                    raise ControllerOperationError

                if simulation.use_credit is True:
                    self._handle_info_ui(
                        "info",
                        "use_limit",
                        wait=True,
                        required=simulation.credit_required,
                    )
                    proceed = self._confirm_credit_limit()

                    if proceed == UserConfirmType.NO:
                        raise UserAbortError

            self._handle_info_ui("info", "withdrawal_ok", wait=True)
        except (AccessDeniedError, DeniedOperationError) as e:
            self._handle_exception_ui("withdrawal_errors", e)
            raise ControllerOperationError from e

    def _handle_balance_statement(self) -> None:
        """Orchestrates the display sequence for account metrics and chronological statements.

        Retrieves unified snapshots from the backend infrastructure, triggers historical
        window duration parameters selection from presentation views, computes date boundaries,
        and flushes the mathematically consistent event list down to terminal views.
        """
        account_summary = self._service.get_account_summary(
            self._active_access_token, request_financial=True
        )
        summary_dicts = self._get_summary_dicts(account_summary)
        base_summary_dict, financial_dict = summary_dicts
        views.views_balance_statement(base_summary_dict, financial_dict)

        start_date = self._get_start_date()
        statement_dto = self._service.generate_statement(
            StatementDTO(self._active_access_token, start_date)
        )

        summary_dicts = self._get_summary_dicts(statement_dto.account_info)
        base_summary_dict, financial_dict = summary_dicts

        views.views_balance_statement(
            base_summary_dict, financial_dict, statement_dto.financial_events
        )

    def _get_transaction_value(self) -> Decimal:
        """Prompts and retrieves the monetary value for a withdrawal or deposit.

        Queries the interface boundaries, enforces min value validations, and parses
        raw user input strings securely into immutable high-precision decimals.

        Returns:
            Decimal: The validated financial transaction magnitude.

        Raises:
            RuntimeError: If called from an unsupported transaction operational type.
        """
        transaction_mapper = {
            TransactionMenuType.WITHDRAWAL: "withdrawal",
            TransactionMenuType.DEPOSIT: "deposit",
        }

        if self._transaction_type not in transaction_mapper:
            raise RuntimeError(
                f"Method doesn't handle {self._transaction_type} operation"
            )

        transaction_key = transaction_mapper[self._transaction_type]

        value = io_utils.get_user_input(
            self._config_mapper[transaction_key],
            Decimal,
            validators.validate_money,
            loop_header=partial(
                self._handle_info_ui,
                context_key="info",
                info_key="min_value",
                min_atm=self._service.min_transaction_amount,
            ),
        )
        return value

    def _get_target_account(self) -> tuple[str, str]:
        """Determines the destination routing coordinates for the deposit.

        Implements dual-mode routing. Extracts account indices directly from active tokens
        if session configurations allow. Otherwise, triggers conversational manual boundary inputs.

        Returns:
            tuple[str, str]: A pair containing the validated branch_code and account_num.
        """
        if self._token:
            branch_code = self._token.branch_code
            account_num = self._token.account_num
        else:
            branch_code = io_utils.get_user_input(
                self._config_mapper["branch_code"], str, validators.validate_branch_code
            )
            account_num = io_utils.get_user_input(
                self._config_mapper["account_num"], str, validators.validate_account_num
            )

        return (branch_code, account_num)

    def _confirm_deposit(
        self, target_dto: DepositTargetProjectionDTO, amount: Decimal
    ) -> None:
        """Enforces explicit user confirmation before committing the transaction.

        Converts the target metadata into primitive mappings and injects the dynamic
        deposit diagnostic review screen as a loop header callback, waiting for explicit
        client agreement while maintaining terminal screen resilience.

        Args:
            target_dto (DepositTargetProjectionDTO): Data transfer object containing target account
                ownership details to be displayed on the confirmation screen.
            amount (Decimal): The high-precision monetary magnitude of the deposit.

        Raises:
            UserAbortError: If the operator explicitly declines terms or cancels input screens.
        """
        target_dict = asdict(target_dto)

        confirm = io_utils.get_user_input(
            self._config_mapper["confirmation"],
            int,
            UserConfirmType,
            loop_header=partial(
                views.confirm_deposit, deposit_info=target_dict, amount=amount
            ),
        )

        if confirm == UserConfirmType.NO:
            raise UserAbortError

    def _confirm_credit_limit(self) -> UserConfirmType:
        """Prompts for explicit client authorization to utilize the account's credit limit.

        Queries the interface to ask permission for credit lines activation to cover balance deficits.

        Returns:
            UserConfirmType: The structured confirmation selection state from the user.
        """
        confirm = io_utils.get_user_input(
            self._config_mapper["limit"],
            int,
            UserConfirmType,
        )
        return confirm

    def _get_start_date(self) -> date:
        """Captures the chronological filtering boundary for account activity history.

        Queries the interface for the target statement period (30, 90, or 180 days),
        validates the numerical selection, and computes the absolute historical
        cutoff date relative to the system's execution clock.

        Returns:
            date: The computed starting date threshold for ledger event retrieval.
        """
        days_mapper = {
            StatementPeriodType.THIRTY_DAYS: 30,
            StatementPeriodType.NINETY_DAYS: 90,
            StatementPeriodType.ONE_HUNDRED_EIGHTY_DAYS: 180,
        }

        user_in = io_utils.get_user_input(
            self._config_mapper["statement"], int, StatementPeriodType
        )
        days = days_mapper[user_in]
        start_date = clock.get_today() - timedelta(days=days)

        return start_date

    def _get_summary_dicts(
        self, summary_dto: SummaryProjectionDTO
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Unpackages an abstract account summary DTO into presentation-ready dictionaries.

        Extracts the foundational account attributes and isolates the inner financial
        payload, decoupling the domain DTO structural definition from the raw,
        key-value mapping structures expected by terminal view rendering engines.

        Args:
            summary_dto (SummaryProjectionDTO): The source domain data transfer object.

        Returns:
            tuple[dict[str, Any], dict[str, Any]]: A pair containing the base account
                metadata dictionary and the inner financial info dictionary, respectively.
        """
        account_summary_dict = asdict(summary_dto)
        financial_dict = account_summary_dict.pop("financial_info")

        return (account_summary_dict, financial_dict)
