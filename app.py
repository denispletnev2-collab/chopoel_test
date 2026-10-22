#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Универсальная точка входа «ЧёПоел» (Python).
Запуск: python app.py
Автоматически запускает FastAPI + SQLAlchemy (PostgreSQL / SQLite), либо встроенный
реляционный сервер стандартной библиотеки Python (sqlite3), сохраняя 100% истории записей.
"""

import os
import sys
import webbrowser
import threading

def main():
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "127.0.0.1")
    url = f"http://127.0.0.1:{port}"

    if os.getenv("NO_BROWSER") != "1":
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    try:
        import uvicorn
        print(f"🚀 Запуск ЧёПоел (FastAPI + SQLAlchemy 2.0) на {url}")
        uvicorn.run("backend.main:app", host=host, port=port, reload=False)
    except ImportError:
        print(f"🚀 Запуск ЧёПоел (Python Standard Library SQLite 3NF) на {url}")
        from backend.stdlib_server import run_local_server
        run_local_server(host=host, port=port)

if __name__ == "__main__":
    main()
