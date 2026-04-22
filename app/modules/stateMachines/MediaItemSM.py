from statemachine import StateMachine, State
from app.models.media import MediaStatus
import logging

logger = logging.getLogger(__name__)

class MediaStateMachine(StateMachine):

    pending = State(MediaStatus.PENDING.value, initial=True)
    downloading = State(MediaStatus.DOWNLOADING.value)
    downloaded = State(MediaStatus.DOWNLOADED.value)
    segmenting = State(MediaStatus.SEGMENTING.value)
    segmented = State(MediaStatus.SEGMENTED.value)
    source = State(MediaStatus.SOURCE.value)
    processing = State(MediaStatus.PROCESSING.value)
    processed = State(MediaStatus.PROCESSED.value)
    uploading = State(MediaStatus.UPLOADING.value)
    uploaded = State(MediaStatus.UPLOADED.value)
    publishing = State(MediaStatus.PUBLISHING.value)
    published = State(MediaStatus.PUBLISHED.value)
    failed = State(MediaStatus.FAILED.value)

    fail = (downloading | segmenting | processing | uploading | publishing).to(failed)

    start_download = pending.to(downloading)
    retry_download = failed.to(downloading)
    finish_download = (start_download | fail).to(downloaded)

    start_segment = downloaded.to(segmenting)
    retry_segment = failed.to(segmenting)
    finish_segment = (start_segment | fail).to(source)

    start_process = segmented.to(processing)
    retry_process = failed.to(processing)
    finish_process = (start_process | fail).to(processed)

    start_upload = finish_process.to(uploading)
    retry_upload = failed.to(uploading)
    finish_upload = (start_upload | fail).to(uploaded)

    start_publish = finish_upload.to(publishing)
    retry_publish = failed.to(published)
    finish_publish = (start_publish | fail).to(published)

    retry = failed.to(pending)

    @downloading.on_enter
    def log_start_download(self):
        self.logger.info(f"Media Item (id={self.model.id}) starts downloading...")

    @segmenting.on_enter
    def log_start_segmenting(self):
        self.logger.info(f"Media Item (id={self.model.id}) starts segmenting...")