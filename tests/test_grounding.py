import pytest

from out_of_frame.grounding import appears_in

FOUND = [
    ("Klärwerkstraße 3", "Kfz-Werkstatt, Klärwerkstraße 3, 13597 Berlin"),
    ("Klärwerkstr. 3", "Klärwerkstr. 3 13597 Berlin"),
    ("Müller", "Müller KFZ-Service"),
    ("operating", "The site is operating."),
]
NOT_FOUND = [
    ("Klärwerkstraße 1", "Ed. Sprenger GmbH, Klärwerkstraße 1a"),
    ("Klärwerkstraße 3", "Klärwerkstraße 31"),
    ("100", "The hall has 1100 m²."),
    ("operating", "The two firms are cooperating."),
]


@pytest.mark.parametrize("fact, text", FOUND)
def test_a_fact_is_found_as_whole_words(fact, text):
    assert appears_in(fact, text)


@pytest.mark.parametrize("fact, text", NOT_FOUND)
def test_a_fact_is_not_found_inside_another_word(fact, text):
    assert not appears_in(fact, text)
