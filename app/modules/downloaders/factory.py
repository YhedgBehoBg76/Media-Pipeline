
from typing import Dict, Type
from app.modules.downloaders.base import DownloaderAdapter
from app.modules.downloaders.youtube import YoutubeDownloader
from app.modules.downloaders.filesystem import FilesystemDownloader


class DownloaderFactory:
    _adapters: Dict[str, Type[DownloaderAdapter]] = {
        "youtube_channels": YoutubeDownloader,
        "youtube_search": YoutubeDownloader,
        "filesystem": FilesystemDownloader
    }

    @classmethod
    def get_downloader(cls, source_type: str) -> DownloaderAdapter:
        downloader_class = cls._adapters.get(source_type.lower())

        if not downloader_class:
            supported = ", ".join(cls._adapters.keys())
            raise ValueError(
                f"Unknown source type: '{source_type}'"
                f"Supported types: {supported}"
            )

        return downloader_class()

    @classmethod
    def get_available_types(cls) -> list:
        return list(cls._adapters.keys())
