"""Application Service for account and holder onboarding workflows.

This module exposes the `OnboardingService` class, which serves as an application-layer
orchestrator for registering new bank accounts, linking existing or new account holders,
and conducting lightweight existence checks prior to persistence.
"""

from application.dtos import CheckDataDTO, NewAccountDTO
from application.services.base_service import BaseApplicationService
from application.types import NewAccountType
from domain.account import Account, CheckingAccount, SavingsAccount
from domain.account_holder import AccountHolder
from domain.snapshots import AccountHolderSnapshot, AccountSnapshot
from domain.value_objects import (
    CPF,
    AccountHolderName,
    AccountNumber,
    BirthDate,
    BranchCode,
    Password,
)
from shared import verify
from shared.exceptions import (
    AccountHolderNotFoundError,
    DataNotFoundError,
    DuplicatedAccountError,
    DuplicatedAccountHolderError,
    DuplicatedDataError,
    RepositoryError,
    ServiceUnavailableError,
)

# =====================================================================
# OnboardingService
# =====================================================================


class OnboardingService(BaseApplicationService):
    """Application Service responsible for orchestrating account onboarding workflows.

    Acts as the entry point in the Application layer for creating new accounts and account
    holders. It coordinates domain entity creation via internal factories, delegates password
    hashing, and interacts with the repository protocol to atomically persist domain snapshots.

    Attributes:
        _hasher (HasherProtocol): The cryptographic hashing interface inherited from BaseApplicationService.
        _repository (RepositoryProtocol): The persistence interface inherited from BaseApplicationService.
    """

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
            RuntimeError: If DTO attributes violate Domain VO invariants.
        """
        verify.verify_instance(dto, CheckDataDTO)

        if dto.holder_cpf:
            cpf = self._instantiate_vo(CPF, dto.holder_cpf)
            return self._repository.account_holder_exists(cpf)

        if dto.account:
            branch_code = self._instantiate_vo(BranchCode, dto.account.branch_code)
            account_num = self._instantiate_vo(AccountNumber, dto.account.account_num)
            return self._repository.account_exists(branch_code, account_num)

        return False

    def register_account(self, dto: NewAccountDTO) -> None:
        """Registers a newly created account and links it to an account holder.

        Orchestrates the onboarding process by converting DTO data into domain entities,
        generating persistence snapshots, hashing the validated raw password, and delegating
        the atomic transactional saving to the repository protocol.

        Args:
            dto (NewAccountDTO): The immutable unified payload containing account setup
                and holder details.

        Raises:
            TypeError: If dto is not an instance of NewAccountDTO.
            RuntimeError: If DTO attributes violate Domain VO invariants or required holder
                details are missing, indicating a corrupted boundary payload.
            DuplicatedAccountError: If the branch and account number are already registered.
            DuplicatedAccountHolderError: If a new holder CPF is already registered.
            AccountHolderNotFoundError: If an existing holder CPF is not found in the system.
            ServiceUnavailableError: If persistence fails due to an internal repository error.
        """
        verify.verify_instance(dto, NewAccountDTO)

        branch_code = self._instantiate_vo(BranchCode, dto.branch_code)
        account_num = self._instantiate_vo(AccountNumber, dto.account_num)
        password = self._instantiate_vo(Password, dto.password)
        cpf = self._instantiate_vo(CPF, dto.holder_cpf)
        holder_snap_or_cpf = cpf

        if dto.holder_name and dto.holder_birth_date:
            name = self._instantiate_vo(AccountHolderName, dto.holder_name)
            birth_date = self._instantiate_vo(BirthDate, dto.holder_birth_date)
            holder_snap_or_cpf = self._get_holder_snap((name, cpf, birth_date))

        account_snap = self._get_account_snap(
            (dto.account_type, branch_code, account_num)
        )
        pwd_hash = self._hasher.generate_password_hash(pwd_str=password.value)

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
    # Protected methods (Internal Helpers - Trust Zone)
    # --------------------------------------------------------------------------

    def _get_account_snap(
        self, account_data: tuple[NewAccountType, BranchCode, AccountNumber]
    ) -> AccountSnapshot:
        """Internal helper operating in the Trust Zone to instantiate an Account and return its Snapshot.

        Args:
            account_data (tuple[NewAccountType, BranchCode, AccountNumber]): A 3-tuple containing
                the account target type enum and pre-validated BranchCode and AccountNumber VOs.

        Returns:
            AccountSnapshot: Immutable domain snapshot of the instantiated Account entity.

        Raises:
            KeyError: If new_acc_type is not a supported NewAccountType enum value.
        """
        type_mapper: dict[NewAccountType, type[Account]] = {
            NewAccountType.CHECKING_ACCOUNT: CheckingAccount,
            NewAccountType.SAVINGS_ACCOUNT: SavingsAccount,
        }

        new_acc_type, branch_code, account_num = account_data
        acc_type = type_mapper[new_acc_type]

        return acc_type(branch_code=branch_code, account_num=account_num).to_snapshot()

    def _get_holder_snap(
        self, holder_data: tuple[AccountHolderName, CPF, BirthDate]
    ) -> AccountHolderSnapshot:
        """Internal helper operating in the Trust Zone to instantiate an AccountHolder and return its Snapshot.

        Args:
            holder_data (tuple[AccountHolderName, CPF, BirthDate]): A 3-tuple containing
                pre-validated AccountHolderName, CPF, and BirthDate VOs.

        Returns:
            AccountHolderSnapshot: Immutable domain snapshot of the instantiated AccountHolder entity.
        """
        name, cpf, birth_date = holder_data

        return AccountHolder(name=name, cpf=cpf, birth_date=birth_date).to_snapshot()
