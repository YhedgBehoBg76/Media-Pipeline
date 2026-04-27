# app/modules/uploaders/youtube_uploader.py
import os
from asyncio import run
import yaml

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from app.core.config import settings
from app.modules.uploaders.base import UploaderAdapter
from app.modules.uploaders.base import UploadResult
from app.modules.uploaders.youtube_auth import get_authenticated_client, YouTubeTokenExpiredError

import logging


logger = logging.getLogger(__name__)


class YouTubeUploader(UploaderAdapter):
    @property
    def name(self) -> str:
        return "youtube_shorts"

    def upload(self, file_path: str, params: dict) -> UploadResult:
        try:
            youtube = run(get_authenticated_client())
        except YouTubeTokenExpiredError as e:
            logger.critical("⚠️ ACTION REQUIRED: %s.\nUSER_CODE: %s.\nDEVICE_CODE: %s", e.verification_url, e.user_code, e.device_code)
            raise

        title = params.get("title", f"Shorts {params.get('media_id')}")[:100]
        description = params.get("description", "")[:5000]
        tags = params.get("tags", [])[:30]

        media = MediaFileUpload(file_path, chunksize=-1, resumable=True, mimetype='video/mp4')

        request = youtube.videos().insert(
            part="snippet,status",
            body={
                "snippet": {"title": title, "description": f"{description}\n\n{' '.join(tags)}", "tags": tags, "categoryId": params.get("category_id")},
                "status": {"privacyStatus": params.get("privacy"), "selfDeclaredMadeForKids": False}
            },
            media_body=media
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                logger.info(f"Uploaded {int(status.progress() * 100)}%")

        if not response:
            raise ValueError("[YoutubeUploader] response is None")

        video_id = response['id']
        url = f"https://youtube.com/shorts/{video_id}"
        logger.info(f"Published: {url}")

        result = UploadResult(
            success=True,
            url=url,
            external_id=response['id'] if response else None,
            platform="youtube_shorts",
            metadata=response
        )

        if not result:
            raise ValueError("[YoutubeUploader] UploadResult is None")

        return result