"""Read and validate YouTube transcript records."""
from .fetch import fetch, fetch_many, normalize_video_id, parse_rows, to_seconds
from .models import (ExtractionResult, FetchResult, Segment, Transcript,
                     TranscriptRecord, TranscriptSegment, ValidationError)
from .organize import (kb_chunks, paragraphs, punctuation_density, stamp,
                       to_markdown, to_plain)

__all__ = ["fetch", "fetch_many", "normalize_video_id", "parse_rows", "to_seconds",
           "FetchResult", "ExtractionResult", "Segment", "Transcript", "TranscriptRecord",
           "TranscriptSegment", "ValidationError", "kb_chunks",
           "paragraphs", "punctuation_density", "stamp", "to_markdown", "to_plain"]
__version__ = "0.2.0"
