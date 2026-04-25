CREATE TABLE clients (
    id INT PRIMARY KEY AUTO_INCREMENT NOT NULL,
    cpf CHAR(11) NOT NULL UNIQUE,
    name VARCHAR(50) NOT NULL,
    birth_date DATE NOT NULL
);

CREATE TABLE accounts (
    id INT PRIMARY KEY AUTO_INCREMENT NOT NULL,
    branch_code CHAR(4) NOT NULL,
    account_num CHAR(8) NOT NULL,
    account_type VARCHAR(20) NOT NULL,
    balance DECIMAL(13, 2) NOT NULL,
    is_active BOOLEAN NOT NULL,
    used_overdraft DECIMAL(10, 2),
    password_hash VARCHAR(255) NOT NULL,
    failed_login_attempts INT DEFAULT 0,
    client_id INT NOT NULL,
    FOREIGN KEY (client_id) REFERENCES clients(id),
    UNIQUE (branch_code, account_num)
);

CREATE TABLE transactions (
    id INT PRIMARY KEY AUTO_INCREMENT NOT NULL,
    previous_balance DECIMAL (10, 2) NOT NULL,
    amount DECIMAL(10, 2) NOT NULL,
    transaction_type VARCHAR(20) NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    account_id INT NOT NULL,
    FOREIGN KEY (account_id) REFERENCES accounts(id)
);
