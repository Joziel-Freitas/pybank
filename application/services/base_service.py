from abc import ABC

from application.protocols import HasherProtocol, RepositoryProtocol
from domain.types import VOValueTypes
from domain.value_objects import DomainVO
from shared.exceptions import DomainVOError

# =====================================================================
# BaseApplicationService
# =====================================================================


class BaseApplicationService(ABC):
    """Abstract Base Class for all Application Services in the PyBank system.

    Establishes a unified foundation for the Application layer, centralizing common
    infrastructure dependencies (repository persistence and password hashing) shared
    across all use cases and workflow orchestrators.

    Attributes:
        _hasher (HasherProtocol): The cryptographic hashing interface implementation.
        _repository (RepositoryProtocol): The persistence layer interface implementation.
    """

    # --------------------------------------------------------------------------
    # Constructor
    # --------------------------------------------------------------------------
    def __init__(
        self,
        hasher: HasherProtocol,
        repository: RepositoryProtocol,
    ) -> None:
        """Initializes the base application service with required infrastructure protocols.

        Args:
            hasher (HasherProtocol): Cryptographic password hashing interface.
            repository (RepositoryProtocol): Database interaction interface.
        """
        self._hasher = hasher
        self._repository = repository

    # --------------------------------------------------------------------------
    # Dunder methods
    # --------------------------------------------------------------------------
    def __repr__(self) -> str:
        """Returns an unambiguous string representation of the concrete application service instance.

        Useful for debugging and logging, capturing the active class name along with its
        internal repository and hasher protocol instances.

        Returns:
            str: Developer-targeted string representation of the service.
        """
        class_name = type(self).__name__

        return f"{class_name}(hasher={self._hasher!r}, repository={self._repository!r})"

    def _instantiate_vo[VO_T: DomainVO](
        self, vo_type: type[VO_T], vo_value: VOValueTypes
    ) -> VO_T:
        """Centralizes Fail-Fast Domain Value Object instantiation in the Application layer.

        Converts internal DomainVOError exceptions into boundary RuntimeError exceptions,
        protecting upper application boundaries from unhandled domain validation errors.

        Args:
            vo_type (type[VO_T]): The concrete DomainVO class to instantiate.
            vo_value (ValueTypes): The primitive value to be validated and encapsulated.

        Returns:
            VO_T: A fully validated Domain Value Object instance.

        Raises:
            RuntimeError: If vo_value violates domain invariants or is missing/invalid.
        """
        try:
            return vo_type(vo_value)
        except DomainVOError as e:
            raise RuntimeError(f"Corrupted boundary payload: {e}") from e
