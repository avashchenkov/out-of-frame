import pytest

from out_of_frame.grounding import appears_in

FOUND = [
    ("Klärwerkstraße 3", "Kfz-Werkstatt, Klärwerkstraße 3, 13597 Berlin"),
    ("Klärwerkstr. 3", "Klärwerkstr. 3 13597 Berlin"),
    ("Müller", "Müller KFZ-Service"),
    ("operating", "The site is operating."),
    ("Automobile Ruhleben GmbH, Klärwerkstraße 3", "Automobile Ruhleben Gmbh - Klärwerkstraße 3"),
    ("Monday 8 am–6 pm", "| Monday | 8\u202fam–6\u202fpm |"),
    ("Müller", "Mu\u0308ller"),  # the same letter, decomposed
    ("Nonnendammallee 11-14", "Nonnendammallee 11–14"),
    ("660.000 Tonnen", "660.000 Tonnen"),
    ("İpek GmbH", "İPEK GMBH"),
]
NOT_FOUND = [
    ("Klärwerkstraße 1", "Ed. Sprenger GmbH, Klärwerkstraße 1a"),
    ("Klärwerkstraße 3", "Klärwerkstraße 31"),
    ("100", "The hall has 1100 m²."),
    ("operating", "The two firms are cooperating."),
    ("Klärwerkstraße 1a", "Klärwerkstraße 1 a"),
    ("–", "8 am–6 pm"),  # no words to find
    ("In Betrieb: ✓", "In Betrieb: ✗"),
    ("Baujahr > 2000", "Baujahr < 2000"),
    ("660 000", "660.000"),
    ("1,500", "1.500"),
    ("11.14", "11-14"),
    ("Masse", "Maße"),
    ("Pek GmbH", "İpek GmbH"),
    ("Halle 1.2", "Halle 1.2a"),
]


@pytest.mark.parametrize("fact, text", FOUND)
def test_a_fact_is_found_as_whole_words(fact, text):
    assert appears_in(fact, text)


@pytest.mark.parametrize("fact, text", NOT_FOUND)
def test_a_fact_is_not_found_inside_another_word(fact, text):
    assert not appears_in(fact, text)
