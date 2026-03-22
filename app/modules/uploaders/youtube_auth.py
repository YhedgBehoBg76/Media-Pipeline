# app/modules/uploaders/youtube_auth.py
import os
import pickle
import logging
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl"
]


def get_authenticated_client(token_path: str):
    """
    OAuth 2.0 авторизация для личных аккаунтов.

    Токен генерируется на хосте и монтируется в контейнер.

    Args:
        token_path: Путь к token.pickle (смонтированному из хоста)

    Returns:
        YouTube API client
    """
    creds = None

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
            raise RuntimeError(
                f"\nyoutube_auth error: token_path='{token_path}'\n"
                f"os.path.exists(token_path)='{os.path.exists(token_path)}'\n"
                f"creds is {'' if not creds else 'not'} None\n"
                f"creds.expired='{creds.expired if creds else None}'\n"
                f"creds.refresh_token='{creds.refresh_token if creds else None}'\n"
            )

    return build('youtube', 'v3', credentials=creds)