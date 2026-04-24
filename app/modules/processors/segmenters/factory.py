from app.modules.processors.segmenters.fixed_duration_segmenter import FixedDurationSegmenter


SEGMENTERS = {
    "fixed_duration_segmenter": FixedDurationSegmenter
}

def get_segmenter(segmenter: str):
    segm = SEGMENTERS.get(segmenter)

    if not segm:
        raise ValueError(f"Cannot find segmenter: '{segmenter}'")

    return segm