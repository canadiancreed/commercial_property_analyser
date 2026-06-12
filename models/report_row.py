from dataclasses import dataclass


@dataclass
class ReportRow:
    metric: str
    value:  str
    grade:  str

    def __str__(self):
        return f"{self.metric:<25} | {self.value:<30} | {self.grade}"

    def to_dict(self) -> dict:
        return {"metric": self.metric, "value": self.value, "grade": self.grade}
