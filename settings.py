from os import environ

from dotenv import load_dotenv

load_dotenv()

BANK_NAME = environ.get("BANK_NAME", "PyBank S. A.")
BRANCH_CODE = environ.get("BRANCH_CODE", "0001")
BANK_SECRET_KEY = environ.get("BANK_SECRET_KEY", "chave-secreta-padrao-apenas-para-dev")
