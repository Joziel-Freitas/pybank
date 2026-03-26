"""
Shared Credentials and Access Tokens Module.

This module defines immutable Value Objects used for identification and
authentication across the banking system.

By extracting these structures from the core domain entities (Bank and Person),
we prevent circular dependencies and establish a clear boundary for data that
travels between the Interface layer (Controllers) and the Domain/Infrastructure layers.

Classes:
    AccountCard: Represents a saved physical/virtual card in a client's wallet,
                 used for quick identification.
    AuthToken: Represents a verified session token issued by the Bank, used to
               identify the user (Lobby access) and authorize basic operations.
    AccessToken: Represents a highly secure session token, proving strict password
                 authorization (Vault access) for sensitive operations.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class AccountCard:
    """
    Immutable value object representing the credentials for quick account access.
    Acts as a 'saved card' in the client's wallet.
    """

    cpf: str
    branch_code: str
    account_num: str

    def __str__(self) -> str:
        """User-friendly string representation for UI/Menus."""
        return f"CPF: {self.cpf} | Ag: {self.branch_code} Conta: {self.account_num}"


@dataclass(frozen=True)
class AuthToken:
    """
    Represents a secure access token for stateless authentication.

    Acts as an immutable digital badge for client operations. It utilizes a
    cryptographic signature to ensure payload integrity, preventing unauthorized
    tampering or lateral movement between accounts.

    Attributes:
        cpf (str): The client's unique identifier.
        branch_code (str): The branch code associated with the session.
        account_num (str): The account number associated with the session.
        signature (str): A cryptographic hash (e.g., HMAC-SHA256) generated exclusively
            by the Bank's internal secret key, proving the authenticity of the token.
    """

    cpf: str
    branch_code: str
    account_num: str
    signature: str


@dataclass(frozen=True)
class AccessToken:
    """
    Represents a highly secure, stateless token granting full vault access.

    Acts as the 'Vault Key' for sensitive financial operations. Unlike the
    AuthToken, which only proves identity (Lobby access), the AccessToken
    proves that strict authorization (password verification) has occurred.

    Its cryptographic signature integrates the account's current database
    password hash. This Zero Trust design ensures that the token becomes
    immediately invalid if the user's password is changed elsewhere, acting
    as an automatic defense mechanism against session hijacking.

    Attributes:
        branch_code (str): The branch code associated with the vault.
        account_num (str): The account number associated with the vault.
        signature (str): A cryptographic hash (e.g., HMAC-SHA256) proving
            both authenticity and active password validation.
    """

    branch_code: str
    account_num: str
    signature: str
