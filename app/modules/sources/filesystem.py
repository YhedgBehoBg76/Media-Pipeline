import os
import logging
from pathlib import Path
from typing import List, Dict
from app.modules.sources.base import SourceAdapter


logger = logging.getLogger(__name__)

class FilesystemAdapter(SourceAdapter):
    """
    Адаптер для сканирования локальной файловой системы.

    Поддерживаемые форматы: .mp4, .mkv, .avi, .mov, .webm
    Метаданные: base.meta.json (папка) + video.meta.json (файл)
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
            [
                {
                    "url": "/media/spongebob/S01E01.mp4",
                    "external_id": "S01E01",
                    "source_type": "filesystem",
                    "metadata": {
                        "title": "Губка Боб - Помощник",
                        "description": "Приключения... Серия 1",
                        "tags": ["spongebob", "cartoon"]
                    }
                }
            ]
        """
        if not self.validate_config(config):
            raise ValueError(f"[FileSystemAdapter] invalid config: {config}")

        recursive = config.get("recursive", False)
        path = config.get("path")

        base_meta_path = self._get_base_meta_file_path(path)
        base_metadata = self._load_json_file(base_meta_path)

        videos = []

        for file in Path(path).iterdir():
            if file.is_dir() or file.name.startswith('.'):
                continue

            if not self._is_video_file(file.name):
                continue

            individual_meta_path = self._get_meta_file_path(file)
            individual_metadata = self._load_json_file(individual_meta_path)

            merged_metadata = self._merge_metadata(
                base=base_metadata,
                individual=individual_metadata,
                filename=file.stem
            )

            videos.append({
                "url": str(file.absolute()),
                "external_id": file.stem,
                "source_type": "filesystem",
                "metadata": merged_metadata
            })

        return videos

    def validate_config(self, config: dict) -> bool:
        path = config.get("path")
        if not path:
            print("NO PATH")
            return False

        if not os.path.exists(path):
            print(f"PATH DOES NOT EXISTS: {path}")
            return False

        if not os.path.isdir(path):
            print("PATH IS NOT A DIR")
            return False

        return True

    def _is_video_file(self, filename: str):
        _, ext = os.path.splitext(filename)
        return ext.lower() in self.SUPPORTED_EXTENSIONS
