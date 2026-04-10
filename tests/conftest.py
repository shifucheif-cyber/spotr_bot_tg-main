import os
import sys
from pathlib import Path

# Тесты всегда используют SQLite in-memory (не требуют PostgreSQL)
os.environ.setdefault("DB_BACKEND", "sqlite")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
