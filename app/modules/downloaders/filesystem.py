import shutil
from pathlib import Path
from app.modules.downloaders.base import DownloaderAdapter


class FilesystemDownloader(DownloaderAdapter):
    """Копирует файл из локальной папки вместо скачивания"""

    def download(self, media_item) -> str:
        """
        Копирует файл из original_url во временную папку.

        Args:
            media_item: MediaItem с original_url = путь к файлу

        Returns:
            Путь к скопированному файлу
        """
        if not media_item.original_url:
            raise ValueError(
                f"[FilesystemDownloader] original_url is None"
            )

        source_path = media_item.original_url
        dest_path = f"/tmp/media/{media_item.id}{Path(source_path).suffix}"

        # Создаём папку если нет
        Path(dest_path).parent.mkdir(parents=True, exist_ok=True)

        # Копируем файл
        shutil.copy2(source_path, dest_path)

        return dest_path