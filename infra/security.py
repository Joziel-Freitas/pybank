"""Infrastructure Security and Cryptography Module.

This module provides low-level cryptographic utilities for password hashing,
HMAC token signing, and session integrity verification. It encapsulates all
security primitives (such as bcrypt and HMAC-SHA256) away from the core domain.
"""

import hashlib
import hmac
from datetime import timedelta

import bcrypt

from settings import BANK_SECRET_KEY, LOBBY_TIME_SECONDS, VAULT_TIME_SECONDS
from shared import clock
from shared.credentials import AccessToken, AuthToken
from shared.exceptions import (
    BankSecurityError,
    ExpiredTokenError,
)


class PasswordHasher:
    """Provides cryptographic hashing and verification for user credentials using bcrypt."""

    def generate_password_hash(self, password_str: str) -> str:
        """Generates a secure cryptographic hash for a plain-text password.

        Uses the bcrypt algorithm with a randomly generated salt to ensure
        protection against rainbow table and brute-force attacks.

        Args:
            password_str (str): The plain-text password string.

        Returns:
            str: The securely hashed password string encoded in UTF-8.
        """
        pwd_bytes = password_str.encode("utf-8")
        salt = bcrypt.gensalt()
        pwd_hash_bytes = bcrypt.hashpw(pwd_bytes, salt)
        return pwd_hash_bytes.decode("utf-8")

    def check_password(self, pwd_str: str, pwd_hash_str: str) -> bool:
        """Verifies a plain-text password string against a bcrypt hash.

        Args:
            pwd_str (str): The raw plain-text password string to verify.
            pwd_hash_str (str): The target bcrypt hash string to compare against.

        Returns:
            bool: True if the raw password matches the hash, False otherwise.
        """
        pwd_bytes = pwd_str.encode("utf-8")
        hashed_pwd_bytes = pwd_hash_str.encode("utf-8")

        return bcrypt.checkpw(pwd_bytes, hashed_pwd_bytes)


class TokenService:
    """Manages the creation, cryptographic signing, and verification of session tokens."""

    _secret_key: bytes
    _lobby_ttl: timedelta
    _vault_ttl: timedelta

    def __init__(
        self,
        secret_key: str = BANK_SECRET_KEY,
        lobby_time_seconds: timedelta = LOBBY_TIME_SECONDS,
        vault_time_seconds: timedelta = VAULT_TIME_SECONDS,
    ) -> None:
        """Initializes the TokenService with secret keys and session TTL parameters.

        Args:
            secret_key (str): The master HMAC secret key. Defaults to BANK_SECRET_KEY.
            lobby_time_seconds (timedelta): The TTL duration for lobby tokens.
            vault_time_seconds (timedelta): The TTL duration for vault tokens.

        Raises:
            TypeError: If secret_key is not a string.
        """
        if not isinstance(secret_key, str):
            raise TypeError(f"Object expects str, got: {type(secret_key).__name__}")

        self._secret_key = secret_key.encode("utf-8")
        self._lobby_ttl = lobby_time_seconds
        self._vault_ttl = vault_time_seconds

    def generate_auth_token(
        self, cpf: str, branch_code: str, account_num: str
    ) -> AuthToken:
        """Issues an AuthToken populated with account coordinates and an HMAC signature.

        Args:
            cpf (str): The user's identification string.
            branch_code (str): The branch code string.
            account_num (str): The account number string.

        Returns:
            AuthToken: A signed identification token object.
        """
        payload = f"{cpf}:{branch_code}:{account_num}"
        signature = self._sign_token_payload(payload)

        return AuthToken(
            cpf=cpf,
            branch_code=branch_code,
            account_num=account_num,
            signature=signature,
            expires_at=clock.get_now() + self._lobby_ttl,
        )

    def generate_access_token(
        self, auth_token: AuthToken, password_hash: str
    ) -> AccessToken:
        """Issues an AccessToken binding account coordinates and password hash into an HMAC signature.

        Args:
            auth_token (AuthToken): The source identification token.
            password_hash (str): The active password hash string to bind to the signature.

        Returns:
            AccessToken: A signed access token object.
        """
        payload = f"{auth_token.cpf}:{auth_token.branch_code}:{auth_token.account_num}:{password_hash}"
        signature = self._sign_token_payload(payload)

        return AccessToken(
            cpf=auth_token.cpf,
            branch_code=auth_token.branch_code,
            account_num=auth_token.account_num,
            signature=signature,
            expires_at=clock.get_now() + self._vault_ttl,
        )

    def validate_token_integrity(
        self, token: AccessToken | AuthToken, pwd_hash: str = ""
    ) -> None:
        """Validates instance type, HMAC signature integrity, and TTL expiration of a token.

        Reconstructs the expected signature using the token's primitive payload (and optional password hash)
        and verifies it using constant-time comparison.

        Args:
            token (AccessToken | AuthToken): The token instance to be validated.
            pwd_hash (str, optional): The password hash required for AccessToken verification.
                Ignored for AuthToken. Defaults to "".

        Raises:
            TypeError: If token is not an instance of AuthToken or AccessToken.
            BankSecurityError: If the signature comparison fails (tampering or payload mismatch).
            ExpiredTokenError: If current time exceeds the token's expiration timestamp.
        """
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

        if clock.get_now() > token.expires_at:
            raise ExpiredTokenError(
                "This token is no longer valid because it has expired"
            )

    def _sign_token_payload(self, payload_str: str) -> str:
        """Generates an HMAC-SHA256 hexadecimal signature for a given raw payload string.

        Args:
            payload_str (str): The raw string payload to be signed.

        Returns:
            str: A hexadecimal string representing the cryptographic signature.
        """
        payload_bytes = payload_str.encode("utf-8")
        return hmac.new(self._secret_key, payload_bytes, hashlib.sha256).hexdigest()
