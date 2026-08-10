from abc import ABC

from application.protocols import HasherProtocol, RepositoryProtocol

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
