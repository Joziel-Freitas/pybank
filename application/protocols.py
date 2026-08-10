"""Application Layer Infrastructure Protocols Module.

This module defines abstract structural protocols (interfaces using PEP 544)
required by Application Services. It establishes strict inversion-of-control (IoC)
boundaries, decoupling use cases from concrete infrastructure implementations such as
relational databases, cryptographic security handlers, and token issuers.
"""

from contextlib import AbstractContextManager
from datetime import date
from typing import Any, Protocol

from domain.snapshots import AccountHolderSnapshot, AccountSnapshot
from domain.value_objects import LedgerEvent
from shared.credentials import AccessToken, AuthToken
from shared.projections import AccountProjectionDTO


class RepositoryProtocol(Protocol):

    def unit_of_work(self) -> AbstractContextManager[None]: ...

    def account_holder_exists(self, cpf: str) -> bool: ...

    def account_exists(self, branch_code: str, account_num: str) -> bool: ...

    def holder_has_account(self, cpf: str) -> bool: ...

    def get_holder_snapshot(self, cpf: str) -> AccountHolderSnapshot: ...

    def get_account_projection(
        self,
        branch_code: str,
        account_num: str,
        access_info: bool = False,
        holder_info: bool = False,
        for_update: bool = False,
    ) -> AccountProjectionDTO: ...

    def get_account_snapshot(
        self, branch_code: str, account_num: str, for_update: bool = False
    ) -> AccountSnapshot: ...

    def get_ledger_entries(
        self, branch_code: str, account_num: str, start_date: date
    ) -> tuple[dict[str, Any], ...]: ...

    def register_account_bundle(
        self,
        account_snap: AccountSnapshot,
        holder_snap_or_cpf: AccountHolderSnapshot | str,
        password_hash: str,
    ) -> None: ...

    def save_transaction(
        self, account_snap: AccountSnapshot, events: tuple[LedgerEvent, ...]
    ) -> None: ...

    def register_failed_login(self, branch_code: str, account_num: str) -> None: ...

    def reset_login_attempts(self, branch_code: str, account_num: str) -> None: ...

    def update_account_status(self, account_snap: AccountSnapshot) -> None: ...

    def update_password(
        self, branch_code: str, account_num: str, new_password_hash: str
    ) -> None: ...

    def delete_account(self, branch_code: str, account_num: str) -> None: ...

    def delete_account_holder(self, cpf: str) -> None: ...


class TokenServiceProtocol(Protocol):
    def generate_auth_token(
        self, cpf: str, branch_code: str, account_num: str
    ) -> AuthToken: ...

    def generate_access_token(
        self, auth_token: AuthToken, pwd_hash: str
    ) -> AccessToken: ...

    def validate_token_integrity(
        self, token: AuthToken | AccessToken, pwd_hash: str = ""
    ) -> None: ...


class HasherProtocol(Protocol):
    def generate_password_hash(self, pwd_str: str) -> str: ...

    def check_password(self, pwd_str: str, pwd_hash: str) -> bool: ...
