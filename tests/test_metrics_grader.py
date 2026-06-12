import pytest
from analysis.metrics.grader import Grader


class TestGrader:
    # ── higher_is_better=True (default) ──────────────────────────────────

    def test_good_at_good_threshold(self):
        assert Grader.grade(7.5, 7.5, 5.0) == "GOOD"

    def test_good_above_threshold(self):
        assert Grader.grade(10.0, 7.5, 5.0) == "GOOD"

    def test_fair_at_fair_threshold(self):
        assert Grader.grade(5.0, 7.5, 5.0) == "FAIR"

    def test_fair_between_thresholds(self):
        assert Grader.grade(6.0, 7.5, 5.0) == "FAIR"

    def test_poor_below_fair(self):
        assert Grader.grade(4.9, 7.5, 5.0) == "POOR"

    def test_poor_at_zero(self):
        assert Grader.grade(0.0, 7.5, 5.0) == "POOR"

    # ── higher_is_better=False ────────────────────────────────────────────

    def test_good_at_or_below_good_threshold(self):
        assert Grader.grade(5.0, 5.0, 10.0, higher_is_better=False) == "GOOD"

    def test_good_below_good_threshold(self):
        assert Grader.grade(3.0, 5.0, 10.0, higher_is_better=False) == "GOOD"

    def test_fair_between_thresholds_inverted(self):
        assert Grader.grade(7.0, 5.0, 10.0, higher_is_better=False) == "FAIR"

    def test_poor_above_fair_threshold_inverted(self):
        assert Grader.grade(12.0, 5.0, 10.0, higher_is_better=False) == "POOR"

    # ── custom labels ─────────────────────────────────────────────────────

    def test_custom_labels_good(self):
        result = Grader.grade(100, 90, 70, labels=("EXCELLENT", "OK", "BAD"))
        assert result == "EXCELLENT"

    def test_custom_labels_middle(self):
        result = Grader.grade(75, 90, 70, labels=("EXCELLENT", "OK", "BAD"))
        assert result == "OK"

    def test_custom_labels_worst(self):
        result = Grader.grade(50, 90, 70, labels=("EXCELLENT", "OK", "BAD"))
        assert result == "BAD"

    def test_custom_labels_inverted(self):
        result = Grader.grade(50, 80, 100, higher_is_better=False,
                              labels=("LOW", "MED", "HIGH"))
        assert result == "LOW"

    # ── edge cases ────────────────────────────────────────────────────────

    def test_exact_boundary_higher_is_better(self):
        # At exactly good_thresh → GOOD
        assert Grader.grade(10, 10, 5) == "GOOD"
        # At exactly fair_thresh → FAIR
        assert Grader.grade(5, 10, 5) == "FAIR"

    def test_negative_value(self):
        assert Grader.grade(-1, 5, 0) == "POOR"
