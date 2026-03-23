from typing import Dict, Any, Optional
from abc import ABC, abstractmethod
from pydantic import BaseModel


class UploadResult(BaseModel):
    success: bool
    url: str
    external_id: str
    platform: str
    metadata: Optional[Dict[str, Any]] = None


class UploaderAdapter(ABC):
    """Базовый класс для всех загрузчиков видео"""
    def upload(self, file_path, params: dict):
        """
        Загружает видео и возвращает идентификатор/путь.

        Args:
            file_path: Путь к файлу для загрузки
            params: Параметры загрузки (метаданные, название, etc.)

        Returns:
            Идентификатор загруженного файла (S3 ключ, YouTube ID, etc.)

        Raises:
            Exception: Если загрузка не удалась
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Возвращает название загрузчика (для логирования)"""
        pass
