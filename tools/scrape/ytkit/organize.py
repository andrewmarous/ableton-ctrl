"""Turn raw caption segments into something a person can read.

A transcript panel gives you three-second fragments broken on display lines,
not on sentences:

    12.4  "so the first thing you want to"
    15.1  "do is check whether the policy"
    18.0  "actually covers it. most people"

That is a data structure, not a document. This module joins the fragments back
into prose, splits it into paragraphs on the two signals that actually mark a
change of thought, and exports it with timestamps you can seek to.

THE TWO SIGNALS. A paragraph break needs a sentence end AND a pause. Either one
alone is wrong in a way the other catches:

  a sentence end with no pause    the speaker ran straight on, and breaking
                                  there cuts mid-thought
  a pause with no sentence end    the speaker hesitated, or the caption
                                  segmenting simply ran out of line

Auto-captions frequently carry NO punctuation at all. When that happens there
are no sentence ends to find, `paragraphs()` says so rather than returning one
enormous block, and the caller can decide what to do about it.
"""
from __future__ import annotations

import re

TERMINAL = (".", "?", "!")

#: A gap longer than this, between the end of one segment and the start of the
#: next, reads as a change of thought rather than a breath. Tuned on ordinary
#: interview and presentation speech; raise it for a fast talker.
PARAGRAPH_GAP = 0.65

#: Below this, a "paragraph" is a fragment and gets folded into its neighbour.
#:
#: Eight, not twelve. At twelve, "And that brings us to the part everybody gets
#: wrong" -- ten words and a complete thought -- was being swallowed by the
#: paragraph before it. The fragments this is for are "Okay." and "Right, so.",
#: which are one to three words.
MIN_PARAGRAPH_WORDS = 8


def _segments(value):
    if hasattr(value, "segments"):
        return [s.to_dict() for s in value.segments]
    return value or []


def punctuation_density(segments) -> float:
    """Sentence ends per minute. Near zero means unpunctuated auto-captions.

    Worth checking before anything else: a transcript with no punctuation
    cannot be paragraphed, and the failure otherwise looks like "this video is
    one long thought".
    """
    segments = _segments(segments)
    if not segments:
        return 0.0
    text = " ".join(s.get("text", "") for s in segments)
    ends = sum(text.count(c) for c in TERMINAL)
    last_end = segments[-1].get("end")
    span = max(1.0, float((last_end if last_end is not None else segments[-1].get("start", 0))) - float(segments[0].get("start", 0)))
    return ends / (span / 60.0)


def paragraphs(segments, gap: float = PARAGRAPH_GAP) -> list:
    """[{start, end, text}] split where a sentence end meets a real pause.

    Raises ValueError when the transcript carries no punctuation, because the
    honest answer there is "this cannot be paragraphed", not one giant block.
    """
    segs = [s for s in _segments(segments) if (s.get("text") or "").strip()]
    if not segs:
        return []
    if punctuation_density(segs) < 1.0:
        raise ValueError(
            "this transcript has almost no punctuation (%.1f sentence ends per "
            "minute), which is what YouTube's automatic captions look like. "
            "There is nothing to split on. Use the raw segments, or transcribe "
            "the audio yourself." % punctuation_density(segs))

    out, cur = [], []
    for i, s in enumerate(segs):
        cur.append(s)
        text = (s.get("text") or "").rstrip()
        ends_sentence = text.endswith(TERMINAL)
        nxt = segs[i + 1] if i + 1 < len(segs) else None
        pause = ((float(nxt["start"]) - float(s["end"]))
                 if nxt and s.get("end") is not None else 0.0) if nxt else 99.0
        if ends_sentence and pause >= gap:
            out.append(_join(cur))
            cur = []
    if cur:
        out.append(_join(cur))
    return _fold_fragments(out)


def _join(group) -> dict:
    end = group[-1].get("end")
    return {"start": round(float(group[0]["start"]), 2),
            "end": round(float(end), 2) if end is not None else None,
            "text": re.sub(r"\s+", " ", " ".join(
                (g.get("text") or "").strip() for g in group)).strip()}


def _fold_fragments(paras) -> list:
    """Merge anything too short to stand alone into the paragraph before it."""
    out = []
    for p in paras:
        if out and len(p["text"].split()) < MIN_PARAGRAPH_WORDS:
            out[-1]["text"] = (out[-1]["text"] + " " + p["text"]).strip()
            out[-1]["end"] = p["end"]
        else:
            out.append(dict(p))
    return out


def stamp(seconds: float) -> str:
    """Seconds to h:mm:ss, or m:ss below an hour."""
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return "%d:%02d:%02d" % (h, m, sec) if h else "%d:%02d" % (m, sec)


def to_markdown(paras, video_id: str = "", title: str = "") -> str:
    """A readable document, each paragraph carrying a link to its timestamp."""
    lines = []
    if title:
        lines += ["# %s" % title, ""]
    elif video_id:
        lines += ["# Transcript of %s" % video_id, ""]
    for p in paras:
        t = stamp(p["start"])
        if video_id:
            lines.append("**[%s](https://www.youtube.com/watch?v=%s&t=%ds)**  "
                         % (t, video_id, int(p["start"])))
        else:
            lines.append("**%s**  " % t)
        lines += [p["text"], ""]
    return "\n".join(lines).rstrip() + "\n"


def kb_chunks(segments, max_words: int = 180, max_seconds: float = 90.0) -> list[dict]:
    """Bounded chunks for retrieval; never invents timing or requires punctuation."""
    segs = _segments(segments)
    chunks, current, words = [], [], 0
    for seg in segs:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        pieces = text.split()
        # Keep source references even when a single caption is oversized.
        for offset in range(0, len(pieces), max_words):
            part = " ".join(pieces[offset:offset + max_words])
            candidate = words + len(part.split())
            start = current[0]["start"] if current else seg["start"]
            end = seg.get("end")
            span = (end - start) if end is not None else 0
            if current and (candidate > max_words or span > max_seconds):
                chunks.append(_chunk(current)); current, words = [], 0
            current.append({**seg, "text": part, "source_index": seg.get("source_index")})
            words += len(part.split())
    if current:
        chunks.append(_chunk(current))
    return chunks


def _chunk(group):
    return {"start": group[0]["start"], "end": group[-1].get("end"),
            "text": " ".join(x["text"] for x in group),
            "source_indices": [x.get("source_index") for x in group]}


def to_plain(paras) -> str:
    """Just the prose, no timestamps. For pasting somewhere else."""
    return "\n\n".join(p["text"] for p in paras) + "\n"
