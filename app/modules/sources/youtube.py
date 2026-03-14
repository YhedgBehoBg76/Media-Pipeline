from typing import List, Dict, Any, Optional
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from sqlalchemy.orm import Session

from app.modules.sources.base import SourceAdapter
from app.core.config import settings
from app.models.media import MediaItem
from abc import abstractmethod

#TODO: 1. Сделать отсеивание шортсов. Сейчас он находит и сохраняет в MediaItem ссылки на шортсы
#TODO: 2. Надо чето сделать с _on_state_update. Возможно стоит добавить это поле в SourceAdapter

class BaseYoutubeAdapter(SourceAdapter):
    ALLOWED_LICENSES = {"any", "creativeCommon"}
    ALLOWED_ORDERS = {"date", "rating", "relevance", "title", "videoCount", "viewCount"}

    DEFAULT_RESULTS_PER_REQUEST = 10
    DEFAULT_LICENSE = "creativeCommon"
    DEFAULT_ORDER = "relevance"

    MAX_RESULTS_PER_REQUEST = 50
    YOUTUBE_API_QUOTA_COST = 100

    def __init__(self, db_session: Optional[Session] = None):
        """
        Args:
            db_session: Сессия БД для проверки дубликатов (опционально)
        """
        self._db_session = db_session
        self._youtube = None

    @abstractmethod
    def get_new_content(self, config: dict) -> List[Dict]:
        pass

    @abstractmethod
    def validate_config(self, config: dict) -> bool:
        pass

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
                developerKey=settings.YOUTUBE_API_KEY,
                cache_discovery=False
            )
        return self._youtube

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

    def _get_quota_info(self) -> dict:
        """
        Возвращает информацию о квотах YouTube API.

        Returns:
            Словарь с информацией о квотах
        """
        return {
            "daily_limit": 10000,
            "search_cost": self.YOUTUBE_API_QUOTA_COST,
            "max_requests_per_day": 10000 // self.YOUTUBE_API_QUOTA_COST,
            "current_config_cost": self.YOUTUBE_API_QUOTA_COST
        }

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


class YouTubeSearchAdapter(BaseYoutubeAdapter):
    """
    Адаптер для поиска видео на Youtube.
    """

    def __init__(self):
        super().__init__()

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

        Required:
            query

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
        license_filter = config.get("license", self.DEFAULT_LICENSE)
        max_results = min(
            config.get("max_results", self.DEFAULT_RESULTS_PER_REQUEST),
            self.MAX_RESULTS_PER_REQUEST
        )
        order = config.get("order", self.DEFAULT_ORDER)

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

    def validate_config(self, config: dict) -> bool:
        if not config.get("query"):
            return False

        license_filter = config.get("license", self.DEFAULT_LICENSE)
        if license_filter not in self.ALLOWED_LICENSES:
            return False

        order = config.get("order", self.DEFAULT_ORDER)
        if order not in self.ALLOWED_ORDERS:
            return False

        max_results = config.get("max_results", self.DEFAULT_RESULTS_PER_REQUEST)
        if not isinstance(max_results, int):
            try:
                max_results = int(max_results)
            except ValueError:
                return False

        if not (1 <= max_results <= self.MAX_RESULTS_PER_REQUEST):
            return False

        return True


class YoutubeChannelsAdapter(BaseYoutubeAdapter):
    """
    Класс для сбора видео на Youtube с указанных каналов
    """
    DEFAULT_ORDER = "viewCount"

    def __init__(self):
        super().__init__()

        self._on_state_update = None

    def get_new_content(self, config: dict) -> List[Dict]:
        """
        Получает видео из списка каналов с пагинацией.

        Args:
            config: Конфигурация с пагинацией:
                {
                    "channels": [
                        {"channel_id": "UC123", "name": "Channel A"},
                        {"channel_id": "UC456", "name": "Channel B"}
                    ],
                    "order": "viewCount",
                    "max_results": 10,
                    "license": "creativeCommon",
                    "current_channel_index": 0,      # ← Для пагинации
                    "last_page_token": "CAUQAA"      # ← Для пагинации
                }

        Returns:
            Список новых видео в формате:
                [
                    {
                        "video_id": "abc123",
                        "url": "https://youtube.com/watch?v=abc123",
                        "title": "Video Title",
                        "source_type": "youtube_channels"
                    }
                ]
        """

        if not self.validate_config(config):
            raise ValueError(
                f"Invalid config for {__class__.__name__}"
                f"config: {config}"
            )

        channels = config.get("channels", [])
        max_results = min(
            config.get("max_results", self.DEFAULT_RESULTS_PER_REQUEST),
            self.MAX_RESULTS_PER_REQUEST
        )
        order = config.get("order", self.DEFAULT_ORDER)
        license_filter = config.get("license", self.DEFAULT_LICENSE)

        channel_index = config.get("current_channel_index", 0)
        page_token = config.get("last_page_token")

        if not channels or channel_index >= len(channels):
            channel_index = 0
            page_token = None

        channel = channels[channel_index]
        channel_id = channel.get("channel_id")

        search_params = {
            "channelId": channel_id,
            "type": "video",
            "maxResults": max_results,
            "part": "snippet",
            "order": order,
            "videoLicense": license_filter
        }

        if page_token:
            search_params["pageToken"] = page_token

        try:
            youtube = self._get_youtube_client()

            request = youtube.search().list(**search_params)
            response = request.execute()

            next_page_token = response.get("nextPageToken")

            if not next_page_token:
                channel_index += 1

            self._on_state_update({
                "current_channel_index": channel_index,
                "last_page_token": next_page_token
            })

            videos = self._parse_search_response(response)
            new_videos = self._filter_duplicates(videos)

            return new_videos

        except HttpError as e:
            error_details = {
                "status_code": e.resp.status,
                "reason": e.error_details.get("reason", "unknown") if e.error_details else "unknown",
                "message": str(e)
            }
            print(f"[YouTubeChannelsAdapter] API Error: {error_details}")
            return []

        except Exception as e:
            print(f"[YouTubeChannelsAdapter] Unexpected Error: {str(e)}")
            return []

    def validate_config(self, config: dict) -> bool:
        channels = config.get("channels")
        if not channels or not isinstance(channels, list):
            return False

        for channel in channels:
            if not isinstance(channel, dict) or not channel.get("channel_id"):
                return False

        order = config.get("order", self.DEFAULT_ORDER)
        if order not in self.ALLOWED_ORDERS:
            return False

        license_filter = config.get("license", self.DEFAULT_LICENSE)
        if license_filter not in self.ALLOWED_LICENSES:
            return False

        max_results = config.get("max_results", self.DEFAULT_RESULTS_PER_REQUEST)
        if not isinstance(max_results, int) or not (1 <= max_results <= self.MAX_RESULTS_PER_REQUEST):
            return False

        return True

