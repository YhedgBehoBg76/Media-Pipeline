from statemachine import StateMachine, State
from app.models.media import MediaStatus


class MediaStateMachine(StateMachine):
    def __init__(self, logger):
        super().__init__()
        self.logger = logger

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

    start_download = pending.to(downloading)
    finish_download = start_download.to(downloaded)

    start_segment = downloaded.to(segmenting)
    finish_segment = start_segment.to(source)

    start_process = segmented.to(processing)
    finish_process = start_process.to(processed)

    start_upload = finish_process.to(uploading)
    finish_upload = start_upload.to(uploaded)

    start_publish = finish_upload.to(publishing)
    retry_publish = failed.to(published)
    finish_publish = start_publish.to(published)

    fail = (downloading | segmenting | processing | uploading | publishing).to(failed)
    retry = failed.to(pending)

    @downloading.on_enter
    def log_start_download(self):
        self.logger.info(f"Media Item (id={self.model.id}) starts downloading...")

    @segmenting.on_enter
    def log_start_segmenting(self):
        self.logger.info(f"Media Item (id={self.model.id}) starts segmenting...")