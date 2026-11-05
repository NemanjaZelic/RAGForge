"""Multilingual clauses share the bounded engine without changing old policies."""

import pytest

from ragforge.core.planning_v2 import question_facets as previous_facets
from ragforge.core.planning_v3 import question_facets


@pytest.mark.parametrize(
    "query,expected",
    [
        (
            "Kako radi Alpha i kako se zaustavlja Beta?",
            ["Kako radi Alpha?", "kako se zaustavlja Beta?"],
        ),
        ("Како ради Alpha, а шта враћа Beta?", ["Како ради Alpha?", "шта враћа Beta?"]),
        (
            "Šta radi Alpha i da li Beta čuva podatke?",
            ["Šta radi Alpha?", "da li Beta čuva podatke?"],
        ),
        ("Wie startet Alpha und wann endet Beta?", ["Wie startet Alpha?", "wann endet Beta?"]),
        (
            "Comment lancer Alpha et pourquoi arrêter Beta?",
            ["Comment lancer Alpha?", "pourquoi arrêter Beta?"],
        ),
        (
            "¿Cómo funciona Alpha y qué devuelve Beta?",
            ["¿Cómo funciona Alpha?", "qué devuelve Beta?"],
        ),
        (
            "Como iniciar Alpha e quando termina Beta?",
            ["Como iniciar Alpha?", "quando termina Beta?"],
        ),
        (
            "Как работает Alpha и что возвращает Beta?",
            ["Как работает Alpha?", "что возвращает Beta?"],
        ),
        ("Како ради Alpha? Шта враћа Beta?", ["Како ради Alpha?", "Шта враћа Beta?"]),
    ],
)
def test_interrogative_clauses_keep_original_words(query, expected):
    assert question_facets(query) == expected


@pytest.mark.parametrize(
    "literal", ['"i kako Beta"', "`i kako Beta`", "(i kako Beta)", "[i kako Beta]", "“i kako Beta”"]
)
def test_quoted_code_and_arguments_are_not_question_boundaries(literal):
    query = f"Kako radi Alpha sa {literal} i šta vraća Gamma?"
    assert question_facets(query) == [f"Kako radi Alpha sa {literal}?", "šta vraća Gamma?"]
    assert question_facets(f"Kako radi Alpha sa {literal}?") == []


@pytest.mark.parametrize(
    "query",
    [
        "Kako radi Alpha i Beta?",
        "Како ради Alpha и Beta?",
        'Kako radi "Alpha i kako Beta?',
        "Kako radi (Alpha i kako Beta?",
        "Kako radi [Alpha) i kako Beta?",
        "Kako " + "dugo " * 129 + "i kako Beta?",
        "x" * 2049,
    ],
)
def test_no_guessing_from_noun_phrases_malformed_or_excessive_queries(query):
    assert question_facets(query) == []


def test_legacy_english_facets_are_preserved_and_new_branches_bounded():
    for query in [
        "What does ALPHA require and what does BETA provide?",
        "Combine event flags with worker placement.",
        "How do Secure and Hidden cookie attributes restrict access?",
    ]:
        assert question_facets(query) == previous_facets(query)
    assert (
        len(question_facets("Šta radi Alpha i šta radi Beta i šta radi Gamma i šta radi Delta?"))
        == 3
    )
    assert question_facets("Kako radi Alpha i kako radi Alpha?") == []
