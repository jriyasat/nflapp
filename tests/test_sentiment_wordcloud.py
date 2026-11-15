"""Unit test for sentiment.tokenize_for_wordcloud() — the word-frequency
tokenization logic behind the Sentiment Lab word cloud. Pure function,
Run with: pytest -v tests/test_sentiment_wordcloud.py (or: python3 tests/test_sentiment_wordcloud.py)
"""
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sentiment as sm


def test_lowercases_and_strips_punctuation():
    words = sm.tokenize_for_wordcloud("The Eagles' offense is ELITE! Elite.")
    assert "elite" in words
    assert "eagles" in words
    assert all(w == w.lower() for w in words)
    assert all(c.isalpha() for w in words for c in w)


def test_drops_stopwords_and_short_tokens():
    words = sm.tokenize_for_wordcloud("this is a big win for the team and they are happy")
    # 'is', 'a', 'for', 'the', 'and', 'they', 'are' are all stopwords or <3 letters;
    # 'team' is also filtered — generic NFL boilerplate, not sentiment signal.
    for sw in ("this", "for", "the", "and", "they", "are", "is", "a", "team"):
        assert sw not in words, f"stopword {sw!r} leaked through"
    assert "big" in words
    assert "win" in words
    assert "happy" in words


def test_drops_numeric_tokens():
    words = sm.tokenize_for_wordcloud("week 4 preview 2026 season")
    assert "4" not in words
    assert "2026" not in words
    assert "preview" in words


def test_drops_sports_news_boilerplate():
    # Generic NFL-journalism filler that shows up in every team's cloud
    # regardless of actual sentiment — noise, not signal.
    words = sm.tokenize_for_wordcloud(
        "nfl week season game news said according report sunday"
    )
    assert words == []


def test_drops_user_flagged_noise_words():
    words = sm.tokenize_for_wordcloud(
        "fantasy football team rankings field week performance"
    )
    for sw in ("fantasy", "football", "team", "rankings", "field", "week"):
        assert sw not in words, f"noise word {sw!r} leaked through"
    assert "performance" in words


def test_extra_stopwords_excludes_team_name():
    words = sm.tokenize_for_wordcloud(
        "the eagles offense is elite this season",
        extra_stopwords={"eagles"},
    )
    assert "eagles" not in words
    assert "elite" in words


def test_frequency_counts_are_correct():
    words = sm.tokenize_for_wordcloud("quarterback quarterback quarterback defense defense rookie")
    counts = Counter(words)
    assert counts["quarterback"] == 3
    assert counts["defense"] == 2
    assert counts["rookie"] == 1


def test_empty_and_all_stopword_text_returns_empty_list():
    assert sm.tokenize_for_wordcloud("") == []
    assert sm.tokenize_for_wordcloud("the and for are with") == []


if __name__ == "__main__":
    test_lowercases_and_strips_punctuation()
    test_drops_stopwords_and_short_tokens()
    test_drops_numeric_tokens()
    test_drops_sports_news_boilerplate()
    test_drops_user_flagged_noise_words()
    test_extra_stopwords_excludes_team_name()
    test_frequency_counts_are_correct()
    test_empty_and_all_stopword_text_returns_empty_list()
    print("OK - all sentiment tokenizer tests passed")
