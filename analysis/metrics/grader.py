class Grader:

    @staticmethod
    def grade(value, good_thresh, fair_thresh, *,
              higher_is_better=True, labels=("GOOD", "FAIR", "POOR")) -> str:
        g, f, poor = labels
        if higher_is_better:
            return g if value >= good_thresh else f if value >= fair_thresh else poor
        else:
            return g if value <= good_thresh else f if value <= fair_thresh else poor
