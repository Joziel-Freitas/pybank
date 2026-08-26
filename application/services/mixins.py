"""Application Mixins Module.

Provides reusable domain and service helper behaviors, such as account summary resolution
for authenticated application services.
"""

from abc import ABC, abstractmethod

from application.protocols import RepositoryProtocol, TokenServiceProtocol
from domain.account import Account
from domain.types import VOValueTypes
from domain.value_objects import AccountNumber, BranchCode, DomainVO
from shared import verify
from shared.credentials import AccessToken, AuthToken
from shared.exceptions import (
    AuthenticationError,
    DataNotFoundError,
    ExpiredSessionError,
    ExpiredTokenError,
    SessionIntegrityError,
    TokenSignatureError,
)
from shared.projections import SummaryProjectionDTO


class AccountSummaryMixin(ABC):
    """Mixin providing identity and financial summary resolution for authenticated sessions.

    Requires the host class to inherit from BaseApplicationService or provide matching
    infrastructure protocol references (`_token_service`, `_repository`) and the `_instantiate_vo` helper.
    """

    _token_service: TokenServiceProtocol
    _repository: RepositoryProtocol

    @abstractmethod
    def _instantiate_vo[VO_T: DomainVO](
        self, vo_type: type[VO_T], vo_value: VOValueTypes
    ) -> VO_T:
        """Helper contract required to convert raw primitives into domain Value Objects."""
        raise NotImplementedError

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
