from __future__ import annotations

"""Genera un paquete de datos compacto para la demo HTML interactiva."""

import json
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
RESULTS_DIR = ROOT_DIR / "data" / "simulation_results"
PLAYERS_FILE = ROOT_DIR / "data" / "players_dataset.json"
DEMO_DIR = ROOT_DIR / "demo"
OUTPUT_FILE = DEMO_DIR / "demo_data.js"


def load_json(path: Path) -> Any:
    """Carga JSON aceptando archivos con o sin BOM."""
    return json.loads(path.read_text(encoding="utf-8-sig"))


def compact_player(player: dict[str, Any]) -> dict[str, Any]:
    """Conserva solo los campos de jugador que necesita la demo."""
    return {
        "id": player.get("id"),
        "name": player.get("name"),
        "position": player.get("position"),
        "teamName": player.get("teamName"),
        "marketValue": player.get("marketValue", 0),
        "points": player.get("points", 0),
        "averagePoints": player.get("averagePoints", 0),
        "points_history": [
            {
                "round": item.get("round"),
                "points": item.get("points", 0),
            }
            for item in player.get("points_history", [])
            if int(item.get("round") or 0) >= 25
        ],
        "marketValueHistory": player.get("marketValueHistory", []),
        "marketValue_history": player.get("marketValue_history", []),
    }


def collect_referenced_player_ids(
    *,
    lineups: list[dict[str, Any]],
    market_days: list[dict[str, Any]],
) -> set[int]:
    """Detecta jugadores que aparecen en plantillas, onces o mercados."""
    ids: set[int] = set()
    for manager in lineups:
        for entry in manager.get("lineup_history", []):
            for key in ("lineup", "bench", "squad"):
                for player in entry.get(key, []):
                    player_id = player.get("player_id")
                    if player_id is not None:
                        ids.add(int(player_id))
    for day in market_days:
        for key in ("listings", "sales"):
            for player in day.get(key, []):
                player_id = player.get("player_id")
                if player_id is not None:
                    ids.add(int(player_id))
    return ids


def compact_decisions(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reduce los logs LLM a la parte explicable que se pinta en la demo."""
    compacted = []
    for manager in decisions:
        compacted.append(
            {
                "name": manager.get("name"),
                "strategy": manager.get("strategy"),
                "sport_strategy": manager.get("sport_strategy"),
                "economic_strategy": manager.get("economic_strategy"),
                "llm_decision_history": [
                    {
                        "round": item.get("round"),
                        "market_day": item.get("market_day"),
                        "decision_type": item.get("decision_type"),
                        "fallback_used": item.get("fallback_used", False),
                        "summary": item.get("summary"),
                        "key_factors": item.get("key_factors", []),
                        "risk_flags": item.get("risk_flags", []),
                        "decision_trace": item.get("decision_trace", []),
                        "confidence": item.get("confidence"),
                        "recovered_after_run": item.get("recovered_after_run", False),
                        "llm_status": {
                            "parsed": bool(item.get("llm_request", {}).get("parsed_output")),
                            "error": item.get("llm_request", {}).get("error"),
                            "has_raw_output": bool(item.get("llm_request", {}).get("raw_output")),
                        },
                    }
                    for item in manager.get("llm_decision_history", [])
                ],
            }
        )
    return compacted


def main() -> None:
    """Construye demo/demo_data.js para abrir la demo sin servidor."""
    leaderboard = load_json(RESULTS_DIR / "leaderboard.json")
    lineups = load_json(RESULTS_DIR / "lineups_history.json")
    market_days = load_json(RESULTS_DIR / "market_days.json")
    decisions = load_json(RESULTS_DIR / "llm_decisions.json")
    players = load_json(PLAYERS_FILE)

    referenced_ids = collect_referenced_player_ids(lineups=lineups, market_days=market_days)
    player_by_id = {int(player["id"]): player for player in players}
    compact_players = [
        compact_player(player_by_id[player_id])
        for player_id in sorted(referenced_ids)
        if player_id in player_by_id
    ]

    payload = {
        "leaderboard": leaderboard,
        "lineups": lineups,
        "marketDays": market_days,
        "decisions": compact_decisions(decisions),
        "players": compact_players,
    }

    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    json_payload = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    OUTPUT_FILE.write_text(f"window.DEMO_DATA = {json_payload};\n", encoding="utf-8")
    print(f"Demo data generado: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
