from autoshorts.util import text as T


def test_sentences_split_on_terminators_not_abbreviations():
    out = T.sentences("Dr. Smith waited. Then the Mr. Rogers clip played!")
    assert out[0] == "Dr. Smith waited."
    assert "Mr. Rogers" in out[1]


def test_words_ignores_punctuation():
    assert T.words("Stop scrolling, and read this.") == ["Stop", "scrolling", "and", "read", "this"]


def test_clean_strips_markdown_and_smart_quotes():
    assert T.clean("“**Real** speed.”") == '"Real speed."'


def test_estimate_grows_with_length():
    short = T.estimate_seconds("Ship it today.", 150)
    long = T.estimate_seconds(" ".join(["ship"] * 30), 150)
    assert long > short * 3


def test_chunk_text_respects_word_budget():
    source = "One. " * 20
    chunks = T.chunk_text(source, max_seconds=4, words_per_minute=150)
    assert len(chunks) > 1
    assert all(T.word_count(c) <= 11 for c in chunks)


def test_slugify_is_safe_for_paths():
    assert T.slugify("Why 90% of Ads Fail!") == "why-90-of-ads-fail"
    assert T.slugify("") == "clip"
