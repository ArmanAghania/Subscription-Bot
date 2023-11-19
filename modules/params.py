import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DB_URL = os.getenv("DB_URL")
API_ID=os.getenv("API_ID")
API_HASH=os.getenv("API_HASH")