from __future__ import annotations

import json
import random
import unicodedata
from pathlib import Path
from typing import Any

PLAYERS_DATASET = Path("data") / "players_dataset.json"
LEAGUES_DIR = Path("mis_ligas")
CONFIG_DIR = Path("config")
MANAGER_CONFIG_PATH = CONFIG_DIR / "managers.json"

# Punto unico para manipular ventajas/desventajas iniciales en simulaciones nuevas.
# Por defecto todos empiezan en 0. Ejemplo: {"Manager 4": -80} hace que
# Manager 4 empiece 80 puntos por detras del resto.
DEFAULT_INITIAL_POINTS = 0
INITIAL_POINTS_BY_MANAGER: dict[str, int] = {}
# Cambia esto a True si quieres respetar los current_points escritos en managers.json.
USE_INITIAL_POINTS_FROM_MANAGER_CONFIG = False

# Estrategias que se asignan en bucle a managers ficticios.
SPORT_STRATEGY_CYCLE = [
    "cracks",
    "mejor_forma",
    "arriesgado",
    "grandes_clubes",
    "equipos_pequenos",
]
ECONOMIC_STRATEGY_CYCLE = [
    "balanceado",
    "fichar_a_toda_costa",
    "tacano",
]
LEGACY_STRATEGY_MAP = {
    "balanced": ("cracks", "balanceado"),
    "form": ("mejor_forma", "balanceado"),
    "value": ("equipos_pequenos", "tacano"),
    "stars": ("cracks", "fichar_a_toda_costa"),
    "budget": ("grandes_clubes", "tacano"),
    "risk": ("arriesgado", "fichar_a_toda_costa"),
}


def _resolve_strategies(payload: dict[str, Any]) -> tuple[str, str]:
    """Acepta config nueva o antigua y devuelve los dos ejes de estrategia."""
    sport_strategy = str(payload.get("sport_strategy") or "").strip()
    economic_strategy = str(payload.get("economic_strategy") or "").strip()
    if sport_strategy and economic_strategy:
        return sport_strategy, economic_strategy

    legacy_strategy = str(payload.get("strategy", "balanced") or "balanced").strip()
    mapped_sport, mapped_economic = LEGACY_STRATEGY_MAP.get(legacy_strategy, LEGACY_STRATEGY_MAP["balanced"])
    return sport_strategy or mapped_sport, economic_strategy or mapped_economic


def load_players_dataset(dataset_path: str | Path = PLAYERS_DATASET) -> list[dict[str, Any]]:
    """Carga desde disco el dataset de jugadores ya procesado."""
    path = Path(dataset_path)
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _normalize_player_name(value: str) -> str:
    """Normaliza nombres para poder compararlos de forma flexible."""
    for source_encoding in ("latin1", "cp1252", "cp1250"):
        try:
            repaired = value.encode(source_encoding).decode("utf-8")
        except UnicodeError:
            continue
        if repaired != value:
            value = repaired
            break
    # Quitamos tildes, pasamos a ASCII y reducimos espacios para evitar falsos no-coincide.
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_text.lower().split())


def _build_player_indexes(players: list[dict[str, Any]]) -> tuple[dict[int, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    """Construye índices por ID y por nombre para resolver referencias en config."""
    # Este índice permite resolver referencias exactas por ID.
    by_id = {int(player["id"]): player for player in players if player.get("id") is not None}
    by_name: dict[str, list[dict[str, Any]]] = {}
    for player in players:
        # También construimos un índice por nombre normalizado para admitir nombres en la configuración.
        normalized_name = _normalize_player_name(str(player.get("name", "")))
        if not normalized_name:
            continue
        by_name.setdefault(normalized_name, []).append(player)
    return by_id, by_name


def _resolve_player_refs(
    refs: list[Any],
    *,
    field_name: str,
    manager_name: str,
    players_by_id: dict[int, dict[str, Any]],
    players_by_name: dict[str, list[dict[str, Any]]],
) -> list[int]:
    """Resuelve una lista de IDs o nombres a IDs de jugadores."""
    resolved_ids: list[int] = []

    for ref in refs:
        if isinstance(ref, int):
            # Si la referencia ya es un ID, solo validamos que exista.
            if ref not in players_by_id:
                raise ValueError(f"Jugador con ID {ref} no encontrado en {field_name} de {manager_name}")
            resolved_ids.append(ref)
            continue

        if isinstance(ref, str):
            # Si viene por nombre, lo buscamos en el índice normalizado.
            normalized_name = _normalize_player_name(ref)
            matches = players_by_name.get(normalized_name, [])
            if not matches:
                raise ValueError(f"Jugador '{ref}' no encontrado en {field_name} de {manager_name}")
            if len(matches) > 1:
                # Forzamos desambiguación cuando el mismo nombre aparece en varios equipos.
                teams = ", ".join(sorted({str(player.get('teamName', '')) for player in matches}))
                raise ValueError(
                    f"Nombre ambiguo '{ref}' en {field_name} de {manager_name}. Equipos posibles: {teams}"
                )
            resolved_ids.append(int(matches[0]["id"]))
            continue

        raise ValueError(f"Referencia inválida en {field_name} de {manager_name}: {ref!r}")

    return list(dict.fromkeys(resolved_ids))


def _normalize_manager_config(payload: dict[str, Any], default_name: str) -> dict[str, Any]:
    """Convierte distintas variantes de config a un formato interno estable."""
    current_cash = payload.get("cash")
    if current_cash is None:
        current_cash = payload.get("money")
    sport_strategy, economic_strategy = _resolve_strategies(payload)
    manager_name = payload.get("name") or payload.get("managerName") or default_name
    configured_points = int(
        payload.get("current_points", 0)
        or payload.get("points", 0)
        or payload.get("score", 0)
        or payload.get("totalPoints", 0)
        or 0
    )
    initial_points = (
        configured_points
        if USE_INITIAL_POINTS_FROM_MANAGER_CONFIG
        else INITIAL_POINTS_BY_MANAGER.get(str(manager_name), DEFAULT_INITIAL_POINTS)
    )

    # Unificamos distintos alias posibles a una estructura de configuración interna única.
    config = {
        "name": manager_name,
        "strategy": payload.get("strategy"),
        "sport_strategy": sport_strategy,
        "economic_strategy": economic_strategy,
        "decision_engine": str(payload.get("decision_engine", "rules") or "rules").strip().lower(),
        "llm_backend": str(payload.get("llm_backend", "ollama") or "ollama").strip().lower(),
        "llm_model": payload.get("llm_model"),
        "llm_base_url": payload.get("llm_base_url"),
        "llm_controls": list(payload.get("llm_controls", ["sale_candidates", "market_bid", "formation"])),
        "budget": int(payload.get("budget", 0) or 0),
        "cash": int(current_cash or 0),
        "current_points": int(initial_points),
        "preferred_formation": payload.get("preferred_formation"),
        "squad_player_ids": list(payload.get("squad_player_ids", payload.get("squad_players", []))),
        "lineup_player_ids": list(payload.get("lineup_player_ids", payload.get("lineup_players", []))),
        "_cash_is_current": current_cash is not None,
    }
    return config


def build_default_manager_configs(
    num_managers: int = 6,
    budget: int = 180_000_000,
    seed: int | None = None,
) -> list[dict[str, Any]]:
    """Construye managers de ejemplo para poder simular una liga completa."""
    rng = random.Random(seed)
    configs: list[dict[str, Any]] = []

    for index in range(num_managers):
        # Repartimos estrategias distintas para comparar comportamientos en la simulación.
        sport_strategy = SPORT_STRATEGY_CYCLE[index % len(SPORT_STRATEGY_CYCLE)]
        economic_strategy = ECONOMIC_STRATEGY_CYCLE[index % len(ECONOMIC_STRATEGY_CYCLE)]
        configs.append(
            {
                "name": f"Manager {index + 1}",
                "strategy": None,
                "sport_strategy": sport_strategy,
                "economic_strategy": economic_strategy,
                "decision_engine": "rules",
                "llm_backend": "ollama",
                "llm_model": None,
                "llm_base_url": None,
                "llm_controls": ["sale_candidates", "market_bid", "formation"],
                "budget": budget + rng.randint(-8_000_000, 8_000_000),
                "cash": 0,
                "current_points": INITIAL_POINTS_BY_MANAGER.get(f"Manager {index + 1}", DEFAULT_INITIAL_POINTS),
                "preferred_formation": None,
                "squad_player_ids": [],
                "lineup_player_ids": [],
                "_cash_is_current": False,
            }
        )

    return configs


def _extract_player_ids(payload: dict[str, Any]) -> list[int]:
    """Intenta sacar IDs de jugadores desde varios formatos de JSON posibles."""
    candidate_lists = []
    for key in ("players", "lineup", "squad", "roster"):
        # Recorremos varias claves habituales porque cada JSON externo puede venir distinto.
        value = payload.get(key)
        if isinstance(value, list):
            candidate_lists.append(value)

    extracted_ids: list[int] = []
    for candidate_list in candidate_lists:
        for item in candidate_list:
            if isinstance(item, dict) and isinstance(item.get("id"), int):
                extracted_ids.append(item["id"])
    return list(dict.fromkeys(extracted_ids))


def load_manager_configs_from_directory(leagues_dir: str | Path = LEAGUES_DIR) -> list[dict[str, Any]]:
    """Carga managers reales desde una carpeta con ficheros JSON."""
    base_path = Path(leagues_dir)
    if not base_path.exists():
        return []

    configs: list[dict[str, Any]] = []
    for path in sorted(base_path.rglob("*.json")):
        # Este archivo representa el mercado y no un manager concreto.
        if path.name == "market.json":
            continue

        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        manager_payload = payload.get("manager", {}) if isinstance(payload, dict) else {}
        player_ids = _extract_player_ids(payload if isinstance(payload, dict) else {})
        if not manager_payload and not player_ids:
            continue

        # Unificamos distintos nombres de campos a una estructura común interna.
        config = _normalize_manager_config(
            {
                "name": manager_payload.get("managerName") or path.stem,
                "strategy": manager_payload.get("strategy"),
                "sport_strategy": manager_payload.get("sport_strategy"),
                "economic_strategy": manager_payload.get("economic_strategy"),
                "cash": payload.get("budget", 0) or payload.get("money", 0) or 0,
                "points": payload.get("points", 0),
                "score": payload.get("score", 0),
                "totalPoints": payload.get("totalPoints", 0),
                "squad_player_ids": player_ids,
                "lineup_player_ids": _extract_player_ids(manager_payload) if isinstance(manager_payload, dict) else [],
                "preferred_formation": manager_payload.get("preferredFormation"),
            },
            default_name=path.stem,
        )
        configs.append(config)

    return configs


def load_manager_configs_from_file(
    players: list[dict[str, Any]],
    config_path: str | Path = MANAGER_CONFIG_PATH,
) -> list[dict[str, Any]]:
    """Carga la configuración inicial de managers desde un JSON editable."""
    path = Path(config_path)
    if not path.exists():
        return []

    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    raw_managers = payload.get("managers", payload) if isinstance(payload, dict) else payload
    if not isinstance(raw_managers, list):
        raise ValueError(f"El archivo de managers debe contener una lista: {path}")

    # Preparamos índices del dataset para traducir nombres de jugadores a IDs reales.
    players_by_id, players_by_name = _build_player_indexes(players)
    configs: list[dict[str, Any]] = []
    for index, raw_manager in enumerate(raw_managers, start=1):
        if not isinstance(raw_manager, dict):
            continue
        config = _normalize_manager_config(raw_manager, default_name=f"Manager {index}")
        manager_name = str(config["name"])
        # Estas dos listas aceptan tanto IDs como nombres, pero internamente siempre convertimos a IDs.
        config["squad_player_ids"] = _resolve_player_refs(
            list(config.get("squad_player_ids", [])),
            field_name="squad_player_ids",
            manager_name=manager_name,
            players_by_id=players_by_id,
            players_by_name=players_by_name,
        )
        config["lineup_player_ids"] = _resolve_player_refs(
            list(config.get("lineup_player_ids", [])),
            field_name="lineup_player_ids",
            manager_name=manager_name,
            players_by_id=players_by_id,
            players_by_name=players_by_name,
        )
        configs.append(config)
    return configs


def load_manager_configs(
    dataset_path: str | Path = PLAYERS_DATASET,
    num_managers: int = 6,
    budget: int = 180_000_000,
    seed: int | None = None,
    use_real_league: bool = False,
    leagues_dir: str | Path = LEAGUES_DIR,
    manager_config_path: str | Path = MANAGER_CONFIG_PATH,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Devuelve el dataset de jugadores y la configuración de managers a usar."""
    players = load_players_dataset(dataset_path)

    # La prioridad es: archivo manual de configuración > liga real importada > managers por defecto.
    file_configs = load_manager_configs_from_file(players, manager_config_path)
    if file_configs:
        return players, file_configs[:num_managers]

    if use_real_league:
        configs = load_manager_configs_from_directory(leagues_dir)
        if configs:
            return players, configs[:num_managers]

    return players, build_default_manager_configs(num_managers=num_managers, budget=budget, seed=seed)
