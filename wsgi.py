"""Punto de entrada WSGI:  gunicorn -w 4 -b 0.0.0.0:8000 wsgi:app"""
from stocktrack import create_app

app = create_app()
