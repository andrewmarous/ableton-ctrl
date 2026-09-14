"""The organising layer, which is the part with judgement in it."""
import pytest

from ytkit.organize import (paragraphs, punctuation_density, stamp,
                            to_markdown, to_plain)
from ytkit.fetch import to_seconds


def seg(start, end, text):
    return {"start": start, "end": end, "text": text}


# A short punctuated transcript with two clear topic breaks.
PUNCTUATED = [
    seg(0.0, 3.0, "So the first thing you want to do is check the policy."),
    seg(3.1, 6.0, "Most people never read past the first page."),
    seg(8.0, 11.0, "Now, the second question is about timing."),
    seg(11.1, 14.0, "You have thirty days from the date of the notice."),
    seg(16.0, 19.5, "And that brings us to the part everybody gets wrong."),
]

# What YouTube's automatic captions actually look like.
UNPUNCTUATED = [
    seg(0.0, 3.0, "so the first thing you want to do is check"),
    seg(3.0, 6.0, "the policy most people never read past the"),
    seg(6.0, 9.0, "first page and then they wonder why the claim"),
]


def test_a_pause_and_a_sentence_end_together_start_a_paragraph():
    paras = paragraphs(PUNCTUATED)
    assert len(paras) == 3
    assert paras[0]["text"].startswith("So the first thing")
    assert paras[1]["text"].startswith("Now, the second question")


def test_a_sentence_end_with_no_pause_does_not_split():
    """The speaker ran straight on. Breaking there cuts mid-thought."""
    runon = [seg(0.0, 3.0, "That is the first point."),
             seg(3.05, 6.0, "And the second follows from it immediately."),
             seg(6.05, 9.0, "Which is why nobody separates them.")]
    assert len(paragraphs(runon)) == 1


def test_a_pause_with_no_sentence_end_does_not_split():
    """A hesitation, or the caption line simply running out."""
    hesitant = [seg(0.0, 3.0, "So the thing you have to remember is"),
                seg(5.0, 8.0, "that the deadline moves when they amend it.")]
    assert len(paragraphs(hesitant)) == 1


def test_an_unpunctuated_transcript_says_so_rather_than_guessing():
    """Auto-captions carry no punctuation at all. There is nothing to split
    on, and returning one enormous block hides that."""
    with pytest.raises(ValueError) as e:
        paragraphs(UNPUNCTUATED)
    assert "punctuation" in str(e.value).lower()


def test_punctuation_density_separates_the_two_cases():
    assert punctuation_density(PUNCTUATED) > 5.0
    assert punctuation_density(UNPUNCTUATED) < 1.0


def test_a_fragment_is_folded_into_the_paragraph_before_it():
    """A three-word "Okay. Right." is not a paragraph."""
    with_fragment = PUNCTUATED + [seg(22.0, 23.0, "Okay.")]
    paras = paragraphs(with_fragment)
    assert paras[-1]["text"].endswith("Okay.")
    assert len(paras) == 3


def test_empty_input_is_empty_output_not_an_error():
    assert paragraphs([]) == []


def test_markdown_carries_a_seekable_link_per_paragraph():
    md = to_markdown(paragraphs(PUNCTUATED), video_id="abc123")
    assert "youtube.com/watch?v=abc123&t=" in md
    assert md.count("**[") == 3


def test_plain_text_is_just_the_prose():
    txt = to_plain(paragraphs(PUNCTUATED))
    assert "youtube.com" not in txt
    assert "0:00" not in txt


def test_stamps_drop_the_hour_when_there_is_not_one():
    assert stamp(75) == "1:15"
    assert stamp(3675) == "1:01:15"
    assert stamp(0) == "0:00"


def test_timestamp_parsing_handles_all_three_shapes():
    assert to_seconds("12") == 12.0
    assert to_seconds("2:03") == 123.0
    assert to_seconds("1:02:03") == 3723.0
    assert to_seconds("not a stamp") == -1.0
