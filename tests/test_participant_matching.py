"""fuzzy_match_person: an AX-detected participant name links to a Person only
when it is the same person, never because a surname (or any word) is shared."""
from api.views import fuzzy_match_person


def people(*names):
    return [{"id": n.lower().replace(" ", "_") + f"_{i}", "name": n} for i, n in enumerate(names)]


TEAM = people("Dilan Dubey", "Milan Dubey", "Neeraj Yadav", "Ashok Gupta", "Rauhan Ahmed", "Jane Doe")


def name_of(match):
    return match["name"] if match else None


def test_exact_name_links_case_and_spacing_insensitive():
    assert name_of(fuzzy_match_person("neeraj  YADAV", TEAM)) == "Neeraj Yadav"


def test_shared_surname_never_links():
    assert fuzzy_match_person("Mayank Dubey", TEAM) is None
    assert fuzzy_match_person("Shashank Yadav", TEAM) is None


def test_full_name_close_to_another_full_name_does_not_link():
    # difflib ratio 0.78: different first names, same surname
    assert fuzzy_match_person("Mayank Dubey", people("Milan Dubey")) is None


def test_lone_first_name_links_to_the_only_person_with_it():
    assert name_of(fuzzy_match_person("Jane", TEAM)) == "Jane Doe"
    assert name_of(fuzzy_match_person("ashok", TEAM)) == "Ashok Gupta"


def test_lone_name_that_is_a_surname_does_not_link():
    assert fuzzy_match_person("Dubey", TEAM) is None
    assert fuzzy_match_person("Yadav", TEAM) is None


def test_lone_first_name_shared_by_two_people_does_not_link():
    assert fuzzy_match_person("Jane", people("Jane Doe", "Jane Roe")) is None


def test_small_spelling_difference_in_the_same_name_links():
    assert name_of(fuzzy_match_person("Rauhan Ahmad", TEAM)) == "Rauhan Ahmed"
    assert name_of(fuzzy_match_person("Jon Smith", people("John Smith"))) == "John Smith"


def test_empty_name_and_empty_directory():
    assert fuzzy_match_person("  ", TEAM) is None
    assert fuzzy_match_person("Jane", []) is None


# Self vs roster: who on the roster is you.
from participants import same_person_name  # noqa: E402
from speaker_guess import other_participants  # noqa: E402


def test_same_person_name():
    assert same_person_name("Mayank", "Mayank Dubey")
    assert same_person_name("mayank  dubey", "Mayank Dubey")
    assert not same_person_name("Mayank Dubey", "Dilan Dubey")
    assert not same_person_name("Dubey", "Mayank Dubey")
    assert not same_person_name("", "Mayank")


def test_colleague_sharing_your_surname_stays_on_the_roster():
    roster = ["Mayank Dubey", "Dilan Dubey", "Shashank Yadav"]
    assert other_participants(roster, "Mayank Dubey") == ["Dilan Dubey", "Shashank Yadav"]
    assert other_participants(roster, "Mayank") == ["Dilan Dubey", "Shashank Yadav"]
