from __future__ import annotations

"""Recupera decisiones LLM parciales a partir de raw_output no parseable."""

import json
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT_DIR / "model"
if str(MODEL_DIR) not in sys.path:
    sys.path.append(str(MODEL_DIR))

from llm_strategy import _extract_json_payload  # noqa: E402

DECISIONS_FILE = ROOT_DIR / "data" / "simulation_results" / "llm_decisions.json"


def as_list(value: Any) -> list[str]:
    """Normaliza campos explicativos del LLM a lista de cadenas."""
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def apply_recovered_metadata(decision: dict[str, Any], parsed: dict[str, Any]) -> None:
    """Copia resumen, factores y confianza a la entrada visible del log."""
    if isinstance(parsed.get("summary"), str) and parsed["summary"].strip():
        decision["summary"] = parsed["summary"].strip()
    for key in ("key_factors", "risk_flags", "decision_trace"):
        values = as_list(parsed.get(key))
        if values:
            decision[key] = values[:3]
    confidence = parsed.get("confidence")
    if isinstance(confidence, (int, float)):
        decision["confidence"] = max(0.0, min(1.0, float(confidence)))


def main() -> None:
    """Actualiza llm_decisions.json con parseos recuperados desde raw_output."""
    data = json.loads(DECISIONS_FILE.read_text(encoding="utf-8-sig"))
    recovered = 0
    impossible = 0

    for manager in data:
        for decision in manager.get("llm_decision_history", []):
            request = decision.get("llm_request") or {}
            if request.get("parsed_output"):
                continue
            raw_output = request.get("raw_output")
            if not raw_output:
                impossible += 1
                continue
            parsed = _extract_json_payload(str(raw_output))
            if not isinstance(parsed, dict):
                impossible += 1
                continue
            request["parsed_output"] = parsed
            request["recovered_after_run"] = True
            decision["llm_request"] = request
            decision["recovered_after_run"] = True
            apply_recovered_metadata(decision, parsed)
            recovered += 1

    DECISIONS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Decisiones recuperadas: {recovered}")
    print(f"Sin salida recuperable: {impossible}")


if __name__ == "__main__":
    main()
