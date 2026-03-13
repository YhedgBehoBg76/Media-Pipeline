from typing import List, Dict, Any, Optional
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.modules.sources.base import SourceAdapter
from app.core.config import settings
from app.models.media import MediaItem


class YouTubeAdapter(SourceAdapter):
    """
    Адаптер для работы с YouTube как источником контента.

    Использует YouTube Data API v3 для поиска видео с возможностью
    фильтрации по лицензии, категории и другим параметрам.
    """

    MAX_RESULTS_PER_REQUEST = 10
    YOUTUBE_API_QUOTA_COST = 100

    def __init__(self, db_session: Optional[Session] = None):
        """
        Args:
            db_session: Сессия БД для проверки дубликатов (опционально)
        """
        self._db_session = db_session
        self._youtube = None

    def _get_youtube_client(self):
        """Ленивая инициализация Youtube клиента"""
        if self._youtube is None:
            if not settings.YOUTUBE_API_KEY:
                raise ValueError(
                    "Youtube API key is not configured"
                    "set YOUTUBE_API_KEY in .env file"
                )
            self._youtube = build(
                'youtube',
                'v3',
                developerkey=settings.YOUTUBE_API_KEY,
                cache_discovery=False
            )
        return self._youtube

    def get_new_content(self, config: dict) -> List[Dict[str, Any]]:
        """
        Получает список новых видео из YouTube для обработки.

        Args:
            config: Конфигурация поиска, например:
                {
                    "query": "funny cats",
                    "license": "creativeCommon",
                    "max_results": 10,
                    "order": "relevance"
                }

        Returns:
            Список словарей с информацией о видео:
                [
                    {
                        "video_id": "abc123",
                        "url": "https://youtube.com/watch?v=abc123",
                        "title": "Video Title",
                        "source_type": "youtube"
                    }
                ]

        Raises:
            ValueError: Если API ключ не настроен
            HttpError: Если YouTube API вернул ошибку
        """
        query = config.get("query", "")
        license_filter = config.get("license", "creativeCommon")
        max_results = min(
            config.get("max_results", self.MAX_RESULTS_PER_REQUEST),
            50
        )
        order = config.get("order", "relevance")

        if not query:
            return []

        try:
            youtube = self._get_youtube_client()

            request = youtube.search().list(
                q=query,
                type="video",
                videoLicense=license_filter,
                maxResults=max_results,
                part="snippet",
                order=order
            )

            response = request.execute()
            videos = self._parse_search_response(response)
            new_videos = self._filter_duplicates(videos)

            return new_videos

        except HttpError as e:
            #TODO: сделать логирование ошибки через Logger
            error_details = {
                "status_code": e.resp.status,
                "reason": e.error_details.get("reason", "unknown"),
                "message": str(e)
            }
            print(f"[YoutubeAdapter] API Error: {error_details}")
            return []

        except Exception as e:
            print(f"[YoutubeAdapter] Unexpected Error: {str(e)}")
            return []

    def _filter_duplicates(self, videos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Фильтрует уже обработанные видео по базе данных.

        Args:
            videos: Список всех найденных видео

        Returns:
            Список только новых видео (не обработанных ранее)
        """
        if not self._db_session or not videos:
            return videos

        new_video_ids = {v["video_id"] for v in videos}

        existing = self._db_session.query(MediaItem.video_id).filter(
            MediaItem.video_id.in_(new_video_ids)
        ).all()

        existing_ids = {row[0] for row in existing if row[0]}

        return [v for v in videos if v["video_id"] not in existing_ids]

    @staticmethod
    def _parse_search_response(response: Dict) -> List[Dict[str, Any]]:
        """
        Парсит ответ YouTube Search API в унифицированный формат.

        Args:
            response: Сырой ответ от YouTube API

        Returns:
            Список видео в унифицированном формате
        """
        videos = []

        for item in response.get("items", []):
            video_id = item.get("id", {}).get("videoId")
            snippet = item.get("snippet", {})

            if not video_id:
                continue

            videos.append({
                "video_id": video_id,
                "url": f"https://youtube.com/watch?v={video_id}",
                "title": snippet.get("title", "Untitled"),
                "description": snippet.get("description", ""),
                "channel_title": snippet.get("channelTitle", ""),
                "published_at": snippet.get("publishedAt", ""),
                "source_type": "youtube",
                "thumbnail": snippet.get("thumbnails", {}).get("high", {}).get("url", "")
            })

        return videos
