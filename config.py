"""Application configuration, loaded from environment variables.

Values are read from a `.env` file (see `.env.example` for every variable
this app expects) via python-dotenv, then exposed as class attributes so
app.py can do `app.config.from_object(Config)`. Nothing here is a secret —
the actual values live only in the untracked `.env` file.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / '.env')


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY')
    SQLALCHEMY_DATABASE_URI = os.environ.get('SQLALCHEMY_DATABASE_URI', 'sqlite:///database.db')

    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'true').lower() == 'true'
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = ("JSPICT, Kazaure", MAIL_USERNAME)

    PAYMENT_GATEWAY_MODE = os.environ.get('PAYMENT_GATEWAY_MODE', 'remita')

    REMITA_MERCHANT_ID = os.environ.get('REMITA_MERCHANT_ID')
    REMITA_API_KEY = os.environ.get('REMITA_API_KEY')
    REMITA_SERVICE_TYPE_ID = os.environ.get('REMITA_SERVICE_TYPE_ID')
    REMITA_PUBLIC_KEY = os.environ.get('REMITA_PUBLIC_KEY')
    REMITA_BASE_URL = os.environ.get('REMITA_BASE_URL')
    REMITA_CHECKOUT_BASE_URL = os.environ.get('REMITA_CHECKOUT_BASE_URL')
