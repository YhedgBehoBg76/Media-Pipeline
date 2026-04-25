import os
import pickle
import logging
import asyncio
import httpx
import time
import json
from typing import Optional, Tuple
from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from googleapiclient.discovery import build
from app.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/youtube/auth", tags=["YouTube Auth"])

# Для HTTP-запросов Google требует пробелы, для Credentials — список
SCOPES = [
    "https://www.googleapis.com/auth/youtube"
    # "https://www.googleapis.com/auth/youtube.upload",
    # "https://www.googleapis.com/auth/youtube.force-ssl"
]
SCOPES_STR = " ".join(SCOPES)
DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"

# 📦 In-memory хранилище активных сессий. В продакшене замените на Redis/PostgreSQL.
_pending_flows: dict[str, dict] = {}


class YouTubeTokenExpiredError(Exception):
    def __init__(self, verification_url: str, user_code: str, device_code: str):
        self.verification_url = verification_url
        self.user_code = user_code
        self.device_code = device_code
        super().__init__(f"Token expired. Open {verification_url} and enter code: {user_code}")


def _save_token_sync(creds: Credentials) -> None:
    token_path = settings.GOOGLE_TOKEN_PATH
    os.makedirs(os.path.dirname(token_path), exist_ok=True)
    with open(token_path, "wb") as f:
        pickle.dump(creds, f)


def _load_token_sync(path: str) -> Optional[Credentials]:
    if not os.path.exists(path):
        logger.error(f"GOOGLE TOKEN PATH DOES NOT EXISTS: '{path}'")
        return None
    with open(path, "rb") as f:
        return pickle.load(f)


async def get_authenticated_client() -> build:
    """
    Получает YouTube клиент с авто-рефрешем.
    """
    token_path = settings.GOOGLE_TOKEN_PATH

    # Загружаем токен
    creds = await asyncio.to_thread(_load_token_sync, token_path)

    if creds and creds.valid:
        logger.debug("✅ Using valid access token")
        return build("youtube", "v3", credentials=creds)

    # Пробуем рефреш
    if creds and creds.refresh_token:
        try:
            logger.info("🔄 Refreshing expired token...")
            await asyncio.to_thread(lambda: creds.refresh(GoogleRequest()))
            await asyncio.to_thread(_save_token_sync, creds)  # Сохраняем новый access_token
            logger.info("✅ Token refreshed successfully")
            return build("youtube", "v3", credentials=creds)
        except Exception as e:
            logger.error(f"❌ Token refresh failed: {type(e).__name__}: {e}")
            # Не падаем сразу — даём шанс на переавторизацию

    raise HTTPException(
        status_code=401,
        detail={
            "error": "youtube_auth_token_invalid",
            "message": "YouTube token expired or missing refresh capability",
            "action": "Please regenerate token using generate_token.py on a machine with browser",
            "command": f"python generate_token.py client_secrets.json {token_path}",
            "transfer_hint": "Then copy the file to this server via scp/rsync/base64"
        }
    )