-- ==============================================================================
-- PyBank Database Initialization Script
--
-- Description: This schema defines the foundational tables for the PyBank domain,
-- enforcing strict referential integrity, unique constraints, and data typing.
-- ==============================================================================

-- ------------------------------------------------------------------------------
-- Table: account_holders
-- Description: Stores the core personal data of the bank's customers.
-- Represents the 'AccountHolder' domain entity.
-- ------------------------------------------------------------------------------
CREATE TABLE account_holders (
    id INT PRIMARY KEY AUTO_INCREMENT NOT NULL,
    cpf CHAR(11) NOT NULL UNIQUE,
    holder_name VARCHAR(50) NOT NULL,
    birth_date DATE NOT NULL
);

-- ------------------------------------------------------------------------------
-- Table: accounts
-- Description: Stores the financial state, configuration, and security
-- credentials of bank accounts. Represents the 'Account' domain aggregate.
-- ------------------------------------------------------------------------------
CREATE TABLE accounts (
    id INT PRIMARY KEY AUTO_INCREMENT NOT NULL,
    branch_code CHAR(4) NOT NULL,
    account_num CHAR(8) NOT NULL,
    account_type VARCHAR(20) NOT NULL,
    balance DECIMAL(13, 2) NOT NULL,
    last_balance_update DATE NOT NULL,
    is_frozen BOOLEAN NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    failed_login_attempts INT DEFAULT 0,
    account_holder_id INT NOT NULL,
    FOREIGN KEY (account_holder_id) REFERENCES account_holders(id),
    UNIQUE (branch_code, account_num)
);

-- ------------------------------------------------------------------------------
-- Table: ledger_entries
-- Description: An immutable, append-only ledger of financial events (transactions
-- and accruals) used for auditing, accounting, and statement generation.
-- ------------------------------------------------------------------------------
CREATE TABLE ledger_entries (
    id INT PRIMARY KEY AUTO_INCREMENT NOT NULL,
    previous_balance DECIMAL(13, 2) NOT NULL,
    amount DECIMAL(13, 2) NOT NULL,
    event_type VARCHAR(25) NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    account_id INT NOT NULL,
    FOREIGN KEY (account_id) REFERENCES accounts(id)
);
