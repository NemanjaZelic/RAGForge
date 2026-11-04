"""New query syntax preserves legacy facets and never bypasses source grants."""

from pathlib import Path

from typer.testing import CliRunner

from ragforge.cli import app
from ragforge.core.planning import question_facets as legacy_facets
from ragforge.core.planning_v2 import question_facets, referenced_documents


def test_explicit_combinations_and_distinctions_keep_original_words():
    assert question_facets("Combine event flags with worker placement.") == [
        "event flags?",
        "worker placement?",
    ]
    assert question_facets("What distinguishes task waiting from event signaling?") == [
        "task waiting?",
        "event signaling?",
    ]
    assert question_facets("Distinguish entry instrumentation from pointer validation.") == [
        "entry instrumentation?",
        "pointer validation?",
    ]
    query = "What does ALPHA require and what does BETA provide?"
    assert question_facets(query) == legacy_facets(query)
    assert question_facets("Combine " + "long " * 129 + "with a flag") == []
    assert question_facets("This single question has no coordination") == []


def test_technical_stems_are_explicit_bounded_and_scoped():
    docs = [
        ("a", "core/IndexTree.html"),
        ("b", "translations/IndexTree.html"),
        ("c", "core/event_flags.md"),
    ]
    assert referenced_documents("How does IndexTree handle keys?", docs) == ["a", "b"]
    assert referenced_documents("How does IndexTree handle keys?", docs, ["b"]) == ["b"]
    assert referenced_documents("Read IndexTreeExtended", docs) == []
    assert referenced_documents("Read indextree", docs) == []
    assert referenced_documents("Explain event_flags", docs) == ["c"]
    assert referenced_documents("Read IndexTree", docs, ["c"]) == []
    assert (
        len(referenced_documents("IndexTree", [(str(i), f"{i}/IndexTree.html") for i in range(9)]))
        == 4
    )
    assert referenced_documents("Read core/event_flags.md", docs) == ["c"]


def test_cli_rejects_unknown_or_conflicting_policy_before_reading_bundles(tmp_path: Path):
    runner = CliRunner()
    base = [
        "recontextualize",
        str(tmp_path / "missing-child"),
        str(tmp_path / "missing-parent"),
        "--output",
        str(tmp_path / "out"),
    ]
    for arguments in [
        ["--query-planning", "unknown"],
        ["--section-context", "unknown"],
        ["--plan-queries", "--query-planning", "facets-v2"],
        ["--complete-sections", "--section-context", "section-start-v2"],
    ]:
        result = runner.invoke(app, [*base, *arguments])
        assert result.exit_code == 2
        assert "missing-child" not in result.output
        assert not (tmp_path / "out").exists()
