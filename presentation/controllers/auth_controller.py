"""Module containing the AuthController.

Orchestrates user authentication workflows, bridging terminal identity prompts and card
selections with the AuthService to grant Lobby (AuthToken) or Vault (AccessToken) privileges.
"""

from functools import partial

from application import validators
from application.dtos import AccountDataDTO, CheckDataDTO, VaultAccessDTO
from application.services.auth_service import AuthService
from presentation.cli import config, io_utils, views
from presentation.controllers.base_controller import BaseController
from presentation.controllers.mixins import SharedPromptsMixin
from presentation.types import UserConfirmType
from shared.credentials import AccessToken, AccountCard, AuthToken
from shared.exceptions import (
    AccessDeniedError,
    AccountHolderNotFoundError,
    AuthenticationError,
    ControllerCredentialsError,
    InvalidPasswordError,
    UserAbortError,
)


class AuthController(
    BaseController[AuthService, AuthToken | AccessToken], SharedPromptsMixin
):
    """Controller responsible for orchestrating primary and elevated authentication workflows.

    Operates in a two-stage security model:
    - Lobby Gatekeeper (_ensure_lobby_access): Validates client CPF and account identification,
      issuing a primary AuthToken for low-sensitivity routing.
    - Vault Gatekeeper (_ensure_vault_access): Elevates an existing AuthToken to an AccessToken
      by validating vault passwords against secure cryptographic hashes, enforcing brute-force mitigations.
    """

    # --------------------------------------------------------------------------
    # Constructor
    # --------------------------------------------------------------------------
    def __init__(
        self, service: AuthService, auth_token: AuthToken | None = None
    ) -> None:
        """Initializes the AuthController with the authentication service and optional active token.

        Args:
            service (AuthService): The concrete application service managing authentication.
            auth_token (AuthToken | None, optional): An active primary session token. If provided,
                the controller immediately attempts Vault elevation. Defaults to None.
        """
        super().__init__(service)

        self._token = auth_token
        self._config_mapper = (
            config.auth_config | config.menu_config | config.identification_config
        )

    # --------------------------------------------------------------------------
    # Dunder methods
    # --------------------------------------------------------------------------
    def __repr__(self) -> str:
        """Returns the controller's runtime state and target authentication clearance level.

        Returns:
            str: Diagnostic representation containing the underlying AuthService
                and target authentication tier (Lobby-level or Vault-level).
        """
        class_name = type(self).__name__
        auth_level = "Vault-level" if self._token else "Lobby-level"

        return f"{class_name}(service={self._service!r}, auth_level={auth_level!r})"

    # --------------------------------------------------------------------------
    # Public API (Orchestrators)
    # --------------------------------------------------------------------------
    def run_controller(self) -> AuthToken | AccessToken:
        """Routes execution to Lobby authentication or Vault privilege elevation.

        Evaluates the internal token state: if an AuthToken already exists, it prompts for
        password authorization to return an AccessToken. Otherwise, it executes primary Lobby login.

        Returns:
            AuthToken | AccessToken: A signed session token matching the obtained clearance level.
        """
        if self._token:
            return self._ensure_vault_access()

        return self._ensure_lobby_access()

    # --------------------------------------------------------------------------
    # Protected methods (Auth Gatekeepers & Helpers)
    # --------------------------------------------------------------------------
    def _ensure_lobby_access(self) -> AuthToken:
        """The 'Lobby Door'. Ensures the session holds a valid AuthToken.

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

            token = self._service.authenticate(
                CheckDataDTO(
                    holder_cpf=cpf,
                    account=(
                        AccountDataDTO(branch_code=branch_code, account_num=account_num)
                    ),
                )
            )

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
            AuthenticationError,
        ) as e:
            self._handle_info_ui("errors", "auth_failed", wait=True, clean=True)
            raise ControllerCredentialsError from e

    def _ensure_vault_access(self) -> AccessToken:
        """The 'Vault Door'. Upgrades Lobby access to full Vault access.

        Requests the user's password, tracking remaining attempts, and dispatches
        to the AuthService for brute-force mitigation and cryptographic token upgrades.
        Routine authentication errors (wrong password) are caught and handled
        internally via a retry loop.

        Applies strict Zero Trust type checking on the domain's return value to
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
        if not self._token:
            raise RuntimeError(
                "An authentication token is required to attempt to gain access to the vault"
            )

        attempts_left = self._service.get_remaining_login_attempts(self._token)

        for attempt in range(attempts_left, 0, -1):
            if attempt == 1:
                self._handle_info_ui("info", "pwd_last_try", wait=True, clean=True)

            password = None
            try:
                password = io_utils.get_user_input(
                    self._config_mapper["password"], str, validators.validate_password
                )

                token = self._service.authorize_vault_access(
                    VaultAccessDTO(auth_token=self._token, password=password)
                )

                if not isinstance(token, AccessToken):
                    raise TypeError(
                        f"Invalid token instance. Expect type AccessToken, get {type(token).__name__}"
                    )

                return token
            except AuthenticationError as e:
                if e.argument is password:
                    self._handle_info_ui("info", "pwd_wrong", wait=True)
                    continue
                raise
            except AccessDeniedError as e:
                self._handle_exception_ui("errors", e)
                raise ControllerCredentialsError from e
            except InvalidPasswordError:
                raise RuntimeError("Critical error in I/O password validation logic")

        raise ControllerCredentialsError(
            "Credentials could not be validated because of an unknown error"
        )

    def _get_card(self, cpf: str) -> AccountCard | None:
        """Scans for physical token cards matching credentials to bypass manual parsing.

        Args:
            cpf (str): The verified individual holder query key string.

        Returns:
            AccountCard | None: The matching structural data object if selected;
                None if hardware lists return empty or manual strategies win.
        """
        cards = self._service.get_account_holder_cards(CheckDataDTO(holder_cpf=cpf))

        if cards:
            with_card = self._use_card_menu()

            if with_card:
                card = self._select_card(cards)
                return card

        return None

    def _get_account_identifiers(self) -> tuple[str, str]:
        """Gathers raw routing coordinates through terminal prompt loops.

        Returns:
            tuple[str, str]: A pair mapping branch_code and account_num indexes.
        """
        branch_code = io_utils.get_user_input(
            self._config_mapper["branch_code"], str, validators.validate_branch_code
        )
        account_num = io_utils.get_user_input(
            self._config_mapper["account_num"], str, validators.validate_account_num
        )

        return (branch_code, account_num)

    def _select_card(self, cards_list: list[AccountCard]) -> AccountCard:
        """Displays available hardware cards for the active client and prompts for selection.

        Args:
            cards_list (list[AccountCard]): Collection array of detected profile card records.

        Returns:
            AccountCard: The selected card object matching interaction indexes.
        """
        cards_list.sort(key=lambda card: (card.branch_code, card.account_num))

        expected_size = len(cards_list)
        validation_fn = lambda x: 0 <= x < expected_size
        cards_views: list[str] = [str(card) for card in cards_list]
        card_idx = io_utils.get_user_input(
            self._config_mapper["card"],
            int,
            validation_fn,
            loop_header=partial(views.show_cards, client_cards=cards_views),
        )

        return cards_list[card_idx]

    def _use_card_menu(self) -> bool:
        """Prompts the user to select the authentication strategy.

        Returns:
            bool: True if the user chooses to use a card, False for manual input.
        """
        user_in = io_utils.get_user_input(
            self._config_mapper["use_card_menu"], int, UserConfirmType
        )

        return user_in == UserConfirmType.YES
