
import yt_dlp
import os
from app.modules.downloaders.base import DownloaderAdapter
from app.models.media import MediaItem


class YoutubeDownloader(DownloaderAdapter):

    def download(self, media_item: MediaItem) -> str:
        """
        Скачивает видео с YouTube.

        Args:
            media_item: Объект MediaItem с URL видео

        Returns:
            Путь к скачанному файлу на диске

        Raises:
            Exception: Если скачивание не удалось
        """
        test = True
        test_format = "best[height<=480]"
        video_format = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"

        os.makedirs("/tmp/media", exist_ok=True)
        output_path = f"/tmp/media/{media_item.id}.mp4"

        ydl_opts = {
            'format': test_format if test else video_format,
            'outtmpl': output_path,
            'nonplaylist': True
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([media_item.original_url])
            return output_path
        except Exception as e:
            raise Exception(f"[YoutubeDownloader] Failed to download: {str(e)}")

