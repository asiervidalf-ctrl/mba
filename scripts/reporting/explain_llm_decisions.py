from __future__ import annotations

"""Genera un Markdown explicable desde las trazas JSON del LLM."""

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_INPUT = Path("data") / "simulation_results" / "llm_decisions.json"
DEFAULT_OUTPUT = Path("data") / "simulation_results" / "llm_decisions_explained.md"


def _money(value: Any) -> str:
    """Formatea importes en euros y controla valores no numericos."""
    if not isinstance(value, (int, float)):
        return "sin importe"
    return f"{int(value):,} EUR".replace(",", ".")


def _compact_list(values: list[Any], *, limit: int = 8) -> str:
    """Resume listas largas para que las frases del informe sean legibles."""
    clean = [str(value) for value in values if value not in (None, "")]
    if not clean:
        return "sin datos"
    if len(clean) > limit:
        return ", ".join(clean[:limit]) + f" y {len(clean) - limit} mas"
    return ", ".join(clean)


def _name_lookup(decision: dict[str, Any]) -> dict[int, str]:
    """Construye un indice de nombres usando el contexto enviado al LLM."""
    payload = decision.get("llm_request", {}).get("input_payload", {})
    lookup: dict[int, str] = {}
    for collection_name in ("squad", "market_open"):
        collection = payload.get(collection_name, []) if isinstance(payload, dict) else []
        if not isinstance(collection, list):
            continue
        for item in collection:
            if not isinstance(item, dict):
                continue
            player_id = item.get("player_id", item.get("id"))
            if not isinstance(player_id, int):
                continue
            name = item.get("name") or item.get("n") or item.get("player") or f"jugador {player_id}"
            lookup[player_id] = str(name)
    return lookup


def _player_label(player_id: Any, lookup: dict[int, str]) -> str:
    """Resuelve un ID de jugador a nombre, o conserva el ID si no existe."""
    if isinstance(player_id, str) and player_id.isdigit():
        player_id = int(player_id)
    if isinstance(player_id, int):
        return lookup.get(player_id, f"jugador {player_id}")
    return str(player_id)


def _decision_sentence(decision: dict[str, Any]) -> str:
    """Traduce la decision final validada a una frase corta."""
    decision_type = decision.get("decision_type")
    final_decision = decision.get("final_decision", {})
    fallback_used = bool(decision.get("fallback_used"))
    prefix = "El LLM propuso" if not fallback_used else "Se uso fallback tras consultar al LLM"
    lookup = _name_lookup(decision)

    if decision_type == "market_day_plan":
        sale_ids = final_decision.get("sale_player_ids", [])
        bid_by_player_id = final_decision.get("bid_by_player_id", {})
        sale_labels = [_player_label(player_id, lookup) for player_id in sale_ids] if isinstance(sale_ids, list) else []
        bids = []
        if isinstance(bid_by_player_id, dict):
            bids = [f"{_player_label(player_id, lookup)} por {_money(bid)}" for player_id, bid in bid_by_player_id.items()]
        return (
            f"{prefix} un plan de mercado: vender {_compact_list(sale_labels)} "
            f"y pujar por {_compact_list(bids)}."
        )

    if decision_type in {"lineup", "formation"}:
        formation = final_decision.get("formation", "sin formacion")
        lineup_names = final_decision.get("lineup", [])
        lineup_ids = final_decision.get("lineup_player_ids", [])
        lineup_labels = [_player_label(player_id, lookup) for player_id in lineup_ids] if isinstance(lineup_ids, list) else []
        lineup_text = _compact_list(lineup_names if lineup_names else lineup_labels, limit=11)
        return f"{prefix} la alineacion {formation}: {lineup_text}."

    if decision_type == "sale_candidates":
        sale_ids = final_decision.get("sell_player_ids", final_decision.get("sale_player_ids", []))
        sale_labels = [_player_label(player_id, lookup) for player_id in sale_ids] if isinstance(sale_ids, list) else []
        return f"{prefix} vender {_compact_list(sale_labels)}."

    if decision_type == "market_bid":
        bid = final_decision.get("bid")
        player_id = final_decision.get("player_id", "desconocido")
        return f"{prefix} pujar {_money(bid)} por {_player_label(player_id, lookup)}."

    return f"{prefix} una decision de tipo {decision_type}: {final_decision}."


def _request_status(decision: dict[str, Any]) -> str:
    """Resume el estado tecnico de la llamada al LLM."""
    request = decision.get("llm_request", {})
    if not isinstance(request, dict):
        return "sin traza tecnica"
    elapsed = request.get("elapsed_seconds")
    error = request.get("error")
    parsed_output = request.get("parsed_output", {})
    if error:
        return f"fallo tecnico: {error}"
    if parsed_output:
        return f"respuesta parseada en {elapsed}s"
    raw_output = request.get("raw_output")
    if raw_output:
        return f"respuesta no parseable en {elapsed}s"
    return f"sin respuesta parseada en {elapsed}s"


def explain_decision(decision: dict[str, Any]) -> list[str]:
    """Convierte una decision individual en varias lineas Markdown."""
    lines = [
        f"- Jornada {decision.get('round')}, dia de mercado {decision.get('market_day')}: "
        f"{_decision_sentence(decision)}",
    ]

    summary = decision.get("summary")
    if summary:
        lines.append(f"  Motivo resumido: {summary}")

    key_factors = decision.get("key_factors", [])
    if key_factors:
        lines.append(f"  Factores clave: {_compact_list(key_factors, limit=5)}.")

    risk_flags = decision.get("risk_flags", [])
    if risk_flags:
        lines.append(f"  Riesgos detectados: {_compact_list(risk_flags, limit=5)}.")

    decision_trace = decision.get("decision_trace", [])
    if decision_trace:
        lines.append(f"  Rastro de decision declarado: {_compact_list(decision_trace, limit=6)}.")

    context = decision.get("context", {})
    bid_adjustments = context.get("bid_adjustments", []) if isinstance(context, dict) else []
    if bid_adjustments:
        adjusted = [
            f"{item.get('player', item.get('player_id'))}: {_money(item.get('original_bid'))} -> {_money(item.get('accepted_bid'))}"
            for item in bid_adjustments
            if isinstance(item, dict)
        ]
        lines.append(f"  Ajustes de puja por precio: {_compact_list(adjusted, limit=5)}.")

    confidence = decision.get("confidence")
    if isinstance(confidence, (int, float)):
        lines.append(f"  Confianza declarada: {confidence:.2f}.")

    lines.append(f"  Estado de la llamada: {_request_status(decision)}.")
    return lines


def build_report(data: list[dict[str, Any]]) -> str:
    """Agrupa por manager y compone el informe completo."""
    lines = [
        "# Explicacion de decisiones LLM",
        "",
        "Este informe traduce el JSON tecnico de decisiones a lenguaje natural.",
        "",
    ]

    total_decisions = sum(len(manager.get("llm_decision_history", [])) for manager in data)
    lines.append(f"Total de managers: {len(data)}")
    lines.append(f"Total de decisiones registradas: {total_decisions}")
    lines.append("")

    for manager in data:
        name = manager.get("name", "Manager sin nombre")
        sport_strategy = manager.get("sport_strategy", "sin estrategia deportiva")
        economic_strategy = manager.get("economic_strategy", "sin estrategia economica")
        history = manager.get("llm_decision_history", [])
        lines.append(f"## {name}")
        lines.append("")
        lines.append(f"Estrategia: {sport_strategy} + {economic_strategy}.")
        lines.append("")
        if not history:
            lines.append("No hay decisiones LLM registradas.")
            lines.append("")
            continue
        for decision in history:
            lines.extend(explain_decision(decision))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def parse_args() -> argparse.Namespace:
    """Lee rutas de entrada y salida desde argumentos de linea de comandos."""
    parser = argparse.ArgumentParser(description="Convierte llm_decisions.json a un informe explicable.")
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="Ruta del llm_decisions.json.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Ruta del informe Markdown de salida.")
    return parser.parse_args()


def main() -> None:
    """Ejecuta la conversion de JSON tecnico a Markdown explicativo."""
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)
    data = json.loads(input_path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, list):
        raise ValueError(f"El archivo no tiene el formato esperado: {input_path}")
    report = build_report(data)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(f"Informe generado: {output_path}")


if __name__ == "__main__":
    main()
