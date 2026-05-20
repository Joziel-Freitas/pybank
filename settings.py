"""
Application Settings Module.

This module acts as the central configuration hub for the PyBank system.
Following the 12-Factor App methodology, it loads environment variables
from the .env file and provides safe fallbacks and type casting for the
entire application.
"""

from os import environ

from dotenv import load_dotenv

# Load environment variables from the .env file into os.environ
load_dotenv()

# ==============================================================================
# Domain Configurations
# ==============================================================================
# The commercial name of the Bank displayed in the terminal UI
BANK_NAME: str = environ.get("BANK_NAME", "PyBank S. A.")

# The 4-digit code identifying the home branch
BRANCH_CODE: str = environ.get("BRANCH_CODE", "0001")

# ==============================================================================
# Security & Cryptography
# ==============================================================================
# Cryptographic key for hashing passwords and securing AccessTokens (HMAC).
# WARNING: The default value must strictly be used in local development only.
BANK_SECRET_KEY: str = environ.get(
    "BANK_SECRET_KEY", "default-dev-secret-key-do-not-use-in-prod"
)

# ==============================================================================
# Kiosk Terminal Controls
# ==============================================================================
# The secret numeric code used to safely shutdown the Kiosk terminal loop
ADMIN_EXIT_CODE: int = int(environ.get("PYBANK_ADMIN_CODE", "999999"))

# Maximum allowed idle time (in seconds) before killing a user session
SYSTEM_TIMEOUT: float = float(environ.get("SYSTEM_TIMEOUT", "30.0"))
