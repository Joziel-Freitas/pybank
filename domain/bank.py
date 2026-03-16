"""
Bank Management Module.

This module defines the central 'Bank' class, which acts as an aggregate root
for Clients and Accounts. It is responsible for:
1. Storing and managing the lifecycle of Client and Account entities.
2. Validating business rules regarding account ownership and access.
3. Authenticating users and granting access to sensitive operations.

The Bank enforces strict consistency rules, ensuring that every client is
properly linked to their accounts and that security credentials (passwords)
are validated before access is granted.
"""

import hashlib
import hmac
from typing import Any

import bcrypt
from infra import verify
from infra.mysql_repository import MySQLRepository
from shared.credentials import AccountCard, AuthToken
from shared.exceptions import (
    AuthenticationError,
    BankPasswordError,
    BankSecurityError,
    BlockedAccountError,
    ClientNotFoundError,
    DataNotFoundError,
    DuplicatedAccountError,
    DuplicatedClientError,
    DuplicatedDataError,
)

from .account import Account
from .person import Client


class Bank:

    _bank_name: str
    _branch_code: str
    _repository: MySQLRepository
    _secret_key: bytes

    def __init__(
        self,
        bank_name: str,
        branch_code: str,
        repository: MySQLRepository,
        secret_key: str,
    ):
        """
        Initializes a new Bank instance.

        Args:
            bank_name (str): The name of the institution.
            branch_code (str): The 4-digit numeric string representing the branch.

        Raises:
            TypeError: If arguments are not strings.
            ValueError: If branch_code does not have exactly 4 digits.
        """
        verify.verify_instance(bank_name, str)
        self._bank_name = bank_name

        verify.verify_instance(branch_code, str)
        verify.verify_digits(branch_code, 4)
        self._branch_code = branch_code

        verify.verify_instance(repository, MySQLRepository)
        self._repository = repository
        self._secret_key = secret_key.encode("utf-8")

    def __repr__(self) -> str:
        """
        Returns a summary string representation of the Bank.

        Note: Due to the complexity and potential size of the Bank entity,
        this __repr__ does NOT return a strictly reproducible string (eval-safe).
        Instead, it provides a 'Snapshot' of the bank's current load and identity,
        which is optimized for debugging lifecycle and state issues.
        """

        class_name = type(self).__name__
        return (
            f"{class_name}(name={self._bank_name!r}, branch_code={self._branch_code}),"
        )

    @property
    def bank_name(self) -> str:
        """Returns the bank's name."""
        return self._bank_name

    @property
    def bank_branch_code(self) -> str:
        """Returns the bank's branch code."""
        return self._branch_code

    @staticmethod
    def validate_password(password: str) -> None:
        """
        Validates the format of a password.

        Args:
            password (str): The password string to validate.

        Raises:
            BankPasswordError: If the password is not a string or not 6 digits.
        """
        try:
            verify.verify_instance(password, str)
            verify.verify_digits(password, 6)
        except verify.VERIFY_ERRORS as e:
            raise BankPasswordError(f"Invalid password. Cause: {e}")

    def _insert_client(self, new_client: Client) -> None:
        try:
            self._repository.save_client(new_client)
        except DuplicatedDataError as e:
            raise DuplicatedClientError(
                "Client already registered in the system"
            ) from e

    def _generate_password_hash(self, password_str: str) -> str:
        pwd = password_str
        pwd_bytes = pwd.encode("utf-8")
        salt = bcrypt.gensalt()
        pwd_hash_bytes = bcrypt.hashpw(pwd_bytes, salt)
        pwd_hash_str = pwd_hash_bytes.decode("utf-8")

        return pwd_hash_str

    def _check_password(self, pwd_str: str, pwd_hash_str: str) -> None:
        pdw_bytes = pwd_str.encode("utf-8")
        hashed_pwd_bytes = pwd_hash_str.encode("utf-8")

        if not bcrypt.checkpw(pdw_bytes, hashed_pwd_bytes):
            raise AuthenticationError(
                "Given password doesn't match with registered password"
            )

    def _sign_token_payload(self, cpf: str, branch_code: str, account_num: str) -> str:
        payload = f"{cpf}:{branch_code}:{account_num}".encode("utf-8")

        signature = hmac.new(self._secret_key, payload, hashlib.sha256).hexdigest()

        return signature

    def _validate_token(self, token: AuthToken) -> None:
        verify.verify_instance(token, AuthToken)

        bank_signature = self._sign_token_payload(
            token.cpf, token.branch_code, token.account_num
        )
        if not hmac.compare_digest(bank_signature, token.signature):
            raise BankSecurityError("Invalid or tampered authentication token.")

    def get_registered_client(self, cpf: str, get: bool = False) -> Client | None:
        try:
            client_obj = self._repository.get_client(cpf=cpf)
            return client_obj if get else None
        except DataNotFoundError as e:
            raise ClientNotFoundError("Not client registered under this CPF") from e

    def register_account(
        self, new_account: Account, client_or_cpf: Client | str, password: str
    ) -> None:
        parameters = (new_account, client_or_cpf, password)
        types = (Account, (Client, str), str)

        for p, t in zip(parameters, types):
            verify.verify_instance(p, t)

        Bank.validate_password(password)

        if isinstance(client_or_cpf, Client):
            client_cpf = client_or_cpf.cpf
            self._insert_client(client_or_cpf)
        elif isinstance(client_or_cpf, str):
            client_cpf = client_or_cpf
            self.get_registered_client(client_cpf)

        pwd_hash = self._generate_password_hash(password_str=password)

        try:
            self._repository.save_account(new_account, client_cpf, pwd_hash)
        except DuplicatedDataError as e:
            raise DuplicatedAccountError("Account already registered") from e

    def authenticate(
        self, client: Client, branch_code: str, account_num: str
    ) -> AuthToken:

        temp_card = AccountCard(client.cpf, branch_code, account_num)
        if not client.has_account(temp_card):
            raise AuthenticationError("Account card not found between client's cards")

        signature = self._sign_token_payload(client.cpf, branch_code, account_num)
        return AuthToken(client.cpf, branch_code, account_num, signature)

    def _verify_credentials_dict(self, credentials: dict[str, Any]) -> None:
        verify.verify_instance(credentials, dict)

        required_keys = {"is_active", "password_hash", "failed_login_attempts"}

        if not required_keys.issubset(credentials.keys()):
            raise ValueError("Invalid credentials keys mapped from repository")

    def get_access(self, token: AuthToken, password: str) -> Account:
        self._validate_token(token)
        Bank.validate_password(password)

        branch_code = token.branch_code
        account_num = token.account_num

        acc_credentials = self._repository.get_account_credentials(
            branch_code, account_num
        )

        self._verify_credentials_dict(acc_credentials)

        hashed_pwd: str = acc_credentials["password_hash"]
        is_active: bool = acc_credentials["is_active"]
        failed_logins: int = acc_credentials["failed_login_attempts"]

        if is_active is False:
            raise BlockedAccountError("Inactive account. Access denied")

        try:
            self._check_password(password, hashed_pwd)

            if failed_logins > 0:
                self._repository.reset_login_attempts(branch_code, account_num)

            account_obj = self._repository.get_account(branch_code, account_num)
            return account_obj
        except AuthenticationError as e:
            self._repository.register_failed_login(branch_code, account_num)
            if (failed_logins + 1) >= 2:
                self._repository.update_account_status(branch_code, account_num, False)
                raise BlockedAccountError(
                    "The account was frozen due to 3 consecutive failed login attempts."
                ) from e
            raise e
