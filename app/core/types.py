"""
Custom SQLAlchemy types for automatic serialization.
"""

import json
from sqlalchemy.types import TypeDecorator, String


class JSONString(TypeDecorator):
    """
    Тип для хранения JSON-объектов в строковой колонке.

    Автоматически:
    - При записи: dict → JSON string
    - При чтении: JSON string → dict
    """

    impl = String
    cache_ok = True  # Важно для SQLAlchemy 2.0+

    def process_bind_param(self, value, dialect):
        """Конвертация перед записью в БД: dict → str"""
        if value is None:
            return None
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False)
        return value

    def process_result_value(self, value, dialect):
        """Конвертация после чтения из БД: str → dict"""
        if value is None:
            return None
        if isinstance(value, dict):
            return value  # Уже распаршено (например, в тестах)
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return None