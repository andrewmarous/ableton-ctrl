#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 VIDEO_URL [OUTPUT_DIR]" >&2
  echo "Runs the video-ingest skill through Pi. OUTPUT_DIR defaults to a new /tmp directory." >&2
}

if [[ $# -lt 1 || $# -gt 2 ]]; then
  usage
  exit 2
fi

for command in uv pi yt-dlp ffmpeg ffprobe; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Required command not found: $command" >&2
    exit 1
  fi
done

VIDEO_URL=$1
OUTPUT_DIR=${2:-$(mktemp -d "${TMPDIR:-/tmp}/video-ingest-e2e.XXXXXX")}
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
INGEST_DIR=$(cd -- "$SCRIPT_DIR/.." && pwd)
REPO_ROOT=$(cd -- "$INGEST_DIR/../.." && pwd)
SKILL_PATH="$INGEST_DIR/skill/video-ingest/SKILL.md"
RAW_DIR="$OUTPUT_DIR/raw"
CACHE_DIR="$OUTPUT_DIR/cache"

mkdir -p "$RAW_DIR" "$CACHE_DIR"

cat <<EOF
E2E output: $OUTPUT_DIR
Raw directory: $RAW_DIR
Cache directory: $CACHE_DIR
EOF

# The CUDA libraries must be installed and visible to the process before this
# script starts. See tools/transcribe/README.md for LD_LIBRARY_PATH setup.
uv sync --project "$INGEST_DIR" --locked --extra cuda

PROMPT=$(cat <<EOF
Use the explicitly available video-ingest skill to ingest this video end to end.

URL: $VIDEO_URL
Raw directory: $RAW_DIR
Cache directory: $CACHE_DIR

Read and follow the complete skill before starting. Perform complete transcript
analysis; do not use the transcript-only skipped branch. Write candidates.json,
extract screenshot sets, publish the immutable revision, and report both the job
path and published revision path. An empty candidate list is acceptable only
after the complete transcript has been reviewed, with analysis_status set to
"completed" and reviewed_segment_ranges populated.
EOF
)

cd "$REPO_ROOT"
uv run --project "$INGEST_DIR" --locked --extra cuda -- \
  pi --no-skills --skill "$SKILL_PATH" --approve --no-session -p "$PROMPT" \
  | tee "$OUTPUT_DIR/pi-output.txt"

echo "Pi output saved to $OUTPUT_DIR/pi-output.txt"
