from abc import ABC, abstractmethod
from datetime import date
from decimal import Decimal
from functools import partial
from typing import Any, ClassVar, Generic, TypeVar, cast

from domain.account import Account, CheckingAccount, SavingsAccount
from domain.bank import Bank
from domain.person import Client, Person
from infra import config, io_utils, verify, views
from infra.io_utils import (
    CallbackReturn,
    InputType,
    config_loop,
    get_single_input,
    validate_entry,
)
from settings import ADMIN_EXIT_CODE
from shared.credentials import AccessToken, AccountCard, AuthToken
from shared.exceptions import (
    ACCOUNT_ERROR_MAP,
    PERSON_ERROR_MAP,
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
    ErrorMapType,
    HomeBranchRestrictionError,
    NotEmptyAccountError,
    UserAbortError,
    map_exceptions,
)
from shared.types import (
    MainMenuType,
    ManagementType,
    OperationMenuType,
    TransactionType,
)
from shared.validators import ValidatorCallback, boolean_validator_dec, validate_cpf

CreatableT = TypeVar("CreatableT", bound=Person | Account)
ClientDataT = TypeVar("ClientDataT", bound=Client | str)
T = TypeVar("T", bound=Bank | Person | Account)
R = TypeVar("R")

UserInputT = TypeVar("UserInputT", bound=InputType)


def _verify_config_map(obj_config: config.ConfigMap) -> None:
    """
    Verifies if the configuration map follows the expected nested dictionary structure.

    Args:
        obj_config (config.ConfigMap):
            The configuration map to be verified. Must be a dict of dicts.

    Raises:
        TypeError:
            If the structure does not match Dict[str, Dict[...]].
    """
    try:
        verify.verify_instance(obj_config, dict)

        for key, inner_dict in obj_config.items():
            verify.verify_instance(key, str)
            verify.verify_instance(inner_dict, dict)
    except TypeError as e:
        raise TypeError("Unsupported configuration format") from e


def _assert_input(user_in: InputType, expected_type: type[UserInputT]) -> UserInputT:
    if isinstance(user_in, expected_type):
        return user_in

    raise TypeError(
        f"Critical error in I/O logic. Expected type {expected_type}, got {type(user_in).__name__}"
    )


class BaseController(ABC, Generic[T, R]):
    """
    Abstract Base Class for all Application Controllers.

    Establishes the contract for Input/Output orchestration. Subclasses must implement
    the 'run_controller' method to define the specific flow (creation or transaction).

    Attributes:
        _model_class (Type[T]):
            The domain class (Person, Account, Bank) managed by this controller.
        _validation_mapper (ClassVar[dict]):
            Static dictionary mapping field names to validation functions.
    """

    _model_class: type[T]
    _validation_mapper: ClassVar[dict[str, ValidatorCallback]]

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
    the ObjectFactory to instantiate the class.
    """

    _validation_mapper = {
        "name": boolean_validator_dec(Person.validate_name),
        "birth_date": boolean_validator_dec(Person.validate_birth_date),
        "balance": boolean_validator_dec(Account.validate_account_initial_balance),
        "account_num": boolean_validator_dec(Account.validate_account_number),
    }

    _obj_config: config.ConfigMap
    _obj_error_map: ErrorMapType
    _pre_filled_data: dict[str, Any] | None

    def __init__(
        self,
        model_class: type[CreatableT],
        obj_error_map: ErrorMapType,
        obj_config: config.ConfigMap,
        pre_filled_data: dict[str, Any] | None = None,
    ):
        super().__init__(model_class)

        _verify_config_map(obj_config)
        self._obj_config = obj_config
        self._obj_error_map = obj_error_map
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
        controller_validator_cb = partial(
            validate_entry, validation_mapper=self._validation_mapper
        )

        object_attr = io_utils.config_loop(self._obj_config, controller_validator_cb)
        object_attr = cast(dict[str, Any], object_attr)

        if self._pre_filled_data:
            object_attr.update(self._pre_filled_data)

        while True:
            try:
                return self._model_class(**object_attr)
            except DomainError as error:
                config_key = map_exceptions(error, self._obj_error_map)
                new_value = get_single_input(
                    config_key, self._obj_config, controller_validator_cb
                )
                object_attr[config_key] = new_value


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
        "withdraw": boolean_validator_dec(
            partial(verify.verify_interval, min_val=Decimal("0.5"), max_val=None)
        ),
        "deposit": boolean_validator_dec(
            partial(verify.verify_interval, min_val=Decimal("0.5"), max_val=None)
        ),
        "operations": boolean_validator_dec(
            partial(verify.verify_interval, min_val=1, max_val=3)
        ),
        "limit": boolean_validator_dec(
            partial(verify.verify_interval, min_val=1, max_val=2)
        ),
        "options": boolean_validator_dec(
            partial(verify.verify_interval, min_val=1, max_val=2)
        ),
    }

    _bank_instance: Bank
    _transaction_config: config.ConfigMap
    _transaction_type: TransactionType
    _access_token: AccessToken | None
    _model_account: Account | None

    def __init__(
        self,
        bank_instance: Bank,
        transaction_config: config.ConfigMap,
        transaction_type: TransactionType,
        access_token: AccessToken | None = None,
    ):

        super().__init__(Account)

        verify.verify_instance(bank_instance, Bank)
        self._bank_instance = bank_instance

        _verify_config_map(transaction_config)
        self._transaction_config = transaction_config

        self._controller_validator_cb = partial(
            validate_entry, validation_mapper=self._validation_mapper
        )
        self._transaction_type = transaction_type
        self._access_token = access_token
        self._model_account = None

    def __repr__(self) -> str:
        class_name = type(self).__name__
        has_account = self._model_account is not None

        return (
            f"{class_name}("
            f"bank={self._bank_instance._bank_name!r},"
            f"user_cpf={self._access_token.cpf!r}, "
            f"account_accessed={has_account})"
        )

    @property
    def _active_account(self) -> Account:
        """
        Returns the active account instance.

        Raises:
            RuntimeError: If called before account access is granted.
        """
        if self._model_account is None:
            raise RuntimeError("Account access failed. Execute _get_access() method")
        return self._model_account

    def _get_acc_access(self) -> bool:
        """
        Attempts to authorize access to the Account using the provided password.

        Uses the pre-existing AuthToken to request the Account object from the Bank.
        This method is the gatekeeper that transforms a 'Session' (Token) into
        'Access' (Model Object).

        Returns:
            bool: True if the password is correct and access is granted.
                  False if the password is incorrect (allows retries).

        Raises:
            BlockedAccountError: Propagated immediately if the account is frozen.
                                 The controller does NOT catch this here, allowing
                                 the loop to handle the lockout state.
            RuntimeError: If a security mismatch (e.g., Token Signature) occurs.
        """
        key = "password"
        user_in = get_single_input(
            key, self._transaction_config, self._controller_validator_cb
        )
        user_in = _assert_input(user_in, str)
        try:
            self._model_account = self._bank_instance.authorize_vault_access(
                self._access_token, user_in
            )
            return True
        except AccountNotFoundError:
            return False
        except BankSecurityError as error:
            raise RuntimeError(
                "CRITICAL SECURITY FAILURE: Session integrity compromised."
            ) from error

    def _access_loop(self) -> bool | None:
        """
        Manages the authentication retry logic (Max 3 attempts).

        Handles the transition between 'Unauthorized' and 'Authorized' states.
        It specifically interprets the 'BlockedAccountError' to terminate the
        controller flow gracefully if the account gets frozen during the process.

        Returns:
            bool | None:
                - True: Access granted (Account object is ready).
                - False: User manually aborted or exhausted retries (Logic dependent).
                - None: Account is frozen/blocked. The controller must exit.
        """
        for attempt in range(3):
            try:
                if self._get_acc_access():
                    views.controller_output(mapper_key="access", inner_key=True)
                    return True

                views.controller_output(mapper_key="access", inner_key=False)
                if attempt == 1:
                    views.controller_output(mapper_key="access", inner_key="1")
            except BlockedAccountError:
                views.controller_output(mapper_key="access", inner_key="0")
                return None

    def _get_transaction_type(self) -> TransactionType:
        """
        Prompts the user to select an operation (1=Withdraw, 2=Deposit, 3=Statement).

        Returns:
            TransactionType: The enum corresponding to the user choice.
        """
        key = "operations"
        int_transaction = get_single_input(
            key, self._transaction_config, self._controller_validator_cb
        )
        transaction = TransactionType(int_transaction)

        return transaction

    def _get_operation_value(self, operation_option: TransactionType) -> Decimal:
        """
        Prompts the user for the numeric value of the transaction.

        Dynamically selects the configuration ('withdraw' or 'deposit') based on
        the operation type and delegates input collection to the I/O utility.

        Args:
            operation_option (TransactionType): The operation being performed.

        Returns:
            Decimal: The validated monetary value to be deposited or withdrawn.

        Raises:
            UserAbortError: If the user enters the exit command during input.
        """
        operations_configs: config.ConfigMap = {
            k: self._transaction_config[k] for k in ("withdraw", "deposit")
        }

        operation_mapper = {
            TransactionType.WITHDRAW: "withdraw",
            TransactionType.DEPOSIT: "deposit",
        }

        operation_key = operation_mapper[operation_option]
        value_raw = get_single_input(
            operation_key, operations_configs, self._controller_validator_cb
        )
        value = _assert_input(value_raw, Decimal)

        return value

    def _authorize_withdraw(self, value: Decimal) -> bool:
        """
        Verifies if the withdrawal is authorized by the Account rules.

        If the account uses a limit (overdraft), prompts the user for confirmation.

        Args:
            value (Decimal): The amount to be withdrawn.

        Returns:
            bool: True if authorized (and confirmed by user if limit needed), False otherwise.

        Raises:
            RuntimeError: If the validation state returns an invalid combination.
        """
        info = self._active_account.check_withdrawal(value)

        if not info.authorized:
            views.controller_output("transaction", None)
            return False

        if info.uses_limit is False:
            return True

        if info.uses_limit is True:
            views.controller_output("transaction", False)
            limit_option = get_single_input(
                "limit", self._transaction_config, self._controller_validator_cb
            )
            limit_option = _assert_input(limit_option, int)

            limit_mapper = {1: True, 2: False}
            use_limit = limit_mapper[limit_option]
            return use_limit
        raise RuntimeError(f"Invalid withdraw state: {info}")

    def _handle_statement(self) -> None:
        """
        Retrieves account data and orchestrates the statement display.

        It checks the specific type of the active account. If it is a CheckingAccount,
        it gathers additional overdraft limit information (total and remaining)
        to provide a complete financial overview in the view.
        """
        statement = self._active_account.get_statement
        balance = self._active_account.balance
        overdraft_info = None

        if isinstance(self._active_account, CheckingAccount):
            overdraft_info = {
                "total_limit": self._active_account.CREDIT_LIMIT,
                "remaining": self._active_account.remaining_credit,
            }
        views.show_statement(statement, balance, overdraft_info)

    def _handle_withdraw(self) -> None:
        """
        Orchestrates the withdrawal workflow.

        Flow:
        1. Prompts for the withdrawal amount.
        2. Validates authorization via `_authorize_withdraw` (checks balance and
           prompts user confirmation if overdraft is needed).
        3. Executes the withdrawal and shows success feedback if authorized.
        4. Displays a cancellation message if the user aborts the process.
        """
        value = self._get_operation_value(TransactionType.WITHDRAW)
        if self._authorize_withdraw(value):
            self._active_account.withdraw(value)
            views.controller_output("transaction", True)
            return

        views.controller_output("general", "cancel")

    def _handle_deposit(self) -> None:
        """
        Orchestrates the deposit workflow.

        Prompts the user for the deposit amount, updates the account balance,
        and triggers the success feedback view.
        """
        value = self._get_operation_value(TransactionType.DEPOSIT)
        self._active_account.deposit(value)
        views.controller_output("transaction", True)

    def _operation_flow(self) -> None:
        """
        Acts as the central dispatcher for banking operations.

        Identifies the requested transaction type and delegates the execution
        to the specific handler method (`_handle_statement`, `_handle_withdraw`,
        or `_handle_deposit`).

        Raises:
            UserAbortError: If the user cancels the operation selection or input.
            RuntimeError: If an unknown transaction type is encountered.
        """
        operation_type: TransactionType = self._get_transaction_type()

        match operation_type:
            case TransactionType.STATEMENT:
                self._handle_statement()
            case TransactionType.WITHDRAW:
                self._handle_withdraw()
            case TransactionType.DEPOSIT:
                self._handle_deposit()
            case _:
                raise RuntimeError("Unexpected controller error")

    def _select_operation(self) -> bool | None:
        """
        Prompts the user to determine the next step: Continue or Exit.

        Returns:
            bool: True if the user chooses to perform another operation (Option 1).
            None: If the user chooses to return to the main menu (Option 2).
                  This signals the termination of the transaction loop.
        """
        menu_mapper = {1: True, 2: None}

        key = "options"
        user_in = get_single_input(
            key, self._transaction_config, self._controller_validator_cb
        )
        user_in = _assert_input(user_in, int)
        return menu_mapper[user_in]

    def run_controller(self) -> None:
        """
        Main execution loop for the transaction session.

        Manages the cycle of access validation and financial operations.
        If an operation is aborted (UserAbortError), the loop terminates immediately,
        returning control to the main application menu.

        Flow:
        1. Validate Access (Password check via _access_loop).
        2. Execute Operation (Deposit, Withdraw, or Statement).
        3. Determine next step (Continue, Logout, or Exit System).
        """
        accessed = False

        while True:
            try:
                if accessed is False:
                    accessed = self._access_loop()
                elif accessed is None:
                    views.controller_output("general", "exit")
                    break
                elif accessed is True:
                    self._operation_flow()
                    accessed = self._select_operation()
                    if accessed is None:
                        views.controller_output("general", "exit")
                        break
            except UserAbortError:
                views.controller_output("general", "exit")
                break


class BankSystemController(BaseController[Bank, None]):

    _validation_mapper = {
        "cpf": boolean_validator_dec(validate_cpf),
        "password": boolean_validator_dec(Bank.validate_password),
        "operations": boolean_validator_dec(
            partial(verify.verify_interval, min_val=1, max_val=2)
        ),
        "transactions": boolean_validator_dec(
            partial(verify.verify_interval, min_val=1, max_val=3)
        ),
        "management": boolean_validator_dec(
            partial(verify.verify_interval, min_val=1, max_val=3)
        ),
        "acc_type": boolean_validator_dec(
            partial(verify.verify_interval, min_val=1, max_val=2)
        ),
        "birth_date": boolean_validator_dec(Person.validate_birth_date),
        "use_card": boolean_validator_dec(
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
        Initializes the BankSystemController.

        Sets up the connection to the Bank 'Model', validates the Persistence
        Repository using Duck Typing, loads system configurations, and initializes
        session state (Token/Card) as empty.

        Args:
            bank_instance (Bank): The main banking system instance (Model).
            repository (Any): A Class or Object responsible for data persistence.
                              Must implement 'save(bank)' and 'load(data)'.

        Raises:
            TypeError: If the bank_instance is not a Bank or if the repository
                       does not fulfill the required interface contract.
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

        self._controller_validator_cb = partial(
            validate_entry, validation_mapper=self._validation_mapper
        )
        self._client = None
        self._active_auth_token = None
        self._active_access_token = None
        self._active_card = None

    def __repr__(self) -> str:
        class_name = type(self).__name__

        token_status = "Logged In" if self._active_auth_token else "Logged Out"
        card_status = "Card Inserted" if self._active_card else "No Card"

        return (
            f"{class_name}("
            f"connected_to={self._bank_instance.bank_name!r}"
            f"session_status={token_status!r}"
            f"hardware_status={card_status!r})"
        )

    @property
    def _active_client(self):
        if self._client is None:
            raise RuntimeError("Getter called without an Client instance")

        return self._client

    def _prompt_new_password(self) -> str:
        while True:
            views.controller_output("update_password", "1")
            raw_pwd_1 = get_single_input(
                "password", self._auth_config, self._controller_validator_cb
            )
            pwd_1 = _assert_input(raw_pwd_1, str)

            views.controller_output("update_password", "2")
            raw_pwd_2 = get_single_input(
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
        client_cpf = get_single_input(
            "cpf", config.identification_config, self._controller_validator_cb
        )
        client_cpf = _assert_input(client_cpf, str)
        return client_cpf

    def _end_session(self) -> None:
        self._client = None
        self._active_card = None
        self._active_auth_token = None
        self._active_access_token = None

    def _get_client(self) -> Client:
        cpf = self._prompt_cpf()
        return self._bank_instance.get_registered_client(cpf)

    def _authenticate_client(self) -> AuthToken:

        if not self._active_card:
            user_inputs = config_loop(
                self._auth_config,
                self._controller_validator_cb,
                skip_fields=["card", "cpf"],
            )
            branch_code = _assert_input(user_inputs["branch_code"], str)
            account_num = _assert_input(user_inputs["account_num"], str)
        else:
            branch_code = self._active_card.branch_code
            account_num = self._active_card.account_num

        return self._bank_instance.authenticate(
            self._active_client, branch_code, account_num
        )

    def _select_card(self) -> AccountCard:
        client_cards = self._active_client.cards
        views.show_cards(client_cards)

        def local_validator_cb(field: str, user_in_raw: InputType) -> CallbackReturn:
            user_in = _assert_input(user_in_raw, int)
            return {"result": 0 <= user_in < len(client_cards)}

        card_idx_raw = get_single_input("card", self._auth_config, local_validator_cb)
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

        use_card_raw = get_single_input(
            "use_card",
            self._menu_config,
            self._controller_validator_cb,
        )
        use_card_int = _assert_input(use_card_raw, int)
        use_card = use_card_mapper[use_card_int]

        return use_card

    def _ensure_authentication(self) -> None:
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
        if not self._active_auth_token:
            raise RuntimeError("AuthToken is needed to get vault access")

        attempts_left = self._bank_instance.get_remaining_login_attempts(
            self._active_auth_token
        )

        for attempt in range(attempts_left, 0, -1):
            if attempt == 1:
                views.controller_output(mapper_key="access", inner_key="last")

            raw_password = get_single_input(
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

    def _update_password(self) -> None:
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
        if self._active_auth_token is None:
            raise RuntimeError("AuthToken required to perform the operation")

        raw_birth_date = get_single_input(
            "birth_date", self._identification_config, self._controller_validator_cb
        )
        new_password = self._prompt_new_password()

        birth_date_str = _assert_input(raw_birth_date, str)
        birth_date = date.strptime(birth_date_str, "%d/%m/%Y")

        try:
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
        except BankPasswordError as e:
            raise RuntimeError("Critical error in I/O logic") from e

    def _close_account(self) -> None:
        if self._active_access_token is None:
            raise RuntimeError("AccessToken is required to close an account")

        if (
            self._active_access_token.branch_code
            != self._bank_instance.bank_branch_code
        ):
            views.controller_output("close_account", False)
            raise ControllerOperationError

        account = self._bank_instance.get_account(self._active_access_token)

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
        controller_obj = TransactionController(
            self._bank_instance,
            self._transaction_config,
            transaction_type,
            self._active_access_token,
        )
        return controller_obj

    def _ensure_credentials(self, operation: TransactionType | ManagementType) -> None:
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

    def _set_create_client(self, cpf: str) -> CreationController:
        new_client_config = self._identification_config.copy()
        new_client_config.pop("cpf")
        filled_data = {"cpf": cpf}

        controller_obj = CreationController(
            Client, PERSON_ERROR_MAP, new_client_config, filled_data
        )

        return controller_obj

    def _set_create_account(self) -> CreationController:
        acc_type_mapper = {1: CheckingAccount, 2: SavingsAccount}
        new_acc_config = self._new_acc_config.copy()

        user_in = get_single_input(
            "acc_type", self._new_acc_config, self._controller_validator_cb
        )
        int_user_in = _assert_input(user_in, int)
        model_class = acc_type_mapper[int_user_in]
        new_acc_config.pop("acc_type")

        filled_data = {"branch_code": self._bank_instance.bank_branch_code}

        controller_obj = CreationController(
            model_class, ACCOUNT_ERROR_MAP, new_acc_config, filled_data
        )

        return controller_obj

    def _onboarding_workflow(self) -> None:
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
        try:
            transaction_option = get_single_input(
                "transactions", self._menu_config, self._controller_validator_cb
            )
            transaction = TransactionType(transaction_option)
            self._ensure_credentials(transaction)
            controller_obj = self._set_transaction_controller(transaction)
            controller_obj.run_controller()
        except UserAbortError:
            views.controller_output("menu", "cancel")
            return
        except ControllerCredentialsError:
            views.controller_output("menu", "credentials")
            return
        except ControllerOperationError:
            return

    def _management_menu(self) -> None:
        try:
            management_option = get_single_input(
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
        except ControllerCredentialsError:
            views.controller_output("menu", "credentials")
            return
        except ControllerOperationError:
            return

    def _main_menu(self) -> MainMenuType | None:
        is_admin_code = None

        def _main_menu_validator_cb(
            field: str, user_input: InputType
        ) -> CallbackReturn:
            nonlocal is_admin_code

            int_user_input = _assert_input(user_input, int)
            is_valid_menu = int_user_input in (1, 2)
            is_admin_code = user_input == ADMIN_EXIT_CODE

            return {"result": is_valid_menu or is_admin_code}

        main_option = get_single_input(
            "main_menu", self._menu_config, _main_menu_validator_cb
        )

        if is_admin_code:
            views.bye()
            return None

        return MainMenuType(main_option)

    def _operation_hub(self) -> None:
        while True:
            try:
                raw_operation = get_single_input(
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
            except BankSecurityError:
                self._end_session()
                views.controller_output("menu", "security")
                return

    def run_controller(self) -> None:
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
