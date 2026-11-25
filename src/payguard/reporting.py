"""Markdown helpers shared by both problems' generated reports."""


def table(header: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    return "\n".join(lines + ["| " + " | ".join(map(str, row)) + " |" for row in rows])


def pct(x: float) -> str:
    return f"{x:.1%}"
