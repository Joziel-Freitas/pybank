"""Application Settings Module.

This module acts as the central configuration hub for the PyBank system.
Following the 12-Factor App methodology, it loads environment variables
from the .env file and provides safe fallbacks and type casting for the
entire application.
"""

from datetime import timedelta
from os import environ
from zoneinfo import ZoneInfo

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

# Time-To-Live (TTL) duration for Lobby authentication tokens (default: 300s / 5 min)
LOBBY_TIME_SECONDS: timedelta = timedelta(seconds=int(environ.get("LOBBY_TIME", "300")))

# Time-To-Live (TTL) duration for Vault authorization tokens (default: 120s / 2 min)
VAULT_TIME_SECONDS: timedelta = timedelta(seconds=int(environ.get("VAULT_TIME", "120")))

# ==============================================================================
# Kiosk Terminal Controls
# ==============================================================================
# The secret numeric code used to safely shutdown the Kiosk terminal loop
ADMIN_EXIT_CODE: int = int(environ.get("PYBANK_ADMIN_CODE", "999999"))

# Maximum allowed idle time (in seconds) between keypresses before killing a user session
INACTIVITY_TIMEOUT: int = int(environ.get("INACTIVITY_TIMEOUT", "30"))

# Maximum total duration (in seconds) allowed for a single input session regardless of activity
TOTAL_TIMEOUT: int = int(environ.get("TOTAL_TIMEOUT", "120"))

# ==============================================================================
# System Locality & Time
# ==============================================================================
# The default timezone used for all business time calculations.
# Ensures deterministic financial operations regardless of the host OS timezone.
SYSTEM_TIMEZONE: ZoneInfo = ZoneInfo(
    environ.get("SYSTEM_TIMEZONE", "America/Sao_Paulo")
)
