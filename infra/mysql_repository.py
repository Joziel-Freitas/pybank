"""
MySQL Repository Persistence Module.

This module provides the `MySQLRepository` class, acting as the Anti-Corruption
Layer (ACL) between the PyBank domain entities and the relational database.
It encapsulates all SQL statements, manages database connections, guarantees
ACID compliance for financial operations, and maps raw database rows back
into pure Python domain objects.
"""

from datetime import datetime
from decimal import Decimal
from os import environ
from typing import Any

from domain.account import Account
from domain.person import Client
from dotenv import load_dotenv
from pymysql import connect, cursors, err
from shared.exceptions import (
    DataNotFoundError,
    DuplicatedDataError,
)

from .verify import verify_instance

load_dotenv()


class MySQLRepository:
    """
    Repository class responsible for MySQL database persistence operations.

    Acts as the Anti-Corruption Layer (ACL) between the PyBank domain and the
    relational database. Manages ACID transactions, data serialization, and
    state mutations for Clients, Accounts, and Transactions.

    Attributes:
        _connection (Connection): The active PyMySQL database connection instance
            configured with a DictCursor.
    """

    def __init__(self) -> None:
        """
        Initializes the repository and establishes the database connection.

        Connection parameters are securely fetched from environment variables.
        Utilizes `cursors.DictCursor` to return row data as Python dictionaries.
        """
        self._connection = connect(
            database=environ["MYSQL_DATABASE"],
            user=environ["MYSQL_USER"],
            password=environ["MYSQL_PASSWORD"],
            host=environ["DB_HOST"],
            cursorclass=cursors.DictCursor,
        )

    def _insert_transaction_record(
        self, cursor, account_id: int, amount: Decimal
    ) -> None:
        """Helper method to insert a transaction. Does NOT manage commits."""

        sql = """INSERT INTO transactions (account_id, amount)
        VALUES (%s, %s)"""

        cursor.execute(sql, (account_id, amount))

    def save_client(self, client: Client) -> None:
        """
        Persists a new Client entity into the database.

        Args:
            client (Client): The domain Client instance to be saved.

        Raises:
            TypeError: If the provided object is not a valid Client instance.
            DuplicatedDataError: If a client with the same CPF already exists
                in the database.
        """
        verify_instance(client, Client)

        query = "INSERT INTO clients (cpf, name, birth_date) VALUES (%(cpf)s, %(name)s, %(birth_date)s)"
        data = client.to_dict()

        with self._connection.cursor() as cursor:
            try:
                cursor.execute(query, data)
                self._connection.commit()
            except err.IntegrityError as e:
                self._connection.rollback()
                raise DuplicatedDataError from e

    def get_client(self, cpf: str) -> Client:
        """
        Retrieves a fully hydrated Client domain entity and their associated account cards.

        Executes two sequential, lightweight queries to fetch the core client
        data and their account credentials. This KISS approach prevents cartesian
        products (JOINs) and simplifies the data reconstruction process.
        The raw database records are mapped directly into a domain object before returning.

        Args:
            cpf (str): The 11-digit string representing the client's CPF.

        Returns:
            Client: A fully populated Client domain object, including their
                wallet of AccountCards.

        Raises:
            TypeError: If the provided CPF is not a string.
            DataNotFoundError: If no client matches the provided CPF.
        """
        verify_instance(cpf, str)

        client_sql = "SELECT * FROM clients WHERE cpf = %s"
        account_sql = (
            "SELECT branch_code, account_num FROM accounts WHERE client_id = %s"
        )

        with self._connection.cursor() as cursor:
            cursor.execute(client_sql, (cpf,))
            client_dict = cursor.fetchone()

            if not client_dict:
                raise DataNotFoundError("Client not registered under this CPF")

            client_id = client_dict.pop("id")
            cursor.execute(account_sql, (client_id,))
            rows = cursor.fetchall()

        cards_list = []
        for row in rows:
            row["cpf"] = cpf
            cards_list.append(row)

        client_dict["account_cards"] = cards_list
        client_obj = Client.from_dict(client_dict)
        return client_obj

    def save_account(
        self, account: Account, client_cpf: str, password_hash: str
    ) -> None:
        """
        Persists a new Account and its opening deposit (if applicable) into the database.

        Executes an ACID-compliant transaction to ensure that the account and
        its transaction history are saved indivisibly. Validates the existence
        of the parent client before insertion.

        Args:
            account (Account): The domain Account instance to be saved.
            client_cpf (str): The CPF of the client who owns the account.
            password_hash (str): The hashed password for account access.

        Raises:
            TypeError: If any of the provided arguments have incorrect types.
            RuntimeError: If the provided client_cpf is not registered in the system.
            DuplicatedDataError: If an account with the same account_num already exists.
        """
        verify_instance(account, Account)
        verify_instance(client_cpf, str)
        verify_instance(password_hash, str)

        select_query = "SELECT id FROM clients WHERE cpf = %s"

        with self._connection.cursor() as cursor:
            cursor.execute(select_query, (client_cpf,))
            result = cursor.fetchone()

            if not result:
                raise RuntimeError(
                    "Account cannot be saved without a registered client"
                )

            acc_dict = account.to_dict()

            insert_query = (
                "INSERT INTO accounts (branch_code, account_num, account_type, balance, is_active, used_credit, password_hash, client_id)"
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
            )

            values = (
                acc_dict["branch_code"],
                acc_dict["account_num"],
                acc_dict["account_type"],
                acc_dict["balance"],
                True,
                acc_dict.get("used_credit", None),
                password_hash,
                result["id"],
            )
            try:
                cursor.execute(insert_query, values)
                if acc_dict["balance"] > 0:
                    new_acc_id = cursor.lastrowid
                    self._insert_transaction_record(
                        cursor, new_acc_id, acc_dict["balance"]
                    )
                self._connection.commit()
            except err.IntegrityError as e:
                self._connection.rollback()
                raise DuplicatedDataError from e

    def save_transaction(
        self, branch_code: str, account_num: str, amount: Decimal
    ) -> None:
        """
        Executes an atomic transaction to update the account balance and
        record the financial transaction in history.

        This method guarantees data consistency by performing both the balance
        update and the transaction insertion within the same database transaction.
        If either operation fails, a rollback is triggered.

        Args:
            branch_code (str): The 4-digit string representing the branch.
            account_num (str): The unique 8-digit string representing the account.
            amount (Decimal): The monetary amount (positive for deposits, negative for withdrawals).

        Raises:
            TypeError: If the arguments are of incorrect types.
            DataNotFoundError: If the account does not exist in the database.
            RuntimeError: If a database error occurs during the operation, triggering a rollback.
        """
        verify_instance(branch_code, str)
        verify_instance(account_num, str)
        verify_instance(amount, Decimal)

        select_sql = (
            "SELECT id FROM accounts WHERE branch_code = %s AND account_num = %s"
        )

        update_sql = "UPDATE accounts SET balance = balance + %s WHERE id = %s"

        with self._connection.cursor() as cursor:
            cursor.execute(
                select_sql,
                (
                    branch_code,
                    account_num,
                ),
            )
            result = cursor.fetchone()

            if not result:
                raise DataNotFoundError("Account not found in the database")

            account_id = result["id"]
            try:
                self._insert_transaction_record(cursor, account_id, amount)
                cursor.execute(update_sql, (amount, account_id))
                self._connection.commit()
            except Exception as e:
                self._connection.rollback()
                raise RuntimeError(
                    f"Failed to update account transactions due to DB error: {e}"
                )

    def get_account_credentials(
        self, branch_code: str, account_num: str
    ) -> dict[str, Any]:
        """
        Fetches only the security metadata required for authentication.
        Extremely lightweight, avoids hydrating the full Account entity or its transactions.
        """
        verify_instance(branch_code, str)
        verify_instance(account_num, str)

        sql = (
            "SELECT is_active, password_hash, failed_login_attempts"
            "FROM accounts "
            "WHERE branch_code = %s AND account_num = %s "
        )
        with self._connection.cursor() as cursor:
            cursor.execute(sql, (branch_code, account_num))
            result = cursor.fetchone()

            if not result:
                raise DataNotFoundError

            return result

    def get_account(self, branch_code: str, account_num: str) -> Account:
        """
        Retrieves an account from the database.

        Acts as an Anti-Corruption Layer, mapping raw database columns back to
        the keys expected by the domain's `Account.from_dict()` factory.
        This method is highly optimized and fetches only the current state
        of the account, omitting the transaction history for performance.

        Args:
            branch_code (str): The 4-digit string representing the branch.
            account_num (str): The unique 8-digit string representing the account.

        Returns:
            Account: A fully hydrated Account domain object (either CheckingAccount
                or SavingsAccount).

        Raises:
            TypeError: If the provided arguments are not strings.
            DataNotFoundError: If the account does not exist in the database.
        """
        verify_instance(branch_code, str)
        verify_instance(account_num, str)

        acc_keys_mapper = {
            "branch_code": "branch_code",
            "account_num": "account_num",
            "account_type": "type",
            "balance": "balance",
            "used_credit": "used_credit",
        }
        main_sql = "SELECT * FROM accounts WHERE branch_code = %s AND account_num = %s"

        with self._connection.cursor() as cursor:
            cursor.execute(main_sql, (branch_code, account_num))
            db_acc_dict = cursor.fetchone()

            if not db_acc_dict:
                raise DataNotFoundError("Account not found in the database")

            acc_dict: dict[str, Any] = {
                acc_keys_mapper[k]: v
                for k, v in db_acc_dict.items()
                if k in acc_keys_mapper
            }

            if acc_dict.get("used_credit") is None:
                acc_dict.pop("used_credit")

            account_obj = Account.from_dict(acc_dict)
            return account_obj

    def get_transactions(
        self, branch_code: str, account_num: str, start_date: datetime
    ) -> tuple[dict[str, Any], ...]:
        """
        Retrieves a chronological record of transactions for a specific account.

        Filters transactions based on a provided start date, pushing the
        computational load of date filtering and ordering to the database motor.
        Executes an optimized JOIN operation to link the account identifiers to
        their respective transaction history.

        Args:
            branch_code (str): The 4-digit string representing the branch.
            account_num (str): The unique 8-digit string representing the account.
            start_date (datetime): The cutoff date; fetches all transactions occurring
                on or after this exact timestamp.

        Returns:
            tuple[dict[str, Any], ...]: A tuple of dictionaries, where each dictionary
                represents a transaction containing the 'amount' (Decimal) and
                'created_at' (datetime). Ordered from newest to oldest.

        Raises:
            TypeError: If the provided arguments are not of the expected types.
        """
        verify_instance(branch_code, str)
        verify_instance(account_num, str)
        verify_instance(start_date, datetime)

        sql = (
            "SELECT t.amount, t.created_at "
            "FROM transactions AS t "
            "JOIN accounts AS a "
            "ON t.account_id = a.id "
            "WHERE a.branch_code = %s "
            "AND a.account_num = %s "
            "AND t.created_at >= %s "
            "ORDER BY t.created_at DESC"
        )

        with self._connection.cursor() as cursor:
            cursor.execute(sql, (branch_code, account_num, start_date))
            result = cursor.fetchall()

        return result

    def register_failed_login(self, branch_code: str, account_num: str) -> None:
        """
        Increments the failed login attempts counter for a specific account.

        Args:
            branch_code (str): The 4-digit string representing the branch.
            account_num (str): The target 8-digit account number.

        Raises:
            TypeError: If the provided arguments are not strings.
        """
        verify_instance(branch_code, str)
        verify_instance(account_num, str)

        sql = (
            "UPDATE accounts "
            "SET failed_login_attempts = failed_login_attempts + 1 "
            "WHERE branch_code = %s AND account_num = %s"
        )

        with self._connection.cursor() as cursor:
            cursor.execute(sql, (branch_code, account_num))
            self._connection.commit()

    def reset_login_attempts(self, branch_code: str, account_num: str) -> None:
        """
        Resets the failed login attempts counter to zero for a specific account.

        Called upon successful authentication or account unfreezing.

        Args:
            branch_code (str): The 4-digit string representing the branch.
            account_num (str): The target 8-digit account number.

        Raises:
            TypeError: If the provided arguments are not strings.
        """
        verify_instance(branch_code, str)
        verify_instance(account_num, str)

        sql = (
            "UPDATE accounts "
            "SET failed_login_attempts = 0 "
            "WHERE branch_code = %s AND account_num = %s"
        )
        with self._connection.cursor() as cursor:
            cursor.execute(
                sql,
                (
                    branch_code,
                    account_num,
                ),
            )
            self._connection.commit()

    def update_account_status(
        self, branch_code: str, account_num: str, is_active: bool
    ) -> None:
        """
        Updates the active status (frozen/unfrozen) of a specific account.

        Args:
            branch_code (str): The 4-digit string representing the branch.
            account_num (str): The target 8-digit account number.
            is_active (bool): True to unfreeze the account, False to freeze it.

        Raises:
            TypeError: If the provided arguments have incorrect types.
        """
        verify_instance(branch_code, str)
        verify_instance(account_num, str)
        verify_instance(is_active, bool)

        sql = (
            "UPDATE accounts "
            "SET is_active = %s "
            "WHERE branch_code = %s AND account_num = %s"
        )

        with self._connection.cursor() as cursor:
            cursor.execute(sql, (is_active, branch_code, account_num))
            self._connection.commit()

    def update_password(
        self, branch_code: str, account_num: str, new_password_hash: str
    ) -> None:
        """
        Updates the authentication password hash for a specific account.

        Typically called during account recovery or unfreezing procedures when
        the client needs to set new credentials.

        Args:
            branch_code (str): The 4-digit string representing the branch.
            account_num (str): The target 8-digit account number.
            new_password_hash (str): The new securely hashed password.

        Raises:
            TypeError: If the arguments are not strings.
        """
        parameters = (branch_code, account_num, new_password_hash)
        for p in parameters:
            verify_instance(p, str)

        sql = (
            "UPDATE accounts "
            "SET password_hash = %s "
            "WHERE branch_code = %s AND account_num = %s"
        )

        with self._connection.cursor() as cursor:
            cursor.execute(sql, (new_password_hash, branch_code, account_num))
            self._connection.commit()

    def update_security_credentials(
        self,
        branch_code: str,
        account_num: str,
        new_password_hash: str,
        is_active: bool,
    ) -> None:
        """
        Executes an atomic update of the account's security credentials.

        Updates the password hash, modifies the active status (frozen/unfrozen),
        and resets the failed login attempts counter back to zero in a single
        database query to guarantee atomicity and performance.

        Args:
            branch_code (str): The 4-digit string representing the branch.
            account_num (str): The target 8-digit account number.
            new_password_hash (str): The new securely hashed password.
            is_active (bool): The new status of the account (True for active, False for frozen).

        Raises:
            TypeError: If any of the provided arguments have incorrect types.
            RuntimeError: If a database error occurs, triggering a transaction rollback.
        """
        verify_instance(is_active, bool)
        str_parameters = (branch_code, account_num, new_password_hash)

        for p in str_parameters:
            verify_instance(p, str)

        sql = (
            "UPDATE accounts "
            "SET password_hash = %s, is_active = %s, failed_login_attempts = 0 "
            "WHERE branch_code = %s AND account_num = %s"
        )

        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    sql, (new_password_hash, is_active, branch_code, account_num)
                )
                self._connection.commit()
        except Exception as e:
            self._connection.rollback()
            raise RuntimeError(
                f"Failed to update account credentials due to DB error: {e}"
            )

    def delete_account(self, account: Account) -> None:
        """
        Permanently removes an account and its transaction history from the database.

        Executes an ACID-compliant transaction to ensure referential integrity.
        It first deletes all associated records in the 'transactions' table
        before deleting the parent record in the 'accounts' table.

        Args:
            account (Account): The fully hydrated domain Account entity to be deleted.

        Raises:
            RuntimeError: If a database error occurs during the deletion process,
                triggering a full transaction rollback to prevent orphaned records.
        """
        branch_code = account.branch_code
        account_num = account.account_num

        del_trans_sql = (
            "DELETE t FROM transactions as t "
            "JOIN accounts as a "
            "ON t.account_id = a.id "
            "WHERE a.branch_code = %s AND a.account_num = %s "
        )

        del_acc_sql = "DELETE FROM accounts WHERE branch_code = %s AND account_num = %s"

        try:
            with self._connection.cursor() as cursor:
                cursor.execute(del_trans_sql, (branch_code, account_num))
                cursor.execute(del_acc_sql, (branch_code, account_num))
                self._connection.commit()
        except Exception as e:
            self._connection.rollback()
            raise RuntimeError(f"Database error during account deletion: {e}")
