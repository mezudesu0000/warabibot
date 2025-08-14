import os

TOKEN = os.environ.get("TOKEN", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
VERIFY_ROLE_NAME = os.environ.get("VERIFY_ROLE_NAME", "Verified")

DB_PATH = os.environ.get("DB_PATH", "db.json")
PORT = int(os.environ.get("PORT", "10000"))
MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")
