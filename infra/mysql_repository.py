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

type TransactionListType = list[tuple[Decimal, datetime]]


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

    def _save_transactions(
        self, account_id: int, transactions_list: TransactionListType
    ) -> None:
        """
        Bulk inserts a list of transaction amounts into the database.

        Acts as an internal helper for `save_account` and `save_transactions`.
        It leverages `executemany` for optimized network and database performance.
        This method does not commit the transaction, leaving ACID control to the caller.

        Args:
            account_id (int): The internal database ID of the parent account.
            transactions_list (TransactionListType): A list of tuples containing
                the amount (Decimal) and timestamp (datetime) to be saved.
        """
        if not transactions_list:
            return

        with self._connection.cursor() as cursor:
            insert_sql = "INSERT INTO transactions (amount, created_at, account_id) VALUES (%s, %s, %s)"
            insert_data = [(amount, dt, account_id) for amount, dt in transactions_list]
            cursor.executemany(insert_sql, insert_data)

    def save_transactions(
        self, account_num: str, transactions_list: TransactionListType
    ) -> None:
        """
        Persists a list of new transactions for an existing account.

        Acts as the public interface for Controllers to update the transaction
        history during a user session. Automatically resolves the account's
        internal ID and commits the operation.

        Args:
            account_num (str): The account number.
            transactions_list (TransactionListType): The list of transactions to save.

        Raises:
            DataNotFoundError: If the provided account_num does not exist.
        """
        verify_instance(account_num, str)
        verify_instance(transactions_list, list)

        sql = "SELECT id FROM accounts WHERE account_num = %s"

        with self._connection.cursor() as cursor:
            cursor.execute(sql, (account_num,))
            result = cursor.fetchone()

            if not result:
                raise DataNotFoundError

            acc_id = result["id"]

        self._save_transactions(acc_id, transactions_list)
        self._connection.commit()

    def save_account(
        self, account: Account, client_cpf: str, password_hash: str
    ) -> None:
        """
        Persists a new Account and its initial transactions into the database.

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
            transactions_list = acc_dict.pop("transactions")

            insert_query = (
                "INSERT INTO accounts (branch_code, account_num, account_type, balance, is_active, used_credit, password_hash, client_id)"
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
            )

            values = (
                acc_dict["branch_code"],
                acc_dict["account_num"],
                acc_dict["account_type"],
                acc_dict["balance"],
                acc_dict["is_active"],
                acc_dict.get("used_credit", None),
                password_hash,
                result["id"],
            )
            try:
                cursor.execute(insert_query, values)
                new_acc_id = cursor.lastrowid
                self._save_transactions(new_acc_id, transactions_list)
                self._connection.commit()
            except err.IntegrityError as e:
                self._connection.rollback()
                raise DuplicatedDataError from e

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
        Retrieves an account and its transaction history from the database.

        Acts as an Anti-Corruption Layer, mapping raw database columns back to
        the keys expected by the domain's `Account.from_dict()` factory.
        Transactions are retrieved in descending chronological order.
        Searches using the composite unique key (branch_code + account_num).

        Args:
            branch_code (str): The 4-digit string representing the branch.
            account_num (str): The unique 8-digit string representing the account.

        Returns:
            Account: A fully hydrated Account domain object (either CheckingAccount
                or SavingsAccount), including its transaction history.

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
            "is_active": "is_active",
            "used_credit": "used_credit",
        }
        main_sql = "SELECT * FROM accounts WHERE branch_code = %s AND account_num = %s"

        with self._connection.cursor() as cursor:
            cursor.execute(main_sql, (branch_code, account_num))
            db_acc_dict = cursor.fetchone()

            if not db_acc_dict:
                raise DataNotFoundError

            trans_sql = "SELECT amount, created_at FROM transactions WHERE account_id = %s ORDER BY created_at DESC"
            account_id = db_acc_dict["id"]

            cursor.execute(trans_sql, (account_id,))

            trans_dict_list = cursor.fetchall()

            transactions_list: list[tuple[Decimal, datetime]] = [
                (row["amount"], row["created_at"]) for row in trans_dict_list
            ]
            acc_dict: dict[str, Any] = {
                acc_keys_mapper[k]: v
                for k, v in db_acc_dict.items()
                if k in acc_keys_mapper
            }
            acc_dict["transactions"] = transactions_list

            if acc_dict.get("used_credit") is None:
                acc_dict.pop("used_credit")

            account_obj = Account.from_dict(acc_dict)
            return account_obj

    def update_balance(
        self, branch_code: str, account_num: str, amount: Decimal
    ) -> None:
        """
        Updates the balance of an existing account in the database.

        Args:
            branch_code (str): The 4-digit string representing the branch.
            account_num (str): The target 8-digit account number.
            amount (Decimal): The amount to add or subtract.

        Raises:
            TypeError: If the arguments are of incorrect types.
        """
        verify_instance(branch_code, str)
        verify_instance(account_num, str)
        verify_instance(amount, Decimal)

        sql = "UPDATE accounts SET balance = balance + %s WHERE branch_code = %s AND account_num = %s"

        with self._connection.cursor() as cursor:
            cursor.execute(sql, (amount, branch_code, account_num))
            self._connection.commit()

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

    def delete_account(self, account: Account) -> None:
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
