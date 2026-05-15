from __future__ import annotations

"""Restaura `decision_engine=llm` en estados generados con MBA_FORCE_RULES."""

import json
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_STATE_FILE = ROOT_DIR / "data" / "simulation_results" / "current_state.json"
DEFAULT_MANAGER_CONFIG = ROOT_DIR / "config" / "managers.json"


def load_json(path: Path) -> Any:
    """Carga JSON aceptando BOM si lo hubiera."""
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main(
    state_file: Path = DEFAULT_STATE_FILE,
    manager_config_file: Path = DEFAULT_MANAGER_CONFIG,
) -> None:
    """Copia la configuracion LLM declarada en managers.json al estado actual."""
    state = load_json(state_file)
    manager_config = load_json(manager_config_file)
    configured = {
        manager["name"]: manager
        for manager in manager_config.get("managers", [])
        if isinstance(manager, dict) and manager.get("name")
    }

    changed = 0
    for manager_state in state.get("managers", []):
        manager_name = manager_state.get("name")
        source = configured.get(manager_name)
        if not source:
            continue
        for key in ("decision_engine", "llm_backend", "llm_model", "llm_base_url", "llm_controls"):
            if key in source:
                manager_state[key] = source[key]
        changed += 1

    state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Estado actualizado: {changed} managers restaurados desde {manager_config_file}")


if __name__ == "__main__":
    main()
