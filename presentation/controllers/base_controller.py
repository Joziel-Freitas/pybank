from abc import ABC, abstractmethod

from application.services.base_service import BaseApplicationService
from presentation.cli import views
from presentation.types import (
    MessageMap,
)
from shared import exceptions, verify
from shared.exceptions import (
    ApplicationError,
    ControllerError,
)

# =====================================================================
# Base Controller
# =====================================================================


class BaseController[ServiceT: BaseApplicationService, ReturnType = None](ABC):
    """Abstract Base Class for all Application Controllers.

    Establishes the contract for terminal I/O orchestration and application service
    interaction. Subclasses must implement the 'run_controller' method to define
    specific interaction workflows (e.g., onboarding, banking operations).

    Centralizes presentation output rendering, translation of system exceptions
    into localized UI keys, and message catalog lookup.

    Type Parameters:
        ServiceT: The concrete application service type bound to the controller.
            Enables precise static type inference for `self._service` across subclasses.
        ReturnType: The expected return type of the 'run_controller' execution loop.
            Defaults to None for fire-and-forget controllers, or specialized DTO/tokens
            for stateful authentication/orchestration controllers.
    """

    _ui_message_map: MessageMap

    # --------------------------------------------------------------------------
    # Constructor
    # --------------------------------------------------------------------------
    def __init__(self, service: ServiceT) -> None:
        """Initializes the controller with an injected Application Service.

        Args:
            service (BaseApplicationService): The concrete application service
                responsible for orchestrating target boundary workflows.
        """
        verify.verify_instance(service, BaseApplicationService)
        self._service = service

    # --------------------------------------------------------------------------
    # Dunder methods
    # --------------------------------------------------------------------------
    def __repr__(self) -> str:
        """Returns a string representation of the controller's runtime identity.

        Returns:
            str: The operational class name appended with the underlying service type.
        """
        class_name = type(self).__name__
        return f"{class_name}({type(self._service).__name__})"

    # --------------------------------------------------------------------------
    # Abstract methods
    # --------------------------------------------------------------------------
    @abstractmethod
    def run_controller(self) -> ReturnType:
        """Executes the primary lifecycle loop and routing logic of the controller.

        Must be overridden by concrete subclasses to define how the controller
        orchestrates its respective boundary context.

        Raises:
            NotImplementedError: If the concrete subclass fails to override the method.
        """
        raise NotImplementedError()

    # --------------------------------------------------------------------------
    # Protected methods
    # --------------------------------------------------------------------------
    def _handle_exception_ui(
        self,
        context_key: str,
        error: ApplicationError | ControllerError,
        **kwargs,
    ) -> None:
        """Translates a caught backend exception into a standardized UI message template.

        Delegates string formatting and rendering to the View layer (`views.system_output`).
        Forces a screen clear and execution pause (clean=True, wait=True) to ensure
        critical error feedback captures user attention.

        Args:
            context_key (str): The category inside the message catalog (e.g., 'errors').
            error (ApplicationError | ControllerError): The exception instance raised
                by application service orchestration or controller workflows.
            **kwargs: Dynamic values (e.g., balance, minimum amounts) to be formatted
                into the message template.
        """
        error_key = exceptions.map_exceptions(error)
        error_msg = self._ui_message_map[context_key][error_key]

        views.system_output(error_msg, wait=True, clean=True, kwargs=kwargs)

    def _handle_info_ui(
        self,
        context_key: str,
        info_key: str,
        wait: bool = False,
        clean: bool = False,
        **kwargs,
    ) -> None:
        """Retrieves standard informative message templates from the UI catalog.

        Delegates string formatting and rendering to the View layer (`views.system_output`).
        Exposes terminal flow flags (`wait` and `clean`) to allow controllers
        to control UI transitions dynamically.

        Args:
            context_key (str): The category inside the message catalog (e.g., 'info').
            info_key (str): The specific lookup key for the message template.
            wait (bool, optional): If True, pauses execution for user readability. Defaults to False.
            clean (bool, optional): If True, clears the terminal screen before rendering. Defaults to False.
            **kwargs: Dynamic values (e.g., holder names, transaction amounts) to be
                formatted into the message template.
        """
        info_msg = self._ui_message_map[context_key][info_key]

        views.system_output(info_msg, wait=wait, clean=clean, kwargs=kwargs)
