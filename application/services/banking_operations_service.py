"""Application Service for core banking and financial operations.

This module exposes the `BankingOperationsService` class, which serves as an
application-layer orchestrator for read and write financial use cases, including
account summary retrieval, deposits, gatekept withdrawals, and statement generation.
"""

from collections.abc import Generator
from contextlib import contextmanager
from decimal import Decimal

from application.dtos import DepositDTO, StatementDTO, WithdrawalDTO
from application.protocols import (
    HasherProtocol,
    RepositoryProtocol,
    TokenServiceProtocol,
)
from application.services.base_service import BaseApplicationService
from domain.account import Account
from domain.value_objects import AccountNumber, BranchCode, Money, WithdrawalSimulation
from shared import verify
from shared.credentials import AccessToken, AuthToken
from shared.exceptions import (
    AccessDeniedError,
    AccountNotFoundError,
    AuthenticationError,
    DataNotFoundError,
    DeniedOperationError,
    ExpiredSessionError,
    ExpiredTokenError,
    FrozenAccountError,
    InsufficientFundsError,
    RepositoryError,
    ServiceUnavailableError,
    SessionIntegrityError,
    TokenSignatureError,
)
from shared.projections import StatementProjectionDTO, SummaryProjectionDTO

# =====================================================================
# BankingOperationsService
# =====================================================================


class BankingOperationsService(BaseApplicationService):
    """Application Service responsible for orchestrating financial banking operations.

    Acts as the entry point in the Application layer for querying account summaries,
    executing deposits, performing transactional gatekept withdrawals, and generating
    historical ledger statements. Coordinates Domain entities (`Account`), enforces
    security token verification via `TokenServiceProtocol`, and ensures transactional
    ACID boundaries using `RepositoryProtocol.unit_of_work()`.

    Attributes:
        _hasher (HasherProtocol): The cryptographic hashing interface inherited from BaseApplicationService.
        _repository (RepositoryProtocol): The persistence interface inherited from BaseApplicationService.
        _token_service (TokenServiceProtocol): The stateless token management interface.
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
        """Initializes the BankingOperationsService with required infrastructure protocols.

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
        """Returns an unambiguous string representation of the BankingOperationsService instance.

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

    def get_account_summary(
        self,
        token: AuthToken | AccessToken,
        request_financial: bool = False,
    ) -> SummaryProjectionDTO:
        """Safely retrieves identity and, conditionally, financial information for a session.

        Operates under a dual-layer security model. By default (Identity-First), it accepts
        a basic AuthToken to fetch non-sensitive routing data (Lobby access). If financial
        data is explicitly requested, the system escalates to a strict Zero Trust model:
        it demands an AccessToken, fetches the live password hash, validates cryptographic
        integrity, and completely hydrates the Account entity to ensure the returned
        financial truth (balances, limits, and accruals) is mathematically precise.

        Args:
            token (AuthToken | AccessToken): A stateless token proving account ownership.
                Must be an AccessToken if `request_financial` is True.
            request_financial (bool): Flag indicating if the presentation layer requires
                the mathematical resolution of the account's finances. Defaults to False.

        Returns:
            SummaryProjectionDTO: An immutable snapshot containing basic account routing,
                status flags, and dynamically populated financial data if requested.

        Raises:
            TypeError: If arguments are not of expected types.
            RuntimeError: If token claims violate Domain VO invariants, or if financial
                data is requested using only a primary AuthToken instead of an AccessToken.
            ExpiredSessionError: If the token's TTL has passed.
            SessionIntegrityError: If the token is invalid, tampered with, or if cryptographic
                validation against the live database hash fails (Zero Trust enforcement).
            AuthenticationError: If the account or holder no longer exists (TOCTOU mitigation).
        """
        verify.verify_instance(token, (AuthToken, AccessToken))
        verify.verify_instance(request_financial, bool)

        if request_financial and isinstance(token, AuthToken):
            raise RuntimeError("Financial info requires AccessToken")

        account_obj = None
        financial_dto = None
        pwd_hash = ""

        branch_code = self._instantiate_vo(BranchCode, token.branch_code)
        account_num = self._instantiate_vo(AccountNumber, token.account_num)

        try:
            account_info = self._repository.get_account_projection(
                branch_code,
                account_num,
                holder_info=True,
                access_info=request_financial,
            )
            if request_financial:
                account_db_snap = self._repository.get_account_snapshot(
                    branch_code, account_num
                )
                account_obj = Account.from_snapshot(account_db_snap)
        except DataNotFoundError:
            raise AuthenticationError("Authentication failed: Account no longer exists")

        if request_financial and account_obj:
            access_info = account_info.unwrap_access()
            financial_dto = account_obj.financial_info
            pwd_hash = access_info.password_hash

        try:
            self._token_service.validate_token_integrity(token, pwd_hash)
        except ExpiredTokenError as e:
            raise ExpiredSessionError(
                "The current user session has expired. Re-authentication is required."
            ) from e
        except TokenSignatureError as e:
            raise SessionIntegrityError(
                "Session token integrity check failed due to invalid cryptographic signature."
            ) from e

        holder_info = account_info.unwrap_holder()

        return SummaryProjectionDTO(
            holder_name=holder_info.name,
            branch_code=account_info.branch_code,
            account_num=account_info.account_num,
            account_type=account_info.account_type,
            is_frozen=account_info.is_frozen,
            financial_info=financial_dto,
        )

    def execute_deposit(self, dto: DepositDTO) -> None:
        """Executes a secure, public-facing deposit operation.

        Bypasses vault authentication (no password required) to allow fast deposits
        from third parties. Operates under a strict Unit of Work with exclusive transactional
        isolation (`for_update=True`) to prevent race conditions. Strictly respects Domain
        boundaries by hydrating the target Account entity and delegating state-mutating
        logic to it.

        Args:
            dto (DepositDTO): Command payload containing branch code, account number, and deposit amount.

        Raises:
            TypeError: If dto is not an instance of DepositDTO.
            RuntimeError: If branch code, account number, or deposit amount violate
                Domain VO invariants (e.g., minimum ATM limit).
            AccessDeniedError: If the target account is currently frozen (translating
                domain-level FrozenAccountError).
            AccountNotFoundError: If the provided branch or account number does not exist.
            ServiceUnavailableError: If the deposit could not be persisted due to a repository error.
        """
        verify.verify_instance(dto, DepositDTO)

        branch_code, account_num, money = self._get_operation_vos(
            dto.branch_code, dto.account_num, dto.amount
        )

        try:
            with self._repository.unit_of_work():
                account_db_snap = self._repository.get_account_snapshot(
                    branch_code, account_num, for_update=True
                )
                account_obj = Account.from_snapshot(account_db_snap)
                try:
                    events = account_obj.deposit(money)
                except FrozenAccountError as e:
                    raise AccessDeniedError(
                        "This account is frozen and cannot be accessed"
                    ) from e
                account_snap = account_obj.to_snapshot()
                self._repository.save_transaction(account_snap, events)
        except DataNotFoundError as e:
            raise AccountNotFoundError(
                "The requested account does not exist in our records"
            ) from e
        except RepositoryError as e:
            raise ServiceUnavailableError(
                "The intended operation could not be persisted due to an internal error"
            ) from e

    @contextmanager
    def execute_withdrawal(self, dto: WithdrawalDTO) -> Generator[WithdrawalSimulation]:
        """Orchestrates a secure withdrawal operation using a state-locked context manager.

        Acts as a transactional gatekeeper under a strict Zero Trust model. Verifies cryptographic
        identity before granting access to the vault. Employs an atomic Unit of Work with
        a pessimistic database lock (`for_update=True`) to prevent Time-of-Check to Time-of-Use
        (TOCTOU) race conditions.

        Execution Flow:
        1. Validates token integrity and locks the Account entity in the database.
        2. Yields a `WithdrawalSimulation` Value Object to the caller (Controller), pausing execution.
        3. The caller uses this simulation to optionally prompt the user for consent (e.g., if
           overdraft is required) and either continues or aborts the context.
        4. Upon resumption, executes the withdrawal and ledger event generation against the
           actively locked Entity and persists state snapshots.

        Args:
            dto (WithdrawalDTO): Command payload containing the AccessToken and withdrawal amount.

        Yields:
            WithdrawalSimulation: Value Object detailing authorization status and exact credit/overdraft requirements.

        Raises:
            TypeError: If dto is not an instance of WithdrawalDTO.
            RuntimeError: If token claims or withdrawal amount violate Domain VO invariants.
            ExpiredSessionError: If the token's TTL has passed.
            SessionIntegrityError: If the cryptographic signature of the token is invalid or tampered with.
            AuthenticationError: If the account was deleted during the active session.
            AccessDeniedError: If the target account is frozen during the operation.
            DeniedOperationError: If the requested withdrawal is rejected due to insufficient available funds.
            ServiceUnavailableError: If the transaction could not be persisted due to an internal error.
        """
        verify.verify_instance(dto, WithdrawalDTO)

        branch_code, account_num, money = self._get_operation_vos(
            dto.access_token.branch_code, dto.access_token.account_num, dto.amount
        )

        try:
            account_info = self._repository.get_account_projection(
                branch_code, account_num, access_info=True
            )
        except DataNotFoundError as e:
            raise AuthenticationError(
                "Authentication failed: Account no longer exists"
            ) from e

        access_info = account_info.unwrap_access()

        try:
            self._token_service.validate_token_integrity(
                dto.access_token, access_info.password_hash
            )
        except ExpiredTokenError as e:
            raise ExpiredSessionError(
                "The current user session has expired. Re-authentication is required."
            ) from e
        except TokenSignatureError as e:
            raise SessionIntegrityError(
                "Session token integrity check failed due to invalid cryptographic signature."
            ) from e

        try:
            with self._repository.unit_of_work():
                account_db_snap = self._repository.get_account_snapshot(
                    branch_code, account_num, for_update=True
                )
                account_obj = Account.from_snapshot(account_db_snap)
                simulation = account_obj.simulate_withdrawal(money)
                yield simulation
                try:
                    events = account_obj.withdrawal(money)
                except FrozenAccountError as e:
                    raise AccessDeniedError(
                        "This account is frozen and cannot be accessed"
                    ) from e
                except InsufficientFundsError as e:
                    raise DeniedOperationError(
                        "Withdrawal denied: Insufficient available funds"
                    ) from e
                account_snap = account_obj.to_snapshot()
                self._repository.save_transaction(account_snap, events)
        except DataNotFoundError as e:
            raise AuthenticationError(
                "Authentication failed: Account no longer exists"
            ) from e
        except RepositoryError as e:
            raise ServiceUnavailableError(
                "The intended operation could not be persisted due to an internal error"
            ) from e

    def generate_statement(self, dto: StatementDTO) -> StatementProjectionDTO:
        """Retrieves a mathematically consistent, chronologically ordered bank statement.

        Operates under a Zero Trust model for data privacy using a read-only Unit of Work to
        guarantee that the account summary (via `SummaryProjectionDTO`) and the ledger event history
        are evaluated with strict temporal consistency. Incorporates TOCTOU mitigation to ensure
        the account has not been deleted mid-session.

        Args:
            dto (StatementDTO): Command payload containing the AccessToken and start cutoff date.

        Returns:
            StatementProjectionDTO: An immutable snapshot combining the account's complete
                summary and chronological ledger event history.

        Raises:
            TypeError: If dto is not an instance of StatementDTO.
            RuntimeError: If token claims violate Domain VO invariants.
            ExpiredTokenError: If the token's TTL has passed.
            TokenSecurityError: If the token's cryptographic signature is invalid or tampered with.
            AuthenticationError: If the account was deleted during the active session (TOCTOU mitigation).
            ServiceUnavailableError: If the statement query could not be executed due to a repository error.
        """
        verify.verify_instance(dto, StatementDTO)

        access_token = dto.access_token

        branch_code = self._instantiate_vo(BranchCode, access_token.branch_code)
        account_num = self._instantiate_vo(AccountNumber, access_token.account_num)

        try:
            with self._repository.unit_of_work():
                events = self._repository.get_ledger_entries(
                    branch_code, account_num, dto.start_date
                )
                account_summary = self.get_account_summary(
                    access_token, request_financial=True
                )
        except DataNotFoundError as e:
            raise AuthenticationError(
                "Authentication failed: Account no longer exists"
            ) from e

        return StatementProjectionDTO(
            account_info=account_summary, financial_events=events
        )

    # --------------------------------------------------------------------------
    # Protected methods (Internal Helpers - Trust Zone)
    # --------------------------------------------------------------------------

    def _get_operation_vos(
        self, branch_code_str: str, account_num_str: str, amount: Decimal
    ) -> tuple[BranchCode, AccountNumber, Money]:
        """Converts raw primitives into validated Domain Value Objects for banking operations.

        Encapsulates Fail-Fast boundary conversion using `BaseApplicationService._instantiate_vo`.

        Args:
            branch_code_str (str): Raw 4-digit branch code primitive.
            account_num_str (str): Raw 8-digit account number primitive.
            amount (Decimal): Raw monetary transaction amount primitive.

        Returns:
            tuple[BranchCode, AccountNumber, Money]: A 3-tuple containing initialized Domain VOs.

        Raises:
            RuntimeError: If any primitive value violates Domain Value Object invariant rules.
        """
        branch_code = self._instantiate_vo(BranchCode, branch_code_str)
        account_num = self._instantiate_vo(AccountNumber, account_num_str)
        money = self._instantiate_vo(Money, amount)

        return (branch_code, account_num, money)
