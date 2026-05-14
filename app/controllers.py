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
from dataclasses import asdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from functools import partial
from typing import Any, Callable, ClassVar, Generic, TypeVar, cast

from domain.account import Account
from domain.bank import Bank
from domain.person import AccountHolder, Person
from infra import config, io_utils, ui_messages, verify, views
from infra.io_utils import CallbackReturn, InputType
from settings import ADMIN_EXIT_CODE
from shared import exceptions, validators
from shared.credentials import AccessToken, AccountCard, AuthToken
from shared.dtos import AccountSummaryDTO, NewAccountDTO, NewAccountHolderDTO
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
    InvalidBirthDateError,
    InvalidDepositError,
    InvalidWithdrawError,
    NotEmptyAccountError,
    OverdraftRequiredError,
    SecurityError,
    UserAbortError,
)
from shared.types import (
    AdminCodeType,
    MainMenuType,
    OperationMenuType,
    RestrictedMenuType,
    TransactionMenuType,
)
from shared.validators import ValidatorCallback

CreatableT = TypeVar("CreatableT", bound=Person | Account)
ClientDataT = TypeVar("ClientDataT", bound=AccountHolder | str)
T = TypeVar("T", bound=Bank | Person | Account)
R = TypeVar("R")

UserInputT = TypeVar("UserInputT", bound=InputType)


def _verify_message_map(message_map: dict[str, dict[str, str]]) -> None:
    """
    Verifies if the UI message catalog follows the expected nested dictionary structure.

    Performs a deep validation to ensure that the outer map keys are strings,
    the inner values are dictionaries, and all inner keys and values are strictly
    strings representing context keys and UI feedback messages.

    Args:
        message_map (dict[str, dict[str, str]]):
            The UI message catalog to be verified.

    Raises:
        TypeError:
            If the structure violates the expected nested dictionary format at any depth.
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


class SharedPromptsMixin(ABC):
    """
    Mixin providing reusable I/O workflows for common, sensitive data entry.

    Encapsulates standard routines like double-entry password creation and
    CPF gathering, maintaining the DRY (Don't Repeat Yourself) principle across
    multiple controllers.
    """

    _auth_config: io_utils.ConfigMap
    _identification_config: io_utils.ConfigMap
    _controller_validator_cb: Callable[[str, InputType], CallbackReturn]

    @abstractmethod
    def _handle_info_ui(self, context_key: str, info_key: str, **kwargs) -> None:
        raise NotImplementedError

    def _prompt_new_password(self) -> str:
        """
        Handles the double-input loop for creating or updating a secure password.

        Returns:
            str: The validated, matching 6-digit password string.
        """
        while True:
            self._handle_info_ui("info", "pwd_input")
            raw_pwd_1 = io_utils.get_single_input(
                "password", self._auth_config, self._controller_validator_cb
            )
            pwd_1 = _assert_input(raw_pwd_1, str)

            self._handle_info_ui("info", "pwd_confirm")
            raw_pwd_2 = io_utils.get_single_input(
                "password", self._auth_config, self._controller_validator_cb
            )
            pwd_2 = _assert_input(raw_pwd_2, str)

            matched = pwd_1 == pwd_2

            if matched:
                return pwd_1

            self._handle_info_ui("info", "pwd_error")

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


class BaseController(ABC, Generic[T, R]):
    """
    Abstract Base Class for all Application Controllers.

    Establishes the contract for Input/Output orchestration. Subclasses must implement
    the 'run_controller' method to define the specific flow (creation or transaction).
    It also centralizes the construction of the input validation callback used across
    all controllers and the UI message mapping mechanism.

    Attributes:
        _model_class (Type[T]): The domain class managed by this controller.
        _validation_mapper (ClassVar[dict]): Static dictionary mapping field names
            to domain-level validation functions.
        _controller_validator_cb (Callable): Pre-loaded callback for I/O validation.
        _ui_message_map (dict): The specific message catalog for the controller.
    """

    _model_class: type[T]
    _validation_mapper: ClassVar[dict[str, ValidatorCallback]]
    _controller_validator_cb: Callable[[str, InputType], CallbackReturn]
    _ui_message_map: dict[str, dict[str, str]]

    def __init__(self, model_class: type[T]):
        """
        Initializes the controller with model type and error mapping rules.

        Args:
            model_class (Type[T]): The concrete domain class type.

        Raises:
            TypeError: If model_class is not a valid Domain Entity subclass.
        """
        verify.verify_instance(model_class, type)

        if not issubclass(model_class, (Bank, Person, Account)):
            raise TypeError(
                f"model_class {model_class} must be a subclass of Bank, Person, or Account."
            )

        self._model_class = model_class

        self._controller_validator_cb = partial(
            io_utils.validate_entry, validation_mapper=self._validation_mapper
        )

    def __repr__(self) -> str:
        """Returns a string representation of the controller's runtime identity."""
        class_name = type(self).__name__
        return f"{class_name}({self._model_class.__name__})"

    @abstractmethod
    def run_controller(self) -> R:

        raise NotImplementedError()

    def _handle_exception_ui(
        self,
        context_key: str,
        error: ControllerError | DomainError | SecurityError,
        **kwargs,
    ) -> None:
        """
        Translates a caught backend exception into a standardized UI message.

        Args:
            context_key (str): The category inside the message catalog (e.g., 'errors').
            error (Exception): The exception raised by the domain/application logic.
            **kwargs: Dynamic arguments to format into the resulting message.
        """
        error_key = exceptions.map_exceptions(error)
        error_msg = self._ui_message_map[context_key][error_key]

        if kwargs:
            error_msg = error_msg.format(**kwargs)

        views.controller_output(error_msg)

    def _handle_info_ui(self, context_key: str, info_key: str, **kwargs) -> None:
        """
        Retrieves and outputs standard informative messages from the UI catalog.

        Args:
            context_key (str): The category inside the message catalog (e.g., 'info').
            info_key (str): The specific lookup key for the message.
            **kwargs: Dynamic arguments to format into the resulting message.
        """
        info_msg = self._ui_message_map[context_key][info_key]

        if kwargs:
            info_msg = info_msg.format(**kwargs)

        views.controller_output(info_msg)


class OnboardingController(BaseController[Bank, None], SharedPromptsMixin):
    """
    Controller responsible for the registration of new clients and accounts.

    Guides the user through data collection via dynamic loops, packages the input
    into Data Transfer Objects (DTOs), and acts as the entry point for persisting
    new domain states into the Bank aggregate.
    """

    _validation_mapper = {
        "name": validators.boolean_validator_dec(Person.validate_name),
        "cpf": validators.boolean_validator_dec(Person.validate_cpf),
        "birth_date": validators.boolean_validator_dec(Person.validate_birth_date),
        "acc_type": validators.boolean_validator_dec(
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

    def __init__(
        self,
        bank_instance: Bank,
    ):
        """
        Initializes the onboarding controller, injecting the Bank aggregate and UI configs.
        """
        super().__init__(Bank)

        verify.verify_instance(bank_instance, Bank)
        io_utils.verify_config_map(config.auth_config)
        io_utils.verify_config_map(config.identification_config)
        io_utils.verify_config_map(config.new_account_config)
        _verify_message_map(ui_messages.ONBOARDING_MESSAGES)

        self._bank_instance = bank_instance
        self._auth_config = config.auth_config
        self._identification_config = config.identification_config
        self._new_account_config = config.new_account_config
        self._ui_message_map = ui_messages.ONBOARDING_MESSAGES

    def _handle_account_holder_data(self, cpf: str) -> NewAccountHolderDTO | str:
        """
        Handles the account holder data gathering workflow.

        Checks if the CPF is already registered. If so, returns the CPF.
        Otherwise, prompts the user for the remaining registration fields.

        Args:
            cpf (str): The validated CPF string.

        Returns:
            NewAccountHolderDTO | str: The DTO containing the new account holder's data,
                or the CPF string if the account holder already exists.
        """
        is_holder = self._bank_instance.check_account_holder_exists(cpf)

        if is_holder:
            self._handle_info_ui("info", "already_account_holder")
            return cpf

        self._handle_info_ui("info", "new_account_holder")
        obj_attr = io_utils.config_loop(
            self._identification_config,
            self._controller_validator_cb,
            skip_fields=["cpf"],
        )
        obj_attr["cpf"] = cpf
        obj_attr = cast(dict[str, Any], obj_attr)
        return NewAccountHolderDTO(**obj_attr)

    def _handle_account_data(self) -> NewAccountDTO:
        """
        Orchestrates the collection of account-specific configurations (type and number).

        Returns:
            NewAccountDTO: The immutable payload for the new account parameters.
        """
        obj_attr = io_utils.config_loop(
            self._new_account_config, self._controller_validator_cb
        )
        obj_attr["branch_code"] = self._bank_instance.bank_branch_code
        obj_attr = cast(dict[str, Any], obj_attr)
        return NewAccountDTO(**obj_attr)

    def run_controller(self) -> None:
        """
        Executes the main onboarding workflow.

        Orchestrates data gathering for the account holder and the account,
        prompts for a secure password, and dispatches the registration to
        the Bank aggregate. Handles domain exceptions by rendering UI messages
        and allows critical infrastructure errors (BankUnavailableError) to bubble up.
        """
        try:
            cpf = self._prompt_cpf()
            holder_dto_or_cpf = self._handle_account_holder_data(cpf)
            account_dto = self._handle_account_data()
            password = self._prompt_new_password()

            self._handle_info_ui("info", "pwd_ok")
            self._bank_instance.register_account(
                account_dto=account_dto,
                holder_dto_or_cpf=holder_dto_or_cpf,
                password=password,
            )
            self._handle_info_ui("info", "register_ok")
        except UserAbortError:
            self._handle_info_ui("info", "user_cancel")
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


class TransactionController(BaseController[Account, None]):
    """
    Controller responsible for executing banking transactions (Deposit, Withdraw, Statement).

    Operates in a hybrid manner: it can perform public, stateless operations
    (like third-party deposits) or highly secure, stateful operations (like
    withdrawals and statements) utilizing an injected AccessToken representing
    the active vault session.
    """

    _validation_mapper = {
        "branch_code": validators.boolean_validator_dec(Account.validate_branch_code),
        "account_num": validators.boolean_validator_dec(
            Account.validate_account_number
        ),
        "deposit": validators.boolean_validator_dec(Account.validate_account_deposit),
        "withdraw": validators.boolean_validator_dec(
            partial(
                verify.verify_interval,
                min_val=Account.MIN_ATM_TRANSACTION,
                max_val=None,
            )
        ),
        "limit": validators.boolean_validator_dec(
            partial(verify.verify_interval, min_val=1, max_val=2)
        ),
        "statement": validators.boolean_validator_dec(
            partial(verify.verify_interval, min_val=1, max_val=3)
        ),
    }

    _bank_instance: Bank
    _transaction_type: TransactionMenuType
    _access_token: AccessToken | None
    _controller_config: io_utils.ConfigMap

    def __init__(
        self,
        bank_instance: Bank,
        transaction_type: TransactionMenuType,
        access_token: AccessToken | None = None,
    ):
        """
        Initializes the transaction controller for a specific operational context.

        Args:
            bank_instance (Bank): The core domain aggregate.
            transaction_type (TransactionMenuType): The specific operation to perform.
            access_token (AccessToken, optional): The secure vault token. Must be provided
                for all operations except public deposits.
        """

        super().__init__(Account)

        verify.verify_instance(bank_instance, Bank)
        verify.verify_instance(transaction_type, TransactionMenuType)
        io_utils.verify_config_map(config.auth_config)
        io_utils.verify_config_map(config.transaction_config)
        _verify_message_map(ui_messages.TRANSACTION_MESSAGES)

        if access_token is not None:
            verify.verify_instance(access_token, AccessToken)

        if transaction_type is not TransactionMenuType.DEPOSIT and access_token is None:
            raise RuntimeError(
                "AccessToken is required to perform the requested operation"
            )

        self._bank_instance = bank_instance
        self._transaction_type = transaction_type
        self._access_token = access_token
        self._controller_config = config.auth_config | config.transaction_config
        self._ui_message_map = ui_messages.TRANSACTION_MESSAGES

    def __repr__(self) -> str:
        """Returns the controller's runtime state, indicating the access level."""
        class_name = type(self).__name__
        access_status = "Authorized" if self._access_token else "Not authorized"
        account_accessed = (
            self._access_token.account_num if self._access_token else None
        )

        return (
            f"{class_name}("
            f"bank={self._bank_instance.bank_name!r},"
            f"access_status={access_status!r})"
            f"account_accessed={account_accessed!r},"
        )

    @property
    def _active_access_token(self) -> AccessToken:
        """
        Safe getter for the vault access token. Acts as a guard clause.

        Returns:
            AccessToken: The active vault token.

        Raises:
            RuntimeError: If called during an unauthenticated flow.
        """
        if self._access_token is None:
            raise RuntimeError("Getter called without an AccessToken")

        return self._access_token

    def _get_transaction_value(self) -> Decimal:
        """
        Prompts and retrieves the monetary value for a withdrawal or deposit.

        Returns:
            Decimal: The exact transaction amount requested by the user.
        """
        transaction_mapper = {
            TransactionMenuType.WITHDRAW: "withdraw",
            TransactionMenuType.DEPOSIT: "deposit",
        }

        if self._transaction_type not in transaction_mapper:
            raise RuntimeError(
                f"Method doesn't handle {self._transaction_type} operation"
            )
        self._handle_info_ui("info", "min_value", min_atm=Account.MIN_ATM_TRANSACTION)
        transaction_key = transaction_mapper[self._transaction_type]
        value_raw = io_utils.get_single_input(
            transaction_key, self._controller_config, self._controller_validator_cb
        )
        value = _assert_input(value_raw, Decimal)
        return value

    def _confirm_overdraft(self) -> bool:
        """
        Prompts for explicit client authorization to utilize the account's credit limit.

        Returns:
            bool: True if authorized, False if denied.
        """
        use_overdraft_mapper = {1: True, 2: False}
        user_in_raw = io_utils.get_single_input(
            "limit", self._controller_config, self._controller_validator_cb
        )
        int_user_in = _assert_input(user_in_raw, int)
        return use_overdraft_mapper[int_user_in]

    def _handle_withdraw(self) -> None:
        """
        Manages the complete stateful withdrawal workflow.

        Requests the amount, dispatches to the Bank, handles dynamic fallback
        prompts for overdraft limits, and traps business constraint errors.
        """
        amount = self._get_transaction_value()
        use_overdraft = False

        for _ in range(2):
            try:
                self._bank_instance.execute_withdraw(
                    self._active_access_token, amount, use_overdraft=use_overdraft
                )
                self._handle_info_ui("info", "withdraw_ok")
                break
            except OverdraftRequiredError as e:
                self._handle_exception_ui("withdraw_errors", e)
                proceed = self._confirm_overdraft()

                if not proceed:
                    raise UserAbortError

                use_overdraft = True
            except (BankAccessError, InvalidWithdrawError) as e:
                self._handle_exception_ui("withdraw_errors", e)
                raise ControllerOperationError

    def _handle_public_deposit(self) -> None:
        """
        Manages the stateless, public-facing deposit workflow.

        Requires target routing info (branch and account) instead of a token,
        translating UI entries into a dispatch request to the Bank.
        """
        user_in_dict = io_utils.get_selected_inputs(
            ("branch_code", "account_num"),
            self._controller_config,
            self._controller_validator_cb,
        )
        branch_code = _assert_input(user_in_dict["branch_code"], str)
        account_num = _assert_input(user_in_dict["account_num"], str)
        amount = self._get_transaction_value()

        try:
            self._bank_instance.execute_deposit(branch_code, account_num, amount)
            self._handle_info_ui("info", "deposit_ok")
        except (AccountNotFoundError, BankAccessError) as e:
            self._handle_exception_ui("deposit_errors", e)
            raise ControllerOperationError
        except InvalidDepositError:
            raise RuntimeError("Critical error in I/O deposit value validation logic")

    def _handle_balance_statement(self) -> None:
        account_info_dto = self._bank_instance.get_account_info(
            self._active_access_token
        )
        account_info_dict = asdict(account_info_dto)

        views.show_balance_statement(account_info_dict)

        days_mapper = {1: 30, 2: 90, 3: 180}
        user_in_raw = io_utils.get_single_input(
            "statement", self._controller_config, self._controller_validator_cb
        )
        int_user_in = _assert_input(user_in_raw, int)
        days = days_mapper[int_user_in]
        start_date = datetime.now() - timedelta(days=days)

        statement_dto = self._bank_instance.generate_statement(
            self._active_access_token, start_date
        )

        account_info_dto = statement_dto.account_info
        account_info_dict = asdict(account_info_dto)
        transactions = statement_dto.transactions

        views.show_balance_statement(account_info_dict, transactions)

    def run_controller(self) -> None:
        """
        Routes execution to the correct private transaction handler.
        """
        match self._transaction_type:
            case TransactionMenuType.DEPOSIT:
                self._handle_public_deposit()
            case TransactionMenuType.WITHDRAW:
                self._handle_withdraw()
            case TransactionMenuType.STATEMENT:
                self._handle_balance_statement()
            case _:
                raise RuntimeError("Unmapped TransactionType")


class BankSystemController(BaseController[Bank, None], SharedPromptsMixin):
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

    _validation_mapper = {
        "main_menu": validators.boolean_validator_dec(
            lambda user_in: (
                AdminCodeType(user_in)
                if user_in == ADMIN_EXIT_CODE
                else MainMenuType(user_in)
            )
        ),
        "operations_menu": validators.boolean_validator_dec(OperationMenuType),
        "restrict_menu": validators.boolean_validator_dec(RestrictedMenuType),
        "cpf": validators.boolean_validator_dec(validators.validate_cpf),
        "password": validators.boolean_validator_dec(Bank.validate_password),
        "birth_date": validators.boolean_validator_dec(Person.validate_birth_date),
        "use_card_menu": validators.boolean_validator_dec(
            partial(verify.verify_interval, min_val=1, max_val=2)
        ),
        "branch_code": validators.boolean_validator_dec(Account.validate_branch_code),
        "account_num": validators.boolean_validator_dec(
            Account.validate_account_number
        ),
    }

    _bank_instance: Bank
    _auth_config: io_utils.ConfigMap
    _identification_config: io_utils.ConfigMap
    _menu_config: io_utils.ConfigMap
    _auth_token: AuthToken | None
    _access_token: AccessToken | None

    def __init__(self, bank_instance: Bank):
        """
        Initializes the controller with the injected Bank domain aggregate.

        Validates and loads all UI configuration maps required for the terminal prompts,
        and sets the initial session state to fully disconnected.

        Args:
            bank_instance (Bank): The core domain aggregate root.
        """
        super().__init__(Bank)

        verify.verify_instance(bank_instance, Bank)
        io_utils.verify_config_map(config.auth_config)
        io_utils.verify_config_map(config.identification_config)
        io_utils.verify_config_map(config.menu_config)
        _verify_message_map(ui_messages.SYSTEM_MESSAGES)

        self._bank_instance = bank_instance
        self._auth_config = config.auth_config
        self._identification_config = config.identification_config
        self._menu_config = config.menu_config
        self._auth_token = None
        self._access_token = None
        self._ui_message_map = ui_messages.SYSTEM_MESSAGES

    def __repr__(self) -> str:
        """
        Returns a diagnostic string representation of the controller's current state.
        Useful for debugging session leaks or hardware state issues.
        """
        class_name = type(self).__name__

        auth_status = "Authenticated" if self._auth_token else "Not authenticated"
        access_status = "Authorized" if self._access_token else "Not authorized"

        return (
            f"{class_name}("
            f"connected_to={self._bank_instance.bank_name!r}"
            f"authentication_status={auth_status!r}"
            f"access_status={access_status!r}"
        )

    def _select_card(self, cards_list: list[AccountCard]) -> AccountCard:
        """
        Displays available hardware cards for the active client and prompts for selection.

        Returns:
            AccountCard: The selected card object.
        """

        def local_validator_cb(field: str, user_in_raw: InputType) -> CallbackReturn:
            user_in = _assert_input(user_in_raw, int)
            return {"result": 0 <= user_in < len(cards_list)}

        cards_views: list[str] = [str(card) for card in cards_list]
        views.show_cards(cards_views)

        card_idx_raw = io_utils.get_single_input(
            "card", self._auth_config, local_validator_cb
        )
        card_idx = _assert_input(card_idx_raw, int)

        return cards_list[card_idx]

    def _use_card_menu(self) -> bool:
        """
        Prompts the user to select the authentication strategy.

        Returns:
            bool: True if the user chooses 'Use Saved Card'.
                  False if the user chooses 'Manual Input'.
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

    def _ensure_lobby_access(self) -> AuthToken:
        """
        The 'Lobby Door'. Ensures the session holds a valid AuthToken.

        Handles the initial greeting workflow, asking for CPF, resolving the client,
        and prompting for credentials (card or manual). Gracefully handles 'Not Found'
        errors to prevent terminal crashes.

        Raises:
            ControllerCredentialsError: If the user fails to provide valid credentials
                after repeated attempts or aborts the process.
        """
        cpf = self._prompt_cpf()
        cards = None
        with_card = None
        card = None

        try:
            cards = self._bank_instance.get_account_holder_cards(cpf)

            if cards:
                with_card = self._use_card_menu()

            if with_card:
                card = self._select_card(cards)
                return self._bank_instance.authenticate(
                    cpf, card.branch_code, card.account_num
                )

            user_inputs = io_utils.get_selected_inputs(
                ("branch_code", "account_num"),
                self._auth_config,
                self._controller_validator_cb,
            )
            branch_code = _assert_input(user_inputs["branch_code"], str)
            account_num = _assert_input(user_inputs["account_num"], str)

            return self._bank_instance.authenticate(cpf, branch_code, account_num)
        except UserAbortError:
            self._handle_info_ui("info", "user_cancel")
            raise ControllerCredentialsError
        except (
            AccountHolderNotFoundError,
            BankAuthenticationError,
        ) as e:
            self._handle_info_ui("error", "auth_failed")
            raise ControllerCredentialsError from e

    def _ensure_vault_access(self) -> AccessToken:
        """
        The 'Vault Door'. Upgrades Lobby access to full Vault access.

        Requests the user's password, tracking remaining attempts, and dispatches
        to the Bank domain for brute-force mitigation and cryptographic token upgrades.

        Returns:
            AccessToken: A secure token granting vault access.

        Raises:
            RuntimeError: If called without first obtaining an AuthToken.
            ControllerCredentialsError: If authentication fails, the account freezes,
                or the user aborts.
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
                self._handle_info_ui("info", "pwd_last_try")

            try:
                raw_password = io_utils.get_single_input(
                    "password", self._auth_config, self._controller_validator_cb
                )
                password = _assert_input(raw_password, str)
                return self._bank_instance.authorize_vault_access(
                    self._auth_token, password=password
                )
            except BankAuthenticationError:
                self._handle_info_ui("info", "pwd_wrong")
            except BankAccessError as e:
                self._handle_exception_ui("errors", e)
                raise ControllerCredentialsError from e
            except UserAbortError:
                self._handle_info_ui("info", "user_cancel")
                raise ControllerCredentialsError
            except BankPasswordError:
                raise RuntimeError("Critical error in I/O password validation logic")

        raise ControllerCredentialsError(
            "Credentials could not be validated because of an unknown error"
        )

    def _end_session(self) -> None:
        """
        Purges all sensitive data and tokens from memory, resetting the terminal
        to an unauthenticated state. Acts as a strict security teardown.
        """
        self._auth_token = None
        self._access_token = None

    def _update_password(self) -> None:
        """
        Handles the workflow for modifying an account's security password.
        Ensures the active session token is destroyed upon success.
        """
        if not self._access_token:
            raise RuntimeError("Access token required to update the password")

        new_password = self._prompt_new_password()
        try:
            self._bank_instance.update_password(self._access_token, new_password)
            self._access_token = None
            self._handle_info_ui("info", "pwd_update_ok")
        except BankAccessError as e:
            self._handle_exception_ui("errors", e)
            raise ControllerOperationError from e
        except BankPasswordError as e:
            raise RuntimeError("Critical error in I/O password validation logic") from e

    def _unfreeze_account(self) -> None:
        """
        Provides the specialized workflow for recovering a blocked account
        using identity verification (birth date confirmation).
        """
        if self._auth_token is None:
            raise RuntimeError("AuthToken required to perform the operation")

        raw_birth_date = io_utils.get_single_input(
            "birth_date", self._identification_config, self._controller_validator_cb
        )
        new_password = self._prompt_new_password()

        birth_date = _assert_input(raw_birth_date, date)

        try:
            birth_date = Person.validate_birth_date(birth_date)
            self._bank_instance.unfreeze_account(
                self._auth_token, birth_date, new_password
            )
            self._handle_info_ui("info", "unfreeze_acc_ok")
        except (BankAuthenticationError, AccountAlreadyActiveError) as e:
            self._handle_exception_ui("errors", e)
            raise ControllerOperationError
        except (BankPasswordError, InvalidBirthDateError) as e:
            raise RuntimeError("Critical error in I/O validation logic") from e

    def _close_account(self) -> None:
        """
        Handles the complete account termination workflow, applying constraints
        such as enforcing a strict zero-balance policy before deletion.
        """
        if self._access_token is None:
            raise RuntimeError("AccessToken is required to close an account")

        try:
            self._bank_instance.close_account(self._access_token)
            self._handle_info_ui("info", "close_acc_ok")
            raise ControllerCredentialsError
        except NotEmptyAccountError:
            account_info_dto = self._bank_instance.get_account_info(self._access_token)
            key = (
                "close_acc_positive"
                if account_info_dto.balance > 0
                else "close_acc_negative"
            )
            self._handle_info_ui("info", key, balance=account_info_dto.balance)
            raise ControllerOperationError
        except (HomeBranchRestrictionError, BankAccessError) as e:
            self._handle_exception_ui("errors", e)
            raise ControllerOperationError

    def _run_transaction_controller(
        self, transaction_type: TransactionMenuType
    ) -> None:
        """Delegates financial transaction logic to the specialized Controller."""
        controller_obj = TransactionController(
            self._bank_instance,
            transaction_type,
            self._access_token,
        )
        controller_obj.run_controller()

    def _restrict_operations_menu(
        self, acc_summary: AccountSummaryDTO
    ) -> RestrictedMenuType:
        """Shows the specific UI menu for frozen/blocked accounts."""
        acc_type_map = {
            "CheckingAccount": "Conta corrente",
            "SavingsAccount": "Conta poupança",
        }
        self._handle_info_ui(
            "info", "lobby_restrict", acc_type=acc_type_map[acc_summary.account_type]
        )
        user_in_raw = io_utils.get_single_input(
            "restrict_menu", self._menu_config, self._controller_validator_cb
        )
        user_in_int = _assert_input(user_in_raw, int)

        return RestrictedMenuType(user_in_int)

    def _operations_menu(self) -> OperationMenuType:
        """Shows the standard UI operations menu."""
        user_in_raw = io_utils.get_single_input(
            "operations", self._menu_config, self._controller_validator_cb
        )
        user_in_int = _assert_input(user_in_raw, int)

        return OperationMenuType(user_in_int)

    def _vault_hub(self, operation: OperationMenuType) -> None:
        """
        The routing endpoint for Vault-level operations (Withdraw, Statement, Change Password, Close Account).
        Demands AccessToken authorization.
        """
        if not self._access_token:
            self._access_token = self._ensure_vault_access()
            self._handle_info_ui("info", "access_ok")

        match operation:
            case OperationMenuType.WITHDRAW:
                self._run_transaction_controller(TransactionMenuType.WITHDRAW)
            case OperationMenuType.STATEMENT:
                self._run_transaction_controller(TransactionMenuType.STATEMENT)
            case OperationMenuType.CHANGE_PASSWORD:
                self._update_password()
            case OperationMenuType.CLOSE_ACCOUNT:
                self._close_account()
            case _:
                raise RuntimeError("Critical error: Unmapped type")

    def _lobby_hub(self) -> None:
        """
        The authenticated environment loop.

        Demands an AuthToken to enter. Allows navigation between restricted
        operations (such as password change and account closure) and operations
        that only depend on basic authentication, without requiring vault access
        (such as unfreezing an account). Upgrades access dynamically if the user
        selects a vault-level operation. Safely catches local errors while ensuring
        critical errors cleanly close the session via 'Intercept and Rethrow'.
        """
        try:
            if not self._auth_token:
                self._auth_token = self._ensure_lobby_access()
                self._handle_info_ui("info", "auth_ok")
        except ControllerCredentialsError as e:
            self._handle_exception_ui("errors", e)
            self._end_session()

        while type(self._auth_token) is AuthToken:
            try:
                account_summary = self._bank_instance.get_account_summary(
                    self._auth_token
                )
                self._handle_info_ui(
                    "info", "lobby_hello", user_name=account_summary.holder_name
                )
                operation = (
                    self._operations_menu()
                    if account_summary.is_active
                    else self._restrict_operations_menu(account_summary)
                )
                match operation:
                    case OperationMenuType.DEPOSIT:
                        self._run_transaction_controller(TransactionMenuType.DEPOSIT)
                    case RestrictedMenuType.UNFREEZE_ACCOUNT:
                        self._unfreeze_account()
                    case OperationMenuType():
                        self._vault_hub(operation)
                        if operation == OperationMenuType.WITHDRAW:
                            self._end_session()
                    case _:
                        raise RuntimeError("Critical error: Unmapped type")
            except UserAbortError:
                self._handle_info_ui("info", "user_cancel")
                continue
            except InactiveUserError:
                self._end_session()
            except ControllerOperationError as e:
                self._handle_exception_ui("errors", e)
                continue
            except BankUnavailableError:
                self._end_session()
                raise
            except (ControllerCredentialsError, SecurityError) as e:
                self._end_session()
                self._handle_exception_ui("errors", e)

    def _main_menu(self) -> MainMenuType | AdminCodeType:
        """
        Displays the root entry point of the ATM.
        Includes a hidden verification for the ADMIN_EXIT_CODE to safely shut down
        the terminal application.
        """
        user_in = io_utils.get_single_input(
            "main_menu", self._menu_config, self._controller_validator_cb
        )
        int_user_in = _assert_input(user_in, int)

        if int_user_in == ADMIN_EXIT_CODE:
            return AdminCodeType(user_in)

        return MainMenuType(user_in)

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
            except UserAbortError:
                continue

            try:
                match menu:
                    case AdminCodeType.EXIT_CODE:
                        break
                    case MainMenuType.DEPOSIT:
                        self._run_transaction_controller(TransactionMenuType.DEPOSIT)
                    case MainMenuType.ONBOARDING:
                        controller_obj = OnboardingController(self._bank_instance)
                        controller_obj.run_controller()
                    case MainMenuType.OPERATIONS:
                        self._lobby_hub()
                    case _:
                        raise RuntimeError("Critical error: Unmapped type")
            except (BankUnavailableError, ControllerRegisterError) as e:
                self._handle_exception_ui("errors", e)
