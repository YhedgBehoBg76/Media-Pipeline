from typing import List, Dict

from app.modules.sources.base import SourceAdapter


class YouTubeAdapter(SourceAdapter):
    def get_new_content(self, config: dict) -> List[Dict]:
        # TODO: Здесь будет вызов YouTube API
        # Для теста вернем фейковые данные
        return [{
            "url": "https://youtube.com/watch?v=test",
            "title": "Test Video",
            "source_type": "youtube"
        }]