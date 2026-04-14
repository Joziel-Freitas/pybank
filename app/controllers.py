from abc import ABC, abstractmethod
from decimal import Decimal
from functools import partial
from typing import Any, Callable, ClassVar, Generic, TypeVar, cast

from domain.account import Account, CheckingAccount, SavingsAccount, WithdrawalInfo
from domain.bank import Bank
from domain.person import Client, Person
from infra import config, io_utils, verify, views
from infra.io_utils import CallbackReturn, InputType
from settings import ADMIN_EXIT_CODE
from shared import exceptions, validators
from shared.credentials import AccessToken, AccountCard, AuthToken
from shared.exceptions import (
    AccountAlreadyActiveError,
    AccountNotFoundError,
    BankAuthenticationError,
    BankPasswordError,
    BankSecurityError,
    BlockedAccountError,
    ClientNotFoundError,
    ControllerCredentialsError,
    ControllerOperationError,
    DomainError,
    DuplicatedAccountError,
    DuplicatedClientError,
    HomeBranchRestrictionError,
    InvalidBirthDateError,
    InvalidDepositError,
    InvalidWithdrawError,
    NotEmptyAccountError,
    UserAbortError,
)
from shared.types import (
    MainMenuType,
    ManagementType,
    OperationMenuType,
    TransactionType,
)
from shared.validators import ValidatorCallback

CreatableT = TypeVar("CreatableT", bound=Person | Account)
ClientDataT = TypeVar("ClientDataT", bound=Client | str)
T = TypeVar("T", bound=Bank | Person | Account)
R = TypeVar("R")

UserInputT = TypeVar("UserInputT", bound=InputType)


def _verify_config_map(obj_config: config.ConfigMap) -> None:
    """
    Verifies if the configuration map follows the expected nested dictionary structure.

    Ensures that the provided map is a dictionary where each key is a string,
    and its value is an inner dictionary. It validates that within the inner
    dictionary, the 'value_type' key holds a type object, while all other keys
    hold string values.

    Args:
        obj_config (config.ConfigMap):
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

            for k, v in inner_dict.items():
                verify.verify_instance(k, str)

                if k == "value_type":
                    verify.verify_instance(v, type)
                    continue

                verify.verify_instance(v, str)
    except TypeError as e:
        raise TypeError(
            "obj_config must follow the InnerConfig schema strictly."
        ) from e


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
    if isinstance(user_in, expected_type):
        return user_in

    raise TypeError(
        f"Critical error in I/O logic. Expected type {expected_type}, got {type(user_in).__name__}"
    )


class UIExceptionHandlerMixin:
    _ui_message_map: dict[str, dict[str, str]]

    def _handle_exception_ui(self, method_key: str, error: DomainError) -> None:
        error_context = exceptions.map_exceptions(error)
        error_msg = self._ui_message_map[method_key][error_context]
        views.controller_output(error_msg)


class BaseController(ABC, Generic[T, R]):
    """
    Abstract Base Class for all Application Controllers.

    Establishes the contract for Input/Output orchestration. Subclasses must implement
    the 'run_controller' method to define the specific flow (creation or transaction).
    It also centralizes the construction of the input validation callback used across
    all controllers.

    Attributes:
        _model_class (Type[T]):
            The domain class (Person, Account, Bank) managed by this controller.
        _validation_mapper (ClassVar[dict]):
            Static dictionary mapping field names to validation functions.
            Must be defined by each concrete subclass.
        _controller_validator_cb (Callable[[str, InputType], CallbackReturn]):
            A dynamically bound callback function, pre-loaded with the subclass's
            validation mapper, ready to be passed to IO utility functions.
    """

    _model_class: type[T]
    _validation_mapper: ClassVar[dict[str, ValidatorCallback]]
    _controller_validator_cb: Callable[[str, InputType], CallbackReturn]

    def __init__(self, model_class: type[T]):
        """
        Initializes the controller with model type and error mapping rules.

        Args:
            model_class (Type[T]):
                The concrete class type (Bank, Person, Account) to be managed.
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
        class_name = type(self).__name__
        return f"{class_name}({self._model_class.__name__})"

    @abstractmethod
    def run_controller(self) -> R:
        """
        Executes the main business logic of the controller.

        Returns:
            R: The result of the controller execution (Object or None).
        """
        raise NotImplementedError()


class CreationController(BaseController[CreatableT, CreatableT]):
    """
    Controller responsible for the instantiation workflow of new entities.

    It handles the UI loop to collect data for Person or Account creation,
    manages validation errors by re-prompting specific fields, and calls
    the Model constructor to instantiate the class.
    """

    _validation_mapper = {
        "name": validators.boolean_validator_dec(Person.validate_name),
        "birth_date": validators.boolean_validator_dec(Person.validate_birth_date),
        "balance": validators.boolean_validator_dec(
            Account.validate_account_initial_balance
        ),
        "account_num": validators.boolean_validator_dec(
            Account.validate_account_number
        ),
    }

    _obj_config: config.ConfigMap
    _pre_filled_data: dict[str, Any] | None

    def __init__(
        self,
        model_class: type[CreatableT],
        obj_config: config.ConfigMap,
        pre_filled_data: dict[str, Any] | None = None,
    ):
        """
        Initializes the controller for entity creation.

        Args:
            model_class (type[CreatableT]): The domain class to be instantiated.
            obj_config (config.ConfigMap): UI prompts and validation types for the entity.
            pre_filled_data (dict[str, Any] | None, optional):
                A dictionary of pre-validated data (e.g., CPF) to be injected directly
                into the creation payload, bypassing the user input prompt. Defaults to None.
        """
        super().__init__(model_class)

        _verify_config_map(obj_config)
        self._obj_config = obj_config
        self._pre_filled_data = pre_filled_data

    def __repr__(self) -> str:
        class_name = type(self).__name__
        config_keys = list(self._obj_config.keys())

        return (
            f"{class_name}"
            f"(model_class={self._model_class.__name__}, "
            f"configured_fields={config_keys!r})"
        )

    def run_controller(self) -> CreatableT:
        """
        Orchestrates the creation loop: Input -> Validate -> Factory -> Retry on Error.

        The loop continues until the ObjectFactory successfully returns a valid instance.
        If a DomainError occurs (e.g., Invalid CPF logic), the exception mapper identifies
        which field caused it, and the loop requests only that specific field again.

        Returns:
            CreatableT: A fully initialized instance of Person or Account.
        """

        object_attr = io_utils.config_loop(
            self._obj_config, self._controller_validator_cb
        )
        object_attr = cast(dict[str, Any], object_attr)

        if self._pre_filled_data:
            object_attr.update(self._pre_filled_data)

        while True:
            try:
                return self._model_class(**object_attr)
            except DomainError as error:
                config_key = exceptions.map_exceptions(error)
                new_value = io_utils.get_single_input(
                    config_key, self._obj_config, self._controller_validator_cb
                )
                object_attr[config_key] = new_value


class TransactionController(BaseController[Account, None], UIExceptionHandlerMixin):
    """
    Controller responsible for executing banking transactions (Deposit, Withdraw, Statement).

    Operates in a 'Stateful' manner regarding the session token, but requires
    'Just-in-Time' password authentication to unlock the Account object.

     Lifecycle:
    1. Initialization: Receives a valid AuthToken from the parent controller.
    2. Access Loop: Prompts for password to retrieve the Account instance.
    3. Operation Loop: Orchestrates financial operations until logout or exit.
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
    _auth_config: config.ConfigMap
    _transaction_config: config.ConfigMap
    _transaction_type: TransactionType
    _access_token: AccessToken | None
    _ui_message_map: dict[str, dict[str, str]]

    def __init__(
        self,
        bank_instance: Bank,
        auth_config: config.ConfigMap,
        transaction_config: config.ConfigMap,
        transaction_type: TransactionType,
        access_token: AccessToken | None = None,
    ):

        super().__init__(Account)

        verify.verify_instance(bank_instance, Bank)
        self._bank_instance = bank_instance

        _verify_config_map(auth_config)
        self._auth_config = auth_config

        _verify_config_map(transaction_config)
        self._transaction_config = transaction_config

        verify.verify_instance(transaction_type, TransactionType)

        if transaction_type != TransactionType.DEPOSIT and access_token is None:
            raise RuntimeError(
                "AccessToken is required to perform the requested operation"
            )

        self._transaction_type = transaction_type

        if access_token is not None:
            verify.verify_instance(access_token, AccessToken)

        self._access_token = access_token

    def __repr__(self) -> str:
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
        if self._access_token is None:
            raise RuntimeError("Getter called without an AccessToken")

        return self._access_token

    def _get_transaction_value(self) -> Decimal:
        transaction_mapper = {
            TransactionType.WITHDRAW: "withdraw",
            TransactionType.DEPOSIT: "deposit",
        }

        if self._transaction_type not in transaction_mapper:
            raise RuntimeError(
                f"Method doesn't handle {self._transaction_type} operation"
            )

        transaction_key = transaction_mapper[self._transaction_type]
        views.controller_output("transaction", "min_value")
        value_raw = io_utils.get_single_input(
            transaction_key, self._transaction_config, self._controller_validator_cb
        )
        value = _assert_input(value_raw, Decimal)
        return value

    def _confirm_withdraw(self, info: WithdrawalInfo) -> bool:

        if not info.authorized:
            views.controller_output("transaction", None)
            return False

        if info.uses_limit is False:
            return True

        views.controller_output("transaction", False)
        use_limit_mapper = {1: True, 2: False}
        limit_option_raw = io_utils.get_single_input(
            "limit", self._transaction_config, self._controller_validator_cb
        )
        limit_option = _assert_input(limit_option_raw, int)
        use_limit = use_limit_mapper[limit_option]

        if not use_limit:
            raise UserAbortError

        return True

    def _handle_withdraw(self) -> None:
        amount = self._get_transaction_value()

        try:
            info = self._bank_instance.check_withdrawal_info(
                self._active_access_token, amount
            )
            verify.verify_instance(info, WithdrawalInfo)
            proceed = self._confirm_withdraw(info)

            if not proceed:
                raise ControllerOperationError

            self._bank_instance.execute_withdraw(self._active_access_token, amount)
            views.controller_output("transaction", True)
        except InvalidWithdrawError:
            raise ControllerOperationError
        except BlockedAccountError:
            views.controller_output("access", "withdraw_blocked")
            raise ControllerCredentialsError

    def _handle_public_deposit(self) -> None:
        user_in_dict = io_utils.get_selected_inputs(
            ("branch_code", "account_num"),
            self._auth_config,
            self._controller_validator_cb,
        )
        branch_code = _assert_input(user_in_dict["branch_code"], str)
        account_num = _assert_input(user_in_dict["account_num"], str)
        amount = self._get_transaction_value()

        try:
            self._bank_instance.execute_deposit(branch_code, account_num, amount)
            views.controller_output("transaction", True)
        except InvalidDepositError:
            raise ControllerOperationError
        except AccountNotFoundError:
            views.controller_output("transaction", "not_found")
            raise ControllerOperationError
        except BlockedAccountError:
            views.controller_output("transaction", "blocked")
            raise ControllerOperationError

    def run_controller(self) -> None:
        match self._transaction_type:
            case TransactionType.DEPOSIT:
                self._handle_public_deposit()
            case TransactionType.WITHDRAW:
                self._handle_withdraw()
            case TransactionType.STATEMENT:
                ...
            case _:
                raise RuntimeError("Unmapped TransactionType")


class BankSystemController(BaseController[Bank, None]):
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
        "cpf": validators.boolean_validator_dec(validators.validate_cpf),
        "password": validators.boolean_validator_dec(Bank.validate_password),
        "operations": validators.boolean_validator_dec(
            partial(verify.verify_interval, min_val=1, max_val=2)
        ),
        "transactions": validators.boolean_validator_dec(
            partial(verify.verify_interval, min_val=1, max_val=3)
        ),
        "management": validators.boolean_validator_dec(
            partial(verify.verify_interval, min_val=1, max_val=3)
        ),
        "acc_type": validators.boolean_validator_dec(
            partial(verify.verify_interval, min_val=1, max_val=2)
        ),
        "birth_date": validators.boolean_validator_dec(Person.validate_birth_date),
        "use_card": validators.boolean_validator_dec(
            partial(verify.verify_interval, min_val=1, max_val=2)
        ),
    }

    _bank_instance: Bank
    _menu_config: config.ConfigMap
    _identification_config: config.ConfigMap
    _new_acc_config: config.ConfigMap
    _auth_config: config.ConfigMap
    _transaction_config: config.ConfigMap
    _client: Client | None
    _active_auth_token: AuthToken | None
    _active_access_token: AccessToken | None
    _active_card: AccountCard | None

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
        self._bank_instance = bank_instance

        config_mappers = (
            config.menu_config,
            config.identification_config,
            config.new_account_config,
            config.auth_config,
            config.transaction_config,
        )

        for cfg_map in config_mappers:
            _verify_config_map(cfg_map)

        self._menu_config = config.menu_config
        self._identification_config = config.identification_config
        self._new_acc_config = config.new_account_config
        self._auth_config = config.auth_config
        self._transaction_config = config.transaction_config
        self._client = None
        self._active_auth_token = None
        self._active_access_token = None
        self._active_card = None

    def __repr__(self) -> str:
        """
        Returns a diagnostic string representation of the controller's current state.
        Useful for debugging session leaks or hardware state issues.
        """
        class_name = type(self).__name__

        auth_status = (
            "Authenticated" if self._active_auth_token else "Not authenticated"
        )
        access_status = "Authorized" if self._active_access_token else "Not authorized"
        card_status = "Card Inserted" if self._active_card else "No Card"

        return (
            f"{class_name}("
            f"connected_to={self._bank_instance.bank_name!r}"
            f"authentication_status={auth_status!r}"
            f"access_status={access_status!r}"
            f"hardware_status={card_status!r})"
        )

    @property
    def _active_client(self):
        """
        Safely retrieves the hydrated Client entity for the active session.

        Raises:
            RuntimeError: If accessed before the client is properly authenticated.
        """
        if self._client is None:
            raise RuntimeError("Getter called without an Client instance")

        return self._client

    def _prompt_new_password(self) -> str:
        """
        Handles the double-input loop for creating or updating a secure password.

        Returns:
            str: The validated, matching 6-digit password string.
        """
        while True:
            views.controller_output("update_password", "1")
            raw_pwd_1 = io_utils.get_single_input(
                "password", self._auth_config, self._controller_validator_cb
            )
            pwd_1 = _assert_input(raw_pwd_1, str)

            views.controller_output("update_password", "2")
            raw_pwd_2 = io_utils.get_single_input(
                "password", self._auth_config, self._controller_validator_cb
            )
            pwd_2 = _assert_input(raw_pwd_2, str)

            matched = pwd_1 == pwd_2

            if matched:
                return pwd_1

            views.controller_output("update_password", False)

    def _prompt_cpf(self) -> str:
        """
        Helper method to collect and enforce string type for the CPF input.

        Returns:
            str: The CPF provided by the user.
        """
        client_cpf = io_utils.get_single_input(
            "cpf", config.identification_config, self._controller_validator_cb
        )
        client_cpf = _assert_input(client_cpf, str)
        return client_cpf

    def _get_client(self) -> Client:
        """
        Prompts for a CPF and retrieves the corresponding registered Client entity.
        """
        cpf = self._prompt_cpf()
        return self._bank_instance.get_registered_client(cpf)

    def _select_card(self) -> AccountCard:
        """
        Displays available hardware cards for the active client and prompts for selection.

        Returns:
            AccountCard: The selected card object.
        """
        client_cards = self._active_client.cards
        views.show_cards(client_cards)

        def local_validator_cb(field: str, user_in_raw: InputType) -> CallbackReturn:
            user_in = _assert_input(user_in_raw, int)
            return {"result": 0 <= user_in < len(client_cards)}

        card_idx_raw = io_utils.get_single_input(
            "card", self._auth_config, local_validator_cb
        )
        card_idx = _assert_input(card_idx_raw, int)

        return client_cards[card_idx]

    def _use_card_menu(self) -> bool:
        """
        Prompts the user to select the authentication strategy.

        Returns:
            bool: True if the user chooses 'Use Saved Card'.
                  False if the user chooses 'Manual Input'.
        """
        use_card_mapper = {1: True, 2: False}

        use_card_raw = io_utils.get_single_input(
            "use_card",
            self._menu_config,
            self._controller_validator_cb,
        )
        use_card_int = _assert_input(use_card_raw, int)
        use_card = use_card_mapper[use_card_int]

        return use_card

    def _end_session(self) -> None:
        """
        Purges all sensitive data and tokens from memory, resetting the terminal
        to an unauthenticated state. Acts as a strict security teardown.
        """
        self._client = None
        self._active_card = None
        self._active_auth_token = None
        self._active_access_token = None

    def _authenticate_client(self) -> AuthToken:
        """
        Generates the initial Lobby AuthToken via hardware card or manual input.

        Returns:
            AuthToken: A stateless token proving account ownership.
        """
        if not self._active_card:
            user_inputs = io_utils.config_loop(
                self._auth_config, self._controller_validator_cb, skip_fields=["card"]
            )
            branch_code = _assert_input(user_inputs["branch_code"], str)
            account_num = _assert_input(user_inputs["account_num"], str)
        else:
            branch_code = self._active_card.branch_code
            account_num = self._active_card.account_num

        return self._bank_instance.authenticate(
            self._active_client, branch_code, account_num
        )

    def _ensure_authentication(self) -> None:
        """
        The 'Lobby Door'. Ensures the session holds a valid AuthToken.

        Handles the initial greeting workflow, asking for CPF, resolving the client,
        and prompting for credentials (card or manual). Gracefully handles 'Not Found'
        errors to prevent terminal crashes.

        Raises:
            ControllerCredentialsError: If the user fails to provide valid credentials
                after repeated attempts.
        """
        while True:
            try:
                if not self._client:
                    self._client = self._get_client()

                with_card = False
                if self._active_client.cards:
                    with_card = self._use_card_menu()

                if with_card:
                    self._active_card = self._select_card()
                else:
                    self._active_card = None

                self._active_auth_token = self._authenticate_client()
                break
            except ClientNotFoundError:
                self._client = None
                continue
            except BankAuthenticationError:
                self._active_card = None

        if self._active_auth_token is None:
            raise ControllerCredentialsError("Authentication process failed")

    def _ensure_access(self) -> None:
        """
        The 'Vault Door'. Upgrades an AuthToken to a highly secure AccessToken.

        Requires a password challenge. Synchronizes with the Domain to check for
        account freezes and remaining login attempts, providing real-time warnings
        to the user via the View.

        Raises:
            RuntimeError: If called without a prior AuthToken.
            ControllerCredentialsError: If password validation fails entirely or
                the account gets blocked during the process.
        """
        if not self._active_auth_token:
            raise RuntimeError("AuthToken is needed to get vault access")

        attempts_left = self._bank_instance.get_remaining_login_attempts(
            self._active_auth_token
        )

        for attempt in range(attempts_left, 0, -1):
            if attempt == 1:
                views.controller_output(mapper_key="access", inner_key="last")

            raw_password = io_utils.get_single_input(
                "password", self._auth_config, self._controller_validator_cb
            )
            password = _assert_input(raw_password, str)

            try:
                self._active_access_token = self._bank_instance.authorize_vault_access(
                    self._active_auth_token, password=password
                )
                views.controller_output(mapper_key="access", inner_key=True)
                break
            except BankAuthenticationError:
                views.controller_output(mapper_key="access", inner_key=False)
            except BlockedAccountError:
                views.controller_output(mapper_key="access", inner_key="blocked")
                raise ControllerCredentialsError("Access process failed")

        if self._active_access_token is None:
            raise ControllerCredentialsError("Access process failed")

    def _ensure_credentials(self, operation: TransactionType | ManagementType) -> None:
        """
        Security Routing Checkpoint.

        Evaluates the requested operation and enforces the principle of least privilege,
        triggering either 'Lobby' authentication or 'Vault' authorization depending
        on the sensitivity of the transaction.

        Args:
            operation (TransactionType | ManagementType): The intended user action.

        Raises:
            RuntimeError: If an unknown operation bypasses the security map.
        """
        match operation:
            case TransactionType.DEPOSIT:
                pass
            case ManagementType.UNFREEZE:
                if not self._active_auth_token:
                    self._ensure_authentication()
            case (
                TransactionType.WITHDRAW
                | TransactionType.STATEMENT
                | ManagementType.PASSWORD
                | ManagementType.CLOSE
            ):
                if not self._active_auth_token:
                    self._ensure_authentication()
                if not self._active_access_token:
                    self._ensure_access()
            case _:
                raise RuntimeError("Critical Security Error: Unmapped operation type.")

    def _update_password(self) -> None:
        """
        Orchestrates the secure password update workflow.
        Automatically revokes the current AccessToken upon success, forcing re-authentication.
        """
        if not self._active_access_token:
            raise RuntimeError("Access token required to update the password")

        new_password = self._prompt_new_password()
        try:
            self._bank_instance.update_password(self._active_access_token, new_password)
            self._active_access_token = None
            views.controller_output("update_password", True)
        except BankPasswordError as e:
            raise RuntimeError("Critical error in I/O logic") from e

    def _unfreeze_account(self) -> None:
        """
        Orchestrates the account recovery workflow.
        Verifies identity via birth date and resets the password, restoring account access.
        """
        if self._active_auth_token is None:
            raise RuntimeError("AuthToken required to perform the operation")

        raw_birth_date = io_utils.get_single_input(
            "birth_date", self._identification_config, self._controller_validator_cb
        )
        new_password = self._prompt_new_password()

        birth_date_str = _assert_input(raw_birth_date, str)

        try:
            birth_date = validators.validate_date_format(birth_date_str)
            self._bank_instance.unfreeze_account(
                self._active_auth_token, birth_date, new_password
            )
            views.controller_output("unfreeze", True)
        except BankAuthenticationError:
            views.controller_output("unfreeze", "authentication")
            raise ControllerOperationError
        except AccountAlreadyActiveError:
            views.controller_output("unfreeze", "already_active")
            raise ControllerOperationError
        except (BankPasswordError, InvalidBirthDateError) as e:
            raise RuntimeError("Critical error in I/O logic") from e

    def _close_account(self) -> None:
        """
        Orchestrates the permanent account closure workflow.

        Enforces 'Defense in Depth' by validating the Home Branch Rule and Zero
        Balance Rule at the presentation layer before delegating to the Domain.
        """
        if self._active_access_token is None:
            raise RuntimeError("AccessToken is required to close an account")

        if (
            self._active_access_token.branch_code
            != self._bank_instance.bank_branch_code
        ):
            views.controller_output("close_account", False)
            raise ControllerOperationError

        account = self._bank_instance._get_account(self._active_access_token)

        if account.balance != 0:
            views.show_close_account_status(account.balance)
            raise ControllerOperationError

        try:
            self._bank_instance.close_account(self._active_access_token)
            views.controller_output("close_account", True)
            self._end_session()
        except NotEmptyAccountError:
            views.show_close_account_status(account.balance)
            raise ControllerOperationError
        except HomeBranchRestrictionError:
            views.controller_output("close_account", False)
            raise ControllerOperationError

    def _set_transaction_controller(self, transaction_type) -> TransactionController:
        """Instantiates and prepares the TransactionController."""
        controller_obj = TransactionController(
            self._bank_instance,
            self._auth_config,
            self._transaction_config,
            transaction_type,
            self._active_access_token,
        )
        return controller_obj

    def _set_create_client(self, cpf: str) -> CreationController:
        """
        Instantiates a CreationController for a new Client entity.
        Injects the pre-validated CPF to streamline the UX.
        """
        new_client_config = self._identification_config.copy()
        new_client_config.pop("cpf")
        filled_data = {"cpf": cpf}

        controller_obj = CreationController(Client, new_client_config, filled_data)

        return controller_obj

    def _set_create_account(self) -> CreationController:
        """
        Instantiates a dynamically typed CreationController for Accounts.
        Silently injects the terminal's Home Branch Code to enforce domain rules.
        """
        acc_type_mapper = {1: CheckingAccount, 2: SavingsAccount}
        new_acc_config = self._new_acc_config.copy()

        user_in = io_utils.get_single_input(
            "acc_type", self._new_acc_config, self._controller_validator_cb
        )
        int_user_in = _assert_input(user_in, int)
        model_class = acc_type_mapper[int_user_in]
        new_acc_config.pop("acc_type")

        filled_data = {"branch_code": self._bank_instance.bank_branch_code}

        controller_obj = CreationController(model_class, new_acc_config, filled_data)

        return controller_obj

    def _onboarding_workflow(self) -> None:
        """
        The Maestro of the Account Creation process.

        Orchestrates a robust, ACID-ready workflow to register clients and accounts.
        It evaluates client existence, delegates entity instantiation to internal
        factories, and securely hashes the initial password.

        Catches Domain-level race conditions (e.g., duplicated unique constraints
        during parallel kiosk usage) and gracefully returns to the main menu without
        crashing.
        """
        try:
            cpf = self._prompt_cpf()
            client_or_cpf = None

            is_client = self._bank_instance.check_client_exists(cpf)

            if not is_client:
                views.controller_output("client", "new")
                controller_obj = self._set_create_client(cpf)
                client_or_cpf = controller_obj.run_controller()
            else:
                client_or_cpf = cpf
                views.controller_output("client", "not_new")

            controller_obj = self._set_create_account()
            account = controller_obj.run_controller()
            password = self._prompt_new_password()
            self._bank_instance.register_account(account, client_or_cpf, password)
            views.controller_output("new_account", True)
        except UserAbortError:
            views.controller_output("menu", "cancel")
            return
        except BankPasswordError:
            views.controller_output("new_account", "password")
        except DuplicatedAccountError:
            views.controller_output("new_account", "duplicated")
        except DuplicatedClientError:
            views.controller_output("new_account", False)
            return
        except ClientNotFoundError:
            views.controller_output("new_account", False)
            return

    def _transactions_menu(self) -> None:
        """Displays and routes the Transactions sub-menu options."""
        try:
            transaction_option = io_utils.get_single_input(
                "transactions", self._menu_config, self._controller_validator_cb
            )
            transaction = TransactionType(transaction_option)
            self._ensure_credentials(transaction)
            controller_obj = self._set_transaction_controller(transaction)
            controller_obj.run_controller()
        except UserAbortError:
            views.controller_output("menu", "cancel")
            return
        except ControllerOperationError:
            return

    def _management_menu(self) -> None:
        """Displays and routes the Account Management sub-menu options."""
        try:
            management_option = io_utils.get_single_input(
                "management", self._menu_config, self._controller_validator_cb
            )
            management = ManagementType(management_option)

            self._ensure_credentials(management)

            match management:
                case ManagementType.PASSWORD:
                    self._update_password()
                case ManagementType.UNFREEZE:
                    self._unfreeze_account()
                case ManagementType.CLOSE:
                    self._close_account()
                case _:
                    raise RuntimeError("Unmapped type for ManagementType")
        except UserAbortError:
            views.controller_output("menu", "cancel")
            return
        except ControllerOperationError:
            return

    def _operation_hub(self) -> None:
        """
        The secure hub for all logged-in operations.
        Catches high-level security breaches (like tampered tokens) and user aborts,
        ensuring the session is immediately purged before returning to the main menu.
        """
        while True:
            try:
                raw_operation = io_utils.get_single_input(
                    "operations", self._menu_config, self._controller_validator_cb
                )
                operation = OperationMenuType(_assert_input(raw_operation, int))

                match operation:
                    case OperationMenuType.TRANSACTIONS:
                        self._transactions_menu()
                    case OperationMenuType.MANAGEMENT:
                        self._management_menu()
                    case _:
                        raise RuntimeError("Unmapped OperationMenuType")
            except UserAbortError:
                self._end_session()
                views.controller_output("menu", "exit")
                return
            except (BankSecurityError, ControllerCredentialsError):
                self._end_session()
                views.controller_output("menu", "security")
                return

    def _main_menu(self) -> MainMenuType | None:
        """
        Displays the root entry point of the ATM.
        Includes a hidden verification for the ADMIN_EXIT_CODE to safely shut down
        the terminal application.
        """
        is_admin_code = None

        def _main_menu_validator_cb(
            field: str, user_input: InputType
        ) -> CallbackReturn:
            nonlocal is_admin_code

            int_user_input = _assert_input(user_input, int)
            is_valid_menu = int_user_input in (1, 2)
            is_admin_code = user_input == ADMIN_EXIT_CODE

            return {"result": is_valid_menu or is_admin_code}

        main_option = io_utils.get_single_input(
            "main_menu", self._menu_config, _main_menu_validator_cb
        )

        if is_admin_code:
            views.bye()
            return None

        return MainMenuType(main_option)

    def run_controller(self) -> None:
        """
        The Kiosk Loop.

        The absolute entry point of the presentation layer. It maintains an infinite
        loop, ensuring the terminal always returns to the Welcome Screen regardless
        of successful operations, user cancellations, or handled exceptions.
        """
        while True:
            menu = self._main_menu()

            if menu is None:
                break

            match menu:
                case MainMenuType.OPERATIONS:
                    self._operation_hub()
                case MainMenuType.ONBOARDING:
                    self._onboarding_workflow()
                case _:
                    raise RuntimeError("Critical error in main menu logic")
