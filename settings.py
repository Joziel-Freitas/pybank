from os import environ

from dotenv import load_dotenv

load_dotenv()

BANK_NAME = environ.get("BANK_NAME", "PyBank S. A.")
BRANCH_CODE = environ.get("BRANCH_CODE", "0001")
BANK_SECRET_KEY = environ.get("BANK_SECRET_KEY", "chave-secreta-padrao-apenas-para-dev")
ADMIN_EXIT_CODE = int(environ.get("PYBANK_ADMIN_CODE", "999999"))
SYSTEM_TIMEOUT = float(environ.get("SYSTEM_TIMEOUT", "30"))
