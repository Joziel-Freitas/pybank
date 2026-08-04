"""
PyBank Presentation and Application Controllers Module.

This module acts as the orchestrator between the external environment (User/IO)
and the core Domain layer (Bank). It handles user interactions, input validation,
routing, and session management within a highly secure, terminal-based Kiosk environment.

Core Responsibilities:
1. I/O Orchestration: Utilizes configuration maps and dynamic callbacks to safely
    prompt, capture, and validate user inputs before they ever touch the domain.
2. Exception Translation: Acts as a protective barrier, catching Domain and
    Infrastructure exceptions and translating them into user-friendly UI messages
    via a centralized mapping system, preventing stack trace leaks.
3. State & Session Management: Securely handles authentication tokens (`AuthToken`
    and `AccessToken`), ensuring strict access control to financial operations.
4. Resiliency: Implements an 'Intercept-and-Rethrow' pattern and a Global Exception
    Handler to guarantee the terminal recovers gracefully from infrastructure
    failures (like database unavailability) without exposing secure sessions.

Controllers strictly adhere to the 'Tell, Don't Ask' principle when interacting
with the Bank aggregate, sending immutable DTOs and tokens without ever manipulating
domain state directly.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import asdict
from datetime import date, timedelta
from decimal import Decimal
from functools import partial
from typing import Any, ClassVar, TypeVar

from domain.account import Account
from domain.account_holder import AccountHolder
from domain.bank import Bank
from infra import config, io_utils, ui_messages, views
from infra.io_utils import CallbackReturn, InputType
from settings import ADMIN_EXIT_CODE
from shared import clock, exceptions, validators, verify
from shared.credentials import AccessToken, AccountCard, AuthToken
from shared.dtos import AccountSummaryDTO, DepositTargetDTO, NewAccountDTO
from shared.exceptions import (
    AccountAlreadyActiveError,
    AccountHolderNotFoundError,
    AccountNotFoundError,
    BankAccessError,
    BankAuthenticationError,
    BankPasswordError,
    BankUnavailableError,
    ControllerCredentialsError,
    ControllerError,
    ControllerOperationError,
    ControllerRegisterError,
    DomainError,
    DuplicatedAccountError,
    DuplicatedAccountHolderError,
    HomeBranchRestrictionError,
    InactiveUserError,
    InsufficientFundsError,
    InvalidBirthDateError,
    NotEmptyAccountError,
    SecurityError,
    UserAbortError,
)
from shared.types import (
    AdminCodeType,
    MainMenuType,
    OperationMenuType,
    RestrictedMenuType,
    TransactionMenuType,
    UserConfirmType,
)
from shared.validators import ValidatorCallback

UserInputT = TypeVar("UserInputT", bound=InputType)

# =====================================================================
# Global Helpers (Procedural Level)
# =====================================================================


def _assert_input(user_in: InputType, expected_type: type[UserInputT]) -> UserInputT:
    """
    Enforces strict runtime type checking for dynamically captured user inputs.

    Acts as a bridge between the untyped I/O boundaries and the statically typed
    Python ecosystem (mypy). Ensures that validation callbacks returned the expected
    data types before they are routed to domain components.

    Args:
        user_in (InputType): The raw input value returned from the UI layer.
        expected_type (type[UserInputT]): The explicitly required Python type.

    Returns:
        UserInputT: The validated input securely cast to the expected type.

    Raises:
        TypeError: If the input type does not perfectly match the expected type,
            indicating a critical flaw in the internal validation mapping.
    """
    if isinstance(user_in, expected_type):
        return user_in

    raise TypeError(
        f"Critical error in I/O logic. Expected type {expected_type}, got {type(user_in).__name__}"
    )


def _verify_message_map(message_map: dict[str, dict[str, str]]) -> None:
    """
    Verifies if the UI message catalog follows the expected nested dictionary structure.

    Performs a deep validation to ensure that the outer map keys are strings,
    the inner values are dictionaries, and all inner keys and values are strictly
    strings representing context keys and UI feedback messages.

    Args:
        message_map (dict[str, dict[str, str]]): The UI message catalog to be verified.

    Raises:
        TypeError: If the structure violates the expected nested dictionary format
            at any depth.
    """
    try:
        verify.verify_instance(message_map, dict)
        for key, inner_dict in message_map.items():
            verify.verify_instance(key, str)
            verify.verify_instance(inner_dict, dict)

            for k, v in inner_dict.items():
                verify.verify_instance(k, str)
                verify.verify_instance(v, str)
    except TypeError:
        raise TypeError("message_map must be of type dict[str, dict[str, str]]")


# =====================================================================
# Shared Prompts Mixin
# =====================================================================


class SharedPromptsMixin(ABC):
    """
    Mixin providing reusable I/O workflows for common, sensitive data entry.

    Encapsulates standard routines like double-entry password creation and
    CPF gathering, maintaining the DRY (Don't Repeat Yourself) principle across
    multiple controllers.
    """

    # --------------------------------------------------------------------------
    # Class attributes
    # --------------------------------------------------------------------------
    _auth_config: io_utils.ConfigMap
    _identification_config: io_utils.ConfigMap
    _controller_validator_cb: Callable[[str, InputType], CallbackReturn]

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
        """
        Abstract contract to trigger contextual presentation outputs.

        Args:
            context_key (str): The category inside the message catalog.
            info_key (str): The specific lookup key for the message.
            wait (bool, optional): If True, pauses execution. Defaults to False.
            clean (bool, optional): If True, clears screen. Defaults to False.
            **kwargs: Dynamic arguments to be formatted into the message template.
        """
        raise NotImplementedError

    # --------------------------------------------------------------------------
    # Protected methods
    # --------------------------------------------------------------------------
    def _prompt_new_password(self) -> str:
        """
        Handles the double-input loop for creating or updating a secure password.

        Returns:
            str: The validated, matching 6-digit password string.
        """
        while True:
            raw_pwd_1 = io_utils.get_single_input(
                "password",
                self._auth_config,
                self._controller_validator_cb,
                loop_header=partial(
                    self._handle_info_ui, context_key="info", info_key="pwd_input"
                ),
            )
            pwd_1 = _assert_input(raw_pwd_1, str)

            raw_pwd_2 = io_utils.get_single_input(
                "password",
                self._auth_config,
                self._controller_validator_cb,
                loop_header=partial(
                    self._handle_info_ui, context_key="info", info_key="pwd_confirm"
                ),
            )
            pwd_2 = _assert_input(raw_pwd_2, str)

            matched = pwd_1 == pwd_2

            if matched:
                return pwd_1

            self._handle_info_ui("info", "pwd_error", wait=True)

    def _prompt_cpf(self) -> str:
        """
        Helper method to collect and enforce string type for the CPF input.

        Returns:
            str: The CPF provided by the user.
        """
        cpf = io_utils.get_single_input(
            "cpf", config.identification_config, self._controller_validator_cb
        )
        cpf = _assert_input(cpf, str)
        return cpf


# =====================================================================
# Base Controller
# =====================================================================


class BaseController(ABC):
    """
    Abstract Base Class for all Application Controllers.

    Establishes the contract for Input/Output orchestration. Subclasses must implement
    the 'run_controller' method to define the specific flow (creation or transaction).
    It also centralizes the construction of the input validation callback used across
    all controllers and the UI message mapping mechanism.
    """

    # --------------------------------------------------------------------------
    # Class attributes
    # --------------------------------------------------------------------------
    _bank_instance: Bank
    _validation_mapper: ClassVar[dict[str, ValidatorCallback]]
    _controller_validator_cb: Callable[[str, InputType], CallbackReturn]
    _ui_message_map: dict[str, dict[str, str]]

    # --------------------------------------------------------------------------
    # Constructor
    # --------------------------------------------------------------------------
    def __init__(self, bank_instance: Bank):
        """
        Initializes the controller with the Domain's Aggregate Root and error mapping rules.

        Args:
            bank_instance (Bank): The concrete domain aggregate root instance.
        """
        verify.verify_instance(bank_instance, Bank)

        self._bank_instance = bank_instance
        self._controller_validator_cb = partial(
            io_utils.validate_entry, validation_mapper=self._validation_mapper
        )

    # --------------------------------------------------------------------------
    # Dunder methods
    # --------------------------------------------------------------------------
    def __repr__(self) -> str:
        """
        Returns a string representation of the controller's runtime identity.

        Returns:
            str: The operational class name appended with the structural bank type.
        """
        class_name = type(self).__name__
        return f"{class_name}({type(self._bank_instance).__name__})"

    # --------------------------------------------------------------------------
    # Abstract methods
    # --------------------------------------------------------------------------
    @abstractmethod
    def run_controller(self) -> None:
        """
        Executes the primary lifecycle loop and routing logic of the controller.

        Must be overridden by concrete subclasses to define how the controller
        orchestrates its respective boundary context.

        Raises:
            NotImplementedError: If the concrete subclass fails to override the method.
        """
        raise NotImplementedError()

    # --------------------------------------------------------------------------
    # Protected methods
    # --------------------------------------------------------------------------
    def _handle_exception_ui(
        self,
        context_key: str,
        error: ControllerError | DomainError | SecurityError,
        **kwargs,
    ) -> None:
        """
        Translates a caught backend exception into a standardized UI message template.

        Delegates the actual string formatting and rendering to the presentation layer (Views).
        By design, this method forces a screen clear and execution pause (clean=True, wait=True)
        to guarantee that critical error messages capture the user's full attention.

        Args:
            context_key (str): The category inside the message catalog (e.g., 'errors').
            error (ControllerError | DomainError | SecurityError): The exception raised
                by the domain/application logic.
            **kwargs: Dynamic arguments (e.g., balances, limits) to be formatted and
                injected into the UI message by the View layer.
        """
        error_key = exceptions.map_exceptions(error)
        error_msg = self._ui_message_map[context_key][error_key]

        views.system_output(error_msg, wait=True, clean=True, kwargs=kwargs)

    def _handle_info_ui(
        self,
        context_key: str,
        info_key: str,
        wait: bool = False,
        clean: bool = False,
        **kwargs,
    ) -> None:
        """
        Retrieves standard informative message templates from the UI catalog.

        Delegates the actual string formatting and rendering to the presentation layer (Views).
        Exposes UI state controls ('wait' and 'clean') to the caller, allowing specific controllers
        to orchestrate terminal transitions and pacing dynamically.

        Args:
            context_key (str): The category inside the message catalog (e.g., 'info').
            info_key (str): The specific lookup key for the message.
            wait (bool, optional): If True, pauses execution to ensure readability. Defaults to False.
            clean (bool, optional): If True, clears the terminal screen before rendering. Defaults to False.
            **kwargs: Dynamic arguments (e.g., names, transaction values) to be formatted and
                injected into the UI message by the View layer.
        """
        info_msg = self._ui_message_map[context_key][info_key]

        views.system_output(info_msg, wait=wait, clean=clean, kwargs=kwargs)


# =====================================================================
# Onboarding Controller
# =====================================================================


class OnboardingController(BaseController, SharedPromptsMixin):
    """
    Controller responsible for the registration of new clients and accounts.

    Guides the user through data collection via dynamic loops, packages the input
    into Data Transfer Objects (DTOs), and acts as the entry point for persisting
    new domain states into the Bank aggregate.
    """

    # --------------------------------------------------------------------------
    # Class attributes
    # --------------------------------------------------------------------------
    _validation_mapper: ClassVar[dict[str, ValidatorCallback]] = {
        "name": validators.boolean_validator_dec(AccountHolder.validate_name),
        "cpf": validators.boolean_validator_dec(AccountHolder.validate_cpf),
        "birth_date": validators.boolean_validator_dec(
            AccountHolder.validate_birth_date
        ),
        "account_type": validators.boolean_validator_dec(
            partial(verify.verify_interval, min_val=1, max_val=2)
        ),
        "account_num": validators.boolean_validator_dec(
            Account.validate_account_number
        ),
        "password": validators.boolean_validator_dec(Bank.validate_password),
    }

    _bank_instance: Bank
    _auth_config: io_utils.ConfigMap
    _identification_config: io_utils.ConfigMap
    _new_account_config: io_utils.ConfigMap

    # --------------------------------------------------------------------------
    # Constructor
    # --------------------------------------------------------------------------
    def __init__(
        self,
        bank_instance: Bank,
    ):
        """
        Initializes the onboarding controller and UI configs.

        Delegates the Aggregate Root (Bank) initialization to the BaseController.

        Args:
            bank_instance (Bank): The concrete domain aggregate root instance.
        """
        super().__init__(bank_instance)

        io_utils.verify_config_map(config.auth_config)
        io_utils.verify_config_map(config.identification_config)
        io_utils.verify_config_map(config.new_account_config)
        _verify_message_map(ui_messages.ONBOARDING_MESSAGES)

        self._auth_config = config.auth_config
        self._identification_config = config.identification_config
        self._new_account_config = config.new_account_config
        self._ui_message_map = ui_messages.ONBOARDING_MESSAGES

    # --------------------------------------------------------------------------
    # Public API
    # --------------------------------------------------------------------------
    def run_controller(self) -> None:
        """
        Orchestrates the client registration and account onboarding lifecycle.

        Guides the applicant through dynamic I/O gathering loops to capture identity
        data, builds required transfer payloads, enforces secure password double-entry,
        and dispatches the transaction into the core Bank aggregate root.

        Raises:
            ControllerRegisterError: If the target account number already exists or if
                the business rules reject the enrollment.
            RuntimeError: If a fatal, unexpected error occurs during input mapping
                or internal verification.
        """
        try:
            cpf = self._prompt_cpf()
            name_date_tuple = self._handle_account_holder_data(cpf)
            account_dict = self._handle_account_data()
            account_dict["holder_cpf"] = cpf
            if name_date_tuple:
                account_dict["holder_name"], account_dict["holder_birth_date"] = (
                    name_date_tuple
                )
            password = self._prompt_new_password()

            self._handle_info_ui("info", "pwd_ok")
            self._bank_instance.register_account(
                NewAccountDTO(**account_dict), password
            )
            self._handle_info_ui("info", "register_ok", wait=True)
        except UserAbortError:
            self._handle_info_ui("info", "user_cancel", wait=True)
        except DuplicatedAccountError as e:
            self._handle_exception_ui("errors", e)
            raise ControllerRegisterError from e
        except (
            BankPasswordError,
            DuplicatedAccountHolderError,
            AccountHolderNotFoundError,
        ):
            raise RuntimeError(
                "Critical error in I/O logic in password input or internal logic"
            )

    # --------------------------------------------------------------------------
    # Protected methods
    # --------------------------------------------------------------------------
    def _handle_account_holder_data(self, cpf: str) -> tuple[str, date] | None:
        """Handles the account holder data gathering workflow.

        Checks if the CPF is already registered. If so, informs the user and returns None.
        Otherwise, prompts the user for the remaining registration fields (name and birth date).

        Args:
            cpf (str): The validated CPF string.

        Returns:
            tuple[str, date] | None: A tuple containing (name, birth_date) if the holder is new,
                or None if the holder already exists in the system.
        """
        is_holder = self._bank_instance.check_account_holder_exists(cpf)

        if is_holder:
            self._handle_info_ui(
                "info", "already_account_holder", wait=True, clean=True
            )
            return None

        self._handle_info_ui("info", "new_account_holder", wait=True, clean=True)
        obj_attr = io_utils.config_loop(
            self._identification_config,
            self._controller_validator_cb,
            skip_fields=["cpf"],
        )
        name = _assert_input(obj_attr["name"], str)
        birth_date = _assert_input(obj_attr["birth_date"], date)

        return (name, birth_date)

    def _handle_account_data(self) -> dict[str, Any]:
        """Orchestrates the collection of account-specific configurations.

        Prompts the user to select the account type and desired number via the
        I/O engine, performing preventative verification against the database.

        Returns:
            dict[str, Any]: A dictionary containing key parameters (account_type,
                branch_code, account_num) ready to populate the NewAccountDTO.

        Raises:
            ControllerRegisterError: If the proposed account coordinates collide
                with an existing deployed record.
        """
        obj_attr = io_utils.config_loop(
            self._new_account_config, self._controller_validator_cb
        )

        acc_type = _assert_input(obj_attr["account_type"], int)
        acc_num = _assert_input(obj_attr["account_num"], str)

        if self._bank_instance.check_account_exists(
            self._bank_instance.bank_branch_code, acc_num
        ):
            self._handle_info_ui("errors", "acc_duplicated", wait=True, clean=True)
            raise ControllerRegisterError

        return {
            "account_type": acc_type,
            "branch_code": self._bank_instance.bank_branch_code,
            "account_num": acc_num,
        }


class TransactionController(BaseController):
    """
    Controller responsible for executing banking transactions (Deposit, Withdrawal, Statement).

    Operates in a hybrid state model based on the provided token:
    - Public Mode (None): Executes anonymous third-party deposits.
    - Lobby Mode (AuthToken): Executes authenticated deposits, bypassing account identification.
    - Vault Mode (AccessToken): Executes highly secure, stateful operations (withdrawals
      and statements) requiring full cryptographic clearance.
    """

    # --------------------------------------------------------------------------
    # Class attributes
    # --------------------------------------------------------------------------
    _validation_mapper: ClassVar[dict[str, ValidatorCallback]] = {
        "branch_code": validators.boolean_validator_dec(Account.validate_branch_code),
        "account_num": validators.boolean_validator_dec(
            Account.validate_account_number
        ),
        "deposit": validators.boolean_validator_dec(Account.validate_amount_entry),
        "withdrawal": validators.boolean_validator_dec(Account.validate_amount_entry),
        "limit": validators.boolean_validator_dec(UserConfirmType),
        "statement": validators.boolean_validator_dec(
            partial(verify.verify_interval, min_val=1, max_val=3)
        ),
        "confirmation": validators.boolean_validator_dec(UserConfirmType),
    }

    _transaction_type: TransactionMenuType
    _token: AuthToken | AccessToken | None
    _controller_config: io_utils.ConfigMap

    # --------------------------------------------------------------------------
    # Constructor
    # --------------------------------------------------------------------------
    def __init__(
        self,
        bank_instance: Bank,
        transaction_type: TransactionMenuType,
        token: AuthToken | AccessToken | None = None,
    ):
        """
        Initializes the transaction controller for a specific operational context.

        Delegates the Aggregate Root (Bank) initialization to the BaseController.

        Args:
            bank_instance (Bank): The core domain aggregate.
            transaction_type (TransactionMenuType): The specific operation to perform.
            token (AuthToken | AccessToken, optional): The session token. Determines the
                controller's clearance level. Must be an AccessToken for vault-level
                operations (Withdrawal, Statement). Defaults to None.

        Raises:
            RuntimeError: If a vault-level operation is requested without an AccessToken.
        """
        super().__init__(bank_instance)

        verify.verify_instance(transaction_type, TransactionMenuType)
        io_utils.verify_config_map(config.auth_config)
        io_utils.verify_config_map(config.transaction_config)
        _verify_message_map(ui_messages.TRANSACTION_MESSAGES)

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
        self._controller_config = config.auth_config | config.transaction_config
        self._ui_message_map = ui_messages.TRANSACTION_MESSAGES

    # --------------------------------------------------------------------------
    # Dunder methods
    # --------------------------------------------------------------------------
    def __repr__(self) -> str:
        """
        Returns the controller's runtime state, indicating the access level and account.

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
            f"bank={self._bank_instance.bank_name!r}, "
            f"access_status={access_status!r}, "
            f"account_accessed={account_accessed!r}"
            f")"
        )

    # --------------------------------------------------------------------------
    # Properties
    # --------------------------------------------------------------------------
    @property
    def _active_access_token(self) -> AccessToken:
        """
        Guard clause for Vault operations (withdrawal, Statement).

        Guarantees that the token is specifically an AccessToken.

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
        """
        Routes execution to the correct private transaction handler.

        Evaluates the runtime transaction context parameter and dispatches handling
        to specialized methods inside the boundary.
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
        """
        Orchestrates the public-facing and smart deposit transaction flow.

        Coordinates target coordinate resolution, pulls pre-sanitized confirmation
        metadata records from the aggregate domain root, and safely triggers the
        parameterized confirmation loop before committing the ledger transaction state mutation.

        Raises:
            ControllerOperationError: If the destination target account coordinates
                do not resolve, if the target is blocked, or if database mutations fail.
        """
        target_account = self._get_target_account()
        branch_code, account_num = target_account

        amount = self._get_transaction_value()

        try:
            target_info = self._bank_instance.get_deposit_target_info(
                branch_code, account_num
            )
        except AccountNotFoundError as e:
            self._handle_exception_ui("deposit_errors", e)
            raise ControllerOperationError

        self._confirm_deposit(target_info, amount)

        try:
            self._bank_instance.execute_deposit(branch_code, account_num, amount)
            self._handle_info_ui("info", "deposit_ok", wait=True)
        except (AccountNotFoundError, BankAccessError) as e:
            self._handle_exception_ui("deposit_errors", e)
            raise ControllerOperationError

    def _handle_withdrawal(self) -> None:
        """
        Manages the complete stateful withdrawal workflow using a pessimistic lock.

        Requests financial transaction magnitudes and initiates an isolated transaction context.
        Evaluates domain authorization parameters immediately; if the transaction is flagged
        as unauthorized (e.g., exceeding total combined limits), execution is aborted to prevent
        UI drift. If credit lines are required and valid, it holds the critical database lock,
        pauses execution threads, and prompts the client for explicit overdraft terms approval.

        Raises:
            ControllerOperationError: If underlying balances or total credit limits are
                insufficient (simulation.authorized is False), if the aggregate session
                validation rejects parameters, or if infrastructural errors emerge.
            UserAbortError: If credit limit approval is explicitly declined by the user.
        """
        amount = self._get_transaction_value()

        try:
            with self._bank_instance.execute_withdraw(
                self._active_access_token, amount
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
        except (BankAccessError, InsufficientFundsError) as e:
            self._handle_exception_ui("withdrawal_errors", e)
            raise ControllerOperationError

    def _handle_balance_statement(self) -> None:
        """
        Orchestrates the display sequence for account metrics and chronological statements.

        Retrieves unified snapshots from the backend infrastructure, triggers historical
        window duration parameters selection from the presentation layers, computes date delta boundaries,
        and flushes the mathematically consistent event list down to terminal views.
        """
        account_summary = self._bank_instance.get_account_summary(
            self._active_access_token, request_financial=True
        )
        summary_dicts = self._get_summary_dicts(account_summary)
        base_summary_dict, financial_dict = summary_dicts
        views.views_balance_statement(base_summary_dict, financial_dict)

        start_date = self._get_start_date()
        statement_dto = self._bank_instance.generate_statement(
            self._active_access_token, start_date
        )

        summary_dicts = self._get_summary_dicts(statement_dto.account_info)
        base_summary_dict, financial_dict = summary_dicts

        views.views_balance_statement(
            base_summary_dict, financial_dict, statement_dto.financial_events
        )

    def _get_transaction_value(self) -> Decimal:
        """
        Prompts and retrieves the monetary value for a withdrawal or deposit.

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
        value_raw = io_utils.get_single_input(
            transaction_key,
            self._controller_config,
            self._controller_validator_cb,
            loop_header=partial(
                self._handle_info_ui,
                context_key="info",
                info_key="min_value",
                min_atm=Account.MIN_ATM_TRANSACTION,
            ),
        )
        value = _assert_input(value_raw, Decimal)
        return value

    def _get_target_account(self) -> tuple[str, str]:
        """
        Determines the destination routing coordinates for the deposit.

        Implements dual-mode routing. Extracts account indices directly from active tokens
        if session configurations allow. Otherwise, triggers conversational manual boundary inputs.

        Returns:
            tuple[str, str]: A pair containing the validated branch_code and account_num.
        """
        if self._token:
            branch_code = self._token.branch_code
            account_num = self._token.account_num
        else:
            user_in_dict = io_utils.get_selected_inputs(
                ("branch_code", "account_num"),
                self._controller_config,
                self._controller_validator_cb,
            )
            branch_code = _assert_input(user_in_dict["branch_code"], str)
            account_num = _assert_input(user_in_dict["account_num"], str)

        return (branch_code, account_num)

    def _confirm_deposit(self, target_dto: DepositTargetDTO, amount: Decimal) -> None:
        """
        Enforces explicit user confirmation before committing the transaction.

        Converts the target metadata into primitive mappings and injects the dynamic
        deposit diagnostic review screen as a loop header callback, waiting for explicit
        client agreement while maintaining terminal screen resilience.

        Args:
            target_dto (DepositTargetDTO): Data transfer object containing target account
                ownership details to be displayed on the confirmation screen.
            amount (Decimal): The high-precision monetary magnitude of the deposit.

        Raises:
            UserAbortError: If the operator explicitly declines terms or cancels input screens.
        """
        target_dict = asdict(target_dto)

        user_in = io_utils.get_single_input(
            "confirmation",
            self._controller_config,
            self._controller_validator_cb,
            loop_header=partial(
                views.confirm_deposit, deposit_info=target_dict, amount=amount
            ),
        )

        user_in_int = _assert_input(user_in, int)
        confirm_operation = UserConfirmType(user_in_int)

        if confirm_operation == UserConfirmType.NO:
            raise UserAbortError

    def _confirm_credit_limit(self) -> UserConfirmType:
        """
        Prompts for explicit client authorization to utilize the account's credit limit.

        Queries the interface to ask permission for credit lines activation to cover balance deficits.

        Returns:
            UserConfirmType: The structured confirmation selection state from the user.
        """
        user_in_raw = io_utils.get_single_input(
            "limit", self._controller_config, self._controller_validator_cb
        )
        int_user_in = _assert_input(user_in_raw, int)
        return UserConfirmType(int_user_in)

    def _get_start_date(self) -> date:
        """
        Captures the chronological filtering boundary for account activity history.

        Queries the interface for the target statement period (30, 90, or 180 days),
        validates the numerical selection, and computes the absolute historical
        cutoff date relative to the system's execution clock.

        Returns:
            date: The computed starting date threshold for ledger event retrieval.
        """
        days_mapper = {1: 30, 2: 90, 3: 180}
        user_in_raw = io_utils.get_single_input(
            "statement", self._controller_config, self._controller_validator_cb
        )
        int_user_in = _assert_input(user_in_raw, int)
        days = days_mapper[int_user_in]
        start_date = clock.get_today() - timedelta(days=days)

        return start_date

    def _get_summary_dicts(
        self, summary_dto: AccountSummaryDTO
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """
        Unpackages an abstract account summary DTO into presentation-ready dictionaries.

        Extracts the foundational account attributes and isolates the inner financial
        payload, decoupling the domain DTO structural definition from the raw,
        key-value mapping structures expected by terminal view rendering engines.

        Args:
            summary_dto (AccountSummaryDTO): The source domain data transfer object.

        Returns:
            tuple[dict[str, Any], dict[str, Any]]: A pair containing the base account
                metadata dictionary and the inner financial info dictionary, respectively.
        """
        account_summary_dict = asdict(summary_dto)
        financial_dict = account_summary_dict.pop("financial_info")

        return (account_summary_dict, financial_dict)


# =====================================================================
# Bank System Controller
# =====================================================================


class BankSystemController(BaseController, SharedPromptsMixin):
    """
    The Main Application Controller (Maestro) for the PyBank terminal.

    Operates strictly as an orchestrator in the Presentation Layer. It runs in a
    continuous 'Kiosk Mode' loop, capturing user intent, delegating input collection
    to generic UI utilities, and passing validated data to the Domain Layer (Bank).

    It manages the state of the current session (Client, Hardware Cards, and Auth Tokens)
    and enforces strict routing rules, ensuring no sensitive operation is reached
    without passing through the proper authentication ('Lobby') and authorization
    ('Vault') checkpoints.
    """

    # --------------------------------------------------------------------------
    # Class attributes
    # --------------------------------------------------------------------------
    _validation_mapper: ClassVar[dict[str, ValidatorCallback]] = {
        "main_menu": validators.boolean_validator_dec(
            lambda user_in: (
                AdminCodeType(user_in)
                if user_in == ADMIN_EXIT_CODE
                else MainMenuType(user_in)
            )
        ),
        "operations_menu": validators.boolean_validator_dec(OperationMenuType),
        "restricted_menu": validators.boolean_validator_dec(RestrictedMenuType),
        "cpf": validators.boolean_validator_dec(validators.validate_cpf),
        "password": validators.boolean_validator_dec(Bank.validate_password),
        "birth_date": validators.boolean_validator_dec(
            AccountHolder.validate_birth_date
        ),
        "use_card_menu": validators.boolean_validator_dec(UserConfirmType),
        "branch_code": validators.boolean_validator_dec(Account.validate_branch_code),
        "account_num": validators.boolean_validator_dec(
            Account.validate_account_number
        ),
    }

    _auth_config: io_utils.ConfigMap
    _identification_config: io_utils.ConfigMap
    _menu_config: io_utils.ConfigMap
    _auth_token: AuthToken | None
    _access_token: AccessToken | None

    # --------------------------------------------------------------------------
    # Constructor
    # --------------------------------------------------------------------------
    def __init__(self, bank_instance: Bank):
        """
        Initializes the controller with the injected Bank domain aggregate.

        Validates and loads all UI configuration maps required for the terminal prompts,
        and sets the initial session state to fully disconnected.

        Args:
            bank_instance (Bank): The core domain aggregate root.
        """
        super().__init__(bank_instance)

        io_utils.verify_config_map(config.auth_config)
        io_utils.verify_config_map(config.identification_config)
        io_utils.verify_config_map(config.menu_config)
        _verify_message_map(ui_messages.SYSTEM_MESSAGES)

        self._auth_config = config.auth_config
        self._identification_config = config.identification_config
        self._menu_config = config.menu_config
        self._auth_token = None
        self._access_token = None
        self._ui_message_map = ui_messages.SYSTEM_MESSAGES

    # --------------------------------------------------------------------------
    # Dunder methods
    # --------------------------------------------------------------------------
    def __repr__(self) -> str:
        """
        Returns a diagnostic string representation of the controller's current state.

        Useful for debugging session leaks or hardware state issues.

        Returns:
            str: Operational state breakdown including live connection maps and tokens.
        """
        class_name = type(self).__name__

        auth_status = "Authenticated" if self._auth_token else "Not authenticated"
        access_status = "Authorized" if self._access_token else "Not authorized"

        return (
            f"{class_name}("
            f"connected_to={self._bank_instance.bank_name!r}, "
            f"authentication_status={auth_status!r}, "
            f"access_status={access_status!r}"
            f")"
        )

    # --------------------------------------------------------------------------
    # Public API (Orchestrators)
    # --------------------------------------------------------------------------
    def run_controller(self) -> None:
        """
        The Kiosk Loop.

        The absolute entry point of the presentation layer. It maintains an infinite
        loop, acting as the Global Exception Handler, ensuring the terminal always
        returns to the Welcome Screen gracefully, regardless of successful operations,
        user cancellations, or unhandled infrastructure exceptions.
        """
        while True:
            try:
                menu = self._main_menu()
                if menu == AdminCodeType.EXIT_CODE:
                    break
            except UserAbortError:
                continue

            try:
                self._main_menu_router(menu)
            except UserAbortError:
                self._handle_info_ui("info", "user_cancel", wait=True)
            except InactiveUserError:
                continue
            except (
                BankUnavailableError,
                ControllerOperationError,
                ControllerRegisterError,
            ) as e:
                self._handle_exception_ui("errors", e)

    # --------------------------------------------------------------------------
    # Protected methods (High-to-Low Abstraction Flow)
    # --------------------------------------------------------------------------
    def _main_menu_router(self, menu_type: MainMenuType) -> None:
        """
        Routes the primary terminal options down to dedicated operational units.

        Args:
            menu_type (MainMenuType): The captured root menu operational intent.

        Raises:
            RuntimeError: If an unmapped or invalid menu enumeration reaches the router.
        """
        match menu_type:
            case MainMenuType.DEPOSIT:
                self._run_transaction_controller(TransactionMenuType.DEPOSIT)
            case MainMenuType.ONBOARDING:
                controller_obj = OnboardingController(self._bank_instance)
                controller_obj.run_controller()
            case MainMenuType.OPERATIONS:
                self._lobby_hub()
            case _:
                raise RuntimeError("Critical error: Unmapped type")

    def _lobby_hub(self) -> None:
        """
        The authenticated environment loop (Lobby State Machine).

        Acts as the primary orchestrator for active client sessions. It leverages
        clean state transitions to secure the transition between the Lobby and
        the Vault, ensuring that the continuous select-and-dispatch loop remains
        active until explicitly terminated by user logout, transaction finalization,
        inactivity timeout, or critical exceptions.

        If a sensitive withdrawal completes or if a session-severing security block
        is triggered, this hub purges credentials from memory and gracefully returns
        the terminal to the main public kiosk.
        """
        account_summary = None

        if not self._auth_token:
            account_summary = self._initialize_lobby_session()

        if account_summary is None or self._auth_token is None:
            return

        while self._auth_token is not None:
            try:
                operation = self._execute_lobby_operation(account_summary)
                if operation == OperationMenuType.WITHDRAWAL or operation is None:
                    self._end_session()
            except UserAbortError:
                self._handle_info_ui("info", "user_cancel", wait=True)
                continue
            except InactiveUserError:
                self._end_session()
            except ControllerOperationError as e:
                self._handle_exception_ui("errors", e)
                continue
            except BankUnavailableError:
                self._end_session()
                raise
            except (
                BankAuthenticationError,
                ControllerCredentialsError,
                SecurityError,
            ) as e:
                self._end_session()
                self._handle_exception_ui("errors", e)

    def _vault_hub(self, operation: OperationMenuType) -> None:
        """
        The routing endpoint for Vault-level operations.

        Demands an active AccessToken to execute sensitive operations
        (Withdrawal, Statement, Change Password, Close Account). If the
        current session is restricted to basic Lobby access, it dynamically
        upgrades the session state to full Vault access before dispatching
        the requested operation.

        Args:
            operation (OperationMenuType): The specific vault-level operation to execute.

        Raises:
            RuntimeError: If an unmapped operation type is passed to the hub.
        """
        if not self._access_token:
            token = self._ensure_vault_access()
            self._transition_to_vault(token)

        match operation:
            case OperationMenuType.WITHDRAWAL:
                self._run_transaction_controller(TransactionMenuType.WITHDRAWAL)
            case OperationMenuType.STATEMENT:
                self._run_transaction_controller(TransactionMenuType.STATEMENT)
            case OperationMenuType.CHANGE_PASSWORD:
                self._update_password()
            case OperationMenuType.CLOSE_ACCOUNT:
                self._close_account()
            case _:
                raise RuntimeError("Critical error: Unmapped type")

    def _initialize_lobby_session(self) -> AccountSummaryDTO | None:
        """
        Executes the atomic handshake protocol to establish a Lobby session.

        This helper orchestrates the sequential authentication of a client:
        1. Prompts for credentials (hardware card or manual indices).
        2. Signs and registers the AuthToken inside the application state.
        3. Fetches a lightweight, non-financial projection (AccountSummaryDTO).
        4. Triggers the personalized client greeting.

        Returns:
            AccountSummaryDTO | None: The active session's summary data if the
                handshake is successful; None if authentication, credentials,
                or signature validation fails.
        """
        try:
            token = self._ensure_lobby_access()
            self._transition_to_lobby(token)
            summary = self._bank_instance.get_account_summary(token)
            self._greet_user(summary)
            return summary
        except (
            BankAuthenticationError,
            ControllerCredentialsError,
            SecurityError,
        ) as e:
            self._auth_token = None
            self._handle_exception_ui("errors", e)
            return None

    def _execute_lobby_operation(
        self, account_summary: AccountSummaryDTO
    ) -> OperationMenuType | RestrictedMenuType | None:
        """
        Orchestrates a single, isolated execution loop of an ATM option.

        Captures user navigation choices, dynamically evaluating if the target
        account status is operational or frozen (presenting the appropriate
        menu). Once an option is selected, it routes execution to the corresponding
        operational controllers or security procedures.

        Args:
            account_summary (AccountSummaryDTO): The current cached state
                of the active account session.

        Returns:
            OperationMenuType | RestrictedMenuType | None: The evaluated action
                taken by the user; None if the user explicitly aborts/cancels
                the operation selection prompt.
        """
        operation = None
        try:
            operation = self._select_operation(account_summary)
        except UserAbortError:
            self._handle_info_ui("info", "user_cancel", wait=True)

        if operation:
            self._dispatch_operation(operation)

        return operation

    def _main_menu(self) -> MainMenuType | AdminCodeType:
        """
        Displays the root entry point of the ATM.

        Includes a hidden verification for the ADMIN_EXIT_CODE to safely shut down
        the terminal application.

        Returns:
            MainMenuType | AdminCodeType: The wrapper option type stating choice indices.
        """

        user_in = io_utils.get_single_input(
            "main_menu",
            self._menu_config,
            self._controller_validator_cb,
            loop_header=views.welcome,
            use_timeout=False,
        )
        int_user_in = _assert_input(user_in, int)

        if int_user_in == ADMIN_EXIT_CODE:
            return AdminCodeType(user_in)

        return MainMenuType(user_in)

    def _ensure_lobby_access(self) -> AuthToken:
        """
        The 'Lobby Door'. Ensures the session holds a valid AuthToken.

        Handles the initial greeting workflow, asking for CPF, resolving the client,
        and prompting for credentials (card or manual). Gracefully handles 'Not Found'
        errors to prevent terminal crashes.

        Applies strict Zero Trust type checking on the domain's return value to
        guarantee the controller only operates with a valid AuthToken instance.

        Returns:
            AuthToken: A secure token granting basic lobby access.

        Raises:
            TypeError: If the domain layer returns an unexpected token type.
            ControllerCredentialsError: If the user fails to provide valid credentials
                after repeated attempts or aborts the process.
        """
        cpf = self._prompt_cpf()
        card = None

        try:
            card = self._get_card(cpf)

            if card:
                branch_code = card.branch_code
                account_num = card.account_num
            else:
                branch_code, account_num = self._get_account_identifiers()

            token = self._bank_instance.authenticate(cpf, branch_code, account_num)

            if not isinstance(token, AuthToken):
                raise TypeError(
                    f"Invalid token instance. Expect type AuthToken, get {type(token).__name__}"
                )
            return token
        except UserAbortError:
            self._handle_info_ui("info", "user_cancel", wait=True)
            raise ControllerCredentialsError
        except (
            AccountHolderNotFoundError,
            BankAuthenticationError,
        ) as e:
            self._handle_info_ui("errors", "auth_failed", wait=True, clean=True)
            raise ControllerCredentialsError from e

    def _get_card(self, cpf: str) -> AccountCard | None:
        """
        Scans for physical token cards matching credentials to bypass manual parsing.

        Args:
            cpf (str): The verified individual holder query key string.

        Returns:
            AccountCard | None: The matching structural data object if selected;
                None if hardware lists return empty or manual strategies win.
        """
        cards = self._bank_instance.get_account_holder_cards(cpf)

        if cards:
            with_card = self._use_card_menu()

            if with_card:
                card = self._select_card(cards)
                return card

        return None

    def _get_account_identifiers(self) -> tuple[str, str]:
        """
        Gathers raw routing coordinates through terminal prompt loops.

        Returns:
            tuple[str, str]: A pair mapping branch_code and account_num indexes.
        """
        user_inputs = io_utils.get_selected_inputs(
            ("branch_code", "account_num"),
            self._auth_config,
            self._controller_validator_cb,
        )
        branch_code = _assert_input(user_inputs["branch_code"], str)
        account_num = _assert_input(user_inputs["account_num"], str)

        return (branch_code, account_num)

    def _ensure_vault_access(self) -> AccessToken:
        """
        The 'Vault Door'. Upgrades Lobby access to full Vault access.

        Requests the user's password, tracking remaining attempts, and dispatches
        to the Bank domain for brute-force mitigation and cryptographic token upgrades.
        Routine authentication errors (wrong password) are caught and handled
        internally via a retry loop.

        Applies strict Zero Zero Trust type checking on the domain's return value to
        guarantee the controller only operates with a valid AccessToken instance.

        Returns:
            AccessToken: A secure token granting vault access.

        Raises:
            RuntimeError: If called without first obtaining an AuthToken, or if
                a critical error occurs in the I/O password validation logic.
            TypeError: If the domain layer returns an unexpected token type.
            ControllerCredentialsError: If access is blocked (account frozen)
                after brute-force exhaustion or isolation boundaries.
            UserAbortError: Raised naturally if the operator explicitly cancels
                the password prompt screen to return to the operational lobby.
        """
        if not self._auth_token:
            raise RuntimeError(
                "An authentication token is required to attempt to gain access to the vault"
            )

        attempts_left = self._bank_instance.get_remaining_login_attempts(
            self._auth_token
        )

        for attempt in range(attempts_left, 0, -1):
            if attempt == 1:
                self._handle_info_ui("info", "pwd_last_try", wait=True, clean=True)

            password = None
            try:
                raw_password = io_utils.get_single_input(
                    "password", self._auth_config, self._controller_validator_cb
                )
                password = _assert_input(raw_password, str)

                token = self._bank_instance.authorize_vault_access(
                    self._auth_token, password=password
                )

                if not isinstance(token, AccessToken):
                    raise TypeError(
                        f"Invalid token instance. Expect type AccessToken, get {type(token).__name__}"
                    )

                return token
            except BankAuthenticationError as e:
                if e.argument is password:
                    self._handle_info_ui("info", "pwd_wrong", wait=True)
                    continue
                raise
            except BankAccessError as e:
                self._handle_exception_ui("errors", e)
                raise ControllerCredentialsError from e
            except BankPasswordError:
                raise RuntimeError("Critical error in I/O password validation logic")

        raise ControllerCredentialsError(
            "Credentials could not be validated because of an unknown error"
        )

    def _select_operation(
        self, account_summary: AccountSummaryDTO
    ) -> OperationMenuType | RestrictedMenuType:
        """
        Evaluates the account state to present the appropriate operations menu.

        Ensures that frozen accounts are restricted to the recovery menu, preventing
        any financial transactions until the security block is resolved.

        Args:
            account_summary (AccountSummaryDTO): The current state of the account.

        Returns:
            OperationMenuType | RestrictedMenuType: The specific operation requested
                by the user.
        """
        if account_summary.is_frozen:
            return self._restrict_operations_menu(account_summary)

        return self._operations_menu()

    def _dispatch_operation(
        self, operation: OperationMenuType | RestrictedMenuType
    ) -> None:
        """
        Routes the selected menu operation to its corresponding execution flow.

        Acts as an internal dispatcher, invoking transaction controllers, account
        recovery flows, or vault hub upgrades based on the operation type.

        Args:
            operation (OperationMenuType | RestrictedMenuType): The operation to execute.

        Raises:
            RuntimeError: If the provided operation type is unmapped.
        """
        match operation:
            case RestrictedMenuType.UNFREEZE_ACCOUNT:
                self._unfreeze_account()
            case OperationMenuType.DEPOSIT:
                self._run_transaction_controller(TransactionMenuType.DEPOSIT)
            case OperationMenuType():
                self._vault_hub(operation)
            case _:
                raise RuntimeError("Critical error: Unmapped type")

    def _operations_menu(self) -> OperationMenuType:
        """
        Shows the standard UI operations menu.

        Returns:
            OperationMenuType: The evaluated valid operation menu state selection.
        """
        user_in_raw = io_utils.get_single_input(
            "operations_menu", self._menu_config, self._controller_validator_cb
        )
        user_in_int = _assert_input(user_in_raw, int)

        return OperationMenuType(user_in_int)

    def _restrict_operations_menu(
        self, acc_summary: AccountSummaryDTO
    ) -> RestrictedMenuType:
        """
        Shows the specific UI menu for frozen/blocked accounts.

        Args:
            acc_summary (AccountSummaryDTO): The current cached state summary object.

        Returns:
            RestrictedMenuType: The mapped target selection index enum.
        """
        acc_type_map = {
            "CheckingAccount": "Conta corrente",
            "SavingsAccount": "Conta poupança",
        }
        acc_type = acc_type_map[acc_summary.account_type]
        user_in_raw = io_utils.get_single_input(
            "restricted_menu",
            self._menu_config,
            self._controller_validator_cb,
            loop_header=partial(
                self._handle_info_ui,
                context_key="info",
                info_key="lobby_restrict",
                acc_type=acc_type,
            ),
        )
        user_in_int = _assert_input(user_in_raw, int)

        return RestrictedMenuType(user_in_int)

    def _update_password(self) -> None:
        """
        Handles the workflow for modifying an account's security password.

        Prompts the user for a new matching password sequence and delegates the
        cryptographic hashing and update operation to the Bank core. Forcefully
        triggers a credential reset to invalidate the active session upon success.

        Raises:
            RuntimeError: If called without elevated vault clearance maps in active memory,
                or if password strings fail structural validation thresholds.
        """
        if not self._access_token:
            raise RuntimeError("Access token required to update the password")

        new_password = self._prompt_new_password()
        try:
            self._bank_instance.update_password(self._access_token, new_password)
            self._handle_info_ui("info", "pwd_update_ok", wait=True)
            raise ControllerCredentialsError
        except BankAccessError as e:
            raise RuntimeError(
                "Critical routing failure: Vault operation reached by an unauthorized/blocked session."
            ) from e
        except BankPasswordError as e:
            raise RuntimeError("Critical error in I/O password validation logic") from e

    def _unfreeze_account(self) -> None:
        """
        Provides the specialized workflow for recovering a blocked account.

        Coordinates the collection of the account holder's registered birth date
        for identity verification. Once verified, prompts for password creation,
        resets failed authentication counters, and restores the account's operational state.

        Raises:
            RuntimeError: If execution boundaries are breached without initial token handshakes.
            ControllerOperationError: If identity factors clash or activation protocols fail.
        """
        if self._auth_token is None:
            raise RuntimeError("AuthToken required to perform the operation")

        raw_birth_date = io_utils.get_single_input(
            "birth_date", self._identification_config, self._controller_validator_cb
        )
        birth_date = _assert_input(raw_birth_date, date)
        new_password = self._prompt_new_password()

        try:
            self._bank_instance.unfreeze_account(
                self._auth_token, birth_date, new_password
            )
            self._handle_info_ui("info", "unfreeze_acc_ok", wait=True, clean=True)
            raise ControllerCredentialsError
        except (BankAuthenticationError, AccountAlreadyActiveError) as e:
            self._handle_exception_ui("errors", e)
            raise ControllerOperationError
        except (BankPasswordError, InvalidBirthDateError) as e:
            raise RuntimeError("Critical error in I/O validation logic") from e

    def _close_account(self) -> None:
        """
        Handles the complete account termination workflow.

        Enforces strict domain constraints, most notably an absolute zero-balance
        policy prior to deletion. If the account is not empty, it dynamically
        fetches the live adjusted 'balance' (disregarding credit limit inflation)
        to precisely inform the client of the exact settlement amount required
        before closure can proceed.

        Raises:
            RuntimeError: If dispatched without a verified AccessToken context payload.
            ControllerOperationError: If underlying balances or rules reject termination requests.
        """
        if self._access_token is None:
            raise RuntimeError("AccessToken is required to close an account")

        try:
            self._bank_instance.close_account(self._access_token)
            self._handle_info_ui("info", "close_acc_ok", wait=True, clean=True)
            raise ControllerCredentialsError
        except NotEmptyAccountError:
            account_summary = self._bank_instance.get_account_summary(
                self._access_token, request_financial=True
            )
            self._not_empty_notification(account_summary)
            raise ControllerOperationError
        except HomeBranchRestrictionError as e:
            self._handle_exception_ui("errors", e)
            raise ControllerOperationError
        except BankAccessError as e:
            raise RuntimeError(
                "Critical routing failure: Vault operation reached by an unauthorized/blocked session."
            ) from e

    def _not_empty_notification(self, account_summary: AccountSummaryDTO) -> None:
        """
        Evaluates and flashes specialized UI alerts for non-zero liquidation barriers.

        Args:
            account_summary (AccountSummaryDTO): The data transfer footprint of target records.
        """
        financial_info = account_summary.unwrap_financial()
        key = (
            "close_acc_positive" if financial_info.balance > 0 else "close_acc_negative"
        )
        self._handle_info_ui(
            "info", key, wait=True, clean=True, balance=financial_info.balance
        )

    def _run_transaction_controller(
        self, transaction_type: TransactionMenuType
    ) -> None:
        """
        Delegates financial transaction logic to the specialized Controller.

        Args:
            transaction_type (TransactionMenuType): The explicit target sub-context enum.
        """
        controller_obj = TransactionController(
            self._bank_instance,
            transaction_type,
            self._access_token or self._auth_token,
        )
        controller_obj.run_controller()

    def _select_card(self, cards_list: list[AccountCard]) -> AccountCard:
        """
        Displays available hardware cards for the active client and prompts for selection.

        Args:
            cards_list (list[AccountCard]): Collection array of detected profile card records.

        Returns:
            AccountCard: The selected card object matching interaction indexes.
        """

        cards_list.sort(key=lambda card: (card.branch_code, card.account_num))

        def local_validator_cb(field: str, user_in_raw: InputType) -> CallbackReturn:
            user_in = _assert_input(user_in_raw, int)
            return {"result": 0 <= user_in < len(cards_list)}

        cards_views: list[str] = [str(card) for card in cards_list]

        card_idx_raw = io_utils.get_single_input(
            "card",
            self._auth_config,
            local_validator_cb,
            loop_header=partial(views.show_cards, client_cards=cards_views),
        )
        card_idx = _assert_input(card_idx_raw, int)

        return cards_list[card_idx]

    def _use_card_menu(self) -> bool:
        """
        Prompts the user to select the authentication strategy.

        Returns:
            bool: True if the user chooses 'Use Saved Card', False for Manual Input.
        """
        use_card_mapper = {1: True, 2: False}

        use_card_raw = io_utils.get_single_input(
            "use_card_menu",
            self._menu_config,
            self._controller_validator_cb,
        )
        use_card_int = _assert_input(use_card_raw, int)
        use_card = use_card_mapper[use_card_int]

        return use_card

    def _greet_user(self, account_summary: AccountSummaryDTO) -> None:
        """
        Extracts the account holder's first name and dispatches the welcome UI.

        Args:
            account_summary (AccountSummaryDTO): The current state data context.
        """
        first_name = account_summary.holder_name.split()[0]

        self._handle_info_ui(
            "info",
            "lobby_hello",
            clean=True,
            user_name=first_name,
        )

    def _transition_to_lobby(self, token: AuthToken) -> None:
        """
        Transitions the session state to the authenticated Lobby environment.

        Args:
            token (AuthToken): The valid verified token instance object.

        Raises:
            TypeError: If the object violates raw abstract interface types.
        """
        if not isinstance(token, AuthToken):
            raise TypeError(
                f"Invalid state transition. Expected AuthToken, got {type(token).__name__}"
            )

        self._auth_token = token

    def _transition_to_vault(self, token: AccessToken) -> None:
        """
        Upgrades the session state to the secure Vault environment.

        Args:
            token (AccessToken): The high-clearance cryptographically generated token.

        Raises:
            RuntimeError: If called without active prerequisite lobby tokens in memory.
            TypeError: If instance parameters conflict with security specs.
        """
        if not self._auth_token:
            raise RuntimeError(
                "Cannot transition to Vault without an active Lobby session."
            )
        if not isinstance(token, AccessToken):
            raise TypeError(
                f"Invalid state transition. Expected AccessToken, got {type(token).__name__}"
            )

        self._access_token = token

    def _end_session(self) -> None:
        """
        Purges all sensitive data and tokens from memory, resetting the terminal.

        Acts as a strict security teardown routine.
        """
        self._auth_token = None
        self._access_token = None
