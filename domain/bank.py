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
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import ClassVar

import bcrypt

from infra import verify
from infra.mysql_repository import MySQLRepository
from shared.credentials import AccessToken, AccountCard, AuthToken
from shared.dtos import (
    AccountFinancialDTO,
    AccountSummaryDTO,
    NewAccountDTO,
    NewAccountHolderDTO,
    StatementDTO,
)
from shared.exceptions import (
    AccountAlreadyActiveError,
    AccountHolderNotFoundError,
    AccountNotFoundError,
    BankAccessError,
    BankAuthenticationError,
    BankPasswordError,
    BankSecurityError,
    BankUnavailableError,
    DataNotFoundError,
    DuplicatedAccountError,
    DuplicatedAccountHolderError,
    DuplicatedDataError,
    ExpiredTokenError,
    FrozenAccountError,
    HomeBranchRestrictionError,
    NotEmptyAccountError,
    RepositoryError,
)

from .account import Account, CheckingAccount, SavingsAccount
from .person import AccountHolder


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
        LOBBY_TIME_MINUTES (ClassVar[timedelta]): The strict Time-To-Live (TTL)
            duration for an AuthToken, defining how long a client can remain
            in the unauthenticated lobby.
        VAULT_TIME_MINUTES (ClassVar[timedelta]): The strict Time-To-Live (TTL)
            duration for an AccessToken, defining the maximum duration of a
            highly sensitive, authenticated vault session.
    """

    MAX_LOGIN_ATTEMPTS: ClassVar[int] = 3
    LOBBY_TIME_MINUTES: ClassVar[timedelta] = timedelta(minutes=5)
    VAULT_TIME_MINUTES: ClassVar[timedelta] = timedelta(minutes=2)

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
        return f"{class_name}(name={self._bank_name!r}, branch_code={self._branch_code!r}),"

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
            TypeError: If the password is not a string (indicates a system type bug).
            BankPasswordError: If the password does not consist of exactly 6 digits.
        """
        verify.verify_instance(password, str)
        try:
            verify.verify_digits(password, 6)
        except ValueError as e:
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
            BankAuthenticationError: If the password does not match the hash.
        """
        pdw_bytes = pwd_str.encode("utf-8")
        hashed_pwd_bytes = pwd_hash_str.encode("utf-8")

        if not bcrypt.checkpw(pdw_bytes, hashed_pwd_bytes):
            raise BankAuthenticationError(
                "Given password doesn't match with registered password"
            )

    def _validate_token_integrity(
        self, token: AccessToken | AuthToken, pwd_hash: str = ""
    ) -> None:
        """
        Validates the cryptographic integrity and Time-To-Live (TTL) of a session token.

        Enforces a strict Zero Trust model by focusing solely on mathematical and
        cryptographic validity, adhering to the Single Responsibility Principle.
        It does not interact with the database; instead, it relies on the injected
        'pwd_hash' (for Vault access) to reconstruct and verify the expected signature.

        1. TTL Check: Prevents the use of expired sessions globally (Fail-Fast).
        2. AuthToken (Lobby): Reconstructs the payload using static embedded data.
        3. AccessToken (Vault): Reconstructs the payload using the injected password
           hash. If the hash provided by the caller is empty or changed, the
           cryptographic signature will naturally mismatch, invalidating the session.

        Args:
            token (AccessToken | AuthToken): The session token to be validated.
            pwd_hash (str, optional): The current password hash provided by the caller.
                Required for AccessToken validation; ignored for AuthToken. Defaults to "".

        Raises:
            ExpiredTokenError: If the token's TTL has passed.
            BankSecurityError: If the cryptographic signature has been tampered with
                or if the provided hash causes a signature mismatch.
            TypeError: If the provided token object is not a valid recognized instance.
        """
        if datetime.now() > token.expires_at:
            raise ExpiredTokenError(
                "This token is no longer valid because it has expired"
            )

        match token:
            case AuthToken():
                payload = f"{token.cpf}:{token.branch_code}:{token.account_num}"
            case AccessToken():
                payload = (
                    f"{token.cpf}:{token.branch_code}:{token.account_num}:{pwd_hash}"
                )
            case _:
                raise TypeError("Invalid token instance")

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
            expires_at=datetime.now() + Bank.LOBBY_TIME_MINUTES,
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
        payload = f"{auth_token.cpf}:{auth_token.branch_code}:{auth_token.account_num}:{password_hash}"
        signature = self._sign_token_payload(payload)

        return AccessToken(
            cpf=auth_token.cpf,
            branch_code=auth_token.branch_code,
            account_num=auth_token.account_num,
            signature=signature,
            expires_at=datetime.now() + Bank.VAULT_TIME_MINUTES,
        )

    def _account_factory(self, account_dto: NewAccountDTO) -> Account:
        """
        Internal factory to instantiate Account entities from a DTO.

        Translates the integer flag within the DTO into the correct Account
        subclass (CheckingAccount or SavingsAccount), keeping the Presentation
        layer entirely decoupled from Domain implementations.

        Args:
            account_dto (NewAccountDTO): The immutable payload from the UI.

        Returns:
            Account: A fully initialized domain Account instance.
        """
        type_mapper = {1: CheckingAccount, 2: SavingsAccount}

        acc_type = type_mapper[account_dto.account_type]
        account_obj = acc_type(
            account_dto.branch_code,
            account_dto.account_num,
        )

        return account_obj

    def _account_holder_factory(
        self, acc_holder_dto: NewAccountHolderDTO
    ) -> AccountHolder:
        """
        Internal factory to instantiate an AccountHolder entity from a DTO.

        Args:
            acc_holder_dto (NewAccountHolderDTO): The immutable payload containing the new account holder's data.

        Returns:
            AccountHolder: A fully initialized domain AccountHolder instance.
        """
        holder_obj = AccountHolder(
            acc_holder_dto.name, acc_holder_dto.cpf, acc_holder_dto.birth_date
        )

        return holder_obj

    def _get_account_holder(self, cpf: str) -> AccountHolder:
        """
        Retrieves a fully hydrated account holder entity from the repository.

        Args:
            cpf (str): The 11-digit string representing the account holder's CPF.

        Returns:
            AccountHolder: The domain AccountHolder object.

        Raises:
            AccountHolderNotFoundError: If the CPF is not registered in the system.
        """
        try:
            holder_obj = self._repository.get_account_holder(cpf=cpf)
            return holder_obj
        except DataNotFoundError as e:
            raise AccountHolderNotFoundError(
                "No account holder registered under this CPF"
            ) from e

    def register_account(
        self,
        account_dto: NewAccountDTO,
        holder_dto_or_cpf: NewAccountHolderDTO | str,
        password: str,
    ) -> None:
        """
        Registers a newly created account and links it to an account holder.

        Acts as the strict Domain boundary for the onboarding process.
        It accepts immutable Data Transfer Objects (DTOs) from the Presentation
        layer, delegates instantiation to internal factories, securely hashes
        the password, and persists the domain entities via the repository.

        Args:
            account_dto (NewAccountDTO): The immutable payload containing account setup data.
            holder_dto_or_cpf (NewAccountHolderDTO | str): The payload for a new account holder, or an existing holder's CPF.
            password (str): The raw 6-digit password for the new account.

        Raises:
            TypeError: If any arguments do not match expected types.
            BankPasswordError: If the password format is invalid.
            DuplicatedAccountError: If the account number is already taken.
            DuplicatedAccountHolderError: If a new account holder CPF is already registered.
            AccountHolderNotFoundError: If an existing account holder CPF is not found.
            BankUnavailableError: If the operation fails due to an internal database error.
        """
        verify.verify_instance(account_dto, NewAccountDTO)
        verify.verify_instance(holder_dto_or_cpf, (str, NewAccountHolderDTO))
        verify.verify_instance(password, str)
        Bank.validate_password(password)

        new_account = self._account_factory(account_dto)

        if isinstance(holder_dto_or_cpf, NewAccountHolderDTO):
            holder_or_cpf = self._account_holder_factory(holder_dto_or_cpf)
        elif isinstance(holder_dto_or_cpf, str):
            holder_or_cpf = holder_dto_or_cpf

        pwd_hash = self._generate_password_hash(password_str=password)

        try:
            self._repository.register_account_bundle(
                new_account, holder_or_cpf, pwd_hash
            )
        except DuplicatedDataError as e:
            error_argument = e.argument

            if isinstance(error_argument, (AccountHolder, str)):
                raise DuplicatedAccountHolderError(
                    "Account holder already registered in the system"
                ) from e

            if isinstance(error_argument, Account):
                raise DuplicatedAccountError(
                    "Account already registered in the system"
                ) from e
        except DataNotFoundError:
            raise AccountHolderNotFoundError(
                "No account holder registered under this CPF"
            )
        except RepositoryError:
            raise BankUnavailableError(
                "The intended operation could not be persisted due to an internal error"
            )

    def check_account_holder_exists(self, cpf: str) -> bool:
        """
        Verifies if an account holder is registered in the banking system.

        This is a highly optimized, lightweight check that queries the repository
        without hydrating the full AccountHolder domain entity. Ideal for pre-validation
        during onboarding workflows.

        Args:
            cpf (str): The 11-digit string representing the account holder's CPF.

        Returns:
            bool: True if the account holder exists, False otherwise.

        Raises:
            TypeError: If the provided CPF is not a string.
        """
        verify.verify_instance(cpf, str)

        return self._repository.account_holder_exists(cpf)

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

    def get_account_holder_cards(self, cpf: str) -> list[AccountCard]:
        """
        Safely retrieves the list of registered account cards for an account holder.

        Acts as a secure data gateway, extracting Data Transfer Objects (DTOs)
        from the rich AccountHolder entity. This prevents Domain leakage, ensuring the
        Presentation layer can display available cards without gaining direct
        access to the AccountHolder object's internal state or business methods.

        Args:
            cpf (str): The 11-digit string representing the account holder's CPF.

        Returns:
            list[AccountCard]: A list of lightweight, immutable card representations.

        Raises:
            TypeError: If the provided CPF is not a string.
            AccountHolderNotFoundError: If the provided CPF is not registered in the system.
        """
        verify.verify_instance(cpf, str)

        holder = self._get_account_holder(cpf)

        return holder.cards

    def authenticate(self, cpf: str, branch_code: str, account_num: str) -> AuthToken:
        """
        Authenticates an account holder's claim to an account and issues a stateless token.

        This is the "Lobby" access. It does not open the vault or check if the
        account is frozen. It merely verifies ownership and issues an AuthToken
        that can be used for subsequent secure operations.

        Operates using optimized data fetching via the micro-ORM, completely bypassing
        domain entity hydration to ensure maximum throughput during read-only logins.

        Args:
            cpf (str): The 11-digit string representing the account holder's CPF.
            branch_code (str): The branch code of the target account.
            account_num (str): The target account number.

        Returns:
            AuthToken: A securely signed, stateless authentication token.

        Raises:
            TypeError: If any of the provided arguments are not strings.
            BankAuthenticationError: If the account does not exist, or if the
                requested account does not belong to the provided CPF (prevents
                user enumeration).
            RuntimeError: If the repository fails to return the requested DTO state.
        """
        verify.verify_instance(cpf, str)
        verify.verify_instance(branch_code, str)
        verify.verify_instance(account_num, str)

        try:
            account_info = self._repository.get_account_projection(
                branch_code, account_num, holder_info=True
            )
        except DataNotFoundError:
            raise BankAuthenticationError(
                "Authentication failed: Account not found in system register"
            )

        if not account_info.holder_info:
            raise RuntimeError("Invalid DTO state")

        if account_info.holder_info.cpf != cpf:
            raise BankAuthenticationError(
                "Authentication failed: Account not linked to this client"
            )

        return self._generate_auth_token(
            cpf=cpf, branch_code=branch_code, account_num=account_num
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

        Raises:
            ExpiredTokenError: If the token's TTL has passed.
            BankSecurityError: If the cryptographic signature of the token is invalid
                or has been tampered with.
            BankAuthenticationError: If the account no longer exists in the repository.
            RuntimeError: If the repository fails to return the requested DTO state.
        """
        self._validate_token_integrity(auth_token)
        try:
            account_info = self._repository.get_account_projection(
                auth_token.branch_code, auth_token.account_num, access_info=True
            )
        except DataNotFoundError as e:
            raise BankAuthenticationError("Account no longer exists") from e

        if not account_info.access_info:
            raise RuntimeError("Invalid DTO state")

        return self.MAX_LOGIN_ATTEMPTS - account_info.access_info.failed_attempts

    def authorize_vault_access(
        self, auth_token: AuthToken, password: str
    ) -> AccessToken:
        """
        The primary security checkpoint and brute-force mitigation mechanism.

        This method upgrades 'Lobby' access (AuthToken) to 'Vault' access
        (AccessToken). Operating under a Zero Trust model, it verifies the
        token's integrity and validates the password against the stored Bcrypt hash.

        To simulate real-world ATM behavior, it explicitly denies vault access to
        frozen accounts, preventing any operations (including read-only views) until
        the account is formally unfrozen via identity verification.

        To mitigate brute-force attacks, it tracks failed login attempts. It employs
        an isolated state transaction (Unit of Work) with exclusive access control
        to guarantee that login failures are reliably recorded and the account is
        frozen if the maximum threshold is reached, seamlessly preventing TOCTOU
        race conditions during the security update.

        Args:
            auth_token (AuthToken): A valid, securely signed authentication token.
            password (str): The raw 6-digit password provided by the user.

        Returns:
            AccessToken: The cryptographic key granting full vault access.

        Raises:
            ExpiredTokenError: If the provided AuthToken has passed its Time-To-Live (TTL).
            BankPasswordError: If the provided password format is invalid.
            BankSecurityError: If the AuthToken is tampered with, or if the account
                no longer exists (TOCTOU mitigation).
            BankAccessError: If the account is already frozen, or if it reaches
                the maximum allowed failed login attempts during this check.
            BankAuthenticationError: If the provided password does not match the hash.
            BankUnavailableError: If the validation or security updates could not
                be persisted due to an internal infrastructure error.
        """
        Bank.validate_password(password)
        self._validate_token_integrity(auth_token)

        with self._repository.unit_of_work():
            try:
                account_info = self._repository.get_account_projection(
                    auth_token.branch_code,
                    auth_token.account_num,
                    access_info=True,
                    for_update=True,
                )
            except DataNotFoundError as e:
                raise BankAuthenticationError(
                    "Authentication failed: Account no longer exists"
                ) from e

            is_frozen = account_info["is_frozen"]
            pwd_hash = account_info["password_hash"]
            failed_attempts = account_info["failed_login_attempts"]

            if is_frozen:
                raise BankAccessError("This account is blocked and cannot be accessed")

            auth_exception = None
            access_exception = None

            try:
                self._check_password(password, pwd_hash)
            except BankAuthenticationError as e:
                auth_exception = e

            if not auth_exception:
                if not failed_attempts:
                    return self._generate_access_token(
                        auth_token=auth_token,
                        password_hash=account_info["password_hash"],
                    )

                try:
                    self._repository.reset_login_attempts(
                        auth_token.branch_code, auth_token.account_num
                    )
                    return self._generate_access_token(
                        auth_token=auth_token,
                        password_hash=account_info["password_hash"],
                    )
                except DataNotFoundError as e:
                    raise BankSecurityError(
                        "Security breach or race condition: Account no longer exists"
                    ) from e
                except RepositoryError as e:
                    raise BankUnavailableError(
                        "The intended operation could not be persisted due to an internal error"
                    ) from e

            try:
                self._repository.register_failed_login(
                    auth_token.branch_code, auth_token.account_num
                )
                if (failed_attempts + 1) >= self.MAX_LOGIN_ATTEMPTS:
                    account = self._get_account(
                        auth_token.branch_code,
                        auth_token.account_num,
                        for_update=True,
                    )
                    account.freeze()
                    self._repository.update_account_status(account)

                    access_exception = BankAccessError(
                        "The account was frozen due to 3 consecutive failed login attempts"
                    )
            except (AccountNotFoundError, DataNotFoundError) as e:
                raise BankSecurityError(
                    "Security breach or race condition: Account no longer exists"
                ) from e
            except RepositoryError as e:
                raise BankUnavailableError(
                    "The intended operation could not be persisted due to an internal error"
                ) from e

        raise access_exception or auth_exception

    def get_account_summary(self, auth_token: AuthToken) -> AccountSummaryDTO:
        """
        Safely retrieves basic identity and status information for an authenticated session.

        Operates under the Identity-First security model. It uses a validated AuthToken
        (Lobby access) to fetch non-sensitive data, returning an immutable AccountSummaryDTO.
        This allows external controllers to greet the user and verify account status
        (active/frozen) before attempting any high-privilege operations.

        Args:
            auth_token (AuthToken): A stateless token proving account ownership and identity.

        Returns:
            AccountSummaryDTO: An immutable snapshot containing basic account routing
                and status flags.

        Raises:
            ExpiredTokenError: If the token's TTL has passed.
            BankSecurityError: If the token is invalid, tampered with, or if the account
                state has been compromised during the session (TOCTOU mitigation).
            BankAuthenticationError: If the underlying account or holder no longer exists
                in the repository, invalidating the session state.
            RuntimeError: If the repository fails to return the requested DTO state.
        """
        self._validate_token_integrity(auth_token)
        try:
            account_info = self._repository.get_account_projection(
                auth_token.branch_code, auth_token.account_num, holder_info=True
            )
        except DataNotFoundError:
            raise BankAuthenticationError(
                "Authentication failed: Account no longer exists"
            )

        if not account_info.holder_info:
            raise RuntimeError("Invalid DTO state")

        return AccountSummaryDTO(
            holder_name=account_info.holder_info.name,
            branch_code=account_info.branch_code,
            account_num=account_info.account_num,
            account_type=account_info.account_type,
            is_frozen=account_info.is_frozen,
        )

    def get_financial_summary(self, access_token: AccessToken) -> AccountFinancialDTO:
        """
        Safely retrieves a read-only snapshot of an authenticated account's current financial state.

        Operates under a strict Zero Trust model. It fetches the necessary projection and
        full account entity using the securely validated AccessToken, combining this data
        into an immutable AccountFinancialDTO. This acts as a secure read-only facade,
        preventing full domain entities from leaking into external layers.

        Args:
            access_token (AccessToken): A valid, securely signed vault token containing
                the account holder's identity for resolution.

        Returns:
            AccountFinancialDTO: An immutable snapshot containing the holder's name, account
                branch, number, raw account type, balance, and overdraft information.

        Raises:
            ExpiredTokenError: If the token's TTL has passed.
            BankSecurityError: If the token is invalid or tampered with.
            BankAuthenticationError: If the account or holder no longer exists in the
                repository (TOCTOU mitigation).
            RuntimeError: If the repository fails to return the requested DTO state.
        """
        try:
            account_info = self._repository.get_account_projection(
                access_token.branch_code,
                access_token.account_num,
                access_info=True,
                holder_info=True,
            )
            account_obj = self._repository.get_account(
                access_token.branch_code, access_token.account_num
            )
        except DataNotFoundError:
            raise BankAuthenticationError(
                "Authentication failed: Account no longer exists"
            )

        if not account_info.access_info or not account_info.holder_info:
            raise RuntimeError("Invalid DTO state")

        pwd_hash = account_info.access_info.password_hash
        self._validate_token_integrity(access_token, pwd_hash)

        overdraft_limit = available_overdraft = None

        if isinstance(account_obj, CheckingAccount):
            overdraft_limit = account_obj.OVERDRAFT_LIMIT
            available_overdraft = account_obj.available_overdraft

        return AccountFinancialDTO(
            holder_name=account_info.holder_info.name,
            branch_code=account_info.branch_code,
            account_num=account_info.account_num,
            account_type=account_info.account_type,
            balance=account_obj.balance,
            overdraft_limit=overdraft_limit,
            available_overdraft=available_overdraft,
        )

    def execute_deposit(
        self,
        branch_code: str,
        account_num: str,
        amount: Decimal,
    ) -> None:
        """
        Executes a secure, public-facing deposit operation.

        This method bypasses 'Vault' access (no password required) to allow fast
        deposits from third parties. It operates under a strict Unit of Work with
        pessimistic locking (FOR UPDATE) to prevent race conditions. It strictly
        respects Domain boundaries by hydrating the target Account entity and
        delegating all mathematical and state-mutating logic to it (Tell, Don't Ask).

        Args:
            branch_code (str): The branch code of the target account.
            account_num (str): The target account number.
            amount (Decimal): The positive amount to be deposited.

        Raises:
            TypeError: If the arguments are not of the expected types.
            InvalidDepositError: If the deposit amount violates business rules.
            BankAccessError: If the target account is currently frozen, translating
                the domain-level BlockedAccountError for the presentation layer.
            AccountNotFoundError: If the provided branch or account number does not exist.
            BankUnavailableError: If the deposit could not be persisted due to an internal error.
        """
        verify.verify_instance(branch_code, str)
        verify.verify_instance(account_num, str)
        verify.verify_instance(amount, Decimal)
        Account.validate_account_deposit(amount)

        try:
            with self._repository.unit_of_work():
                account_obj = self._repository.get_account(
                    branch_code, account_num, for_update=True
                )
                try:
                    transaction_type = account_obj.deposit(amount)
                except FrozenAccountError as e:
                    raise BankAccessError(
                        "This account is frozen and cannot be accessed"
                    ) from e
                self._repository.save_transaction(account_obj, amount, transaction_type)
        except DataNotFoundError as e:
            raise AccountNotFoundError(
                "The requested account does not exist in our records"
            ) from e
        except RepositoryError as e:
            raise BankUnavailableError(
                "The intended operation could not be persisted due to an internal error"
            ) from e

    def execute_withdraw(
        self, access_token: AccessToken, amount: Decimal, use_overdraft: bool = False
    ) -> None:
        """
        Executes a secure withdrawal operation and persists it to the database.

        This method operates under a 'Zero Trust' security model. Acting as the
        Aggregate Root, the Bank resolves the target Account strictly from the
        provided AccessToken, ensuring no external layer can inject a tampered
        Account entity.

        It utilizes a Unit of Work with a pessimistic lock to guarantee exclusive
        access during the transaction. It delegates the mathematical evaluation,
        status checks, and limit usage directly to the hydrated Account instance.

        Args:
            access_token (AccessToken): A valid, securely signed vault token.
            amount (Decimal): The positive monetary amount to be withdrawn.
            use_overdraft (bool, optional): Explicit authorization to utilize the
                account's credit limit if the amount exceeds the standard balance.
                Defaults to False.

        Raises:
            TypeError: If the arguments are not of the expected types.
            ExpiredTokenError: If the token's TTL has passed.
            BankSecurityError: If the cryptographic signature of the token is invalid
                or has been tampered with.
            BankAuthenticationError: If the account was deleted during the active
                session (TOCTOU mitigation).
            BankAccessError: If the target account is frozen during the operation.
            OverdraftRequiredError: If the requested amount exceeds the balance
                and explicit overdraft consent (`use_overdraft=True`) was not provided.
            InvalidWithdrawError: If the withdrawal amount violates business rules
                (e.g., negative amount, exceeds total available funds).
            BankUnavailableError: If the transaction could not be persisted due to an
                internal database error.
            RuntimeError: If the repository fails to return the requested DTO state.
        """
        verify.verify_instance(amount, Decimal)
        verify.verify_instance(use_overdraft, bool)

        try:
            account_info = self._repository.get_account_projection(
                access_token.branch_code, access_token.account_num, access_info=True
            )
        except DataNotFoundError as e:
            raise BankAuthenticationError(
                "Authentication failed: Account no longer exists"
            ) from e

        if not account_info.access_info:
            raise RuntimeError("Invalid DTO state")

        self._validate_token_integrity(
            access_token, account_info.access_info.password_hash
        )

        try:
            with self._repository.unit_of_work():
                account = self._repository.get_account(
                    access_token.branch_code, access_token.account_num, for_update=True
                )
                try:
                    transaction_type = account.withdraw(
                        amount, use_overdraft=use_overdraft
                    )
                except FrozenAccountError:
                    raise BankAccessError(
                        "This account is frozen and cannot be accessed"
                    )
                self._repository.save_transaction(account, -amount, transaction_type)
        except DataNotFoundError as e:
            raise BankAuthenticationError(
                "Authentication failed: Account no longer exists"
            ) from e
        except RepositoryError as e:
            raise BankUnavailableError(
                "The intended operation could not be persisted due to an internal error"
            ) from e

    def generate_statement(
        self, access_token: AccessToken, start_date: datetime
    ) -> StatementDTO:
        """
        Retrieves a mathematically consistent, chronologically ordered bank statement.

        Operates under a Zero Trust model for data privacy. It employs a read-only
        Unit of Work to guarantee that the account balance (via AccountFinancialDTO) and
        the transaction history are evaluated with strict temporal consistency,
        reflecting the exact same moment in time. It incorporates TOCTOU mitigation
        to ensure the account has not been deleted mid-session.

        Args:
            access_token (AccessToken): A valid, securely signed vault token.
            start_date (datetime): The cutoff date for filtering transactions.

        Returns:
            StatementDTO: An immutable snapshot combining the account's financial details,
                current balance, and chronological transaction history.

        Raises:
            TypeError: If the arguments do not match the expected types.
            ExpiredTokenError: If the token's TTL has passed.
            BankSecurityError: If the AccessToken's cryptographic signature is invalid
                or has been tampered with.
            BankAuthenticationError: If the account was deleted during the active session
                (TOCTOU mitigation).
            RuntimeError: If the repository fails to return the requested DTO state.
        """
        verify.verify_instance(start_date, datetime)
        try:
            with self._repository.unit_of_work():
                financial_info_dto = self.get_financial_summary(access_token)
                transactions = self._repository.get_transactions(
                    access_token.branch_code, access_token.account_num, start_date
                )
        except DataNotFoundError as e:
            raise BankAuthenticationError(
                "Authentication failed: Account no longer exists"
            ) from e

        return StatementDTO(account_info=financial_info_dto, transactions=transactions)

    def update_password(self, access_token: AccessToken, new_password: str) -> None:
        """
        Updates the account's password and forces an immediate session invalidation.

        This method operates under a Zero Trust model, requiring full vault access
        to authorize the change. It explicitly denies password updates for frozen
        accounts to maintain strict security boundaries.

        It employs an isolated state transaction (Unit of Work) with exclusive
        access control (Pessimistic Lock) to prevent concurrent modifications or
        brute-force attacks during the password hashing process. Due to the architecture
        of the AccessToken (which embeds the current password hash in its signature),
        successfully executing this method will immediately invalidate the active
        token, requiring the client to re-authenticate for future operations.

        Args:
            access_token (AccessToken): A valid, securely signed vault token.
            new_password (str): The new 6-digit plain-text password to be set.

        Raises:
            TypeError: If the new password is not a string.
            BankPasswordError: If the new password format is invalid (e.g., not 6 digits).
            ExpiredTokenError: If the token's TTL has passed.
            BankSecurityError: If the token's cryptographic signature is invalid
                or has been tampered with.
            BankAuthenticationError: If the account no longer exists during the active
                session (TOCTOU mitigation).
            BankAccessError: If the account is currently frozen, blocking the update.
            BankUnavailableError: If the update could not be persisted due to an internal error.
            RuntimeError: If the repository fails to return the requested DTO state.
        """
        Bank.validate_password(new_password)

        try:
            with self._repository.unit_of_work():
                account_info = self._repository.get_account_projection(
                    access_token.branch_code,
                    access_token.account_num,
                    access_info=True,
                    for_update=True,
                )
                if not account_info.access_info:
                    raise RuntimeError("Invalid DTO state")

                self._validate_token_integrity(
                    access_token, account_info.access_info.password_hash
                )

                if account_info.is_frozen:
                    raise BankAccessError(
                        "This account is frozen and cannot be accessed"
                    )
                hashed_pwd = self._generate_password_hash(new_password)

                self._repository.update_password(
                    access_token.branch_code, access_token.account_num, hashed_pwd
                )
        except DataNotFoundError as e:
            raise BankAuthenticationError(
                "Authentication failed: Account no longer exists"
            ) from e
        except RepositoryError as e:
            raise BankUnavailableError(
                "The intended operation could not be persisted due to an internal error"
            ) from e

    def unfreeze_account(
        self, auth_token: AuthToken, birth_date: date, new_password: str
    ) -> None:
        """
        Recovers and unfreezes a frozen account using strict identity verification.

        This method upgrades a standard authentication attempt into a recovery
        operation. It enforces strict state isolation (Unit of Work with exclusive
        access control) to ensure the account cannot be mutated or deleted by
        concurrent processes during the recovery.

        It utilizes a micro-ORM projection for rapid validation before hydrating
        the full Domain entity. It verifies the provided birth date, delegates the
        state change to the Account, applies a new secure password, resets the login
        attempts counter, and persists the active status.

        Args:
            auth_token (AuthToken): A valid, securely signed authentication token.
            birth_date (date): The account holder's birth date for identity verification.
            new_password (str): The new 6-digit password to be set.

        Raises:
            TypeError: If the arguments are not of the expected types.
            ExpiredTokenError: If the token's TTL has passed.
            BankSecurityError: If the cryptographic signature of the token is invalid
                or has been tampered with.
            BankAuthenticationError: If the provided birth date is incorrect, or if
                the account/holder no longer exists (TOCTOU mitigation).
            BankPasswordError: If the new password format is invalid.
            AccountAlreadyActiveError: If the account is already operational.
            BankUnavailableError: If the operation could not be persisted due to
                an internal database error.
            RuntimeError: If the repository fails to return the requested DTO state.
        """
        Bank.validate_password(new_password)
        verify.verify_instance(birth_date, date)
        self._validate_token_integrity(auth_token)

        try:
            with self._repository.unit_of_work():
                account_info = self._repository.get_account_projection(
                    auth_token.branch_code,
                    auth_token.account_num,
                    holder_info=True,
                    for_update=True,
                )

                if not account_info.holder_info:
                    raise RuntimeError("Invalid DTO state")

                if not account_info.is_frozen:
                    raise AccountAlreadyActiveError(
                        "Operational accounts cannot be unfrozen"
                    )

                if account_info.holder_info.birth_date != birth_date:
                    raise BankAuthenticationError(
                        "The given birth date doesn't match with registered birth date"
                    )

                new_hash = self._generate_password_hash(new_password)

                self._repository.update_password(
                    auth_token.branch_code, auth_token.account_num, new_hash
                )
                self._repository.reset_login_attempts(
                    auth_token.branch_code, auth_token.account_num
                )

                account = self._repository.get_account(
                    auth_token.branch_code, auth_token.account_num, for_update=True
                )

                account.unfreeze()
                self._repository.update_account_status(account)
        except DataNotFoundError as e:
            raise BankAuthenticationError(
                "Authentication failed: Account no longer exists"
            ) from e
        except RepositoryError as e:
            raise BankUnavailableError(
                "The intended operation could not be persisted due to an internal error"
            ) from e

    def close_account(self, access_token: AccessToken) -> None:
        """
        Permanently closes and deletes an account from the system.

        This method enforces strict business and security rules:
        1. Home Branch Rule: The operation must be executed at the exact
           branch where the account is registered.
        2. Active Status Rule: The account must be fully operational; frozen
           accounts cannot be closed to prevent evasion of security blocks.
        3. Zero Balance Rule: The account can only be closed if its financial
           balance is exactly zero.

        It employs a Unit of Work with exclusive read/write access to ensure
        strict state isolation, preventing concurrent transactions from modifying
        the balance or status during the closure process. It relies on the
        AccessToken to guarantee full vault authorization.

        Args:
            access_token (AccessToken): A valid, securely signed vault token.

        Raises:
            ExpiredTokenError: If the token's TTL has passed.
            HomeBranchRestrictionError: If the account's branch does not match
                the current terminal's branch.
            BankAccessError: If the account is currently frozen, blocking the closure.
            NotEmptyAccountError: If the account has a positive or negative balance.
            BankSecurityError: If the token's cryptographic signature is invalid
                or has been tampered with.
            BankAuthenticationError: If the account no longer exists in the
                repository (TOCTOU mitigation).
            RuntimeError: If the repository fails to return the requested DTO state.
            BankUnavailableError: If the deletion could not be executed due to
                an internal database error.
        """
        if access_token.branch_code != self._branch_code:
            raise HomeBranchRestrictionError(
                "Account closure can only be performed at the home branch"
            )

        try:
            with self._repository.unit_of_work():
                account_info = self._repository.get_account_projection(
                    access_token.branch_code,
                    access_token.account_num,
                    access_info=True,
                    financial_info=True,
                    for_update=True,
                )

                if not account_info.financial_info or not account_info.access_info:
                    raise RuntimeError("Invalid DTO state")

                self._validate_token_integrity(
                    access_token, account_info.access_info.password_hash
                )

                if account_info.is_frozen:
                    raise BankAccessError("This account is frozen and cannot be closed")

                if account_info.financial_info.balance != 0:
                    raise NotEmptyAccountError(
                        "The account cannot be closed because it has a non-zero balance"
                    )

                self._repository.delete_account(
                    access_token.branch_code, access_token.account_num
                )
        except DataNotFoundError as e:
            raise BankAuthenticationError(
                "Authentication failed: Account no longer exists"
            ) from e
        except RepositoryError as e:
            raise BankUnavailableError(
                "The intended operation could not be persisted due to an internal error"
            ) from e
