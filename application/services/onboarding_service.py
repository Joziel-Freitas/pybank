"""Application Service for account and holder onboarding workflows.

This module exposes the `OnboardingService` class, which serves as an application-layer
orchestrator for registering new bank accounts, linking existing or new account holders,
and conducting lightweight existence checks prior to persistence.
"""

from application.dtos import CheckDataDTO, NewAccountDTO
from application.protocols import HasherProtocol, RepositoryProtocol
from application.types import NewAccountType
from domain.account import Account, CheckingAccount, SavingsAccount
from domain.account_holder import AccountHolder
from domain.snapshots import AccountHolderSnapshot, AccountSnapshot
from shared import verify
from shared.exceptions import (
    AccountError,
    AccountHolderError,
    AccountHolderNotFoundError,
    DataNotFoundError,
    DuplicatedAccountError,
    DuplicatedAccountHolderError,
    DuplicatedDataError,
    InvalidDataError,
    RepositoryError,
    ServiceUnavailableError,
)

# =====================================================================
# OnboardingService
# =====================================================================


class OnboardingService:
    """Application Service responsible for orchestrating account onboarding workflows.

    Acts as the entry point in the Application layer for creating new accounts and account
    holders. It coordinates domain entity creation via internal factories, delegates password
    hashing, and interacts with the repository protocol to atomically persist domain snapshots.

    Attributes:
        _repository (RepositoryProtocol): The persistence interface implementation.
        _hasher (HasherProtocol): The cryptographic hashing interface implementation.
    """

    # --------------------------------------------------------------------------
    # Class attributes
    # --------------------------------------------------------------------------
    _repository: RepositoryProtocol
    _hasher: HasherProtocol

    # --------------------------------------------------------------------------
    # Constructor
    # --------------------------------------------------------------------------
    def __init__(self, repository: RepositoryProtocol, hasher: HasherProtocol) -> None:
        """Initializes the OnboardingService with required infrastructure protocols.

        Args:
            repository (RepositoryProtocol): Database interaction interface.
            hasher (HasherProtocol): Cryptographic password hashing interface.
        """
        self._repository = repository
        self._hasher = hasher

    # --------------------------------------------------------------------------
    # Dunder methods
    # --------------------------------------------------------------------------
    def __repr__(self) -> str:
        """Returns an unambiguous string representation of the OnboardingService instance.

        Useful for debugging and logging, capturing the internal repository and hasher
        protocol instances.

        Returns:
            str: Developer-targeted string representation of the service.
        """
        class_name = type(self).__name__

        return f"{class_name}(repository={self._repository!r}, hasher={self._hasher!r})"

    # --------------------------------------------------------------------------
    # Public API
    # --------------------------------------------------------------------------
    def check_data_exists(self, dto: CheckDataDTO) -> bool:
        """Verifies whether an account holder or account already exists in the system.

        Serves as a lightweight query helper for presentation layer pre-validations,
        allowing controllers to check existence before attempting registration.

        Args:
            dto (CheckDataDTO): Payload containing optional holder CPF or account identifiers.

        Returns:
            bool: True if either the account holder or account exists, False otherwise.

        Raises:
            TypeError: If dto is not an instance of CheckDataDTO.
        """
        verify.verify_instance(dto, CheckDataDTO)

        if dto.cpf:
            return self._check_account_holder_exists(dto.cpf)

        if dto.account:
            return self._check_account_exists(
                dto.account.branch_code, dto.account.account_num
            )

        return False

    def register_account(self, dto: NewAccountDTO) -> None:
        """Registers a newly created account and links it to an account holder.

        Orchestrates the onboarding process by converting DTO data into domain entities,
        generating persistence snapshots, hashing the raw password, and delegating the
        atomic transactional saving to the repository protocol. Maps infrastructure
        persistence and domain validation errors back to clear application-level exceptions.

        Args:
            dto (NewAccountDTO): The immutable unified payload containing account setup
                and holder details.

        Raises:
            TypeError: If dto is not an instance of NewAccountDTO.
            InvalidDataError: If provided onboarding parameters fail domain entity validation.
            DuplicatedAccountError: If the branch and account number are already registered.
            DuplicatedAccountHolderError: If a new holder CPF is already registered.
            AccountHolderNotFoundError: If an existing holder CPF is not found in the system.
            ServiceUnavailableError: If persistence fails due to an internal repository error.
        """
        verify.verify_instance(dto, NewAccountDTO)

        try:
            account_snap, holder_snap_or_cpf = self._get_register_objects(dto)
        except (AccountError, AccountHolderError) as e:
            raise InvalidDataError(
                f"Provided onboarding parameters are invalid: {e}"
            ) from e

        pwd_hash = self._hasher.generate_password_hash(pwd_str=dto.password)

        try:
            self._repository.register_account_bundle(
                account_snap, holder_snap_or_cpf, pwd_hash
            )
        except DuplicatedDataError as e:
            error_argument = e.argument

            if error_argument is holder_snap_or_cpf:
                raise DuplicatedAccountHolderError(
                    "Account holder already registered in the system"
                ) from e

            raise DuplicatedAccountError(
                "Account already registered in the system"
            ) from e
        except DataNotFoundError as e:
            raise AccountHolderNotFoundError(
                "No account holder registered under this CPF"
            ) from e
        except RepositoryError as e:
            raise ServiceUnavailableError(
                "The intended operation could not be persisted due to an internal error"
            ) from e

    # --------------------------------------------------------------------------
    # Protected methods (Internal Helpers)
    # --------------------------------------------------------------------------

    def _get_register_objects(
        self, dto: NewAccountDTO
    ) -> tuple[AccountSnapshot, AccountHolderSnapshot | str]:
        """Assembles persistence snapshots or raw identifiers for onboarding payload processing.

        Coordinates internal entity factories to instantiate the target `Account` and optional
        `AccountHolder`. Converts live domain entities into immutable persistence snapshots.
        If attaching an account to an existing holder, extracts and forwards the raw CPF string.

        Args:
            dto (NewAccountDTO): The onboarding payload containing account setup and holder details.

        Returns:
            tuple[AccountSnapshot, AccountHolderSnapshot | str]: A 2-tuple containing:
                - AccountSnapshot: Immutable snapshot of the newly created Account.
                - AccountHolderSnapshot | str: Full holder snapshot for new registrations, or the raw
                  11-digit CPF string if linking to an existing holder.

        Raises:
            AccountError: If account attributes fail domain validation rules.
            AccountHolderError: If holder attributes fail domain validation rules.
            KeyError: If account_dto.account_type is not a supported NewAccountType enum.
            RuntimeError: If DTO state is invalid for new holder creation.
        """

        new_account = self._account_factory(dto)
        account_snap = new_account.to_snapshot()

        if dto.holder_name and dto.holder_birth_date:
            new_holder = self._account_holder_factory(dto)
            holder_snap_or_cpf = new_holder.to_snapshot()
        else:
            holder_snap_or_cpf = dto.holder_cpf

        return (account_snap, holder_snap_or_cpf)

    def _check_account_holder_exists(self, cpf: str) -> bool:
        """Verifies if an account holder is registered in the banking system.

        Provides a fast, lightweight existence check querying the repository without
        hydrating the full AccountHolder domain entity.

        Args:
            cpf (str): The 11-digit string representing the account holder's CPF.

        Returns:
            bool: True if the account holder exists, False otherwise.

        Raises:
            TypeError: If the provided CPF is not a string.
        """
        return self._repository.account_holder_exists(cpf)

    def _check_account_exists(self, branch_code: str, account_num: str) -> bool:
        """Verifies if an account is registered in the banking system.

        Provides a fast, lightweight existence check avoiding the overhead of
        loading the Account entity or transaction history.

        Args:
            branch_code (str): The 4-digit string representing the branch.
            account_num (str): The unique 8-digit string representing the account.

        Returns:
            bool: True if the account exists, False otherwise.

        Raises:
            TypeError: If any of the provided arguments are not strings.
        """
        return self._repository.account_exists(branch_code, account_num)

    def _account_factory(self, account_dto: NewAccountDTO) -> Account:
        """Internal factory to instantiate concrete Account entities from a DTO.

        Args:
            account_dto (NewAccountDTO): The onboarding payload.

        Returns:
            Account: A fully initialized domain CheckingAccount or SavingsAccount instance.

        Raises:
            KeyError: If account_dto.account_type is not a supported NewAccountType enum value.
            InvalidBranchError: If branch_code fails domain validation.
            InvalidAccountError: If account_num fails domain validation.
        """
        type_mapper = {
            NewAccountType.CHECKING_ACCOUNT: CheckingAccount,
            NewAccountType.SAVINGS_ACCOUNT: SavingsAccount,
        }

        acc_type = type_mapper[account_dto.account_type]
        account_obj = acc_type(
            account_dto.branch_code,
            account_dto.account_num,
        )

        return account_obj

    def _account_holder_factory(self, new_acc_dto: NewAccountDTO) -> AccountHolder:
        """Internal factory to instantiate an AccountHolder entity from a DTO.

        Args:
            new_acc_dto (NewAccountDTO): The unified onboarding payload containing holder details.

        Returns:
            AccountHolder: A fully initialized domain AccountHolder instance.

        Raises:
            RuntimeError: If holder_name or holder_birth_date are missing in the DTO.
            InvalidNameError: If name breaks domain rules.
            InvalidCpfError: If CPF fails validation.
            InvalidBirthDateError: If birth date breaks domain rules.
        """
        if not new_acc_dto.holder_name or not new_acc_dto.holder_birth_date:
            raise RuntimeError("Invalid DTO state")

        holder_obj = AccountHolder(
            name=new_acc_dto.holder_name,
            cpf=new_acc_dto.holder_cpf,
            birth_date=new_acc_dto.holder_birth_date,
        )

        return holder_obj
