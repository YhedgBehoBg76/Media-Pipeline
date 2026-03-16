
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from app.core.config import settings
from app.modules.uploaders.base import UploaderAdapter


class YouTubeUploader(UploaderAdapter):
    """Загрузчик на YouTube Shorts"""

    @property
    def name(self) -> str:
        return "youtube_shorts"

    def upload(self, file_path: str, params: dict) -> str:
        """
        Загружает видео на YouTube.

        Args:
            file_path: Путь к видеофайлу
            params: Метаданные (title, description, tags)

        Returns:
            YouTube video ID
        """
        # Инициализация YouTube API
        youtube = build(
            'youtube',
            'v3',
            developerKey=settings.YOUTUBE_API_KEY
        )

        # Метаданные видео
        title = params.get("title", f"Shorts {params.get('media_id', 'unknown')}")
        description = params.get("description", "")
        tags = params.get("tags", ["shorts"])

        body = {
            'snippet': {
                'title': title[:100],  # Лимит YouTube
                'description': description[:5000],
                'tags': tags
            },
            'status': {
                'privacyStatus': params.get("privacy", "public")  # public, private, unlisted
            }
        }

        # Загрузка файла
        media = MediaFileUpload(
            file_path,
            chunksize=-1,
            resumable=True,
            mimetype='video/mp4'
        )

        request = youtube.videos().insert(
            part=','.join(body.keys()),
            body=body,
            media_body=media
        )

        response = request.next_chunk()
        video_id = response[1]['id']

        return f"https://youtube.com/shorts/{video_id}"