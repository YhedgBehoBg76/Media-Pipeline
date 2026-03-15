# app/modules/uploaders/factory.py
from typing import Dict, Type
from app.modules.uploaders.base import UploaderAdapter
from app.modules.uploaders.s3_uploader import S3Uploader


# from app.modules.uploaders.youtube_uploader import YouTubeUploader

class UploaderFactory:
    """Фабрика для создания загрузчиков"""

    _uploaders: Dict[str, Type[UploaderAdapter]] = {
        "s3": S3Uploader,
        # "youtube": YouTubeUploader,  # ← Будущий
        # "tiktok": TikTokUploader,    # ← Будущий
    }

    @classmethod
    def get_uploader(cls, uploader_type: str) -> UploaderAdapter:
        """
        Создаёт и возвращает загрузчик по типу.

        Args:
            uploader_type: Тип загрузчика (s3, youtube, tiktok)

        Returns:
            Экземпляр соответствующего загрузчика

        Raises:
            ValueError: Если тип не поддерживается
        """
        uploader_class = cls._uploaders.get(uploader_type.lower())

        if not uploader_class:
            supported = ", ".join(cls._uploaders.keys())
            raise ValueError(
                f"Unknown uploader type: '{uploader_type}'. "
                f"Supported types: {supported}"
            )

        return uploader_class()

    @classmethod
    def get_available_types(cls) -> list:
        """Возвращает список доступных загрузчиков"""
        return list(cls._uploaders.keys())