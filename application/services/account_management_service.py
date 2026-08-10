"""Application Service for account lifecycle and administration workflows.

This module exposes the `AccountManagementService` class, which serves as an
application-layer orchestrator for administrative operations, including security
credential updates, frozen account recovery, and permanent account closure.
"""

from application.dtos import UnfreezeAccountDTO, UpdatePasswordDTO
from application.protocols import (
    HasherProtocol,
    RepositoryProtocol,
    TokenServiceProtocol,
)
from application.services.base_service import BaseApplicationService
from domain.account import Account
from shared import verify
from shared.credentials import AccessToken
from shared.exceptions import (
    AccessDeniedError,
    AccountAlreadyActiveError,
    AuthenticationError,
    DataNotFoundError,
    DeniedOperationError,
    FrozenAccountError,
    NotEmptyAccountError,
    RepositoryError,
    ServiceUnavailableError,
)

# =====================================================================
# AccountManagementService
# =====================================================================


class AccountManagementService(BaseApplicationService):
    """Application Service responsible for orchestrating account management workflows.

    Acts as the entry point in the Application layer for updating security credentials,
    recovering frozen accounts via secondary identity verification, and performing
    permanent account closures. Coordinates Domain entities (`Account`), delegates password
    hashing, enforces session security via `TokenServiceProtocol`, and ensures
    transactional consistency using `RepositoryProtocol.unit_of_work()`.

    Attributes:
        _hasher (HasherProtocol): The cryptographic hashing interface inherited from BaseApplicationService.
        _repository (RepositoryProtocol): The persistence interface inherited from BaseApplicationService.
        _token_service (TokenServiceProtocol): The stateless session token management interface.
    """

    # --------------------------------------------------------------------------
    # Constructor
    # --------------------------------------------------------------------------
    def __init__(
        self,
        hasher: HasherProtocol,
        repository: RepositoryProtocol,
        token_service: TokenServiceProtocol,
    ) -> None:
        """Initializes the AccountManagementService with required infrastructure protocols.

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
        """Returns an unambiguous string representation of the AccountManagementService instance.

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
    def update_password(self, dto: UpdatePasswordDTO) -> None:
        """Updates the account's password and forces an immediate session invalidation.

        Operates under a Zero Trust model, requiring full vault access (`AccessToken`)
        to authorize the change. Explicitly denies password updates for frozen
        accounts to maintain security boundaries.

        Employs an isolated Unit of Work with exclusive access control (`for_update=True`)
        to prevent race conditions. Because the `AccessToken` signature embeds the
        current password hash, updating the database password immediately invalidates
        the active token, requiring the client to re-authenticate for future operations.

        Args:
            dto (UpdatePasswordDTO): Command payload containing the AccessToken and proposed new password.

        Raises:
            TypeError: If dto is not an instance of UpdatePasswordDTO.
            ExpiredTokenError: If the token's TTL has passed.
            TokenSecurityError: If the token's cryptographic signature is invalid or tampered with.
            AuthenticationError: If the account no longer exists during the active session.
            AccessDeniedError: If the account is currently frozen, blocking credential updates.
            ServiceUnavailableError: If the update could not be persisted due to a repository error.
        """
        verify.verify_instance(dto, UpdatePasswordDTO)

        access_token = dto.access_token

        try:
            with self._repository.unit_of_work():
                account_info = self._repository.get_account_projection(
                    access_token.branch_code,
                    access_token.account_num,
                    access_info=True,
                    for_update=True,
                )

                access_info = account_info.unwrap_access()

                self._token_service.validate_token_integrity(
                    access_token, access_info.password_hash
                )

                if account_info.is_frozen:
                    raise AccessDeniedError(
                        "This account is frozen and cannot be accessed"
                    )
                hashed_pwd = self._hasher.generate_password_hash(dto.new_password)

                self._repository.update_password(
                    access_token.branch_code, access_token.account_num, hashed_pwd
                )
        except DataNotFoundError as e:
            raise AuthenticationError(
                "Authentication failed: Account no longer exists"
            ) from e
        except RepositoryError as e:
            raise ServiceUnavailableError(
                "The intended operation could not be persisted due to an internal error"
            ) from e

    def unfreeze_account(self, dto: UnfreezeAccountDTO) -> None:
        """Recovers and unfreezes a frozen account using secondary identity verification.

        Upgrades a basic authentication attempt into a recovery operation. Enforces
        strict state isolation (`unit_of_work` with `for_update=True`) to ensure the
        account cannot be mutated or deleted by concurrent processes during recovery.

        Verifies the holder's birth date against identity projections, hydrates the `Account`
        domain entity, delegates unfreezing to it, applies a new password, resets the login
        attempt counter, and persists the restored active state.

        Args:
            dto (UnfreezeAccountDTO): Command payload containing AuthToken, birth date, and new password.

        Raises:
            TypeError: If dto is not an instance of UnfreezeAccountDTO.
            ExpiredTokenError: If the token's TTL has passed.
            TokenSecurityError: If the token's cryptographic signature is invalid or tampered with.
            AuthenticationError: If the birth date is incorrect, or if the account/holder no longer exists.
            AccountAlreadyActiveError: If the account is already operational.
            ServiceUnavailableError: If the unfreeze operation could not be persisted due to a repository error.
        """
        verify.verify_instance(dto, UnfreezeAccountDTO)
        self._token_service.validate_token_integrity(dto.auth_token)

        auth_token = dto.auth_token

        try:
            with self._repository.unit_of_work():
                account_info = self._repository.get_account_projection(
                    auth_token.branch_code,
                    auth_token.account_num,
                    holder_info=True,
                    for_update=True,
                )

                if not account_info.is_frozen:
                    raise AccountAlreadyActiveError(
                        "Operational accounts cannot be unfrozen"
                    )

                holder_info = account_info.unwrap_holder()

                if holder_info.birth_date != dto.birth_date:
                    raise AuthenticationError(
                        "The given birth date doesn't match with registered birth date"
                    )

                new_hash = self._hasher.generate_password_hash(dto.new_password)

                self._repository.update_password(
                    auth_token.branch_code, auth_token.account_num, new_hash
                )
                self._repository.reset_login_attempts(
                    auth_token.branch_code, auth_token.account_num
                )
                account_db_snap = self._repository.get_account_snapshot(
                    auth_token.branch_code, auth_token.account_num, for_update=True
                )
                account = Account.from_snapshot(account_db_snap)
                account.unfreeze()
                account_snap = account.to_snapshot()
                self._repository.update_account_status(account_snap)
        except DataNotFoundError as e:
            raise AuthenticationError(
                "Authentication failed: Account no longer exists"
            ) from e
        except RepositoryError as e:
            raise ServiceUnavailableError(
                "The intended operation could not be persisted due to an internal error"
            ) from e

    def close_account(self, access_token: AccessToken) -> None:
        """Permanently closes and deletes an account from the system.

        Requires full vault access (`AccessToken`). Executes within an exclusive Unit of Work
        to lock the account state during evaluation. Hydrates the live `Account` entity and
        delegates closure validation to it:
        - Active Status Invariant: Frozen accounts cannot be closed.
        - Zero Balance Invariant: Accounts with non-zero balances cannot be closed.

        Upon successful domain closure, commands the repository to delete the account and
        triggers an automatic cleanup check to expunge orphaned holder PII records.

        Args:
            access_token (AccessToken): A valid, securely signed vault token.

        Raises:
            TypeError: If access_token is not an instance of AccessToken.
            ExpiredTokenError: If the token's TTL has passed.
            TokenSecurityError: If the token signature is invalid or tampered with.
            AuthenticationError: If the account no longer exists (TOCTOU mitigation).
            AccessDeniedError: If the account is frozen (translating FrozenAccountError).
            DeniedOperationError: If the account has a non-zero financial balance.
            ServiceUnavailableError: If account deletion fails due to a repository error.
        """
        verify.verify_instance(access_token, AccessToken)

        try:
            with self._repository.unit_of_work():
                account_info = self._repository.get_account_projection(
                    access_token.branch_code,
                    access_token.account_num,
                    access_info=True,
                    holder_info=True,
                    for_update=True,
                )

                access_info = account_info.unwrap_access()
                holder_info = account_info.unwrap_holder()

                self._token_service.validate_token_integrity(
                    access_token, access_info.password_hash
                )

                if account_info.is_frozen:
                    raise AccessDeniedError(
                        "This account is frozen and cannot be closed"
                    )

                account_db_snap = self._repository.get_account_snapshot(
                    access_token.branch_code, access_token.account_num
                )
                account_obj = Account.from_snapshot(account_db_snap)

                try:
                    account_obj.close()
                except FrozenAccountError as e:
                    raise AccessDeniedError(
                        "This account is frozen and cannot be closed"
                    ) from e
                except NotEmptyAccountError as e:
                    raise DeniedOperationError(
                        "Close account denied: Account has a non zero balance"
                    ) from e

                self._repository.delete_account(
                    access_token.branch_code, access_token.account_num
                )
                self._cleanup_unlinked_holder(holder_info.cpf)
        except DataNotFoundError as e:
            raise AuthenticationError(
                "Authentication failed: Account no longer exists"
            ) from e
        except RepositoryError as e:
            raise ServiceUnavailableError(
                "The intended operation could not be persisted due to an internal error"
            ) from e

    # --------------------------------------------------------------------------
    # Protected methods
    # --------------------------------------------------------------------------
    def _cleanup_unlinked_holder(self, cpf: str) -> None:
        """Enforces the data retention policy by evaluating an account holder's linkage status.

        Delegates to the repository abstraction to determine if the specified holder maintains
        any remaining active accounts. If the holder is entirely unlinked (orphaned), commands
        the repository to permanently remove their identity records from the system.

        Assumes execution within an active transactional boundary established by the caller.

        Args:
            cpf (str): The 11-digit string representing the account holder's CPF.

        Raises:
            DataNotFoundError: If the provided CPF does not exist in the persistence layer.
        """
        has_active_account = self._repository.holder_has_account(cpf)

        if not has_active_account:
            self._repository.delete_account_holder(cpf)
