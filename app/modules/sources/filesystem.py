import os
import logging
from typing import List, Dict
from app.modules.sources.base import SourceAdapter

#TODO: доделать FileSystemAdapter, сделать для него адаптеры скачивания, загрузки для MVP, чтобы не ебаться с ютубом

logger = logging.getLogger(__name__)

class FileSystemAdapter(SourceAdapter):
    """
    Адаптер для сканирования локальной файловой системы.
    Ищет видеофайлы в указанной папке.
    """
    SUPPORTED_EXTENSIONS = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.m4v'}

    def get_new_content(self, config: dict) -> List[Dict]:
        """
        Сканирует папку и возвращает новые видеофайлы.

        Args:
            config: Конфигурация источника
                - path: Путь к папке с видео
                - extensions: Список расширений (опционально)
                - recursive: Рекурсивный поиск (опционально)

        Returns:
            Список словарей с информацией о новых файлах
        """
        if not self.validate_config(config):
            raise ValueError(f"[FileSystemAdapter] invalid config: {config}")

        recursive = config.get("recursive", False)

        video_files = {}

    def validate_config(self, config: dict) -> bool:
        path = config.get("path")
        if not path:
            return False

        if not os.path.exists(path):
            return False

        if not os.path.isdir(path):
            return False

        return True

    def _is_video_file(self, filename: str):
        _, ext = os.path.splitext(filename)
        return ext.lower() in self.SUPPORTED_EXTENSIONS
