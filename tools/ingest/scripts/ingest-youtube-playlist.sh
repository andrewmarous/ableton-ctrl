#!/usr/bin/env bash
set -euo pipefail

log() {
  printf '[%s] [ingest-playlist] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2
}

usage() {
  cat >&2 <<EOF
Usage: $0 PLAYLIST_URL [WIKI_DIR [WORK_DIR]]

Ingest every video in a public YouTube playlist into an Ableton wiki.
WIKI_DIR defaults to ~/.pi/agent/ableton-wiki.
WORK_DIR defaults to a persistent directory under ~/.cache/ableton-ctrl.

The script skips videos recorded as complete in WORK_DIR. If a video already
has a published raw bundle, Pi updates the wiki from its latest revision
without publishing a duplicate.
EOF
}

if [[ $# -lt 1 || $# -gt 3 ]]; then
  usage
  exit 2
fi

for command in uv pi yt-dlp ffmpeg ffprobe jq; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Required command not found: $command" >&2
    exit 1
  fi
done

PLAYLIST_URL=$1
WIKI_DIR=${2:-"$HOME/remote-agent-workspace/ableton-ctrl/content-kb"}
log "Starting ingestion: playlist_url=$PLAYLIST_URL wiki_dir=$WIKI_DIR"
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
INGEST_DIR=$(cd -- "$SCRIPT_DIR/.." && pwd)
SKILL_PATH="$INGEST_DIR/skill/video-ingest/SKILL.md"

if [[ ! -f "$WIKI_DIR/AGENTS.md" ]]; then
  echo "Wiki instructions not found: $WIKI_DIR/AGENTS.md" >&2
  echo "Install the bundled wiki or pass its directory as WIKI_DIR." >&2
  exit 1
fi

mkdir -p "$WIKI_DIR/raw"
WIKI_DIR=$(cd -- "$WIKI_DIR" && pwd)

# Resolve the playlist before choosing the default work directory. The flat
# manifest does not download video media.
PLAYLIST_JSON=$(mktemp "${TMPDIR:-/tmp}/ableton-playlist.XXXXXX.json")
cleanup_manifest() {
  rm -f -- "$PLAYLIST_JSON"
}
trap cleanup_manifest EXIT

log "Resolving playlist metadata with yt-dlp into $PLAYLIST_JSON"
resolve_started=$SECONDS
# --yes-playlist is required for watch URLs that contain both v= and list=.
# --ignore-config prevents a user-level --no-playlist setting from overriding
# this playlist-specific script.
yt-dlp --ignore-config --yes-playlist --flat-playlist --dump-single-json \
  --no-warnings -- "$PLAYLIST_URL" >"$PLAYLIST_JSON"
log "yt-dlp resolved metadata in $((SECONDS - resolve_started))s ($(wc -c <"$PLAYLIST_JSON") bytes)"

if jq -e '._type == "video"' "$PLAYLIST_JSON" >/dev/null; then
  if [[ "$PLAYLIST_URL" == *\?list=* || "$PLAYLIST_URL" == *\&list=* ]]; then
    echo "The playlist URL resolved as one video. Check that the playlist is public and that its list ID is valid." >&2
    exit 1
  fi

  # Preserve support for a plain video URL as a one-entry ingest list.
  log "The URL is a single video; creating a one-entry manifest"
  jq '{
    id: ("single-" + .id),
    title: (.playlist_title // .title // "Single video"),
    entries: [{id: .id, title: .title, url: .webpage_url}]
  }' "$PLAYLIST_JSON" >"$PLAYLIST_JSON.tmp"
  mv -- "$PLAYLIST_JSON.tmp" "$PLAYLIST_JSON"
fi

if ! jq -e '
  (.entries | type == "array") and
  (.entries | length > 0) and
  all(.entries[]; (.id | type == "string") and (.id | length > 0))
' "$PLAYLIST_JSON" >/dev/null; then
  echo "The URL did not resolve to a non-empty playlist with stable video IDs." >&2
  exit 1
fi

PLAYLIST_ID=$(jq -r '.id // empty' "$PLAYLIST_JSON")
if [[ -z "$PLAYLIST_ID" ]]; then
  PLAYLIST_ID=$(printf '%s' "$PLAYLIST_URL" | sha256sum | cut -c1-16)
fi
PLAYLIST_ID=${PLAYLIST_ID//[^A-Za-z0-9._-]/_}
WORK_DIR=${3:-"$HOME/.cache/ableton-ctrl/youtube-playlists/$PLAYLIST_ID"}
mkdir -p "$WORK_DIR/cache" "$WORK_DIR/status" "$WORK_DIR/logs"
WORK_DIR=$(cd -- "$WORK_DIR" && pwd)
cp -- "$PLAYLIST_JSON" "$WORK_DIR/playlist.json"

VIDEO_COUNT=$(jq '.entries | length' "$PLAYLIST_JSON")
PLAYLIST_TITLE=$(jq -r '.title // "Untitled playlist"' "$PLAYLIST_JSON")
FIRST_VIDEO_ID=$(jq -r '.entries[0].id' "$PLAYLIST_JSON")
FIRST_VIDEO_TITLE=$(jq -r '.entries[0].title // .entries[0].id' "$PLAYLIST_JSON")
log "Resolved playlist: id=$PLAYLIST_ID title=$(printf '%q' "$PLAYLIST_TITLE") videos=$VIDEO_COUNT"
log "First playlist entry: id=$FIRST_VIDEO_ID title=$(printf '%q' "$FIRST_VIDEO_TITLE")"
printf 'Resolved video IDs:' >&2
jq -r '.entries[].id' "$PLAYLIST_JSON" | while IFS= read -r id; do printf ' %s' "$id" >&2; done
printf '\n' >&2
printf 'Playlist: %s (%s videos)\nWiki: %s\nWork directory: %s\n' \
  "$PLAYLIST_TITLE" "$VIDEO_COUNT" "$WIKI_DIR" "$WORK_DIR"

# The CUDA libraries must already be visible to this process. See
# tools/transcribe/README.md for the required environment setup.
log "Synchronizing ingestion dependencies"
uv sync --project "$INGEST_DIR" --locked --extra cuda
log "Dependency synchronization complete"

RPC_STDERR="$WORK_DIR/logs/pi-stderr.log"
: >"$RPC_STDERR"
coproc PI_RPC {
  cd -- "$WIKI_DIR"
  exec uv run --project "$INGEST_DIR" --locked --extra cuda -- \
    pi --mode rpc --no-session --no-skills \
      --skill "$SKILL_PATH" --approve
} 2>>"$RPC_STDERR"
RPC_PID=$PI_RPC_PID
RPC_OUT=${PI_RPC[0]}
RPC_IN=${PI_RPC[1]}
log "Started Pi RPC process: pid=$RPC_PID stderr=$RPC_STDERR"

cleanup_rpc() {
  trap - EXIT INT TERM
  exec {RPC_IN}>&- 2>/dev/null || true
  if kill -0 "$RPC_PID" 2>/dev/null; then
    kill "$RPC_PID" 2>/dev/null || true
  fi
  wait "$RPC_PID" 2>/dev/null || true
  cleanup_manifest
}
trap cleanup_rpc EXIT INT TERM

send_rpc() {
  local payload=$1
  printf '%s\n' "$payload" >&"$RPC_IN"
}

wait_for_response() {
  local request_id=$1
  local log_file=$2
  local line
  while IFS= read -r -u "$RPC_OUT" line; do
    printf '%s\n' "$line" >>"$log_file"
    if ! jq -e . >/dev/null 2>&1 <<<"$line"; then
      echo "Pi emitted invalid RPC JSON; see $log_file" >&2
      return 1
    fi
    if [[ $(jq -r '.type // empty' <<<"$line") == response ]] && \
       [[ $(jq -r '.id // empty' <<<"$line") == "$request_id" ]]; then
      if [[ $(jq -r '.success // false' <<<"$line") != true ]]; then
        echo "Pi rejected an RPC command: $(jq -r '.error // "unknown error"' <<<"$line")" >&2
        return 1
      fi
      return 0
    fi
  done
  echo "Pi RPC process stopped unexpectedly; see $RPC_STDERR" >&2
  return 1
}

run_agent_prompt() {
  local request_id=$1
  local prompt=$2
  local log_file=$3
  local line event_type delta accepted=false assistant_error=false

  log "Sending agent prompt: request_id=$request_id rpc_log=$log_file"
  send_rpc "$(jq -cn --arg id "$request_id" --arg message "$prompt" \
    '{id:$id,type:"prompt",message:$message}')"

  while IFS= read -r -u "$RPC_OUT" line; do
    printf '%s\n' "$line" >>"$log_file"
    if ! jq -e . >/dev/null 2>&1 <<<"$line"; then
      echo "Pi emitted invalid RPC JSON; see $log_file" >&2
      return 1
    fi

    event_type=$(jq -r '.type // empty' <<<"$line")
    case "$event_type" in
      response|message_start|message_end|agent_start|agent_end|agent_settled|tool_execution_start|tool_execution_end)
        log "RPC event: request_id=$request_id type=$event_type"
        ;;
    esac
    if [[ "$event_type" == response ]] && \
       [[ $(jq -r '.id // empty' <<<"$line") == "$request_id" ]]; then
      if [[ $(jq -r '.success // false' <<<"$line") != true ]]; then
        echo "Pi rejected the prompt: $(jq -r '.error // "unknown error"' <<<"$line")" >&2
        return 1
      fi
      accepted=true
    elif [[ "$event_type" == message_update ]] && \
         [[ $(jq -r '.assistantMessageEvent.type // empty' <<<"$line") == text_delta ]]; then
      delta=$(jq -r '.assistantMessageEvent.delta' <<<"$line")
      printf '%s' "$delta"
    elif [[ "$event_type" == message_end ]] && \
         [[ $(jq -r '.message.role // empty' <<<"$line") == assistant ]] && \
         [[ $(jq -r '.message.stopReason // empty' <<<"$line") == error ]]; then
      assistant_error=true
    elif [[ "$event_type" == agent_settled ]]; then
      printf '\n'
      if [[ "$accepted" != true || "$assistant_error" == true ]]; then
        echo "Pi did not complete the agent run successfully; see $log_file" >&2
        return 1
      fi
      log "Agent run completed: request_id=$request_id"
      return 0
    fi
  done

  echo "Pi RPC process stopped unexpectedly; see $RPC_STDERR" >&2
  return 1
}

failures=0
for ((index = 0; index < VIDEO_COUNT; index++)); do
  number=$((index + 1))
  video_id=$(jq -r --argjson i "$index" '.entries[$i].id' "$PLAYLIST_JSON")
  title=$(jq -r --argjson i "$index" '.entries[$i].title // .entries[$i].id' "$PLAYLIST_JSON")
  video_url="https://www.youtube.com/watch?v=$video_id"
  status_file="$WORK_DIR/status/$video_id.json"
  log_file="$WORK_DIR/logs/$(printf '%04d' "$number")-$video_id.jsonl"

  if [[ -f "$status_file" ]] && jq -e '.status == "complete"' "$status_file" >/dev/null 2>&1; then
    printf '[%d/%d] Skipping completed video: %s\n' "$number" "$VIDEO_COUNT" "$title"
    continue
  fi

  : >"$log_file"
  printf '\n[%d/%d] %s\n' "$number" "$VIDEO_COUNT" "$title"
  log "Pulling playlist entry: position=$number/$VIDEO_COUNT video_id=$video_id url=$video_url log=$log_file"

  latest_revision=""
  if [[ -d "$WIKI_DIR/raw/youtube/$video_id" ]]; then
    latest_revision=$(find "$WIKI_DIR/raw/youtube/$video_id" -mindepth 1 -maxdepth 1 \
      -type d -exec test -f '{}/manifest.json' ';' -print | sort | tail -n 1)
  fi

  if [[ -n "$latest_revision" ]]; then
    prompt=$(cat <<EOF
Read and follow $WIKI_DIR/AGENTS.md. This playlist video already has an
immutable evidence bundle, so do not prepare, transcribe, extract, or publish
it again.

Playlist: $PLAYLIST_TITLE
Playlist position: $number of $VIDEO_COUNT
Video title: $title
Video URL: $video_url
Published revision: $latest_revision
Wiki directory: $WIKI_DIR

Ingest this source into the wiki now. Read the complete published evidence and
relevant existing wiki pages. Create or update its source page, integrate all
material information into affected pages, add citations and cross-references,
update wiki/index.md, and append the required entry to wiki/log.md. Avoid
content duplication. Report the files changed.
EOF
)
  else
    prompt=$(cat <<EOF
Use the explicitly available video-ingest skill and read and follow
$WIKI_DIR/AGENTS.md. Ingest this one playlist video end to end, then integrate
its published evidence into the wiki.

Playlist: $PLAYLIST_TITLE
Playlist position: $number of $VIDEO_COUNT
Video title: $title
Video URL: $video_url
Raw directory: $WIKI_DIR/raw
Job cache directory: $WORK_DIR/cache
Wiki directory: $WIKI_DIR

Perform complete transcript analysis; do not use the transcript-only skipped
branch. Write candidates.json, extract screenshot sets, and publish one
immutable revision. An empty candidate list is acceptable only after review of
the complete transcript, with analysis_status set to "completed" and all
reviewed segment ranges recorded.

After publication, read the complete evidence and relevant existing wiki
pages. Create or update one source page, integrate all material information
into affected pages, add citations and cross-references, update wiki/index.md,
and append the required entry to wiki/log.md. Avoid content duplication.
Report the job path, published revision path, and files changed.
EOF
)
  fi

  request_id="video-$number-$video_id"
  if run_agent_prompt "$request_id" "$prompt" "$log_file"; then
    if [[ -z "$latest_revision" ]] && \
       ! find "$WIKI_DIR/raw/youtube/$video_id" -mindepth 1 -maxdepth 2 \
         -name manifest.json -type f -print -quit 2>/dev/null | grep -q .; then
      echo "No published revision was found for $video_id after Pi completed." >&2
      failures=$((failures + 1))
    else
      jq -n \
        --arg status complete \
        --arg video_id "$video_id" \
        --arg title "$title" \
        --arg url "$video_url" \
        --arg completed_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        '{status:$status,video_id:$video_id,title:$title,url:$url,completed_at:$completed_at}' \
        >"$status_file.tmp"
      mv -- "$status_file.tmp" "$status_file"
    fi
  else
    failures=$((failures + 1))
    jq -n \
      --arg status failed \
      --arg video_id "$video_id" \
      --arg title "$title" \
      --arg url "$video_url" \
      --arg failed_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      '{status:$status,video_id:$video_id,title:$title,url:$url,failed_at:$failed_at}' \
      >"$status_file.tmp"
    mv -- "$status_file.tmp" "$status_file"
  fi

  # Start each video with a clean model context while keeping one RPC process.
  reset_id="reset-$number"
  send_rpc "$(jq -cn --arg id "$reset_id" '{id:$id,type:"new_session"}')"
  if ! wait_for_response "$reset_id" "$log_file"; then
    exit 1
  fi
done

exec {RPC_IN}>&-
wait "$RPC_PID" || true
trap cleanup_manifest EXIT

if ((failures > 0)); then
  echo "Playlist ingest finished with $failures failed video(s). Re-run to resume." >&2
  exit 1
fi

echo "Playlist ingest complete: $VIDEO_COUNT video(s)."
