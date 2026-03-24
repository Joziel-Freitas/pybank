"""
PyBank Application Entry Point (v3.0).

This module serves exclusively as the Composition Root of the system, adhering
strictly to the Dependency Inversion Principle. It contains no business logic,
state management, or I/O loops.

Core Responsibilities:
1. Configuration Binding: Reads environment variables and system settings.
2. Persistence Initialization: Instantiates the MySQL database connection.
3. Domain Bootstrapping: Instantiates the core 'Bank' aggregate root,
   injecting the required credentials and repository layer.
4. Controller Orchestration: Injects the domain model into the Presentation
   layer and delegates the application execution flow (Kiosk mode).
"""

import sys

from app.controllers import BankSystemController
from domain.bank import Bank
from infra.mysql_repository import MySQLRepository
from settings import BANK_NAME, BANK_SECRET_KEY, BRANCH_CODE


def main() -> None:
    """
    Bootstraps and executes the application.

    Instantiates the foundational layers (Infrastructure -> Domain -> Presentation)
    in a strict 'Bottom-Up' approach, culminating in the execution of the main
    ATM kiosk loop.
    """
    repository = MySQLRepository()
    bank_obj = Bank(BANK_NAME, BRANCH_CODE, repository, BANK_SECRET_KEY)
    controller_obj = BankSystemController(bank_obj)
    controller_obj.run_controller()


if __name__ == "__main__":
    try:
        main()
        sys.exit()
    except Exception as e:
        raise RuntimeError(
            "Major system error. Impossible to initialize the system."
        ) from e
