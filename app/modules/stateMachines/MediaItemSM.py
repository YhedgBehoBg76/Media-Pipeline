from statemachine import StateMachine, State
from app.models.media import MediaStatus
import logging

logger = logging.getLogger(__name__)

class MediaStateMachine(StateMachine):
    # 🔹 Состояния
    pending = State(value=MediaStatus.PENDING, initial=True)
    downloading = State(value=MediaStatus.DOWNLOADING)
    downloaded = State(value=MediaStatus.DOWNLOADED)
    segmenting = State(value=MediaStatus.SEGMENTING)
    segmented = State(value=MediaStatus.SEGMENTED)
    source = State(value=MediaStatus.SOURCE)
    processing = State(value=MediaStatus.PROCESSING)
    processed = State(value=MediaStatus.PROCESSED)
    uploading = State(value=MediaStatus.UPLOADING)
    uploaded = State(value=MediaStatus.UPLOADED)
    publishing = State(value=MediaStatus.PUBLISHING)
    published = State(value=MediaStatus.PUBLISHED, final=True)
    failed = State(value=MediaStatus.FAILED)

    # 🔹 Основные переходы (State → State)

    _init_segmented = pending.to(segmented)

    start_download = pending.to(downloading)
    finish_download = downloading.to(downloaded)  # Исправлено: переход идёт от состояния, а не от другого триггера

    start_segment = downloaded.to(segmenting)
    finish_segment = segmenting.to(source)

    start_process = segmented.to(processing)
    finish_process = processing.to(processed)

    start_upload = processed.to(uploading)
    finish_upload = uploading.to(uploaded)

    start_publish = uploaded.to(publishing)
    finish_publish = publishing.to(published)

    source_to_published = source.to(published)

    # 🔹 Переходы в ошибку (вместо | прописаны явно)
    fail_download = downloading.to(failed)
    fail_segment = segmenting.to(failed)
    fail_process = processing.to(failed)
    fail_upload = uploading.to(failed)
    fail_publish = publishing.to(failed)

    # 🔹 Ретраи из failed
    retry_download = failed.to(downloading)
    retry_segment = failed.to(segmenting)
    retry_process = failed.to(processing)
    retry_upload = failed.to(uploading)
    retry_publish = failed.to(publishing)  # Логичнее возвращаться в publishing, а не сразу в published
    retry_full = failed.to(pending)

    # 🔹 Хуки
    # @downloading.on_enter
    # def log_start_download(self):
    #     logger.info(f"Media Item (id={self.model.id}) starts downloading...")
    #
    # @segmenting.on_enter
    # def log_start_segmenting(self):
    #     logger.info(f"Media Item (id={self.model.id}) starts segmenting...")