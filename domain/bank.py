"""
Bank Management Module.

This module defines the central 'Bank' class, which acts as the aggregate root
and core domain service for the PyBank system. It enforces high-level business
and security rules, delegating persistence to an injected Repository.

Core Responsibilities:
1. Lifecycle Orchestration: Manages the creation, retrieval, and deletion of
   Client and Account entities via the Repository pattern.
2. Stateless Authentication: Issues and validates cryptographic HMAC tokens
   (AuthToken) to verify account ownership without storing session state.
3. Application Security (AppSec): Protects the vault ('get_access') by verifying
   bcrypt password hashes, managing account frozen states, and mitigating
   brute-force attacks.

The Bank ensures that no sensitive operation occurs without strict identity
verification, maintaining absolute consistency across the financial domain.
"""

import hashlib
import hmac
from datetime import date, datetime
from decimal import Decimal
from typing import Any, ClassVar

import bcrypt
from infra import verify
from infra.mysql_repository import MySQLRepository
from shared.credentials import AccessToken, AccountCard, AuthToken
from shared.exceptions import (
    AccountAlreadyActiveError,
    AccountNotFoundError,
    AuthenticationError,
    BankPasswordError,
    BankSecurityError,
    BlockedAccountError,
    ClientNotFoundError,
    DataNotFoundError,
    DuplicatedAccountError,
    DuplicatedClientError,
    DuplicatedDataError,
    NotEmptyAccountError,
)
from shared.types import BankContext

from .account import Account
from .person import Client


class Bank:
    """
    The aggregate root and core domain service of the PyBank system.

    This class encapsulates the absolute source of truth for all business and
    security rules. It acts as a gateway for the presentation layer, ensuring
    that no state changes (like deposits, withdrawals, or status updates) occur
    without strict validation and cryptographic authentication.

    Attributes:
        MAX_LOGIN_ATTEMPTS (ClassVar[int]): The universal business rule defining
            the maximum allowed consecutive failed authentication attempts before
            an account is automatically frozen. Currently set to 3.
    """

    MAX_LOGIN_ATTEMPTS: ClassVar[int] = 3

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

    def _generate_password_hash(self, password_str: str) -> str:
        """
        Generates a secure cryptographic hash for a plain-text password.

        Uses the bcrypt algorithm with a randomly generated salt to ensure
        protection against rainbow table and brute-force attacks.

        Args:
            password_str (str): The plain-text password (already validated).

        Returns:
            str: The securely hashed password string.
        """
        pwd = password_str
        pwd_bytes = pwd.encode("utf-8")
        salt = bcrypt.gensalt()
        pwd_hash_bytes = bcrypt.hashpw(pwd_bytes, salt)
        pwd_hash_str = pwd_hash_bytes.decode("utf-8")

        return pwd_hash_str

    def _check_password(self, pwd_str: str, pwd_hash_str: str) -> None:
        """
        Verifies a plain-text password against a securely hashed password.

        Args:
            pwd_str (str): The plain-text password provided by the user.
            pwd_hash_str (str): The bcrypt hash retrieved from the database.

        Raises:
            AuthenticationError: If the password does not match the hash.
        """
        pdw_bytes = pwd_str.encode("utf-8")
        hashed_pwd_bytes = pwd_hash_str.encode("utf-8")

        if not bcrypt.checkpw(pdw_bytes, hashed_pwd_bytes):
            raise AuthenticationError(
                "Given password doesn't match with registered password"
            )

    def _validate_token(self, token: AccessToken | AuthToken) -> None:
        """
        Validates the cryptographic integrity and authenticity of a session token.

        Operates seamlessly with both AuthToken (Lobby access) and AccessToken
        (Vault access). Utilizing a pattern matching approach, it dynamically
        reconstructs the expected payload. For AccessTokens, it enforces a Zero
        Trust model by fetching the freshest password hash from the repository,
        acting as an automatic session invalidator if the user's password was
        recently changed.

        Args:
            token (AccessToken | AuthToken): The token instance to be validated.

        Raises:
            BankSecurityError: If the token instance is unknown, or if the
                cryptographic signature has been tampered with or invalidated.
        """
        match token:
            case AuthToken():
                payload = f"{token.cpf}:{token.branch_code}:{token.account_num}"
            case AccessToken():
                acc_credentials = self._get_account_credentials(
                    token.branch_code, token.account_num
                )
                pwd_hash = acc_credentials["password_hash"]
                payload = f"{token.branch_code}:{token.account_num}:{pwd_hash}"
            case _:
                raise BankSecurityError("Security breach: Invalid token instance")

        bank_signature = self._sign_token_payload(payload)

        if not hmac.compare_digest(bank_signature, token.signature):
            raise BankSecurityError("Security breach: Tampered token.")

    def _sign_token_payload(self, payload_str: str) -> str:
        """
        Generates a secure cryptographic signature for a given payload.

        Uses HMAC (Hash-based Message Authentication Code) with SHA-256 and the
        internal bank's secret key to ensure the payload cannot be forged or
        altered by malicious actors.

        Args:
            payload_str (str): The raw string payload to be signed.

        Returns:
            str: A hexadecimal string representing the cryptographic signature.
        """
        payload_bytes = payload_str.encode("utf-8")
        return hmac.new(self._secret_key, payload_bytes, hashlib.sha256).hexdigest()

    def _generate_auth_token(
        self, cpf: str, branch_code: str, account_num: str
    ) -> AuthToken:
        """
        Issues an AuthToken for initial client identification.

        This token grants 'Lobby' access, proving the client's identity and
        allowing standard, non-sensitive operations (such as deposits) without
        granting access to the account's vault.

        Args:
            cpf (str): The client's unique identification number.
            branch_code (str): The 4-digit numeric branch code.
            account_num (str): The account number.

        Returns:
            AuthToken: A securely signed identification token.
        """
        payload = f"{cpf}:{branch_code}:{account_num}"
        signature = self._sign_token_payload(payload)

        return AuthToken(
            cpf=cpf,
            branch_code=branch_code,
            account_num=account_num,
            signature=signature,
        )

    def _generate_access_token(
        self, auth_token: AuthToken, password_hash: str
    ) -> AccessToken:
        """
        Issues a highly secure AccessToken for vault authorization.

        This token represents a fully authenticated session. By injecting the
        current database password hash into the cryptographic payload, it ensures
        that the token becomes immediately invalid if the account password is
        changed, providing defense-in-depth against session hijacking.

        Args:
            auth_token (AuthToken): The pre-validated identification token.
            password_hash (str): The latest bcrypt password hash retrieved from
                the database.

        Returns:
            AccessToken: A securely signed vault access token.
        """
        payload = f"{auth_token.branch_code}:{auth_token.account_num}:{password_hash}"
        signature = self._sign_token_payload(payload)

        return AccessToken(
            branch_code=auth_token.branch_code,
            account_num=auth_token.account_num,
            signature=signature,
        )

    def _get_account_credentials(
        self, branch_code: str, account_num: str
    ) -> dict[str, Any]:
        """
        Retrieves and validates the security credentials dictionary from the repository.

        Acts as an internal checkpoint to ensure that all necessary security keys
        (active status, password hash, failed attempts) are properly loaded before
        any sensitive validation occurs.

        Args:
            branch_code (str): The branch code of the target account.
            account_num (str): The target account number.

        Returns:
            dict[str, Any]: A validated dictionary containing the account credentials.

        Raises:
            TypeError: If the retrieved data is not a dictionary.
            ValueError: If any strictly required security keys are missing.
            AccountNotFoundError: If the account does not exist in the repository.
        """
        try:
            acc_credentials = self._repository.get_account_credentials(
                branch_code, account_num
            )
        except DataNotFoundError as e:
            raise AccountNotFoundError(
                "The requested account does not exist in our records."
            ) from e

        verify.verify_instance(acc_credentials, dict)

        required_keys = {"is_active", "password_hash", "failed_login_attempts"}

        if not required_keys.issubset(acc_credentials.keys()):
            raise ValueError("Invalid credentials keys mapped from repository")

        return acc_credentials

    def _ensure_account_is_active(self, credentials_dict: dict[str, Any]) -> None:
        """
        Verifies the active status of an account from its credentials payload.

        Acts as a centralized security checkpoint to prevent unauthorized
        transactions on frozen or blocked accounts.

        Args:
            credentials_dict (dict[str, Any]): The validated credentials dictionary
                retrieved from the repository.

        Raises:
            BlockedAccountError: If the 'is_active' flag is False.
        """
        if not credentials_dict["is_active"]:
            raise BlockedAccountError("Account is unavailable for transactions.")

    def check_client_exists(self, cpf: str) -> bool:
        """
        Verifies if a client is registered in the banking system.

        This is a highly optimized, lightweight check that queries the repository
        without hydrating the full Client domain entity. Ideal for pre-validation
        during onboarding workflows.

        Args:
            cpf (str): The 11-digit string representing the client's CPF.

        Returns:
            bool: True if the client exists, False otherwise.

        Raises:
            TypeError: If the provided CPF is not a string.
        """
        verify.verify_instance(cpf, str)

        return self._repository.client_exists(cpf)

    def check_account_exists(self, branch_code: str, account_num: str) -> bool:
        """
        Verifies if an account is registered in the banking system.

        Provides a fast, lightweight existence check avoiding the overhead of
        loading the Account object or its transaction history. Useful for
        preventing duplicate creation attempts at the controller level.

        Args:
            branch_code (str): The 4-digit string representing the branch.
            account_num (str): The unique 8-digit string representing the account.

        Returns:
            bool: True if the account exists, False otherwise.

        Raises:
            TypeError: If any of the provided arguments are not strings.
        """
        verify.verify_instance(branch_code, str)
        verify.verify_instance(account_num, str)

        return self._repository.account_exists(branch_code, account_num)

    def get_registered_client(self, cpf: str) -> Client:
        """
        Retrieves a fully hydrated client entity from the repository.

        Args:
            cpf (str): The 11-digit string representing the client's CPF.

        Returns:
            Client: The domain Client object.

        Raises:
            ClientNotFoundError: If the CPF is not registered in the system.
        """
        try:
            client_obj = self._repository.get_client(cpf=cpf)
            return client_obj
        except DataNotFoundError as e:
            raise ClientNotFoundError("Not client registered under this CPF") from e

    def register_account(
        self, new_account: Account, client_or_cpf: Client | str, password: str
    ) -> None:
        """
        Registers a newly created account and links it to a client.

        This method handles both existing clients (by CPF) and new clients
        (by Client object), securely hashes the initial password, and persists
        everything via the repository.

        Args:
            new_account (Account): The new domain Account entity to be saved.
            client_or_cpf (Client | str): The owner Client object, or their CPF.
            password (str): The raw 6-digit password for the new account.

        Raises:
            TypeError: If any arguments do not match expected types.
            BankPasswordError: If the password format is invalid.
            DuplicatedAccountError: If the account number is already taken.
            DuplicatedClientError: If a new client CPF is already registered.
            ClientNotFoundError: If an existing client CPF is not found.
        """
        parameters = (new_account, client_or_cpf, password)
        types = (Account, (Client, str), str)

        for p, t in zip(parameters, types):
            verify.verify_instance(p, t)

        Bank.validate_password(password)

        pwd_hash = self._generate_password_hash(password_str=password)

        try:
            self._repository.register_account_bundle(
                new_account, client_or_cpf, pwd_hash
            )
        except DuplicatedDataError as e:
            error_context = BankContext(str(e))

            match error_context:
                case BankContext.CLIENT:
                    raise DuplicatedClientError(
                        "Client already registered in the system"
                    ) from e
                case BankContext.ACCOUNT:
                    raise DuplicatedAccountError(
                        "Account already registered in the system"
                    ) from e
        except DataNotFoundError:
            raise ClientNotFoundError("Not client registered under this CPF")

    def authenticate(
        self, client: Client, branch_code: str, account_num: str
    ) -> AuthToken:
        """
        Authenticates a client's claim to an account and issues a stateless token.

        This is the "Lobby" access. It does not open the vault or check if the
        account is frozen. It merely verifies ownership and issues an AuthToken
        that can be used for subsequent secure operations.

        Args:
            client (Client): The client attempting to access the account.
            branch_code (str): The branch code of the target account.
            account_num (str): The target account number.

        Returns:
            AuthToken: A securely signed, stateless authentication token.

        Raises:
            AuthenticationError: If the account does not belong to the client.
        """
        temp_card = AccountCard(client.cpf, branch_code, account_num)
        if not client.has_account(temp_card):
            raise AuthenticationError("Account card not found between client's cards")

        return self._generate_auth_token(
            cpf=client.cpf, branch_code=branch_code, account_num=account_num
        )

    def get_remaining_login_attempts(self, auth_token: AuthToken) -> int:
        """
        Calculates the remaining vault access attempts for an authenticated client.

        Acts as a safe query method for the presentation layer to synchronize its
        UI state with the strict security records in the database, preventing
        unexpected account freezes without proper user warnings.

        Args:
            auth_token (AuthToken): A valid, securely signed authentication token.

        Returns:
            int: The number of remaining attempts before the account is frozen.
        """
        self._validate_token(auth_token)
        acc_credentials = self._get_account_credentials(
            auth_token.branch_code, auth_token.account_num
        )
        failed_attempts = acc_credentials["failed_login_attempts"]

        return self.MAX_LOGIN_ATTEMPTS - failed_attempts

    def authorize_vault_access(
        self, auth_token: AuthToken, password: str
    ) -> AccessToken:
        """
        The public security checkpoint and brute-force mitigation mechanism.

        This method performs the heavy lifting of security validation without
        incurring the cost of hydrating a full Account entity. It validates
        the active status, verifies the Bcrypt password hash, increments failed
        login attempts on failure, and freezes the account if the threshold is met.
        Upon success, it issues the highly secure AccessToken.

        Args:
            auth_token (AuthToken): A valid, securely signed authentication token.
            password (str): The raw 6-digit password provided by the user.

        Returns:
            AccessToken: The cryptographic key granting full vault access.

        Raises:
            BlockedAccountError: If the account is already frozen, or if it reaches
                the maximum allowed failed login attempts during this check.
            AuthenticationError: If the provided password does not match the hash.
            BankSecurityError: If the AuthToken is tampered with.
        """
        Bank.validate_password(password)
        self._validate_token(auth_token)

        acc_credentials = self._get_account_credentials(
            auth_token.branch_code, auth_token.account_num
        )
        self._ensure_account_is_active(acc_credentials)

        branch_code = auth_token.branch_code
        account_num = auth_token.account_num
        hashed_pwd: str = acc_credentials["password_hash"]
        failed_logins: int = acc_credentials["failed_login_attempts"]

        try:
            self._check_password(password, hashed_pwd)

            if failed_logins > 0:
                self._repository.reset_login_attempts(branch_code, account_num)

            return self._generate_access_token(
                auth_token=auth_token, password_hash=hashed_pwd
            )
        except AuthenticationError as e:
            self._repository.register_failed_login(branch_code, account_num)
            if (failed_logins + 1) >= Bank.MAX_LOGIN_ATTEMPTS:
                self._repository.update_account_status(branch_code, account_num, False)
                raise BlockedAccountError(
                    "The account was frozen due to 3 consecutive failed login attempts."
                ) from e
            raise e

    def get_account(self, access_token: AccessToken) -> Account:
        """
        The Vault Door. Grants access to an active, fully hydrated Account entity.

        This method acts as the primary gateway for sensitive operations. It relies
        on the Zero Trust verification of the AccessToken to guarantee that strict
        security checks have already been passed.

        Args:
            access_token (AccessToken): A valid, securely signed vault token.

        Returns:
            Account: The fully hydrated Account domain entity.

        Raises:
            BankSecurityError: If the AccessToken is invalid, tampered with, or
                invalidated by a recent password change.
        """
        self._validate_token(access_token)

        return self._repository.get_account(
            access_token.branch_code, access_token.account_num
        )

    def execute_deposit(
        self,
        branch_code: str,
        account_num: str,
        amount: Decimal,
        account: Account | None = None,
    ) -> None:
        """
        Executes a secure, public-facing deposit operation directly to the repository.

        This method bypasses both 'Vault' access (no password required) and
        session validation (no AuthToken required) to allow fast deposits from
        third parties. It strictly ensures the target account exists and is active
        before executing the transaction.

        It delegates mathematical validation to the Account domain entity.
        If an active Account instance is provided (e.g., from an open session),
        its in-memory balance is updated alongside the database to ensure state consistency.

        Args:
            branch_code (str): The branch code of the target account.
            account_num (str): The target account number.
            amount (Decimal): The positive amount to be deposited.
            account (Account | None, optional): An active account instance to be
                synchronized in memory. Defaults to None.

        Raises:
            TypeError: If the provided account is not an Account instance.
            InvalidDepositError: If the deposit amount violates business rules.
            BlockedAccountError: If the target account is currently frozen.
            AccountNotFoundError: If the provided branch or account number does not exist.
        """
        Account.validate_account_deposit(amount)

        acc_credentials = self._get_account_credentials(branch_code, account_num)
        self._ensure_account_is_active(acc_credentials)

        if account is not None:
            verify.verify_instance(account, Account)
            account.deposit(amount)

        self._repository.save_transaction(branch_code, account_num, amount)

    def execute_withdraw(
        self, access_token: AccessToken, account: Account, amount: Decimal
    ) -> None:
        """
        Executes a secure withdrawal operation and persists it to the database.

        This method operates under a 'Zero Trust' security model. It strictly
        verifies that the provided AccessToken matches the identifiers of the
        active Account object in memory, preventing cross-account manipulation
        or session hijacking.

        Args:
            access_token (AccessToken): A valid, securely signed vault token.
            account (Account): The active, fully hydrated Account domain entity.
            amount (Decimal): The positive monetary amount to be withdrawn.

        Raises:
            TypeError: If the arguments are not of the expected types.
            BankSecurityError: If the token is invalid, tampered with, or if its
                credentials do not exactly match the provided Account's identifiers.
            InvalidWithdrawError: If the withdrawal amount violates business rules.
        """
        self._validate_token(access_token)
        verify.verify_instance(account, Account)
        verify.verify_instance(amount, Decimal)

        if (access_token.branch_code, access_token.account_num) != (
            account.branch_code,
            account.account_num,
        ):
            raise BankSecurityError(
                "Security breach: Token credentials do not match the provided Account."
            )
        account.withdraw(amount)
        self._repository.save_transaction(
            access_token.branch_code, access_token.account_num, -amount
        )

    def get_statement(
        self, access_token: AccessToken, start_date: datetime
    ) -> tuple[dict[str, Any], ...]:
        """
        Retrieves a secure, chronologically ordered bank statement for a given period.

        Operates under a Zero Trust model for data privacy. To avoid the heavy
        hydration of a full Account object, this method bypasses full account retrieval
        but strictly enforces vault authorization via the AccessToken.

        Args:
            access_token (AccessToken): A valid, securely signed vault token.
            start_date (datetime): The cutoff date for filtering transactions.

        Returns:
            tuple[dict[str, Any], ...]: A tuple of dictionaries containing the
                'amount' and 'created_at' of each transaction, ordered newest to oldest.

        Raises:
            TypeError: If the arguments do not match the expected types.
            BankSecurityError: If the AccessToken is tampered with or invalid.
        """
        self._validate_token(access_token)

        verify.verify_instance(start_date, datetime)

        transactions = self._repository.get_transactions(
            access_token.branch_code, access_token.account_num, start_date
        )

        return transactions

    def update_password(self, access_token: AccessToken, new_password: str) -> None:
        """
        Updates the account's password and forces an immediate session invalidation.

        This method operates under a Zero Trust model, requiring full vault access
        to authorize the change. Due to the architecture of the AccessToken (which
        embeds the current password hash in its signature), successfully executing
        this method will immediately invalidate the active token, requiring the
        client to re-authenticate with the new credentials for future operations.

        Args:
            access_token (AccessToken): A valid, securely signed vault token.
            new_password (str): The new 6-digit plain-text password to be set.

        Raises:
            BankSecurityError: If the token is invalid or tampered with.
            BankPasswordError: If the new password format is invalid (e.g., not 6 digits).
            TypeError: If the new password is not a string.
        """
        self._validate_token(access_token)
        Bank.validate_password(new_password)

        hashed_pwd = self._generate_password_hash(new_password)

        self._repository.update_password(
            access_token.branch_code, access_token.account_num, hashed_pwd
        )

    def unfreeze_account(
        self, auth_token: AuthToken, birth_date: date, new_password: str
    ) -> None:
        """
        Recovers and unfreezes a blocked account.

        Requires strict identity verification by comparing the provided birth
        date against the registered client data. Upon success, applies a new
        secure password, resets the login attempts counter, and restores the
        account to active status.

        Args:
            auth_token (AuthToken): A valid, securely signed authentication token.
            birth_date (date): The client's birth date for identity verification.
            new_password (str): The new 6-digit password to be set.

        Raises:
            BankSecurityError: If the AuthToken is tampered with.
            BankPasswordError: If the new password format is invalid.
            AccountAlreadyActiveError: If the account is already operational.
            AuthenticationError: If the provided birth date does not match.
        """
        self._validate_token(auth_token)
        Bank.validate_password(new_password)
        verify.verify_instance(birth_date, date)

        acc_credentials = self._get_account_credentials(
            auth_token.branch_code, auth_token.account_num
        )

        if acc_credentials["is_active"]:
            raise AccountAlreadyActiveError(
                "Impossible to unfreeze an operational account"
            )

        client = self.get_registered_client(auth_token.cpf)

        if client.birth_date != birth_date:
            raise AuthenticationError(
                "The given birth date doesn't match with registered birth date"
            )

        pwd_hash = self._generate_password_hash(new_password)

        self._repository.update_security_credentials(
            auth_token.branch_code, auth_token.account_num, pwd_hash, True
        )

    def close_account(self, access_token: AccessToken) -> None:
        """
        Permanently closes and deletes an account from the system.

        This method enforces a strict business rule: accounts can only be closed
        if their financial balance is exactly zero. It relies on the AccessToken
        to guarantee full vault authorization.

        Args:
            access_token (AccessToken): A valid, securely signed vault token.

        Raises:
            NotEmptyAccountError: If the account has a positive or negative balance.
            BankSecurityError: If the token is invalid or tampered with.
        """
        account_obj = self.get_account(access_token)

        if account_obj.balance != 0:
            raise NotEmptyAccountError("Account has a non-zero balance")

        self._repository.delete_account(account_obj)
