"""Authentication and access authorization application service.

This module provides the core authentication workflows for the banking application,
orchestrating identity verification across primary (Lobby) and elevated (Vault) security
tiers. It handles session token generation, brute-force mitigation, state updates, and
atomic account freeze enforcement in coordination with infrastructure protocols.
"""

from typing import ClassVar

from application.dtos import CheckDataDTO, VaultAccessDTO
from application.protocols import (
    HasherProtocol,
    RepositoryProtocol,
    TokenServiceProtocol,
)
from application.services.base_service import BaseApplicationService
from domain.account import Account
from domain.account_holder import AccountHolder
from domain.value_objects import CPF, AccountNumber, BranchCode, Password
from shared import verify
from shared.credentials import AccessToken, AccountCard, AuthToken
from shared.exceptions import (
    AccessDeniedError,
    AccountHolderNotFoundError,
    AccountStateTransitionError,
    AuthenticationError,
    DataNotFoundError,
    RepositoryError,
    ServiceUnavailableError,
)

# =====================================================================
# AuthService
# =====================================================================


class AuthService(BaseApplicationService):
    """Application Service responsible for managing user authentication workflows.

    Acts as the entry point in the Application layer for managing identity verification
    for both low-security Lobby access and high-security Vault authorization. It manages
    session token generation, failed attempt tracking, and automatic account freeze
    enforcement within ACID-compliant database boundaries.

    Attributes:
        _hasher (HasherProtocol): The cryptographic hashing interface inherited from BaseApplicationService.
        _repository (RepositoryProtocol): The persistence interface inherited from BaseApplicationService.
        _token_service (TokenServiceProtocol): The stateless session token management interface.
    """

    # --------------------------------------------------------------------------
    # Class attributes
    # --------------------------------------------------------------------------
    MAX_LOGIN_ATTEMPTS: ClassVar[int] = 3

    # --------------------------------------------------------------------------
    # Constructor
    # --------------------------------------------------------------------------
    def __init__(
        self,
        hasher: HasherProtocol,
        repository: RepositoryProtocol,
        token_service: TokenServiceProtocol,
    ) -> None:
        """Initializes the AuthService with required infrastructure protocols.

        Args:
            hasher (HasherProtocol): Cryptographic password hashing interface.
            repository (RepositoryProtocol): Database interaction interface.
            token_service (TokenServiceProtocol): Session token validation interface.
        """
        super().__init__(hasher=hasher, repository=repository)

        self._token_service = token_service

    # --------------------------------------------------------------------------
    # Dunder methods
    # --------------------------------------------------------------------------
    def __repr__(self) -> str:
        """Returns an unambiguous string representation of the AuthService instance.

        Useful for debugging and system logging, capturing internal protocol dependencies.

        Returns:
            str: Developer-targeted string representation of the service.
        """
        base_repr = super().__repr__()
        class_repr = base_repr[:-1] + f", token_service={self._token_service!r})"

        return class_repr

    # --------------------------------------------------------------------------
    # Public API
    # --------------------------------------------------------------------------
    def get_account_holder_cards(self, dto: CheckDataDTO) -> list[AccountCard]:
        """Safely retrieves registered account cards for a verified account holder.

        Acts as an application query boundary, extracting lightweight card projection
        data from the hydrated AccountHolder entity to prevent domain leakage to the
        presentation layer.

        Args:
            dto (CheckDataDTO): DTO containing the account holder's CPF.

        Returns:
            list[AccountCard]: Immutable list of account cards associated with the holder.

        Raises:
            TypeError: If the provided DTO is of an invalid type.
            RuntimeError: If the DTO is missing required parameters (CPF) or contains
                a CPF string that violates Domain VO invariants.
            AccountHolderNotFoundError: If the provided CPF is not registered in the system.
        """
        verify.verify_instance(dto, CheckDataDTO)

        if not dto.holder_cpf:
            raise RuntimeError("Method called without mandatory CPF attribute")

        cpf = self._instantiate_vo(CPF, dto.holder_cpf)

        holder = self._get_account_holder(cpf)
        return holder.cards

    def authenticate(self, dto: CheckDataDTO) -> AuthToken:
        """Authenticates an account holder's claim to an account and issues a primary token.

        Orchestrates primary "Lobby" access verification without opening the secure vault.
        Bypasses full entity hydration by leveraging database projections for read-only throughput.

        Args:
            dto (CheckDataDTO): DTO containing client CPF and account identification (branch/account).

        Returns:
            AuthToken: A securely signed primary authentication token for session tracking.

        Raises:
            TypeError: If the provided DTO is of an invalid type.
            RuntimeError: If required attributes (CPF or Account state) are missing from the DTO
                or fail Domain VO invariants.
            AuthenticationError: If the account does not exist or does not belong to the holder.
        """
        verify.verify_instance(dto, CheckDataDTO)

        if not dto.holder_cpf or not dto.account:
            raise RuntimeError("Cannot authenticate with missing CPF or Account data")

        branch_code = self._instantiate_vo(BranchCode, dto.account.branch_code)
        account_num = self._instantiate_vo(AccountNumber, dto.account.account_num)
        cpf = self._instantiate_vo(CPF, dto.holder_cpf)

        try:
            account_info = self._repository.get_account_projection(
                branch_code, account_num, holder_info=True
            )
        except DataNotFoundError:
            raise AuthenticationError(
                "Authentication failed: Account not found in system register"
            )

        holder_info = account_info.unwrap_holder()

        if holder_info.cpf != cpf.value:
            raise AuthenticationError(
                "Authentication failed: Account not linked to this client"
            )

        return self._token_service.generate_auth_token(
            cpf=cpf.value, branch_code=branch_code.value, account_num=account_num.value
        )

    def get_remaining_login_attempts(self, auth_token: AuthToken) -> int:
        """Calculates remaining vault authentication attempts for an active session.

        Allows the presentation layer to query remaining security attempts and synchronize
        UI warnings prior to triggering automated account blockages.

        Args:
            auth_token (AuthToken): Active primary authentication token.

        Returns:
            int: Remaining allowed attempts before account freezing (0 to MAX_LOGIN_ATTEMPTS).

        Raises:
            TypeError: If the provided token is not an AuthToken instance.
            ExpiredTokenError: If the primary token TTL has expired.
            TokenSecurityError: If token signature verification fails.
            AuthenticationError: If the account no longer exists in persistence.
            RuntimeError: If token claims fail Domain VO invariants.
        """
        verify.verify_instance(auth_token, AuthToken)
        self._token_service.validate_token_integrity(auth_token)

        branch_code = self._instantiate_vo(BranchCode, auth_token.branch_code)
        account_num = self._instantiate_vo(AccountNumber, auth_token.account_num)

        try:
            account_info = self._repository.get_account_projection(
                branch_code, account_num, access_info=True
            )
        except DataNotFoundError as e:
            raise AuthenticationError("Account no longer exists") from e

        access_info = account_info.unwrap_access()
        return max(0, self.MAX_LOGIN_ATTEMPTS - access_info.failed_attempts)

    def authorize_vault_access(self, dto: VaultAccessDTO) -> AccessToken:
        """Executes the Vault Authentication Protocol to elevate session privileges.

        Upgrades a primary Lobby session (AuthToken) into full Vault access (AccessToken).
        Orchestrates token validation, password verification against secure hashes, and atomic
        security state updates within a single transactional Unit of Work.

        Employs pessimistic locking to eliminate TOCTOU race conditions during attempt
        counters updates and account freezing.

        Args:
            dto (VaultAccessDTO): DTO encapsulating the raw password and current AuthToken.

        Returns:
            AccessToken: Elevated cryptographic token granting access to sensitive features.

        Raises:
            TypeError: If the provided DTO is of an invalid type.
            RuntimeError: If DTO or token payload attributes violate Domain VO invariants.
            ExpiredTokenError: If the provided AuthToken has expired.
            TokenSecurityError: If token integrity verification fails.
            AccessDeniedError: If the account is already frozen or becomes frozen due to brute-force protection.
            AuthenticationError: If password verification fails or account does not exist.
            ServiceUnavailableError: If security state mutations cannot be transactionally persisted.
        """
        verify.verify_instance(dto, VaultAccessDTO)

        self._token_service.validate_token_integrity(dto.auth_token)
        auth_token = dto.auth_token

        branch_code = self._instantiate_vo(BranchCode, auth_token.branch_code)
        account_num = self._instantiate_vo(AccountNumber, auth_token.account_num)
        password = self._instantiate_vo(Password, dto.password)

        try:
            with self._repository.unit_of_work():
                account_info = self._repository.get_account_projection(
                    branch_code,
                    account_num,
                    access_info=True,
                    for_update=True,
                )

                if account_info.is_frozen:
                    raise AccessDeniedError(
                        "This account is blocked and cannot be accessed"
                    )

                access_info = account_info.unwrap_access()

                if self._hasher.check_password(
                    password.value, access_info.password_hash
                ):
                    return self._login_success_route(
                        auth_token,
                        (branch_code, account_num),
                        access_info.password_hash,
                        access_info.failed_attempts,
                    )

                exception_to_raise = self._login_failed_route(
                    (branch_code, account_num),
                    access_info.failed_attempts,
                    password.value,
                )

            raise exception_to_raise
        except DataNotFoundError as e:
            raise AuthenticationError(
                "Authentication failed: Account no longer exists"
            ) from e
        except RepositoryError as e:
            raise ServiceUnavailableError(
                "The intended operation could not be persisted due to an internal error"
            ) from e

    # --------------------------------------------------------------------------
    # Protected methods (Internal Helpers - Trust Zone)
    # --------------------------------------------------------------------------
    def _get_account_holder(self, cpf: CPF) -> AccountHolder:
        """Hydrates an AccountHolder domain entity from persistence via snapshot.

        Args:
            cpf (CPF): The value object representing the target account holder's CPF.

        Returns:
            AccountHolder: Hydrated domain aggregate root.

        Raises:
            AccountHolderNotFoundError: If no holder matches the given CPF.
        """
        try:
            holder_db_snap = self._repository.get_holder_snapshot(cpf=cpf)
            return AccountHolder.from_snapshot(holder_db_snap)
        except DataNotFoundError as e:
            raise AccountHolderNotFoundError(
                "No account holder registered under this CPF"
            ) from e

    def _login_success_route(
        self,
        auth_token: AuthToken,
        branch_and_acc_num: tuple[BranchCode, AccountNumber],
        password_hash: str,
        failed_attempts: int,
    ) -> AccessToken:
        """Handles successful vault authorization state transitions within an active Unit of Work.

        Resets failed login counters in persistence if needed and issues the AccessToken.

        Args:
            auth_token (AuthToken): Active primary authentication token.
            branch_and_acc_num (tuple[BranchCode, AccountNumber]): Target account coordinate tuple.
            password_hash (str): Stored password hash for token payload generation.
            failed_attempts (int): Current counter of recorded failed attempts.

        Returns:
            AccessToken: Elevated access token.
        """
        branch_code, account_num = branch_and_acc_num

        if failed_attempts:
            self._repository.reset_login_attempts(branch_code, account_num)

        return self._token_service.generate_access_token(
            auth_token=auth_token, pwd_hash=password_hash
        )

    def _login_failed_route(
        self,
        branch_and_acc_num: tuple[BranchCode, AccountNumber],
        failed_attempts: int,
        password: str,
    ) -> AccessDeniedError | AuthenticationError:
        """Applies security mitigations for failed vault login attempts within an active Unit of Work.

        Executes the 'Return Exception' pattern to ensure state updates (incrementing counters
        or freezing account) are committed before raising the domain error to the caller.

        Args:
            branch_and_acc_num (tuple[BranchCode, AccountNumber]): Target account coordinate tuple.
            failed_attempts (int): Prior count of recorded failures.
            password (str): The invalid password attempted.

        Returns:
            AccessDeniedError | AuthenticationError: Exception object ready to be raised post-commit.

        Raises:
            RuntimeError: If the account aggregate fails its state transition during freezing.
        """
        branch_code, account_num = branch_and_acc_num

        self._repository.register_failed_login(branch_code, account_num)

        if (failed_attempts + 1) >= self.MAX_LOGIN_ATTEMPTS:
            account_db_snap = self._repository.get_account_snapshot(
                branch_code,
                account_num,
                for_update=True,
            )
            account = Account.from_snapshot(account_db_snap)

            try:
                account.freeze()
            except AccountStateTransitionError as e:
                raise RuntimeError("Inconsistent Account state") from e

            account_snap = account.to_snapshot()
            self._repository.update_account_status(account_snap)
            return AccessDeniedError(
                "The account was frozen due to 3 consecutive failed login attempts"
            )

        return AuthenticationError(
            "Login failed. Password doesn't match", argument=password
        )
