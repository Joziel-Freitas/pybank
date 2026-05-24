"""
MySQL Repository Persistence Module.

This module provides the `MySQLRepository` class, acting as the Anti-Corruption
Layer (ACL) between the PyBank domain entities and the relational database.
It encapsulates all SQL statements, manages database connections, guarantees
ACID compliance for financial operations, and maps raw database rows back
into pure Python domain objects.
"""

from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from os import environ
from typing import Any

from dotenv import load_dotenv
from pymysql import connect, cursors, err
from pymysql.connections import Connection
from pymysql.constants import CLIENT

from domain.account import Account
from domain.person import AccountHolder
from infra import verify
from shared.exceptions import (
    DataNotFoundError,
    DomainError,
    DuplicatedDataError,
    RepositoryError,
)
from shared.types import TransactionType

load_dotenv()


class MySQLRepository:
    """
    Repository class responsible for MySQL database persistence operations.

    Acts as the Anti-Corruption Layer (ACL) between the PyBank domain and the
    relational database. Manages ACID transactions, data serialization, and
    state mutations for AccountHolders, Accounts, and Transactions.

    Attributes:
        _connection (Connection): The active PyMySQL database connection instance
            configured with a DictCursor.
    """

    _connection: Connection[cursors.DictCursor]
    _in_transaction: bool

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
            client_flag=CLIENT.FOUND_ROWS,
        )

        self._in_transaction = False

    @contextmanager
    def unit_of_work(self):
        """
        Macro Context Manager for orchestrating Units of Work (Unit of Work Pattern).

        Allows the Domain layer (e.g., Bank) to group multiple repository operations
        into a single, atomic ACID transaction. It explicitly manages the commit/rollback
        lifecycle and sets an internal state flag to authorize subordinate methods
        (like `save_transaction`) to execute.

        Yields:
            None: Yields control back to the caller's context block.

        Raises:
            DomainError: Propagates domain business rules exceptions, triggering a rollback.
            DataNotFoundError: Propagates expected missing data errors, triggering a rollback.
            DuplicatedDataError: Propagates unique constraint violations, triggering a rollback.
            RepositoryError: Catches any unexpected database infrastructure errors,
                triggers a rollback to prevent zombie locks, and re-raises as a safe ACL exception.
        """
        try:
            self._in_transaction = True
            yield None
            self._connection.commit()
        except (DomainError, DataNotFoundError, DuplicatedDataError):
            self._connection.rollback()
            raise
        except Exception as e:
            self._connection.rollback()
            raise RepositoryError(f"Data persistence failed due DB error: {e}") from e
        finally:
            self._in_transaction = False

    def _insert_account_holder_record(
        self, cursor: cursors.DictCursor, holder: AccountHolder
    ) -> int:
        """
        Internal helper to persist a new AccountHolder entity within an active transaction.

        Args:
            cursor (cursors.DictCursor): The active database cursor.
            holder (AccountHolder): The domain AccountHolder instance to be saved.

        Returns:
            int: The auto-generated database ID of the newly inserted account holder.

        Raises:
            DuplicatedDataError: If an account holder with the same CPF already exists.
        """
        query = "INSERT INTO account_holders (cpf, name, birth_date) VALUES (%(cpf)s, %(name)s, %(birth_date)s)"
        data = holder.to_dict()

        try:
            cursor.execute(query, data)
            return cursor.lastrowid
        except err.IntegrityError as e:
            raise DuplicatedDataError(
                f"Duplicated data in the database for {holder.cpf=}", holder
            ) from e

    def _get_account_holder_id(self, cursor: cursors.DictCursor, cpf: str) -> int:
        """
        Internal helper to retrieve an account holder's primary key ID by their CPF.

        Args:
            cursor (cursors.DictCursor): The active database cursor.
            cpf (str): The 11-digit string representing the account holder's CPF.

        Returns:
            int: The primary key ID of the account holder.

        Raises:
            DataNotFoundError: If the CPF is not found in the database.
        """
        sql = "SELECT id FROM account_holders WHERE cpf = %s"

        cursor.execute(sql, (cpf,))
        result = cursor.fetchone()

        if result is None:
            raise DataNotFoundError(f"Data not found in the database for {cpf=}", cpf)

        return result["id"]

    def _insert_transaction_record(
        self,
        cursor,
        account_id: int,
        previous_balance: Decimal,
        amount: Decimal,
        transaction_type: TransactionType,
    ) -> None:
        """
        Helper method to insert a transaction record for auditing purposes.

        Records the exact balance prior to the operation alongside the transaction
        amount and its semantic business type to ensure chronological consistency.
        Does NOT manage commits.

        Args:
            cursor: The active database cursor.
            account_id (int): The primary key of the account.
            previous_balance (Decimal): The account balance strictly BEFORE the transaction.
            amount (Decimal): The transaction amount.
            transaction_type (TransactionType): The semantic business event type.
        """
        sql = """INSERT INTO transactions (account_id, previous_balance, amount, transaction_type)
        VALUES (%s, %s, %s, %s)"""

        transaction_type_str = transaction_type.value

        cursor.execute(
            sql, (account_id, previous_balance, amount, transaction_type_str)
        )

    def _insert_account_record(
        self,
        cursor: cursors.DictCursor,
        account: Account,
        holder_id: int,
        password_hash: str,
    ) -> None:
        """
        Internal helper to persist a newly created Account.

        This method is solely responsible for inserting
        the base account entity into the database.

        Args:
            cursor (cursors.DictCursor): The active database cursor.
            account (Account): The domain Account instance to be saved.
            holder_id (int): The primary key ID of the parent account holder.
            password_hash (str): The hashed password for account access.

        Raises:
            DuplicatedDataError: If an account with the same branch code and account_num already exists.
        """
        acc_dict = account.to_dict()

        sql = (
            "INSERT INTO accounts ( "
            "branch_code, "
            "account_num, "
            "account_type, "
            "balance, "
            "is_active, "
            "used_overdraft, "
            "password_hash, "
            "account_holder_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
        )

        values = (
            acc_dict["branch_code"],
            acc_dict["account_num"],
            acc_dict["type"],
            acc_dict["balance"],
            acc_dict["is_active"],
            acc_dict.get("used_overdraft", None),
            password_hash,
            holder_id,
        )
        try:
            cursor.execute(sql, values)
        except err.IntegrityError as e:
            raise DuplicatedDataError(
                f"Duplicated data in the database for {account.branch_code}, {account.account_num}",
                account,
            ) from e

    def _update_account_status(
        self, cursor: cursors.DictCursor, account: Account
    ) -> None:
        """
        Internal helper to execute the active status update for an account.

        This method maps the domain entity's state to the SQL parameters
        and executes the statement within the provided cursor's transaction scope.
        It does not manage commits, rollbacks, or rowcount validations.

        Args:
            cursor (cursors.DictCursor): The active database cursor.
            account (Account): The domain Account entity containing the updated status.
        """
        acc_dict = account.to_dict()
        branch_code = acc_dict["branch_code"]
        account_num = acc_dict["account_num"]
        status = acc_dict["is_active"]

        sql = (
            "UPDATE accounts SET is_active = %s "
            "WHERE branch_code = %s AND account_num = %s"
        )

        cursor.execute(sql, (status, branch_code, account_num))

    def register_account_bundle(
        self, account: Account, holder_or_cpf: AccountHolder | str, password_hash: str
    ) -> None:
        """
        Executes an ACID-compliant transaction to register an account and its holder.

        Acts as a Facade that unifies the creation of a new account holder (if provided as
        a Domain object) or resolves an existing holder (if provided as a CPF string),
        ensuring that the Account is safely linked and committed indivisibly.

        Args:
            account (Account): The new domain Account entity to be saved.
            holder_or_cpf (AccountHolder | str): The owner AccountHolder object, or their CPF.
            password_hash (str): The hashed password for account access.

        Raises:
            TypeError: If any of the arguments do not match the expected types.
            DataNotFoundError: If a CPF string is provided but the holder does not exist.
            DuplicatedDataError: If a unique constraint (CPF or Account Num) is violated.
            RepositoryError: If a generic database or connection error occurs.
        """
        verify.verify_instance(account, Account)
        verify.verify_instance(holder_or_cpf, (AccountHolder, str))
        verify.verify_instance(password_hash, str)

        try:
            with self._connection.cursor() as cursor:

                if isinstance(holder_or_cpf, AccountHolder):
                    holder_id = self._insert_account_holder_record(
                        cursor, holder_or_cpf
                    )
                else:
                    holder_id = self._get_account_holder_id(cursor, holder_or_cpf)

                self._insert_account_record(cursor, account, holder_id, password_hash)
                self._connection.commit()
        except Exception as e:
            self._connection.rollback()

            if not isinstance(e, RepositoryError):
                raise RepositoryError(
                    f"Data persistence failed due DB error: {e}"
                ) from e

            raise

    def save_transaction(
        self, account: Account, amount: Decimal, transaction_type: TransactionType
    ) -> None:
        """
        Executes an atomic sub-operation to update the account balance and
        record the financial transaction in history.

        This method is a subordinate operation and strictly requires an active
        Unit of Work. It MUST be executed within a `with self.unit_of_work():` block.
        It explicitly fetches the current balance prior to the update to satisfy
        the snapshotting requirements of the transaction ledger.

        Args:
            account (Account): The domain Account entity to be updated.
            amount (Decimal): The monetary amount (positive for deposits, negative for withdrawals).
            transaction_type (TransactionType): The semantic business event type.

        Raises:
            RuntimeError: If called outside an active `unit_of_work()` block, enforcing the Unit of Work.
            TypeError: If the arguments are of incorrect types.
            DataNotFoundError: If the account to be updated does not exist in the database.
            RepositoryError: If a database error occurs during the operation.
        """
        if not self._in_transaction:
            raise RuntimeError(
                "Invalid method call. Use the context manager MySQLRepository.unit_of_work()"
            )

        verify.verify_instance(account, Account)
        verify.verify_instance(amount, Decimal)
        verify.verify_instance(transaction_type, TransactionType)

        select_sql = "SELECT id, balance FROM accounts WHERE branch_code = %s AND account_num = %s FOR UPDATE"
        update_sql = (
            "UPDATE accounts SET balance = %s, used_overdraft = %s WHERE id = %s"
        )

        account_dict = account.to_dict()
        branch_code = account_dict["branch_code"]
        account_num = account_dict["account_num"]
        balance = account_dict["balance"]
        used_overdraft = account_dict.get("used_overdraft", None)

        with self._connection.cursor() as cursor:
            cursor.execute(select_sql, (branch_code, account_num))
            result = cursor.fetchone()

            if not result:
                raise DataNotFoundError(
                    f"Data not found in the database for {account.branch_code=}, {account.account_num=}"
                )

            account_id = result["id"]
            previous_balance = result["balance"]

            cursor.execute(update_sql, (balance, used_overdraft, account_id))

            if cursor.rowcount == 0:
                raise DataNotFoundError(
                    f"Data not found in the database for {branch_code=}, {account_num=}"
                )

            self._insert_transaction_record(
                cursor, account_id, previous_balance, amount, transaction_type
            )

    def account_holder_exists(self, cpf: str) -> bool:
        """
        Performs a highly optimized existence check for an account holder by CPF.

        Executes a lightweight database query (SELECT 1) to determine if an
        account holder record exists without hydrating the full domain entity or
        fetching related account cards.

        Args:
            cpf (str): The 11-digit string representing the account holder's CPF.

        Returns:
            bool: True if the account holder is registered, False otherwise.
        """
        verify.verify_instance(cpf, str)

        sql = "SELECT 1 FROM account_holders WHERE cpf = %s LIMIT 1"

        with self._connection.cursor() as cursor:
            cursor.execute(sql, (cpf,))
            result = cursor.fetchone()

        return bool(result)

    def account_exists(self, branch_code: str, account_num: str) -> bool:
        """
        Performs a highly optimized existence check for an account.

        Executes a lightweight query (SELECT 1) to verify if an account is
        registered under the specified branch and account number, completely
        avoiding object hydration and join operations.

        Args:
            branch_code (str): The 4-digit string representing the branch.
            account_num (str): The unique 8-digit string representing the account.

        Returns:
            bool: True if the account exists, False otherwise.
        """
        verify.verify_instance(branch_code, str)
        verify.verify_instance(account_num, str)
        sql = (
            "SELECT 1 FROM accounts "
            "WHERE branch_code = %s AND account_num = %s "
            "LIMIT 1"
        )

        with self._connection.cursor() as cursor:
            cursor.execute(sql, (branch_code, account_num))
            result = cursor.fetchone()

        return bool(result)

    def get_account_holder(self, cpf: str) -> AccountHolder:
        """
        Retrieves a fully hydrated AccountHolder domain entity and their associated account cards.

        Executes two sequential, lightweight queries to fetch the core holder
        data and their account credentials. This KISS approach prevents cartesian
        products (JOINs) and simplifies the data reconstruction process.
        The raw database records are mapped directly into a domain object before returning.

        Args:
            cpf (str): The 11-digit string representing the account holder's CPF.

        Returns:
            AccountHolder: A fully populated AccountHolder domain object, including their
                wallet of AccountCards.

        Raises:
            TypeError: If the provided CPF is not a string.
            DataNotFoundError: If no account holder matches the provided CPF.
        """
        verify.verify_instance(cpf, str)

        holder_sql = "SELECT * FROM account_holders WHERE cpf = %s"
        account_sql = (
            "SELECT branch_code, account_num FROM accounts WHERE account_holder_id = %s"
        )

        with self._connection.cursor() as cursor:
            cursor.execute(holder_sql, (cpf,))
            holder_dict = cursor.fetchone()

            if not holder_dict:
                raise DataNotFoundError(f"Data not found in the database for {cpf=}")

            holder_id = holder_dict.pop("id")
            cursor.execute(account_sql, (holder_id,))
            rows = cursor.fetchall()

        cards_list = []
        for row in rows:
            row["cpf"] = cpf
            cards_list.append(row)

        holder_dict["account_cards"] = cards_list
        holder_obj = AccountHolder.from_dict(holder_dict)
        return holder_obj

    def get_account_info(
        self,
        branch_code: str,
        account_num: str,
        financial_info: bool = False,
        access_info: bool = False,
        holder_info: bool = False,
        for_update: bool = False,
    ) -> dict[str, Any]:
        """
        Dynamic Query Builder for retrieving specific slices of account data.

        Acts as an optimized 'micro-ORM', allowing the Domain layer to request
        strictly the data needed for a specific context without the overhead of
        full Entity hydration. By default, it returns a lightweight baseline
        of routing and status data. Additional data domains can be appended via
        boolean flags.

        Args:
            branch_code (str): The 4-digit string representing the branch.
            account_num (str): The unique 8-digit string representing the account.
            financial_info (bool, optional): Appends 'balance' and 'used_overdraft'.
            access_info (bool, optional): Appends 'password_hash' and 'failed_login_attempts'.
            holder_info (bool, optional): Executes a JOIN to append 'holder_name', 'cpf', and 'birth_date'.
            for_update (bool, optional): Applies a pessimistic lock (FOR UPDATE)
                to prevent TOCTOU race conditions. Defaults to False.

        Returns:
            dict[str, Any]: A dictionary containing the requested data slice.
                Baseline keys: 'branch_code', 'account_num', 'account_type', 'is_active'.

        Raises:
            TypeError: If the provided arguments are not of the expected types.
            RuntimeError: If `for_update` is True but the method is called outside
                an active `unit_of_work()` block, preventing dangling database locks.
            DataNotFoundError: If the requested account does not exist.
        """

        verify.verify_instance(branch_code, str)
        verify.verify_instance(account_num, str)
        verify.verify_instance(financial_info, bool)
        verify.verify_instance(access_info, bool)
        verify.verify_instance(holder_info, bool)
        verify.verify_instance(for_update, bool)

        if for_update and not self._in_transaction:
            raise RuntimeError(
                "Invalid method call. To update credentials, use the context manager MySQLRepository.unit_of_work()"
            )

        columns = [
            "a.branch_code",
            "a.account_num",
            "a.account_type",
            "a.is_active",
        ]

        if financial_info:
            columns.extend(["a.balance", "a.used_overdraft"])

        if access_info:
            columns.extend(["a.password_hash", "a.failed_login_attempts"])

        if holder_info:
            columns.extend(["ah.holder_name", "ah.cpf", "ah.birth_date"])

        select_clause = ", ".join(columns)
        from_clause = "FROM accounts AS a"

        if holder_info:
            from_clause += " JOIN account_holders AS ah ON a.account_holder_id = ah.id"

        lock_clause = "FOR UPDATE" if for_update else ""

        sql = (
            f"SELECT {select_clause} "
            f"{from_clause} "
            "WHERE a.branch_code = %s AND a.account_num = %s "
            f"{lock_clause}"
        )

        with self._connection.cursor() as cursor:
            cursor.execute(sql, (branch_code, account_num))
            result = cursor.fetchone()

        if not result:
            raise DataNotFoundError(
                f"Data not found in the database for {branch_code=}, {account_num=}"
            )

        return result

    def get_account(
        self, branch_code: str, account_num: str, for_update: bool = False
    ) -> Account:
        """
        Retrieves an account from the database.

        Acts as an Anti-Corruption Layer, mapping raw database columns back to
        the keys expected by the domain's `Account.from_dict()` factory.
        This method is highly optimized and fetches only the current state
        of the account, omitting the transaction history for performance.

        Args:
            branch_code (str): The 4-digit string representing the branch.
            account_num (str): The unique 8-digit string representing the account.
            for_update (bool): If True, applies a pessimistic lock (FOR UPDATE) to the row.
                Defaults to False.

        Returns:
            Account: A fully hydrated Account domain object.

        Raises:
            TypeError: If the provided arguments are not of expected types.
            RuntimeError: If `for_update` is True but the method is called outside
                an active `transaction()` block, preventing dangling database locks.
            DataNotFoundError: If the account does not exist in the database.
        """
        verify.verify_instance(branch_code, str)
        verify.verify_instance(account_num, str)
        verify.verify_instance(for_update, bool)

        if for_update and not self._in_transaction:
            raise RuntimeError(
                "Invalid method call. To update account, use the context manager MySQLRepository.unit_of_work()"
            )

        lock_clause = "FOR UPDATE" if for_update else ""

        acc_keys_mapper = {
            "branch_code": "branch_code",
            "account_num": "account_num",
            "account_type": "type",
            "balance": "balance",
            "is_active": "is_active",
            "used_overdraft": "used_overdraft",
        }
        sql = f"SELECT * FROM accounts WHERE branch_code = %s AND account_num = %s {lock_clause}"

        with self._connection.cursor() as cursor:
            cursor.execute(sql, (branch_code, account_num))
            db_acc_dict = cursor.fetchone()

            if not db_acc_dict:
                raise DataNotFoundError(
                    f"Data not found in the database for {branch_code=}, {account_num=}"
                )

            acc_dict: dict[str, Any] = {
                acc_keys_mapper[k]: v
                for k, v in db_acc_dict.items()
                if k in acc_keys_mapper
            }

            if acc_dict.get("used_overdraft") is None:
                acc_dict.pop("used_overdraft")

            account_obj = Account.from_dict(acc_dict)
            return account_obj

    def get_transactions(
        self, branch_code: str, account_num: str, start_date: datetime
    ) -> tuple[dict[str, Any], ...]:
        """
        Retrieves a chronological record of transactions for a specific account.

        Enforces a Fail-Fast validation by explicitly verifying the account's
        existence before executing the main query. This mitigates TOCTOU
        (Time-of-Check to Time-of-Use) race conditions, preventing the return
        of a false-positive empty statement for an account that was deleted
        in another session.

        Filters transactions based on a provided start date, pushing the
        computational load of date filtering and ordering to the database motor
        using an optimized JOIN operation.

        Args:
            branch_code (str): The 4-digit string representing the branch.
            account_num (str): The unique 8-digit string representing the account.
            start_date (datetime): The cutoff date; fetches all transactions occurring
                on or after this exact timestamp.

        Returns:
            tuple[dict[str, Any], ...]: A tuple of dictionaries, where each dictionary
                represents a transaction containing 'previous_balance' (Decimal),
                'created_at' (datetime), 'transaction_type' (str), and 'amount' (Decimal).
                Ordered from oldest to newest.

        Raises:
            TypeError: If the provided arguments are not of the expected types.
            DataNotFoundError: If the requested account does not exist in the database.
        """
        verify.verify_instance(branch_code, str)
        verify.verify_instance(account_num, str)
        verify.verify_instance(start_date, datetime)

        if not self.account_exists(branch_code, account_num):
            raise DataNotFoundError(
                f"Data not found in the database for {branch_code=}, {account_num=}"
            )

        sql = (
            "SELECT t.previous_balance, t.created_at, t.transaction_type, t.amount "
            "FROM transactions AS t "
            "JOIN accounts AS a "
            "ON t.account_id = a.id "
            "WHERE a.branch_code = %s "
            "AND a.account_num = %s "
            "AND t.created_at >= %s "
            "ORDER BY t.created_at ASC"
        )

        with self._connection.cursor() as cursor:
            cursor.execute(sql, (branch_code, account_num, start_date))
            result = cursor.fetchall()

        return result

    def register_failed_login(self, branch_code: str, account_num: str) -> None:
        """
        Increments the failed login attempts counter for a specific account.

        This method is a subordinate operation and strictly requires an active
        Unit of Work. It MUST be executed within a `with self.unit_of_work():` block.

        Args:
            branch_code (str): The 4-digit string representing the branch.
            account_num (str): The target 8-digit account number.

        Raises:
            RuntimeError: If called outside an active `unit_of_work()` block.
            TypeError: If the provided arguments are not strings.
            DataNotFoundError: If the account does not exist in the database.
            RepositoryError: If a database error occurs, triggering a transaction rollback.
        """
        if not self._in_transaction:
            raise RuntimeError(
                "Invalid method call. Use the context manager MySQLRepository.unit_of_work()"
            )

        verify.verify_instance(branch_code, str)
        verify.verify_instance(account_num, str)

        sql = (
            "UPDATE accounts "
            "SET failed_login_attempts = failed_login_attempts + 1 "
            "WHERE branch_code = %s AND account_num = %s"
        )

        with self._connection.cursor() as cursor:
            cursor.execute(sql, (branch_code, account_num))

            if cursor.rowcount == 0:
                raise DataNotFoundError(
                    f"Data not found in the database for {branch_code=}, {account_num=}"
                )

    def reset_login_attempts(self, branch_code: str, account_num: str) -> None:
        """
        Resets the failed login attempts counter to zero for a specific account.
        Called upon successful authentication or account unfreezing.

        This method is a subordinate operation and strictly requires an active
        Unit of Work. It MUST be executed within a `with self.unit_of_work():` block.

        Args:
            branch_code (str): The 4-digit string representing the branch.
            account_num (str): The target 8-digit account number.

        Raises:
            RuntimeError: If called outside an active `unit_of_work()` block.
            TypeError: If the provided arguments are not strings.
            DataNotFoundError: If the account does not exist in the database.
            RepositoryError: If a database error occurs, triggering a transaction rollback.
        """
        if not self._in_transaction:
            raise RuntimeError(
                "Invalid method call. Use the context manager MySQLRepository.unit_of_work()"
            )

        verify.verify_instance(branch_code, str)
        verify.verify_instance(account_num, str)

        sql = (
            "UPDATE accounts "
            "SET failed_login_attempts = 0 "
            "WHERE branch_code = %s AND account_num = %s"
        )

        with self._connection.cursor() as cursor:
            cursor.execute(sql, (branch_code, account_num))

            if cursor.rowcount == 0:
                raise DataNotFoundError(
                    f"Data not found in the database for {branch_code=}, {account_num=}"
                )

    def update_account_status(self, account: Account) -> None:
        """
        Updates the active status (frozen/unfrozen) of a specific account.

        This method is a subordinate operation and strictly requires an active
        Unit of Work. It MUST be executed within a `with self.unit_of_work():` block.

        Args:
            account (Account): The domain Account entity containing the target branch,
                account number, and the new active status.

        Raises:
            RuntimeError: If called outside an active `unit_of_work()` block, enforcing the Unit of Work.
            TypeError: If the provided argument is not an Account instance.
            DataNotFoundError: If the account does not exist in the database,
                detected by a zero rowcount during the update.
            RepositoryError: If a database error occurs during the operation.
        """
        if not self._in_transaction:
            raise RuntimeError(
                "Invalid method call. Use the context manager MySQLRepository.unit_of_work()"
            )

        verify.verify_instance(account, Account)

        with self._connection.cursor() as cursor:
            self._update_account_status(cursor, account)

            if cursor.rowcount == 0:
                raise DataNotFoundError(
                    f"Data not found in the database for {account.branch_code=}, {account.account_num=}"
                )

    def update_password(
        self, branch_code: str, account_num: str, new_password_hash: str
    ) -> None:
        """
        Updates the authentication password hash for a specific account.

        This method is a subordinate operation and strictly requires an active
        Unit of Work. It MUST be executed within a `with self.unit_of_work():` block.

        Args:
            branch_code (str): The 4-digit string representing the branch.
            account_num (str): The target 8-digit account number.
            new_password_hash (str): The new securely hashed password.

        Raises:
            RuntimeError: If called outside an active `unit_of_work()` block.
            TypeError: If the arguments are not strings.
            DataNotFoundError: If the account does not exist in the database.
            RepositoryError: If a database error occurs, triggering a transaction rollback.
        """
        if not self._in_transaction:
            raise RuntimeError(
                "Invalid method call. Use the context manager MySQLRepository.unit_of_work()"
            )

        verify.verify_instance(branch_code, str)
        verify.verify_instance(account_num, str)
        verify.verify_instance(new_password_hash, str)

        sql = (
            "UPDATE accounts "
            "SET password_hash = %s "
            "WHERE branch_code = %s AND account_num = %s"
        )

        with self._connection.cursor() as cursor:
            cursor.execute(sql, (new_password_hash, branch_code, account_num))

            if cursor.rowcount == 0:
                raise DataNotFoundError(
                    f"Data not found in the database for {branch_code=}, {account_num=}"
                )

    def delete_account(self, account: Account) -> None:
        """
        Permanently removes an account and its transaction history from the database.

        This method is a subordinate operation and strictly requires an active
        Unit of Work. It MUST be executed within a `with self.unit_of_work():` block.
        Executes an ACID-compliant sub-transaction to ensure referential integrity by
        first deleting all associated records in the 'transactions' table before
        deleting the parent record in the 'accounts' table.

        Args:
            account (Account): The fully hydrated domain Account entity to be deleted.

        Raises:
            RuntimeError: If called outside an active `unit_of_work()` block, enforcing the Unit of Work.
            DataNotFoundError: If the account to be deleted does not exist.
            RepositoryError: If a database error occurs during the deletion process.
        """
        if not self._in_transaction:
            raise RuntimeError(
                "Invalid method call. Use the context manager MySQLRepository.unit_of_work()"
            )

        branch_code = account.branch_code
        account_num = account.account_num

        del_trans_sql = (
            "DELETE t FROM transactions as t "
            "JOIN accounts as a "
            "ON t.account_id = a.id "
            "WHERE a.branch_code = %s AND a.account_num = %s "
        )

        del_acc_sql = "DELETE FROM accounts WHERE branch_code = %s AND account_num = %s"

        with self._connection.cursor() as cursor:
            cursor.execute(del_trans_sql, (branch_code, account_num))
            cursor.execute(del_acc_sql, (branch_code, account_num))

            if cursor.rowcount == 0:
                raise DataNotFoundError(
                    f"Data not found in the database for {account.branch_code=}, {account.account_num=}"
                )
