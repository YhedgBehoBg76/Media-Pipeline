import json
from abc import ABC, abstractmethod
from typing import List, Dict
from pathlib import Path

class SourceAdapter(ABC):
    @abstractmethod
    def get_new_content(self, config: dict) -> List[Dict]:
        """
        Возвращает список новых видео для обработки.

        Returns:
            [
                {
                    "url": str,
                    "source_type": str,

                    "metadata":
                    {
                        #обязательные
                        "title": str,
                        "description": str,
                        "tags": list[str], # контентные теги: cartoon, spongebob

                        #опциональные
                        "yt_video_id": str
                        "yt_channel_id": str
                    }
                }
            ]
        """
        pass

    @abstractmethod
    def validate_config(self, config: dict) -> bool:
        """Проверяет валидность конфигурации источника"""
        pass

    @staticmethod
    def _load_json_file(path: Path):
        """
        Загружает JSON файл с обработкой ошибок.

        Returns:
            dict с данными или пустой dict при ошибке
        """
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, PermissionError):
            return {}

    @staticmethod
    def _get_meta_file_path(video_path: Path) -> Path:
        """
        Возвращает путь к .meta.json файлу для видео.
        Формат: /path/to/video.mp4 → /path/to/video.meta.json
        """
        return video_path.parent / f"{video_path.stem}.meta.json"

    @staticmethod
    def _get_base_meta_file_path(folder_path: Path) -> Path:
        """
        Возвращает путь к base.meta.json в папке.
        """
        return folder_path / "base.meta.json"

    @staticmethod
    def _merge_metadata(base: dict, individual: dict, filename: str) -> dict:
        """
        Сливает базовые и индивидуальные метаданные.

        Правила:
        - title: individual.title или f"{base.folder_title} - {filename}"
        - description: конкатенация base + individual
        - tags: объединение списков (без дубликатов)
        - остальные поля: приоритет у individual
        """

        if individual.get("title"):
            title = individual["title"]
        elif base.get("folder_title"):
            title = f"{base['folder_title']} - {filename}"
        else:
            title = filename

        desc_parts = [base.get("description"), individual.get("description")]
        description = " ".join(p for p in desc_parts if p).strip()

        base_tags = base.get("tags", []) if isinstance(base.get("tags"), list) else []
        ind_tags = individual.get("tags", []) if isinstance(individual.get("tags"), list) else []
        tags = list(dict.fromkeys(base_tags + ind_tags))

        merged = {**base, **individual}

        return {
            "title": title,
            "description": description,
            "tags": tags,
            **{k: v for k, v in merged.items()
               if k not in ["title", "description", "tags", "folder_title"]}
        }
