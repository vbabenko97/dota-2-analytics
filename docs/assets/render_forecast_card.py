"""Render the frozen corrected forecast card as a standalone SVG."""

import hashlib
import html
import json
from collections.abc import Mapping
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
CARD_PATH = REPOSITORY / "reports/card_ti2026_rules/recommended_card.json"
ATTESTATION_PATH = REPOSITORY / "reports/postmortems/group-replay.manifest.json"
OUTPUT_PATH = REPOSITORY / "docs/assets/forecast-card.svg"
CATEGORIES = (
    ("4-0", "4-0"),
    ("4-1", "4-1"),
    ("elim_win", "Elimination round winner"),
    ("elim_loss", "Elimination round loser"),
    ("1-4", "1-4"),
    ("0-4", "0-4"),
)
POSITIONS = ((48, 150), (450, 150), (852, 150), (48, 357), (450, 357), (852, 357))
ACCENTS = ("#82dfc6", "#82dfc6", "#82dfc6", "#d5a56b", "#d5a56b", "#d5a56b")


def read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON: {path.relative_to(REPOSITORY)}") from exc


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assignments_from(card: object) -> dict[str, str]:
    if not isinstance(card, Mapping):
        raise TypeError("card must be an object")
    assignments = card.get("assignments")
    if not isinstance(assignments, Mapping) or not assignments:
        raise ValueError("card must contain assignments")
    if not all(
        isinstance(team, str) and isinstance(category, str)
        for team, category in assignments.items()
    ):
        raise ValueError("assignments must map team names to categories")
    return dict(assignments)


def attested_card_hash(manifest: object) -> str:
    if not isinstance(manifest, Mapping):
        raise TypeError("attestation must be an object")
    inputs = manifest.get("inputs")
    if not isinstance(inputs, list):
        raise TypeError("attestation must contain inputs")
    for entry in inputs:
        if (
            isinstance(entry, Mapping)
            and entry.get("path") == CARD_PATH.relative_to(REPOSITORY).as_posix()
        ):
            digest = entry.get("sha256")
            if isinstance(digest, str):
                return digest
    raise ValueError("attestation does not bind the forecast card")


def grouped_assignments(assignments: Mapping[str, str]) -> list[tuple[str, str, list[str]]]:
    groups = {category: [] for category, _ in CATEGORIES}
    for team, category in assignments.items():
        if category not in groups:
            raise ValueError(f"unsupported category: {category}")
        groups[category].append(team)
    grouped = [(category, title, sorted(groups[category])) for category, title in CATEGORIES]
    rendered_teams = [team for _, _, teams in grouped for team in teams]
    if len(rendered_teams) != len(assignments) or set(rendered_teams) != set(assignments):
        raise ValueError("rendered coverage does not match assignments")
    if len(rendered_teams) != len(set(rendered_teams)):
        raise ValueError("an assignment appears more than once")
    return grouped


def text(value: str) -> str:
    return html.escape(value, quote=True)


def render(assignments: Mapping[str, str], card_hash: str) -> str:
    tiles: list[str] = []
    for (category, title, teams), (x, y), accent in zip(
        grouped_assignments(assignments), POSITIONS, ACCENTS, strict=True
    ):
        lines = [
            f'<rect x="{x}" y="{y}" width="380" height="190" rx="16" fill="#122238" stroke="{accent}" stroke-opacity="0.45"/>',
            f'<text x="{x + 24}" y="{y + 37}" fill="{accent}" font-size="18" font-weight="700">{text(title)}</text>',
            f'<text x="{x + 356}" y="{y + 37}" fill="#f4eddd" font-size="16" text-anchor="end">{len(teams)} team{"s" if len(teams) != 1 else ""}</text>',
        ]
        lines.extend(
            f'<text x="{x + 24}" y="{y + 77 + index * 25}" fill="#f4eddd" font-size="21">{text(team)}</text>'
            for index, team in enumerate(teams)
        )
        tiles.extend(lines)
    source = CARD_PATH.relative_to(REPOSITORY).as_posix()
    attestation = ATTESTATION_PATH.relative_to(REPOSITORY).as_posix()
    metadata = (
        f"source-path={source}; source-sha256={card_hash}; "
        f"attestation-path={attestation}; "
        "attestation=retrospective-replay-not-original-run-provenance"
    )
    return "\n".join(
        [
            '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="640" viewBox="0 0 1280 640" role="img" aria-labelledby="title desc">',
            '  <title id="title">Frozen corrected TI 2026 Swiss-stage forecast card</title>',
            '  <desc id="desc">Compendium category assignments from the frozen corrected TI 2026 Swiss-stage forecast card.</desc>',
            f"  <metadata>{text(metadata)}</metadata>",
            '  <rect width="1280" height="640" fill="#0b1523"/>',
            '  <text x="48" y="45" fill="#82dfc6" font-family="system-ui, sans-serif" font-size="24" font-weight="700">DOTA 2 / TI 2026</text>',
            '  <text x="48" y="92" fill="#f4eddd" font-family="system-ui, sans-serif" font-size="40" font-weight="700">Frozen corrected forecast</text>',
            '  <text x="48" y="122" fill="#c7d0d8" font-family="system-ui, sans-serif" font-size="20">Compendium category assignments</text>',
            '  <g font-family="system-ui, sans-serif">',
            *(f"    {line}" for line in tiles),
            "  </g>",
            '  <text x="48" y="591" fill="#f4eddd" font-family="system-ui, sans-serif" font-size="22">Frozen corrected forecast · not tournament results</text>',
            f'  <text x="48" y="620" fill="#c7d0d8" font-family="system-ui, sans-serif" font-size="16">Source: {text(source)}</text>',
            "</svg>",
            "",
        ]
    )


def main() -> None:
    card_hash = sha256(CARD_PATH)
    expected_hash = attested_card_hash(read_json(ATTESTATION_PATH))
    if card_hash != expected_hash:
        raise ValueError("forecast card sha256 differs from retrospective attestation")
    svg = render(assignments_from(read_json(CARD_PATH)), card_hash)
    OUTPUT_PATH.write_text(svg, encoding="utf-8")
    print(f"wrote {OUTPUT_PATH.relative_to(REPOSITORY)}")


if __name__ == "__main__":
    main()
