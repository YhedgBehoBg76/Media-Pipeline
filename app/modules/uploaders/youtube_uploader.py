# app/modules/uploaders/youtube_uploader.py
import os
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from app.modules.uploaders.base import UploaderAdapter
from app.modules.uploaders.youtube_auth import get_authenticated_client
import logging

logger = logging.getLogger(__name__)


class YouTubeUploader(UploaderAdapter):
    PRIVACY_STATUS = 'private'
    CATEGORY_ID = '22'

    @property
    def name(self) -> str:
        return "youtube_shorts"

    def upload(self, file_path: str, params: dict) -> str:
        token_path = os.getenv("GOOGLE_TOKEN_PATH", "/app/secrets/token.pickle")

        youtube = get_authenticated_client(token_path)

        title = params.get("title", f"Shorts {params.get('media_id')}")[:100]
        description = params.get("description", "")[:5000]
        tags = params.get("tags", [])[:30]

        media = MediaFileUpload(file_path, chunksize=-1, resumable=True, mimetype='video/mp4')

        request = youtube.videos().insert(
            part="snippet,status",
            body={
                "snippet": {"title": title, "description": description, "tags": tags, "categoryId": self.CATEGORY_ID},
                "status": {"privacyStatus": self.PRIVACY_STATUS, "selfDeclaredMadeForKids": False}
            },
            media_body=media
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                logger.info(f"Uploaded {int(status.progress() * 100)}%")

        video_id = response['id']
        url = f"https://youtube.com/shorts/{video_id}"
        logger.info(f"Published: {url}")
        return url