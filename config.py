import os

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "TEST")
    DATABASE = os.environ.get("DATABASE_URL", "ønsker.db")