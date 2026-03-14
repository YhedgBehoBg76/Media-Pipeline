
from abc import ABC, abstractmethod

from app.models.media import MediaItem


class DownloaderAdapter:
    """базовый класс для всех загрузчиков"""

    @abstractmethod
    def download(self, media_item: MediaItem) -> str:
        pass