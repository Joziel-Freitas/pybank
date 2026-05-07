from abc import ABC, abstractmethod
from dataclasses import asdict
from datetime import datetime, timedelta
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
from shared.dtos import NewAccountDTO, NewAccountHolderDTO
from shared.exceptions import (
    AccountAlreadyActiveError,
    AccountHolderNotFoundError,
    BankAccessError,
    BankAuthenticationError,
    BankError,
    BankPasswordError,
    BankUnavailableError,
    ControllerCredentialsError,
    ControllerOperationError,
    DomainError,
    DuplicatedAccountError,
    DuplicatedAccountHolderError,
    HomeBranchRestrictionError,
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
    if isinstance(user_in, expected_type):
        return user_in

    raise TypeError(
        f"Critical error in I/O logic. Expected type {expected_type}, got {type(user_in).__name__}"
    )


class SharedPromptsMixin(ABC):
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
            self._handle_info_ui("new_password", "first")
            raw_pwd_1 = io_utils.get_single_input(
                "password", self._auth_config, self._controller_validator_cb
            )
            pwd_1 = _assert_input(raw_pwd_1, str)

            self._handle_info_ui("new_password", "second")
            raw_pwd_2 = io_utils.get_single_input(
                "password", self._auth_config, self._controller_validator_cb
            )
            pwd_2 = _assert_input(raw_pwd_2, str)

            matched = pwd_1 == pwd_2

            if matched:
                return pwd_1

            self._handle_info_ui("new_password", "error")

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
    _ui_message_map: dict[str, dict[str, str]]

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

    def _handle_exception_ui(
        self, context_key: str, error: DomainError, **kwargs
    ) -> None:
        error_key = exceptions.map_exceptions(error)
        error_msg = self._ui_message_map[context_key][error_key]

        if kwargs:
            error_msg = error_msg.format(**kwargs)

        views.controller_output(error_msg)

    def _handle_info_ui(self, context_key: str, info_key: str, **kwargs) -> None:
        info_msg = self._ui_message_map[context_key][info_key]

        if kwargs:
            info_msg = info_msg.format(**kwargs)

        views.controller_output(info_msg)


class OnboardingController(BaseController[Bank, None], SharedPromptsMixin):
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
        super().__init__(Bank)

        verify.verify_instance(bank_instance, Bank)
        io_utils.verify_config_map(config.auth_config)
        io_utils.verify_config_map(config.identification_config)
        io_utils.verify_config_map(config.new_account_config)

        _verify_message_map(ui_messages.SYSTEM_MESSAGES)

        self._bank_instance = bank_instance
        self._auth_config = config.auth_config
        self._identification_config = config.identification_config
        self._new_account_config = config.new_account_config
        self._ui_message_map = ui_messages.SYSTEM_MESSAGES

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
            self._handle_info_ui("account_holder", "already_account_holder")
            return cpf

        self._handle_info_ui("account_holder", "new_account_holder")
        obj_attr = io_utils.config_loop(
            self._identification_config,
            self._controller_validator_cb,
            skip_fields=["cpf"],
        )
        obj_attr["cpf"] = cpf
        obj_attr = cast(dict[str, Any], obj_attr)
        return NewAccountHolderDTO(**obj_attr)

    def _handle_account_data(self) -> NewAccountDTO:
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
        the Bank aggregate. Handles domain and application exceptions by
        rendering appropriate UI messages.
        """
        try:
            cpf = self._prompt_cpf()
            holder_dto_or_cpf = self._handle_account_holder_data(cpf)
            account_dto = self._handle_account_data()
            password = self._prompt_new_password()

            self._handle_info_ui("new_password", "created")
            self._bank_instance.register_account(
                account_dto=account_dto,
                holder_dto_or_cpf=holder_dto_or_cpf,
                password=password,
            )
            self._handle_info_ui("new_account", "success")
        except DuplicatedAccountError as e:
            self._handle_exception_ui("new_account", e)
        except UserAbortError:
            self._handle_info_ui("menu", "cancel")
        except BankUnavailableError as e:
            self._handle_exception_ui("menu", e)
        except (
            BankPasswordError,
            DuplicatedAccountHolderError,
            AccountHolderNotFoundError,
        ):
            raise RuntimeError(
                "Critical error in I/O logic in password input or internal method logic"
            )


class TransactionController(BaseController[Account, None]):
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
    _transaction_type: TransactionMenuType
    _access_token: AccessToken | None
    _controller_config: io_utils.ConfigMap

    def __init__(
        self,
        bank_instance: Bank,
        transaction_type: TransactionMenuType,
        access_token: AccessToken | None = None,
    ):

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
            TransactionMenuType.WITHDRAW: "withdraw",
            TransactionMenuType.DEPOSIT: "deposit",
        }

        if self._transaction_type not in transaction_mapper:
            raise RuntimeError(
                f"Method doesn't handle {self._transaction_type} operation"
            )
        self._handle_info_ui(
            "transaction", "min_value", min_atm=Account.MIN_ATM_TRANSACTION
        )
        transaction_key = transaction_mapper[self._transaction_type]
        value_raw = io_utils.get_single_input(
            transaction_key, self._controller_config, self._controller_validator_cb
        )
        value = _assert_input(value_raw, Decimal)
        return value

    def _confirm_overdraft(self) -> bool:
        use_overdraft_mapper = {1: True, 2: False}
        user_in_raw = io_utils.get_single_input(
            "limit", self._controller_config, self._controller_validator_cb
        )
        int_user_in = _assert_input(user_in_raw, int)
        return use_overdraft_mapper[int_user_in]

    def _handle_withdraw(self) -> None:
        amount = self._get_transaction_value()
        use_overdraft = False

        for _ in range(2):
            try:
                self._bank_instance.execute_withdraw(
                    self._active_access_token, amount, use_overdraft=use_overdraft
                )
                self._handle_info_ui("transaction", "success")
                break
            except OverdraftRequiredError as e:
                self._handle_exception_ui("withdraw", e)
                proceed = self._confirm_overdraft()

                if not proceed:
                    raise UserAbortError

                use_overdraft = True
            except InvalidWithdrawError as e:
                self._handle_exception_ui("withdraw", e)
                break

    def _handle_public_deposit(self) -> None:
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
            self._handle_info_ui("transaction", "success")
        except BankError as e:
            self._handle_exception_ui("deposit", e)
        except InvalidDepositError:
            raise RuntimeError("Critical error in I/O deposit value validation logic")

    def _handle_statement(self) -> None:
        days_mapper = {1: 30, 2: 90, 3: 180}

        user_in_raw = io_utils.get_single_input(
            "statement", self._controller_config, self._controller_validator_cb
        )
        int_user_in = _assert_input(user_in_raw, int)
        days = days_mapper[int_user_in]
        start_date = datetime.now() - timedelta(days=days)
        transactions_raw = self._bank_instance.generate_statement(
            self._active_access_token, start_date
        )
        account_info_dto = self._bank_instance.get_account_info(
            self._active_access_token
        )
        account_info_dict = asdict(account_info_dto)
        views.show_statement(transactions_raw, account_info_dict)

    def run_controller(self) -> None:
        match self._transaction_type:
            case TransactionMenuType.DEPOSIT:
                self._handle_public_deposit()
            case TransactionMenuType.WITHDRAW:
                self._handle_withdraw()
            case TransactionMenuType.STATEMENT:
                ...
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
        "use_card": validators.boolean_validator_dec(
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

        self._bank_instance = bank_instance
        self._auth_config = config.auth_config
        self._identification_config = config.identification_config
        self._menu_config = config.menu_config
        self._auth_token = None
        self._access_token = None

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
            "use_card",
            self._menu_config,
            self._controller_validator_cb,
        )
        use_card_int = _assert_input(use_card_raw, int)
        use_card = use_card_mapper[use_card_int]

        return use_card

    def _authenticate_client(
        self, cpf: str, card: AccountCard | None = None
    ) -> AuthToken:
        """
        Generates the initial Lobby AuthToken via hardware card or manual input.

        Returns:
            AuthToken: A stateless token proving account ownership.
        """
        if not card:
            user_inputs = io_utils.get_selected_inputs(
                ("branch_code", "account_num"),
                self._auth_config,
                self._controller_validator_cb,
            )
            branch_code = _assert_input(user_inputs["branch_code"], str)
            account_num = _assert_input(user_inputs["account_num"], str)

            return self._bank_instance.authenticate(cpf, branch_code, account_num)

        return self._bank_instance.authenticate(cpf, card.branch_code, card.account_num)

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
        cpf = self._prompt_cpf()
        account_holder = None
        with_card = None
        card = None

        try:
            account_holder = self._bank_instance.get_account_holder_cards(cpf)

            if account_holder:
                with_card = self._use_card_menu()

            if with_card:
                card = self._select_card(account_holder)

            self._auth_token = self._authenticate_client(cpf, card)
            self._handle_info_ui("authentication", "success")
        except (AccountHolderNotFoundError, BankAuthenticationError) as e:
            self._handle_exception_ui("authentication", e)
            raise ControllerCredentialsError

        if self._auth_token is None:
            raise ControllerCredentialsError(
                "Authentication process failed due to unknown issue"
            )

    def _ensure_access(self) -> None:

        if not self._auth_token:
            raise RuntimeError("AuthToken is needed to get vault access")

        attempts_left = self._bank_instance.get_remaining_login_attempts(
            self._auth_token
        )

        for attempt in range(attempts_left, 0, -1):
            if attempt == 1:
                self._handle_info_ui("access", "last")

            raw_password = io_utils.get_single_input(
                "password", self._auth_config, self._controller_validator_cb
            )
            password = _assert_input(raw_password, str)

            try:
                self._access_token = self._bank_instance.authorize_vault_access(
                    self._auth_token, password=password
                )
                self._handle_info_ui("access", "success")
                break
            except BankAuthenticationError as e:
                self._handle_exception_ui("access", e)
            except BankAccessError as e:
                self._handle_exception_ui("access", e)
                raise ControllerCredentialsError(
                    "Access process failed due to security issues"
                )
            except BankPasswordError:
                raise RuntimeError("Critical error in I/O password validation logic")

        if self._access_token is None:
            raise ControllerCredentialsError(
                "Access process failed due to unknown issue"
            )

    def _ensure_credentials(
        self, operation: TransactionMenuType | ManagementMenuType
    ) -> None:
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
            case TransactionMenuType.DEPOSIT:
                pass
            case ManagementMenuType.UNFREEZE:
                if not self._auth_token:
                    self._ensure_authentication()
            case (
                TransactionMenuType.WITHDRAW
                | TransactionMenuType.STATEMENT
                | ManagementMenuType.PASSWORD
                | ManagementMenuType.CLOSE
            ):
                if not self._auth_token:
                    self._ensure_authentication()
                if not self._access_token:
                    self._ensure_access()
            case _:
                raise RuntimeError("Critical Security Error: Unmapped operation type.")

    def _end_session(self) -> None:
        """
        Purges all sensitive data and tokens from memory, resetting the terminal
        to an unauthenticated state. Acts as a strict security teardown.
        """
        self._auth_token = None
        self._access_token = None

    def _update_password(self) -> None:
        """
        Orchestrates the secure password update workflow.
        Automatically revokes the current AccessToken upon success, forcing re-authentication.
        """
        if not self._access_token:
            raise RuntimeError("Access token required to update the password")

        new_password = self._prompt_new_password()
        try:
            self._bank_instance.update_password(self._access_token, new_password)
            self._access_token = None
            self._handle_info_ui("new_password", "updated")
        except BankPasswordError as e:
            raise RuntimeError("Critical error in I/O password validation logic") from e

    def _unfreeze_account(self) -> None:
        """
        Orchestrates the account recovery workflow.
        Verifies identity via birth date and resets the password, restoring account access.
        """
        if self._auth_token is None:
            raise RuntimeError("AuthToken required to perform the operation")

        raw_birth_date = io_utils.get_single_input(
            "birth_date", self._identification_config, self._controller_validator_cb
        )
        new_password = self._prompt_new_password()

        birth_date_str = _assert_input(raw_birth_date, str)

        try:
            birth_date = Person.validate_birth_date(birth_date_str)
            self._bank_instance.unfreeze_account(
                self._auth_token, birth_date, new_password
            )
            self._handle_info_ui("unfreeze", "success")
        except (BankAuthenticationError, AccountAlreadyActiveError) as e:
            self._handle_exception_ui("unfreeze", e)
            raise ControllerOperationError
        except (BankPasswordError, InvalidBirthDateError) as e:
            raise RuntimeError("Critical error in I/O validation logic") from e

    def _close_account(self) -> None:
        """
        Orchestrates the permanent account closure workflow.

        Follows the 'Tell, Don't Ask' (EAFP) pattern. It delegates the execution
        directly to the Domain, relying on Domain Exceptions (NotEmptyAccountError,
        HomeBranchRestrictionError) to dynamically format and display the correct
        UI warnings, ensuring business rules remain isolated in the Bank aggregate.
        """
        if self._access_token is None:
            raise RuntimeError("AccessToken is required to close an account")

        try:
            self._bank_instance.close_account(self._access_token)
            self._handle_info_ui("close_account", "success")
            self._end_session()
        except NotEmptyAccountError:
            account_info_dto = self._bank_instance.get_account_info(self._access_token)
            key = "positive" if account_info_dto.balance > 0 else "negative"
            self._handle_info_ui("close_account", key, balance=account_info_dto.balance)
            raise ControllerOperationError
        except HomeBranchRestrictionError as e:
            self._handle_exception_ui("close_account", e)
            raise ControllerOperationError

    def _set_transaction_controller(self, transaction_type) -> TransactionController:
        """Instantiates and prepares the TransactionController."""
        controller_obj = TransactionController(
            self._bank_instance,
            transaction_type,
            self._access_token,
        )
        return controller_obj

    def _transactions_menu(self) -> None:
        """Displays and routes the Transactions sub-menu options."""
        try:
            transaction_option = io_utils.get_single_input(
                "transactions", self._menu_config, self._controller_validator_cb
            )
            transaction = TransactionMenuType(transaction_option)
            self._ensure_credentials(transaction)
            controller_obj = self._set_transaction_controller(transaction)
            controller_obj.run_controller()
        except UserAbortError:
            self._handle_info_ui("menu", "cancel")
        except ControllerOperationError:
            return

    def _management_menu(self) -> None:
        """Displays and routes the Account Management sub-menu options."""
        try:
            management_option = io_utils.get_single_input(
                "management", self._menu_config, self._controller_validator_cb
            )
            management = ManagementMenuType(management_option)

            self._ensure_credentials(management)

            match management:
                case ManagementMenuType.PASSWORD:
                    self._update_password()
                case ManagementMenuType.UNFREEZE:
                    self._unfreeze_account()
                case ManagementMenuType.CLOSE:
                    self._close_account()
                case _:
                    raise RuntimeError("Unmapped type for ManagementType")
        except UserAbortError:
            self._handle_info_ui("menu", "cancel")
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
                self._handle_info_ui("menu", "exit")
            except SecurityError:
                self._end_session()
                self._handle_info_ui("menu", "security")
            except BankUnavailableError:
                self._end_session()
                self._handle_info_ui("menu", "unavailable")
            except ControllerCredentialsError:
                self._end_session()
                return

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
        loop, ensuring the terminal always returns to the Welcome Screen regardless
        of successful operations, user cancellations, or handled exceptions.
        """
        while True:
            try:
                menu = self._main_menu()
            except UserAbortError:
                continue
            except ValueError as e:
                raise RuntimeError(
                    "Critical error in I/O admin code validation logic"
                ) from e

            match menu:
                case AdminCodeType.EXIT_CODE:
                    break
                case MainMenuType.DEPOSIT:
                    self._set_transaction_controller(TransactionMenuType.DEPOSIT)
                case MainMenuType.ONBOARDING:
                    controller_obj = OnboardingController(self._bank_instance)
                    controller_obj.run_controller()
                case MainMenuType.OPERATIONS:
                    self._operation_hub()
                case _:
                    raise RuntimeError("Critical error: Unmapped type")
