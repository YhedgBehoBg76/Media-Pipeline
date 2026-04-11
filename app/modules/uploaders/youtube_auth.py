# app/modules/uploaders/youtube_auth.py
import os
import pickle
import logging

from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow

from app.core.config import settings

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl"
]


class YouTubeTokenExpiredError(Exception):
    """Refresh-токен невалиден. Требуется ручная авторизация."""
    def __init__(self, auth_url: str):
        self.auth_url = auth_url
        super().__init__(f"YouTube token expired. Authorize: {auth_url}")


def get_authorization_url() -> str:
    secrets_path = settings.GOOGLE_TOKEN_PATH
    flow = InstalledAppFlow.from_client_secrets_file(secrets_path, SCOPES)
    url, _ = flow.authorization_url(access_type="offline", prompt="consent")
    return url


def get_authenticated_client():
    """
    OAuth 2.0 авторизация для личных аккаунтов.

    Токен генерируется на хосте и монтируется в контейнер.

    Returns:
        YouTube API client
    """
    creds = None

    token_path = settings.GOOGLE_TOKEN_PATH

    # 1. Загружаем сохранённый токен
    if os.path.exists(token_path):
        with open(token_path, 'rb') as token:  # type: ignore[arg-type]
            creds = pickle.load(token)

    # 2. Если токена нет или он истёк
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            # Токен можно обновить без браузера
            creds.refresh(Request())
            # Сохраняем обновлённый токен (если том с правами на запись)
            with open(token_path, 'wb') as token:
                pickle.dump(creds, token) # type: ignore[arg-type]
    else:
        try:
            creds.refresh(Request())
        except Exception:  # RefreshError, TransportError и т.д.
            auth_url = get_authorization_url()
            logger.critical("🔑 YouTube refresh_token invalid. Generate new token: %s", auth_url)
            raise YouTubeTokenExpiredError(auth_url)

    return build('youtube', 'v3', credentials=creds)