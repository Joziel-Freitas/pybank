"""Module containing the TerminalController.

Acts as the primary orchestrator and entry point for the PyBank Presentation Layer.
Manages the global terminal session lifecycle, state machine transitions between
Lobby and Vault environments, and routes user menu intents to specialized sub-controllers.
"""

from functools import partial

from application.services.account_management_service import AccountManagementService
from presentation.cli import config, io_utils, views
from presentation.controllers.account_management_controller import (
    AccountManagementController,
)
from presentation.controllers.auth_controller import AuthController
from presentation.controllers.banking_operations_controller import (
    BankingOperationsController,
)
from presentation.controllers.base_controller import BaseController
from presentation.controllers.onboarding_controller import OnboardingController
from presentation.dtos import ServiceContainerDTO
from presentation.types import (
    MainMenuType,
    OperationMenuType,
    RestrictedMenuType,
    TransactionMenuType,
)
from shared.credentials import AccessToken, AuthToken
from shared.exceptions import (
    AdminExitError,
    ApplicationSecurityError,
    AuthenticationError,
    ControllerCredentialsError,
    ControllerOperationError,
    ControllerRegisterError,
    InactiveUserError,
    ServiceUnavailableError,
    UserAbortError,
)
from shared.projections import SummaryProjectionDTO


class TerminalController(BaseController[AccountManagementService]):
    """Orchestrates the ATM Kiosk, managing session lifecycles and state boundaries.

    Maintains three distinct execution layers:
    - Kiosk Loop (run_controller): Infinite public loop handling global exceptions
      and graceful terminal resets.
    - Lobby State Machine (_lobby_hub): Authenticated client environment backed by an AuthToken.
    - Vault State Machine (_vault_hub): High-security clearance layer requiring an AccessToken.
    """

    # --------------------------------------------------------------------------
    # Constructor
    # --------------------------------------------------------------------------
    def __init__(
        self,
        services: ServiceContainerDTO,
    ) -> None:
        """Initializes the TerminalController with application services and session state.

        Args:
            services (ServiceContainerDTO): Container object holding all active
                application service instances injected by the composition root.
        """
        super().__init__(services.account_management_service)

        self._services = services
        self._config_mapper = config.menu_config
        self._auth_token: AuthToken | None = None
        self._access_token: AccessToken | None = None

    # --------------------------------------------------------------------------
    # Dunder methods
    # --------------------------------------------------------------------------
    def __repr__(self) -> str:
        """Returns diagnostic representation of the controller's active session state.

        Returns:
            str: String representation containing active session clearance details.
        """
        class_name = type(self).__name__
        has_auth = self._auth_token is not None
        has_access = self._access_token is not None
        return f"{class_name}(authenticated={has_auth}, vault_access={has_access})"

    # --------------------------------------------------------------------------
    # Public API (Orchestrator Entrypoint)
    # --------------------------------------------------------------------------
    def run_controller(self) -> None:
        """The Kiosk Loop.

        The absolute entry point of the presentation layer. It maintains an infinite
        loop, acting as the Global Exception Handler, ensuring the terminal always
        returns to the Welcome Screen gracefully, regardless of successful operations,
        user cancellations, or unhandled infrastructure exceptions.
        """
        while True:
            try:
                menu = self._main_menu()
            except AdminExitError:
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
                ServiceUnavailableError,
                ControllerOperationError,
                ControllerRegisterError,
            ) as e:
                self._handle_exception_ui("errors", e)

    # --------------------------------------------------------------------------
    # Protected methods (High-to-Low Abstraction Flow)
    # --------------------------------------------------------------------------
    def _main_menu_router(self, menu_type: MainMenuType) -> None:
        """Routes the primary terminal options down to dedicated operational units.

        Args:
            menu_type (MainMenuType): The captured root menu operational intent.

        Raises:
            RuntimeError: If an unmapped or invalid menu enumeration reaches the router.
        """
        match menu_type:
            case MainMenuType.DEPOSIT:
                self._run_banking_operations_controller(TransactionMenuType.DEPOSIT)
            case MainMenuType.ONBOARDING:
                OnboardingController(self._services.onboarding_service).run_controller()
            case MainMenuType.OPERATIONS:
                self._lobby_hub()
            case _:
                raise RuntimeError("Critical error: Unmapped type")

    def _lobby_hub(self) -> None:
        """The authenticated environment loop (Lobby State Machine).

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
                operation = self._prompt_operation(account_summary)
                if operation:
                    if (
                        isinstance(operation, OperationMenuType)
                        and operation != OperationMenuType.DEPOSIT
                    ):
                        self._vault_hub()

                    self._dispatch_operation(operation)

                if not operation or operation == OperationMenuType.WITHDRAWAL:
                    self._end_session()
            except UserAbortError:
                self._handle_info_ui("info", "user_cancel", wait=True)
                continue
            except InactiveUserError:
                self._end_session()
            except ControllerOperationError as e:
                self._handle_exception_ui("errors", e)
                continue
            except ServiceUnavailableError:
                self._end_session()
                raise
            except (
                AuthenticationError,
                ControllerCredentialsError,
                ApplicationSecurityError,
            ) as e:
                self._end_session()
                self._handle_exception_ui("errors", e)

    def _vault_hub(self) -> None:
        """The routing endpoint for Vault-level operations.

        Demands an active AccessToken to execute sensitive operations
        (Withdrawal, Statement, Change Password, Close Account). If the
        current session is restricted to basic Lobby access, it dynamically
        upgrades the session state to full Vault access before dispatching
        the requested operation.

        Raises:
            TypeError: If the authentication service fails to return a valid AccessToken.
        """
        if not self._access_token:
            token = self._run_auth_controller()

            if not isinstance(token, AccessToken):
                raise TypeError(f"Expected AccessToken, got: {type(token).__name__}")

            self._transition_to_vault(token)

    def _initialize_lobby_session(self) -> SummaryProjectionDTO | None:
        """Executes the atomic handshake protocol to establish a Lobby session.

        This helper orchestrates the sequential authentication of a client:
        1. Prompts for credentials (hardware card or manual indices).
        2. Signs and registers the AuthToken inside the application state.
        3. Fetches a lightweight, non-financial projection (SummaryProjectionDTO).
        4. Triggers the personalized client greeting.

        Returns:
            SummaryProjectionDTO | None: The active session's summary data if the
                handshake is successful; None if authentication or validation fails.
        """
        try:
            token = self._run_auth_controller()

            if not isinstance(token, AuthToken):
                raise TypeError(f"Expected AuthToken, got: {type(token).__name__}")

            self._transition_to_lobby(token)
            summary = self._service.get_account_summary(token)
            self._greet_user(summary)
            return summary
        except (
            AuthenticationError,
            ControllerCredentialsError,
            ApplicationSecurityError,
        ) as e:
            self._auth_token = None
            self._handle_exception_ui("errors", e)
            return None

    def _prompt_operation(
        self, account_summary: SummaryProjectionDTO
    ) -> OperationMenuType | RestrictedMenuType | None:
        """Orchestrates a single, isolated execution loop of an ATM option.

        Captures user navigation choices, dynamically evaluating if the target
        account status is operational or frozen (presenting the appropriate
        menu).

        Args:
            account_summary (SummaryProjectionDTO): The current cached state
                projection of the active account session.

        Returns:
            OperationMenuType | RestrictedMenuType | None: The evaluated action
                taken by the user; None if the user explicitly aborts/cancels prompt.
        """
        try:
            if account_summary.is_frozen:
                return self._restrict_operations_menu(account_summary)
            return self._operations_menu()
        except UserAbortError:
            self._handle_info_ui("info", "user_cancel", wait=True)
            return None

    def _dispatch_operation(
        self, operation: OperationMenuType | RestrictedMenuType
    ) -> None:
        """Routes the selected menu operation to its corresponding execution flow.

        Acts as a pure command dispatcher, delegating execution to specific sub-controllers
        assuming all necessary security clearances (Lobby or Vault) have already been verified.

        Args:
            operation (OperationMenuType | RestrictedMenuType): The authorized operation to execute.

        Raises:
            RuntimeError: If the provided operation type is unmapped.
        """
        match operation:
            case RestrictedMenuType.UNFREEZE_ACCOUNT:
                self._run_account_management_controller(operation)
            case OperationMenuType.DEPOSIT:
                self._run_banking_operations_controller(TransactionMenuType.DEPOSIT)
            case OperationMenuType.WITHDRAWAL:
                self._run_banking_operations_controller(TransactionMenuType.WITHDRAWAL)
            case OperationMenuType.TRANSFER:
                self._run_banking_operations_controller(TransactionMenuType.TRANSFER)
            case OperationMenuType.STATEMENT:
                self._run_banking_operations_controller(TransactionMenuType.STATEMENT)
            case OperationMenuType.CHANGE_PASSWORD | OperationMenuType.CLOSE_ACCOUNT:
                self._run_account_management_controller(operation)
            case _:
                raise RuntimeError(f"Critical error: Unmapped operation '{operation}'")

    def _operations_menu(self) -> OperationMenuType:
        """Shows the standard UI operations menu.

        Returns:
            OperationMenuType: The evaluated valid operation menu state selection.
        """
        user_in = io_utils.get_user_input(
            self._config_mapper["operations_menu"], int, OperationMenuType
        )
        return user_in

    def _restrict_operations_menu(
        self, acc_summary: SummaryProjectionDTO
    ) -> RestrictedMenuType:
        """Shows the specific UI menu for frozen/blocked accounts.

        Args:
            acc_summary (SummaryProjectionDTO): The current cached state summary object.

        Returns:
            RestrictedMenuType: The mapped target selection index enum.
        """
        acc_type_map = {
            "CheckingAccount": "Conta corrente",
            "SavingsAccount": "Conta poupança",
        }
        acc_type = acc_type_map[acc_summary.account_type]

        user_in = io_utils.get_user_input(
            self._config_mapper["restricted_menu"],
            int,
            RestrictedMenuType,
            loop_header=partial(
                self._handle_info_ui,
                context_key="info",
                info_key="lobby_restrict",
                acc_type=acc_type,
            ),
        )

        return user_in

    def _run_auth_controller(self) -> AccessToken | AuthToken:
        """Instantiates and executes the AuthController.

        Returns:
            AccessToken | AuthToken: Signed session token matching requested clearance level.
        """
        return AuthController(
            self._services.auth_service, self._auth_token
        ).run_controller()

    def _run_account_management_controller(
        self, operation: OperationMenuType | RestrictedMenuType
    ) -> None:
        """Delegates account management routines to AccountManagementController.

        Args:
            operation (OperationMenuType | RestrictedMenuType): Target action enum.

        Raises:
            RuntimeError: If invoked without at least a primary AuthToken in memory.
        """
        token = self._access_token or self._auth_token

        if not token:
            raise RuntimeError("Management operations require at least an AuthToken")

        AccountManagementController(
            self._services.account_management_service, token, operation
        ).run_controller()

    def _run_banking_operations_controller(
        self, transaction_type: TransactionMenuType
    ) -> None:
        """Delegates financial transaction logic to BankingOperationsController.

        Args:
            transaction_type (TransactionMenuType): The explicit target sub-context enum.
        """
        BankingOperationsController(
            self._services.banking_service,
            transaction_type,
            self._access_token or self._auth_token,
        ).run_controller()

    def _main_menu(self) -> MainMenuType:
        """Displays the root entry point of the ATM.

        Includes a hidden verification for the ADMIN_EXIT_CODE inside io_utils
        to safely shut down the terminal application.

        Returns:
            MainMenuType: The selected root menu option.
        """
        user_in = io_utils.get_user_input(
            self._config_mapper["main_menu"],
            int,
            MainMenuType,
            loop_header=views.welcome,
            use_timeout=False,
        )

        return user_in

    def _greet_user(self, account_summary: SummaryProjectionDTO) -> None:
        """Extracts the account holder's first name and dispatches the welcome UI.

        Args:
            account_summary (SummaryProjectionDTO): The current state data context.
        """
        first_name = account_summary.holder_name.split()[0]

        self._handle_info_ui(
            "info",
            "lobby_hello",
            clean=True,
            user_name=first_name,
        )

    def _transition_to_lobby(self, token: AuthToken) -> None:
        """Transitions the session state to the authenticated Lobby environment.

        Args:
            token (AuthToken): The valid verified token instance object.
        """
        self._auth_token = token

    def _transition_to_vault(self, token: AccessToken) -> None:
        """Upgrades the session state to the secure Vault environment.

        Args:
            token (AccessToken): The high-clearance cryptographically generated token.

        Raises:
            RuntimeError: If called without active prerequisite lobby tokens in memory.
        """
        if not self._auth_token:
            raise RuntimeError(
                "Cannot transition to Vault without an active Lobby session."
            )

        self._access_token = token

    def _end_session(self) -> None:
        """Purges all sensitive data and tokens from memory, resetting the terminal.

        Acts as a strict security teardown routine.
        """
        self._auth_token = None
        self._access_token = None
