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
from typing import Any, ClassVar

import bcrypt
from infra import verify
from infra.mysql_repository import MySQLRepository
from shared.credentials import AccessToken, AccountCard, AuthToken
from shared.dtos import (
    AccountInfoDTO,
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

    def _validate_token(self, token: AccessToken | AuthToken) -> None:
        """
        Validates the cryptographic integrity, Time-To-Live (TTL), and authenticity
        of a session token.

        Operates seamlessly with both AuthToken (Lobby access) and AccessToken
        (Vault access). It enforces a strict Zero Trust model by:
        1. Checking the TTL to prevent the use of expired sessions (Fail-Fast).
        2. Unconditionally verifying the account's existence in the repository
           before checking the signature, mitigating Time-of-Check to Time-of-Use
           (TOCTOU) race conditions.

        For AccessTokens, it dynamically reconstructs the expected payload using
        the client's CPF and the freshest password hash, acting as an automatic
        session invalidator if the user's password was recently changed.

        Args:
            token (AccessToken | AuthToken): The token instance to be validated.

        Raises:
            ExpiredTokenError: If the token's TTL has passed.
            BankSecurityError: If the token instance is unknown, if the account
                no longer exists (TOCTOU mitigation), or if the cryptographic
                signature has been tampered with or invalidated.
        """
        if datetime.now() > token.expires_at:
            raise ExpiredTokenError(
                "This token is no longer valid because it has expired"
            )

        try:
            acc_credentials = self._get_account_credentials(
                token.branch_code, token.account_num
            )
        except AccountNotFoundError as e:
            raise BankSecurityError(
                "Security breach or race condition: Account no longer exists"
            ) from e

        match token:
            case AuthToken():
                payload = f"{token.cpf}:{token.branch_code}:{token.account_num}"
            case AccessToken():
                pwd_hash = acc_credentials["password_hash"]
                payload = (
                    f"{token.cpf}:{token.branch_code}:{token.account_num}:{pwd_hash}"
                )
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

    def _get_account(
        self, branch_code: str, account_num: str, for_update: bool = False
    ) -> Account:
        """
        Internal gateway to fetch an active, fully hydrated Account entity.

        This is an internal Trust Zone method. It acts as a neutral data provider,
        translating infrastructure misses into domain-specific misses. It relies
        on the calling public method to determine the security implications of
        a missing account.

        Args:
            branch_code (str): The branch code.
            account_num (str): The account number.
            for_update (bool): If True, signals the persistence mechanism to grant
                exclusive access to this entity for state mutation, preventing
                race conditions during an active Unit of Work. Defaults to False.

        Returns:
            Account: The fully hydrated Account domain entity.

        Raises:
            AccountNotFoundError: If the account does not exist in the repository.
            RuntimeError: If `for_update` is True but the method is called outside
                an active repository transaction.
        """

        try:
            return self._repository.get_account(branch_code, account_num, for_update)
        except DataNotFoundError as e:
            raise AccountNotFoundError(
                "The requested account does not exist in our records"
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
        that can be used for subsequent secure operations. This method securely
        hydrates the AccountHolder entity internally to prevent domain leakage.

        Args:
            cpf (str): The 11-digit string representing the account holder's CPF.
            branch_code (str): The branch code of the target account.
            account_num (str): The target account number.

        Returns:
            AuthToken: A securely signed, stateless authentication token.

        Raises:
            TypeError: If any of the provided arguments are not strings.
            BankAuthenticationError: If the provided CPF is not registered, or if the
                requested account does not belong to the account holder (prevents user enumeration).
        """
        verify.verify_instance(cpf, str)
        verify.verify_instance(branch_code, str)
        verify.verify_instance(account_num, str)

        try:
            holder = self._get_account_holder(cpf)
        except AccountHolderNotFoundError as e:
            raise BankAuthenticationError("Holder not found in system register") from e

        temp_card = AccountCard(holder.cpf, branch_code, account_num)

        if not holder.has_account(temp_card):
            raise BankAuthenticationError(
                "Account card not found between account holder's cards"
            )

        return self._generate_auth_token(
            cpf=holder.cpf, branch_code=branch_code, account_num=account_num
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
        The primary security checkpoint and brute-force mitigation mechanism.

        This method upgrades 'Lobby' access (AuthToken) to 'Vault' access
        (AccessToken). Operating under a Zero Trust model, it verifies the
        token's integrity and validates the password against the stored Bcrypt hash.

        To simulate real-world ATM behavior, it explicitly denies vault access to
        frozen accounts, preventing any operations (including read-only views) until
        the account is formally unfrozen via identity verification.

        To mitigate brute-force attacks, it tracks failed login attempts. If the
        maximum threshold is reached, it employs a Unit of Work with pessimistic
        concurrency control to safely fetch and freeze the account, preventing
        Time-of-Check to Time-of-Use (TOCTOU) race conditions during the
        status update.

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
        self._validate_token(auth_token)

        try:
            acc_credentials = self._get_account_credentials(
                auth_token.branch_code, auth_token.account_num
            )
        except AccountNotFoundError as e:
            raise BankSecurityError(
                "Security breach or race condition: Account no longer exists"
            ) from e

        if not acc_credentials["is_active"]:
            raise BankAccessError("This account is blocked and cannot be accessed")

        branch_code = auth_token.branch_code
        account_num = auth_token.account_num
        hashed_pwd = acc_credentials["password_hash"]
        failed_logins = acc_credentials["failed_login_attempts"]

        try:
            self._check_password(password, hashed_pwd)

            if failed_logins > 0:
                self._repository.reset_login_attempts(branch_code, account_num)

            return self._generate_access_token(
                auth_token=auth_token, password_hash=hashed_pwd
            )
        except BankAuthenticationError:
            try:
                self._repository.register_failed_login(branch_code, account_num)

                if (failed_logins + 1) >= Bank.MAX_LOGIN_ATTEMPTS:
                    with self._repository.unit_of_work():
                        account = self._get_account(
                            branch_code, account_num, for_update=True
                        )
                        account.freeze()
                        self._repository.update_account_status(account)

                    raise BankAccessError(
                        "The account was frozen due to 3 consecutive failed login attempts"
                    )
                raise
            except (AccountNotFoundError, DataNotFoundError) as e:
                raise BankSecurityError(
                    "Security breach or race condition: Account no longer exists"
                ) from e
            except RepositoryError as e:
                raise BankUnavailableError(
                    "The intended operation could not be persisted due to an internal error"
                ) from e
        except DataNotFoundError as e:
            raise BankSecurityError(
                "Security breach or race condition: Account no longer exists"
            ) from e
        except RepositoryError as e:
            raise BankUnavailableError(
                "The intended operation could not be persisted due to an internal error"
            ) from e

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
        """
        self._validate_token(auth_token)

        try:
            holder = self._get_account_holder(auth_token.cpf)
            account = self._get_account(auth_token.branch_code, auth_token.account_num)
        except (AccountHolderNotFoundError, AccountNotFoundError) as e:
            raise BankAuthenticationError(
                "Authentication is no longer valid for this token due to inconsistent data"
            ) from e

        return AccountSummaryDTO(
            holder_name=holder.name,
            branch_code=account.branch_code,
            account_num=account.account_num,
            account_type=type(account).__name__,
            is_active=account.is_active,
        )

    def get_account_info(self, access_token: AccessToken) -> AccountInfoDTO:
        """
        Safely retrieves a read-only snapshot of an authenticated account's current state.

        Operates under a strict Zero Trust model. It fetches both the account and the
        account holder using the securely validated AccessToken, projecting this cross-entity
        state into an immutable AccountInfoDTO. This acts as a secure read-only facade,
        preventing full domain entities (Account and AccountHolder) from leaking into external
        layers (Controllers/Views).

        Args:
            access_token (AccessToken): A valid, securely signed vault token containing
                the account holder's CPF for identity resolution.

        Returns:
            AccountInfoDTO: An immutable snapshot containing the holder's name, account
                branch, number, raw account type (e.g., 'CheckingAccount'), balance,
                active status, and overdraft information (if applicable).

        Raises:
            ExpiredTokenError: If the token's TTL has passed.
            BankSecurityError: If the token is invalid, tampered with, or if the
                account/holder no longer exists during the active session (TOCTOU mitigation).
        """
        self._validate_token(access_token)

        try:
            holder = self._get_account_holder(access_token.cpf)
            account = self._get_account(
                access_token.branch_code, access_token.account_num
            )
        except (AccountHolderNotFoundError, AccountNotFoundError):
            raise BankSecurityError(
                "Security breach or race condition: Account or Holder no longer exists"
            )

        account_type = type(account).__name__
        overdraft_limit = None
        available_overdraft = None

        if isinstance(account, CheckingAccount):
            overdraft_limit = account.OVERDRAFT_LIMIT
            available_overdraft = account.available_overdraft

        return AccountInfoDTO(
            holder_name=holder.name,
            branch_code=account.branch_code,
            account_num=account.account_num,
            account_type=account_type,
            balance=account.balance,
            is_active=account.is_active,
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
        deposits from third parties. However, it strictly respects Domain boundaries
        by hydrating the target Account entity and delegating all mathematical and
        state-mutating logic to it.

        Args:
            branch_code (str): The branch code of the target account.
            account_num (str): The target account number.
            amount (Decimal): The positive amount to be deposited.

        Raises:
            TypeError: If the arguments are not of the expected types.
            InvalidDepositError: If the deposit amount violates business rules.
            BlockedAccountError: If the target account is currently frozen.
            AccountNotFoundError: If the provided branch or account number does not exist.
            BankUnavailableError: If the deposit could not be persisted due to an internal error.
        """
        verify.verify_instance(branch_code, str)
        verify.verify_instance(account_num, str)
        verify.verify_instance(amount, Decimal)
        Account.validate_account_deposit(amount)

        try:
            with self._repository.unit_of_work():
                account = self._get_account(branch_code, account_num, for_update=True)
                transaction_type = account.deposit(amount)
                self._repository.save_transaction(account, amount, transaction_type)
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
        Account entity. It delegates the mathematical evaluation and limit usage
        directly to the Account instance.

        Args:
            access_token (AccessToken): A valid, securely signed vault token.
            amount (Decimal): The positive monetary amount to be withdrawn.
            use_overdraft (bool, optional): Explicit authorization to utilize the
                account's credit limit if the amount exceeds the standard balance.
                Defaults to False.

        Raises:
            TypeError: If the arguments are not of the expected types.
            ExpiredTokenError: If the token's TTL has passed.
            BankSecurityError: If the token is invalid, tampered with, or if
                the account was deleted during the active session (TOCTOU mitigation).
            OverdraftRequiredError: If the requested amount exceeds the balance
                and explicit overdraft consent (`use_overdraft=True`) was not provided.
            InvalidWithdrawError: If the withdrawal amount violates business rules
                (e.g., negative amount, exceeds total available funds).
            BankUnavailableError: If the transaction could not be persisted due to an
                internal database error.
        """
        verify.verify_instance(amount, Decimal)
        verify.verify_instance(use_overdraft, bool)
        self._validate_token(access_token)

        try:
            with self._repository.unit_of_work():
                account = self._get_account(
                    access_token.branch_code, access_token.account_num, for_update=True
                )
                transaction_type = account.withdraw(amount, use_overdraft=use_overdraft)
                self._repository.save_transaction(account, -amount, transaction_type)
        except AccountNotFoundError as e:
            raise BankSecurityError(
                "Security breach or race condition: Account no longer exists"
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
        Unit of Work to guarantee that the account balance (via AccountInfoDTO) and
        the transaction history are evaluated with strict temporal consistency,
        reflecting the exact same moment in time. It incorporates TOCTOU mitigation
        to ensure the account has not been deleted mid-session.

        Args:
            access_token (AccessToken): A valid, securely signed vault token.
            start_date (datetime): The cutoff date for filtering transactions.

        Returns:
            StatementDTO: An immutable snapshot combining the account's details,
                current balance, and chronological transaction history.

        Raises:
            TypeError: If the arguments do not match the expected types.
            ExpiredTokenError: If the token's TTL has passed.
            BankSecurityError: If the AccessToken is tampered with, invalid, or if the
                account was deleted during the active session (race condition).
        """
        verify.verify_instance(start_date, datetime)
        try:
            with self._repository.unit_of_work():
                info_dto = self.get_account_info(access_token)
                transactions = self._repository.get_transactions(
                    access_token.branch_code, access_token.account_num, start_date
                )
        except DataNotFoundError as e:
            raise BankSecurityError(
                "Security breach or race condition: Account no longer exists"
            ) from e

        return StatementDTO(account_info=info_dto, transactions=transactions)

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
            TypeError: If the new password is not a string.
            BankPasswordError: If the new password format is invalid (e.g., not 6 digits).
            ExpiredTokenError: If the token's TTL has passed.
            BankSecurityError: If the token is invalid, tampered with, or if the account
                no longer exists (TOCTOU mitigation).
            BankUnavailableError: If the update could not be persisted due to an internal error.
        """
        Bank.validate_password(new_password)
        self._validate_token(access_token)

        hashed_pwd = self._generate_password_hash(new_password)

        try:
            self._repository.update_password(
                access_token.branch_code, access_token.account_num, hashed_pwd
            )
        except DataNotFoundError as e:
            raise BankSecurityError(
                "Security breach or race condition: Account no longer exists"
            ) from e
        except RepositoryError as e:
            raise BankUnavailableError(
                "The intended operation could not be persisted due to an internal error"
            ) from e

    def unfreeze_account(
        self, auth_token: AuthToken, birth_date: date, new_password: str
    ) -> None:
        """
        Recovers and unfreezes a blocked account using strict identity verification.

        This method employs a Unit of Work to enforce strict state isolation, ensuring
        the account cannot be mutated by concurrent processes during the recovery
        operation. It verifies the provided birth date against the registered
        account holder's data. Upon success, it delegates the state change to the
        Account entity, applies a new secure password, resets the login attempts
        counter, and persists the active status.

        Args:
            auth_token (AuthToken): A valid, securely signed authentication token.
            birth_date (date): The account holder's birth date for identity verification.
            new_password (str): The new 6-digit password to be set.

        Raises:
            TypeError: If the arguments are not of the expected types.
            ExpiredTokenError: If the token's TTL has passed.
            BankSecurityError: If the AuthToken is tampered with, invalid, or if the
                account no longer exists (TOCTOU mitigation).
            BankPasswordError: If the new password format is invalid.
            AccountAlreadyActiveError: If the account is already operational.
            BankAuthenticationError: If the provided birth date does not match
                the registered account holder's data.
            BankUnavailableError: If the operation could not be persisted due to
                an internal database error.
        """
        Bank.validate_password(new_password)
        verify.verify_instance(birth_date, date)
        self._validate_token(auth_token)

        try:
            with self._repository.unit_of_work():
                account = self._get_account(
                    auth_token.branch_code, auth_token.account_num, for_update=True
                )

                if account.is_active:
                    raise AccountAlreadyActiveError(
                        "Impossible to unfreeze an operational account"
                    )

                holder = self._get_account_holder(auth_token.cpf)

                if holder.birth_date != birth_date:
                    raise BankAuthenticationError(
                        "The given birth date doesn't match with registered birth date"
                    )

                pwd_hash = self._generate_password_hash(new_password)
                account.unfreeze()
                self._repository.update_security_credentials(account, pwd_hash)

        except AccountNotFoundError as e:
            raise BankSecurityError(
                "Security breach or race condition: Account no longer exists"
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
        2. Zero Balance Rule: The account can only be closed if its financial
           balance is exactly zero.

        It employs a Unit of Work to ensure strict state isolation, preventing
        concurrent transactions from modifying the balance during the closure
        process. It relies on the AccessToken to guarantee full vault authorization.

        Args:
            access_token (AccessToken): A valid, securely signed vault token.

        Raises:
            ExpiredTokenError: If the token's TTL has passed.
            HomeBranchRestrictionError: If the account's branch does not match
                the current terminal's branch.
            NotEmptyAccountError: If the account has a positive or negative balance.
            BankSecurityError: If the token is invalid, tampered with, or if the
                account no longer exists (TOCTOU mitigation).
            BankUnavailableError: If the deletion could not be executed due to
                an internal database error.
        """
        self._validate_token(access_token)

        if access_token.branch_code != self._branch_code:
            raise HomeBranchRestrictionError(
                "Account closure can only be performed at the home branch"
            )

        try:
            with self._repository.unit_of_work():
                account = self._get_account(
                    access_token.branch_code, access_token.account_num, for_update=True
                )

                if account.balance != 0:
                    raise NotEmptyAccountError("Account has a non-zero balance")

                self._repository.delete_account(account)
        except AccountNotFoundError as e:
            raise BankSecurityError(
                "Security breach or race condition: Account no longer exists"
            ) from e
        except RepositoryError as e:
            raise BankUnavailableError(
                "The intended operation could not be persisted due to an internal error"
            ) from e
