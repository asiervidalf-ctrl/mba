from __future__ import annotations

import json
import logging
import math
import os
import random
from ast import literal_eval
from collections import Counter
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

from mesa import Agent, Model
from mesa.datacollection import DataCollector

from llm_strategy import LLMDecisionEngine
from market_agent import MarketAgent, MarketListing

# Orden lógico usado para recorrer posiciones de forma consistente.
POSITION_ORDER = ["Portero", "Defensa", "Mediocampista", "Delantero"]
# Plantilla objetivo de 15 jugadores por manager.
SQUAD_TEMPLATE = {
    "Portero": 2,
    "Defensa": 5,
    "Mediocampista": 5,
    "Delantero": 3,
}
MAX_SQUAD_SIZE = 22
MAX_LLM_MARKET_CONTEXT = 2
MAX_LLM_SALE_CANDIDATES = 2
MAX_LLM_LIGHT_MARKET_CONTEXT = 1
MAX_LLM_LIGHT_SALE_CANDIDATES = 1
LLM_OBJECTIVE_FINAL_ROUND = 38
# Formaciones válidas para elegir el once titular.
FORMATIONS = [
    ("3-4-3", {"Portero": 1, "Defensa": 3, "Mediocampista": 4, "Delantero": 3}),
    ("3-5-2", {"Portero": 1, "Defensa": 3, "Mediocampista": 5, "Delantero": 2}),
    ("4-3-3", {"Portero": 1, "Defensa": 4, "Mediocampista": 3, "Delantero": 3}),
    ("4-4-2", {"Portero": 1, "Defensa": 4, "Mediocampista": 4, "Delantero": 2}),
    ("4-5-1", {"Portero": 1, "Defensa": 4, "Mediocampista": 5, "Delantero": 1}),
    ("5-3-2", {"Portero": 1, "Defensa": 5, "Mediocampista": 3, "Delantero": 2}),
    ("5-4-1", {"Portero": 1, "Defensa": 5, "Mediocampista": 4, "Delantero": 1}),
]
# Estrategias deportivas: ponderan de forma flexible distintas senales del jugador y su contexto.
SPORT_STRATEGY_WEIGHTS = {
    "cracks": {
        "projection": 0.30,
        "form": 0.18,
        "star": 0.22,
        "club_strength": 0.10,
        "opponent_weakness": 0.04,
        "matchup_ceiling": 0.05,
        "volatility": 0.03,
        "trend": 0.04,
        "safety": 0.04,
    },
    "mejor_forma": {
        "projection": 0.20,
        "form": 0.34,
        "star": 0.05,
        "club_strength": 0.08,
        "opponent_weakness": 0.10,
        "matchup_ceiling": 0.08,
        "volatility": 0.02,
        "trend": 0.08,
        "safety": 0.05,
    },
    "arriesgado": {
        "projection": 0.18,
        "form": 0.12,
        "star": 0.05,
        "club_strength": 0.04,
        "opponent_weakness": 0.10,
        "matchup_ceiling": 0.15,
        "volatility": 0.30,
        "trend": 0.08,
        "safety": -0.02,
    },
    "grandes_clubes": {
        "projection": 0.18,
        "form": 0.12,
        "star": 0.08,
        "club_strength": 0.30,
        "opponent_weakness": 0.12,
        "matchup_ceiling": 0.08,
        "volatility": 0.01,
        "trend": 0.04,
        "safety": 0.07,
    },
    "equipos_pequenos": {
        "projection": 0.16,
        "form": 0.16,
        "star": 0.03,
        "club_strength": 0.04,
        "opponent_weakness": 0.30,
        "matchup_ceiling": 0.16,
        "volatility": 0.04,
        "trend": 0.05,
        "safety": 0.06,
    },
}
ECONOMIC_STRATEGY_CONFIG = {
    "fichar_a_toda_costa": {
        "bid_premium_cap": 0.24,
        "cash_reserve": 750_000,
        "sale_appetite": 2,
        "reserve_size": 12,
        "min_improvement": -0.03,
    },
    "balanceado": {
        "bid_premium_cap": 0.10,
        "cash_reserve": 2_250_000,
        "sale_appetite": 1,
        "reserve_size": 13,
        "min_improvement": 0.08,
    },
    "tacano": {
        "bid_premium_cap": 0.0,
        "cash_reserve": 4_000_000,
        "sale_appetite": 1,
        "reserve_size": 13,
        "min_improvement": 0.18,
    },
}
SPORT_STRATEGY_BRIEF = {
    "cracks": "Prioriza futbolistas diferenciales y con techo alto, aunque no siempre sean los mas baratos.",
    "mejor_forma": "Da mas peso al rendimiento reciente y a jugadores que llegan en buena dinamica.",
    "arriesgado": "Acepta mas incertidumbre si el posible premio en puntos es alto.",
    "grandes_clubes": "Prefiere jugadores de equipos fuertes y contextos competitivos favorables.",
    "equipos_pequenos": "Busca oportunidades infravaloradas, buenos emparejamientos y rendimiento por encima del nombre.",
}
ECONOMIC_STRATEGY_BRIEF = {
    "fichar_a_toda_costa": "Puede usar el presupuesto de forma agresiva si mejora claramente los puntos esperados.",
    "balanceado": "Debe equilibrar mejora deportiva, liquidez y profundidad de plantilla.",
    "tacano": "Debe proteger caja y pujar solo cuando vea una oportunidad clara de valor.",
}
LEGACY_STRATEGY_MAP = {
    "balanced": ("cracks", "balanceado"),
    "form": ("mejor_forma", "balanceado"),
    "value": ("equipos_pequenos", "tacano"),
    "stars": ("cracks", "fichar_a_toda_costa"),
    "budget": ("grandes_clubes", "tacano"),
    "risk": ("arriesgado", "fichar_a_toda_costa"),
}
DEFAULT_MARKET_DAYS_PER_ROUND = 7
FORCE_RULES_DECISION_ENGINE = os.getenv("MBA_FORCE_RULES", "").strip().lower() in {"1", "true", "yes", "si"}
LLM_MARKET_DAYS_PER_ROUND = int(os.getenv("MBA_LLM_MARKET_DAYS_PER_ROUND", "7"))
LLM_LINEUP_START_ROUND = int(os.getenv("MBA_LLM_LINEUP_START_ROUND", "30"))
HOME_ADVANTAGE = 0.22
LOGGER = logging.getLogger(__name__)


def clamp(value: float, lower: float, upper: float) -> float:
    """Restringe un valor a un rango cerrado."""
    return max(lower, min(upper, value))


def safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Divide evitando errores cuando el denominador es cero."""
    return numerator / denominator if denominator else default


def sigmoid(value: float) -> float:
    """Transforma una señal continua en una probabilidad suave."""
    return 1.0 / (1.0 + math.exp(-value))


def parse_score(score: str) -> tuple[int, int] | None:
    """Extrae goles local/visitante a partir de un marcador tipo 2-1."""
    if not score or "-" not in score:
        return None
    left, right = score.split("-", 1)
    try:
        return int(left.strip()), int(right.strip())
    except ValueError:
        return None


def resolve_manager_strategies(config: dict[str, Any]) -> tuple[str, str]:
    """Normaliza configuraciones nuevas y antiguas a dos ejes de estrategia."""
    sport_strategy = str(config.get("sport_strategy") or "").strip()
    economic_strategy = str(config.get("economic_strategy") or "").strip()
    if sport_strategy and economic_strategy:
        return sport_strategy, economic_strategy

    legacy_strategy = str(config.get("strategy", "balanced") or "balanced").strip()
    mapped_sport, mapped_economic = LEGACY_STRATEGY_MAP.get(legacy_strategy, LEGACY_STRATEGY_MAP["balanced"])
    return sport_strategy or mapped_sport, economic_strategy or mapped_economic


def strategy_label(sport_strategy: str, economic_strategy: str) -> str:
    """Compone una etiqueta legible de la combinacion estrategica."""
    return f"{sport_strategy} + {economic_strategy}"


class PlayerAgent(Agent):
    """Agente que representa a un jugador fantasy individual."""

    def __init__(self, model: Model, player_data: dict[str, Any]) -> None:
        """Carga atributos estaticos e historicos desde el dataset agregado."""
        super().__init__(model)
        # Guardamos atributos fijos y métricas históricas del jugador.
        self.player_id = player_data["id"]
        self.name = player_data["name"]
        self.position = player_data["position"]
        self.team_name = player_data["teamName"]
        self.market_value = int(player_data.get("marketValue") or 300_000)
        self.initial_points = float(player_data.get("points") or 0)
        self.average_points = float(player_data.get("averagePoints") or 0)
        self.status = player_data.get("status", "available")
        self.availability = player_data.get("availability")
        self.analytics = player_data.get("analytics", {})
        self.points_history = player_data.get("points_history", [])
        self.market_value_history = player_data.get("marketValue_history", [])

        self.current_points = 0.0
        self.current_price = self.market_value
        self.expected_points = 0.0
        self.expected_price_delta = 0.0

    @property
    def points_samples(self) -> list[float]:
        """Devuelve solo los puntos historicos numericos del jugador."""
        samples: list[float] = []
        for entry in self.points_history:
            value = entry.get("points") if isinstance(entry, dict) else None
            if isinstance(value, (int, float)):
                samples.append(float(value))
        return samples

    def points_for_round(self, round_number: int) -> float | None:
        """Devuelve los puntos reales de una jornada concreta si existen en el dataset."""
        for entry in self.points_history:
            if not isinstance(entry, dict):
                continue
            if entry.get("round") != round_number:
                continue
            value = entry.get("points")
            if isinstance(value, (int, float)):
                return float(value)
        return None

    @property
    def availability_factor(self) -> float:
        """Convierte el estado médico en un factor de disponibilidad."""
        if self.status == "available":
            return 1.0
        if self.availability is None:
            return 0.55
        return clamp(self.availability / 100.0, 0.10, 1.0)

    @property
    def recent_form(self) -> float:
        """Resume el estado reciente del jugador usando medias cortas."""
        recent = [
            float(self.analytics.get("averagePointsLast5") or 0),
            float(self.analytics.get("averagePointsLast3") or 0),
            float(self.analytics.get("averagePointsLast1") or 0),
        ]
        recent = [value for value in recent if value > 0]
        return mean(recent) if recent else self.average_points

    @property
    def season_projection(self) -> float:
        """Estimación base de puntos por jornada según la temporada."""
        matches = int(self.analytics.get("matchesPlayedSeason") or 0)
        if matches > 0:
            return safe_div(self.initial_points, matches, self.average_points)
        return self.average_points

    @property
    def value_score(self) -> float:
        """Mide cuánto rendimiento aporta por cada millón invertido."""
        points_per_million = float(self.analytics.get("pointsPerMillion") or 0)
        if points_per_million > 0:
            return points_per_million / 100_000.0
        return safe_div(self.season_projection * 1_000_000.0, self.market_value, 0.0)

    @property
    def trend_score(self) -> float:
        """Resume la tendencia reciente del valor de mercado."""
        weights = [
            (float(self.analytics.get("marketChange1d") or 0), 0.40),
            (float(self.analytics.get("marketChange3d") or 0), 0.25),
            (float(self.analytics.get("marketChange7d") or 0), 0.20),
            (float(self.analytics.get("marketChange14d") or 0), 0.10),
            (float(self.analytics.get("marketChange30d") or 0), 0.05),
        ]
        trend_raw = sum(delta * weight for delta, weight in weights)
        return trend_raw / max(self.market_value, 1)

    @property
    def volatility_score(self) -> float:
        """Cuantifica la irregularidad del jugador a partir de sus puntuaciones reales."""
        samples = self.points_samples[-8:]
        if len(samples) < 2:
            return 0.0
        return pstdev(samples)

    @property
    def ceiling_score(self) -> float:
        """Estimacion del techo reciente del jugador usando sus mejores actuaciones."""
        samples = sorted(self.points_samples[-8:], reverse=True)
        if not samples:
            return self.recent_form
        return mean(samples[: min(3, len(samples))])

    def project_round(self, random_state: random.Random, current_round: int) -> None:
        """Simula puntos y precio del jugador en la jornada actual."""
        actual_points = self.points_for_round(current_round)
        if actual_points is not None:
            # Si el dataset trae la jornada, usamos solo los puntos de esa jornada,
            # nunca el acumulado de temporada del jugador.
            self.expected_points = round(actual_points, 2)
            self.current_points = actual_points
            self.expected_price_delta = 0.0
            self.current_price = max(300_000, int(round(self.market_value)))
            return

        base_projection = (0.50 * self.season_projection) + (0.35 * self.recent_form)
        ceiling_bonus = float(self.analytics.get("streakLast5") or 0) / 12.0
        context = self.model.build_player_round_context(self, current_round)
        fixture_adjustment = context.get("fixture_adjustment", 0.0)
        matchup_ceiling = context.get("matchup_ceiling", 0.0)
        availability_penalty = self.availability_factor
        volatility = 0.85 + context.get("volatility", 0.0) + (0.20 if self.status != "available" else 0.0)

        expected = max(0.0, (base_projection + ceiling_bonus + fixture_adjustment + matchup_ceiling) * availability_penalty)
        sampled = random_state.gauss(expected, volatility)

        # Los jugadores tocados tienen una probabilidad real de quedarse sin puntuar.
        if self.availability_factor < 0.45 and random_state.random() > self.availability_factor:
            sampled = 0.0

        self.expected_points = round(expected, 2)
        self.current_points = max(0, round(sampled))

        trend_component = self.market_value * self.trend_score * 0.45
        mean_reversion = (self.market_value - (self.market_value_history[-2] if len(self.market_value_history) > 1 else self.market_value)) * -0.15
        noise = random_state.gauss(0, max(self.market_value * 0.008, 25_000))

        # El precio evoluciona por tendencia, corrección y una pequeña parte aleatoria.
        self.expected_price_delta = trend_component + mean_reversion
        self.current_price = max(300_000, int(round(self.market_value + self.expected_price_delta + noise)))
        self.market_value = self.current_price


class ManagerAgent(Agent):
    """Agente que representa a un manager con plantilla y estrategia."""

    def __init__(self, model: Model, config: dict[str, Any]) -> None:
        """Inicializa estrategia, caja, LLM opcional e historicos del manager."""
        super().__init__(model)
        self.name = config["name"]
        self.sport_strategy, self.economic_strategy = resolve_manager_strategies(config)
        self.strategy = strategy_label(self.sport_strategy, self.economic_strategy)
        self.decision_engine = str(config.get("decision_engine", "rules") or "rules").strip().lower()
        self.llm_backend = str(config.get("llm_backend", "ollama") or "ollama").strip().lower()
        self.llm_model = str(config.get("llm_model") or "").strip() or None
        self.llm_base_url = str(config.get("llm_base_url") or "").strip() or None
        raw_llm_controls = config.get("llm_controls", ["sale_candidates", "market_bid", "formation"])
        self.llm_controls = (
            list(raw_llm_controls)
            if isinstance(raw_llm_controls, list)
            else ["sale_candidates", "market_bid", "formation"]
        )
        self.llm_engine = (
            LLMDecisionEngine(
                manager_name=self.name,
                model_name=self.llm_model,
                controls=self.llm_controls,
                backend=self.llm_backend,
                base_url=self.llm_base_url,
            )
            if self.decision_engine == "llm" and not FORCE_RULES_DECISION_ENGINE
            else None
        )
        self.cash = int(config.get("cash", config.get("budget", 0)))
        self.points_total = float(config.get("current_points", 0))
        self.points_round = 0.0
        self.squad: list[PlayerAgent] = []
        self.lineup: list[PlayerAgent] = []
        self.bench: list[PlayerAgent] = []
        self.current_formation = ""
        self.transfers_made = 0
        self.transfer_history: list[dict[str, Any]] = []
        self.bonus_history: list[dict[str, Any]] = []
        self.lineup_history: list[dict[str, Any]] = []
        self.llm_decision_history: list[dict[str, Any]] = []
        self._llm_formation_cache: dict[tuple[Any, ...], dict[str, Any] | None] = {}
        self.market_day_plan: dict[str, Any] = {"sale_player_ids": [], "bid_by_player_id": {}}
        self.proposed_sale_player_ids: list[int] = []
        self.remaining_market_purchase_capacity = 0
        # Estos campos permiten arrancar la simulación desde un estado inicial prefijado.
        self.seed_squad_player_ids = list(config.get("squad_player_ids", []))
        self.seed_lineup_player_ids = list(config.get("lineup_player_ids", []))
        self.preferred_formation = config.get("preferred_formation")
        self.seed_cash_is_current = bool(config.get("_cash_is_current", False))

    @property
    def squad_value(self) -> int:
        """Valor total de mercado de la plantilla actual."""
        return sum(player.market_value for player in self.squad)

    def _refresh_strategy_label(self) -> None:
        """Mantiene una etiqueta compuesta para informes y compatibilidad."""
        self.strategy = strategy_label(self.sport_strategy, self.economic_strategy)

    def _sport_weights(self) -> dict[str, float]:
        """Recupera los pesos deportivos configurados para el manager."""
        return SPORT_STRATEGY_WEIGHTS.get(self.sport_strategy, SPORT_STRATEGY_WEIGHTS["cracks"])

    def _economic_config(self) -> dict[str, float]:
        """Recupera los parametros economicos configurados para el manager."""
        return ECONOMIC_STRATEGY_CONFIG.get(self.economic_strategy, ECONOMIC_STRATEGY_CONFIG["balanceado"])

    def player_interest_profile(self, player: PlayerAgent) -> dict[str, float]:
        """Construye las senales deportivas que usa el manager para valorar un jugador."""
        round_context = self.model.build_player_round_context(player, self.model.current_round)
        team_contexts = self.model._compute_team_contexts(self.model.current_round)
        team = team_contexts.get(player.team_name, {})
        fixture = self.model.fixture_by_round_team.get(self.model.current_round, {}).get(player.team_name)
        opponent_weakness = 0.0
        next_match_opportunity = max(0.0, round_context.get("fixture_adjustment", 0.0)) + max(
            0.0,
            round_context.get("matchup_ceiling", 0.0),
        )

        if fixture is not None:
            opponent = fixture["away_team"] if fixture["home_team"] == player.team_name else fixture["home_team"]
            rival = team_contexts.get(opponent, {})
            opponent_weakness = (
                max(0.0, 1.75 - rival.get("overall_strength", 1.0))
                + max(0.0, rival.get("recent_ga", 1.1) - 1.0) * 0.75
                + max(0.0, 1.25 - rival.get("recent_ppg", 1.0)) * 0.90
                + max(0.0, rival.get("injury_impact", 0.0) - 0.08) * 1.4
            )
            opponent_weakness = (0.55 * opponent_weakness) + (0.45 * next_match_opportunity)

        return {
            "projection": max(player.expected_points, player.season_projection),
            "form": player.recent_form,
            "star": math.log1p(player.market_value / 1_000_000.0),
            "club_strength": team.get("overall_strength", 1.0),
            "opponent_weakness": opponent_weakness,
            "matchup_ceiling": player.ceiling_score + round_context.get("matchup_ceiling", 0.0),
            "volatility": player.volatility_score + (round_context.get("volatility", 0.0) * 8.0),
            "trend": player.trend_score * 100.0,
            "safety": player.availability_factor,
        }

    def player_score(self, player: PlayerAgent) -> float:
        """Calcula cuánto le gusta un jugador a este manager."""
        weights = self._sport_weights()
        signals = self.player_interest_profile(player)
        if self.sport_strategy == "equipos_pequenos":
            # Priorizamos cruces favorables a corto plazo por encima del nombre o del club.
            signals["opponent_weakness"] *= 1.35
            signals["matchup_ceiling"] *= 1.20
            signals["club_strength"] *= 0.75
            signals["star"] *= 0.65
        elif self.sport_strategy == "arriesgado":
            # Buscamos techos altos y aceptamos mejor cierta incertidumbre.
            signals["volatility"] *= 1.40
            signals["matchup_ceiling"] *= 1.30
            signals["projection"] = (0.75 * signals["projection"]) + (0.25 * player.ceiling_score)
            signals["safety"] = 0.70 + (0.30 * player.availability_factor)
        return sum(weights.get(key, 0.0) * value for key, value in signals.items())

    def add_player(
        self,
        player: PlayerAgent,
        charge_budget: bool = True,
        purchase_price: int | None = None,
    ) -> None:
        """Añade un jugador a la plantilla y descuenta su coste."""
        self.squad.append(player)
        self._llm_formation_cache.clear()
        if charge_budget:
            self.cash -= purchase_price if purchase_price is not None else player.market_value

    def remove_player(self, player: PlayerAgent, sale_price: int | None = None) -> None:
        """Vende un jugador y recupera su valor actual."""
        self.squad.remove(player)
        self._llm_formation_cache.clear()
        self.cash += sale_price if sale_price is not None else player.market_value

    def _append_llm_decision_log(
        self,
        *,
        decision_type: str,
        final_decision: dict[str, Any],
        fallback_used: bool,
        raw_response: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Guarda un log estructurado y ligero de cada decision relevante del LLM."""
        if self.llm_engine is None:
            return

        meta = self.llm_engine.get_last_decision_meta(decision_type) or {}
        request_log = self.llm_engine.get_last_request_log() or {}
        self.llm_decision_history.append(
            {
                "round": self.model.current_round,
                "market_day": self.model.current_market_day,
                "manager": self.name,
                "decision_type": decision_type,
                "backend": self.llm_backend,
                "model": self.llm_engine.resolved_model_name,
                "sport_strategy": self.sport_strategy,
                "economic_strategy": self.economic_strategy,
                "fallback_used": fallback_used,
                "summary": meta.get("summary"),
                "key_factors": meta.get("key_factors", []),
                "risk_flags": meta.get("risk_flags", []),
                "decision_trace": meta.get("decision_trace", []),
                "confidence": meta.get("confidence"),
                "elapsed_seconds": request_log.get("elapsed_seconds"),
                "context": context or {},
                "final_decision": final_decision,
                "raw_response": raw_response or {},
                "llm_request": request_log,
            }
        )

    def _llm_objective_payload(self) -> dict[str, Any]:
        """Objetivo comun para que el LLM optimice con horizonte de temporada."""
        final_round = max(LLM_OBJECTIVE_FINAL_ROUND, self.model.current_round)
        return {
            "goal": f"maximizar puntos acumulados de J{self.model.current_round} a J{final_round}",
            "current_round": self.model.current_round,
            "final_round": final_round,
            "remaining_rounds": max(1, final_round - self.model.current_round + 1),
        }

    def _strategy_payload(self) -> dict[str, Any]:
        """Describe las estrategias sin revelar pesos internos ni una receta cerrada."""
        return {
            "sport": self.sport_strategy,
            "economic": self.economic_strategy,
        }

    def _llm_manager_payload(self) -> dict[str, Any]:
        """Resume el estado economico y competitivo del manager para el LLM."""
        return {
            "name": self.name,
            "cash_m": round(self.cash / 1_000_000, 1),
            "squad": len(self.squad),
            "points": int(round(self.points_total)),
        }

    def _formation_payload(self, formation_options: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Compacta formaciones para reducir tokens sin perder requisitos."""
        labels = {"Portero": "P", "Defensa": "D", "Mediocampista": "M", "Delantero": "F"}
        compact_options: list[dict[str, Any]] = []
        for option in formation_options:
            requirements = option["requirements"] if "requirements" in option else dict(dict(FORMATIONS)[option["name"]])
            req = " ".join(f"{labels[position]}{count}" for position, count in requirements.items())
            compact_options.append({"name": option["name"], "req": req})
        return compact_options

    def _non_available_status(self, player: PlayerAgent) -> str | None:
        """Oculta estados normales y solo envia avisos de no disponibilidad."""
        return None if player.status == "available" else str(player.status)

    def _position_code(self, position: str) -> str:
        """Codifica posiciones para que el contexto LLM sea muy corto."""
        return {
            "Portero": "P",
            "Defensa": "D",
            "Mediocampista": "M",
            "Delantero": "F",
        }.get(position, position[:1].upper())

    def _clean_player_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Elimina claves vacias del payload para no ensuciar el contexto LLM."""
        return {key: value for key, value in payload.items() if value is not None}

    def _position_counts(self) -> dict[str, int]:
        """Cuenta cuantos jugadores tiene la plantilla por posicion."""
        return dict(Counter(player.position for player in self.squad))

    def _squad_summary_payload(self) -> dict[str, Any]:
        """Resume profundidad de plantilla y requisitos minimos de alineacion."""
        return {
            "pos": {self._position_code(position): count for position, count in self._position_counts().items()},
            "need": "11 titulares con 1P",
        }

    def _player_payload_for_llm(self, player: PlayerAgent) -> dict[str, Any]:
        """Version compacta del jugador: precio, puntos y senales accionables."""
        return self._clean_player_payload({
            "id": player.player_id,
            "p": self._position_code(player.position),
            "v": round(player.market_value / 1_000_000, 2),
            "pts": round(player.expected_points, 1),
            "f": round(player.recent_form, 1),
            "s": round(player.season_projection, 1),
            "fit": round(player.availability_factor, 2),
        })

    def _squad_payload(self) -> list[dict[str, Any]]:
        """Genera la lista compacta de jugadores propios que vera el LLM."""
        return [
            self._player_payload_for_llm(player)
            for player in sorted(self.squad, key=lambda item: (POSITION_ORDER.index(item.position), item.name))
        ]

    def _select_lineup_with_llm(
        self,
        formation_options: list[dict[str, Any]],
        fallback_option: dict[str, Any],
    ) -> dict[str, Any]:
        """Permite al LLM elegir formacion y once completo, validando las reglas."""
        if (
            self.llm_engine is None
            or self.model.current_round < LLM_LINEUP_START_ROUND
            or not self.llm_engine.supports("lineup")
            or len(formation_options) <= 1
        ):
            return fallback_option

        cache_key = (
            self.model.current_round,
            tuple(sorted(player.player_id for player in self.squad)),
            tuple(option["name"] for option in formation_options),
        )
        cached = self._llm_formation_cache.get(cache_key)
        if isinstance(cached, dict):
            validated_cached = self._validate_llm_lineup(
                cached.get("formation"),
                cached.get("lineup_player_ids", []),
                formation_options,
            )
            if validated_cached is not None:
                return validated_cached

        response = self.llm_engine.choose_lineup(
            {
                "objective": self._llm_objective_payload(),
                "manager": self._llm_manager_payload(),
                "lineup_rules": {
                    "lineup_size": 11,
                    "use_only_squad_players": True,
                    "formations": self._formation_payload(formation_options),
                },
                "strategy": self._strategy_payload(),
                "squad_summary": self._squad_summary_payload(),
                "squad": self._squad_payload(),
            }
        )
        if isinstance(response, dict):
            self._llm_formation_cache[cache_key] = {
                "formation": response.get("formation"),
                "lineup_player_ids": response.get("lineup_player_ids", []),
            }

        raw_formation = response.get("formation") if isinstance(response, dict) else None
        raw_lineup_ids = response.get("lineup_player_ids", []) if isinstance(response, dict) else []
        selected_option = self._validate_llm_lineup(raw_formation, raw_lineup_ids, formation_options)
        lineup_repaired_from_formation = False
        if selected_option is None and isinstance(response, dict):
            selected_option = self._option_for_llm_formation(raw_formation, formation_options)
            lineup_repaired_from_formation = selected_option is not None

        if selected_option is None:
            self._llm_formation_cache[cache_key] = {
                "formation": fallback_option["name"],
                "lineup_player_ids": [player.player_id for player in fallback_option["lineup"]],
            }
            self._append_llm_decision_log(
                decision_type="lineup",
                final_decision={
                    "formation": fallback_option["name"],
                    "lineup_player_ids": [player.player_id for player in fallback_option["lineup"]],
                },
                fallback_used=True,
                raw_response=response if isinstance(response, dict) else None,
                context={
                    "available_formations": [option["name"] for option in formation_options],
                    "fallback_formation": fallback_option["name"],
                },
            )
            return fallback_option

        self._append_llm_decision_log(
            decision_type="lineup",
            final_decision={
                "formation": selected_option["name"],
                "lineup_player_ids": [player.player_id for player in selected_option["lineup"]],
                "lineup": [player.name for player in selected_option["lineup"]],
            },
            fallback_used=False,
            raw_response=response,
            context={
                "available_formations": [option["name"] for option in formation_options],
                "fallback_formation": fallback_option["name"],
                "lineup_repaired_from_formation": lineup_repaired_from_formation,
            },
        )
        self._llm_formation_cache[cache_key] = {
            "formation": selected_option["name"],
            "lineup_player_ids": [player.player_id for player in selected_option["lineup"]],
        }
        return selected_option

    def _validate_llm_lineup(
        self,
        formation_name: Any,
        lineup_player_ids: Any,
        formation_options: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Comprueba que la alineacion LLM cumpla IDs, posiciones y formacion."""
        if not isinstance(formation_name, str) or not isinstance(lineup_player_ids, list):
            return None
        requirements = dict(FORMATIONS).get(formation_name)
        if requirements is None or not any(option["name"] == formation_name for option in formation_options):
            return None
        parsed_ids = [player_id for player_id in lineup_player_ids if isinstance(player_id, int)]
        if len(parsed_ids) != 11 or len(set(parsed_ids)) != 11:
            return None
        squad_by_id = {player.player_id: player for player in self.squad}
        if any(player_id not in squad_by_id for player_id in parsed_ids):
            return None
        lineup = [squad_by_id[player_id] for player_id in parsed_ids]
        counts = Counter(player.position for player in lineup)
        if any(counts.get(position, 0) != amount for position, amount in requirements.items()):
            return None
        lineup_ids = set(parsed_ids)
        bench = [player for player in sorted(self.squad, key=self.player_score, reverse=True) if player.player_id not in lineup_ids]
        score = sum(self.player_score(player) for player in lineup)
        return {
            "name": formation_name,
            "lineup": lineup,
            "bench": bench,
            "score": score,
        }

    def _option_for_llm_formation(
        self,
        formation_name: Any,
        formation_options: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Usa la formacion elegida por el LLM aunque sus IDs no sean validos."""
        if not isinstance(formation_name, str):
            return None
        return next((option for option in formation_options if option["name"] == formation_name), None)

    def _has_valid_formation_after_sales(self, sale_player_ids: list[int]) -> bool:
        """Evita ventas que impidan formar cualquier once legal."""
        sale_ids = set(sale_player_ids)
        remaining_players = [player for player in self.squad if player.player_id not in sale_ids]
        counts = Counter(player.position for player in remaining_players)
        return any(
            all(counts.get(position, 0) >= amount for position, amount in requirements.items())
            for _, requirements in FORMATIONS
        )

    def _validated_sale_ids(self, raw_sale_ids: list[int], max_sales: int) -> list[int]:
        """Filtra ventas propuestas por el LLM segun propiedad y viabilidad."""
        selected_sales: list[int] = []
        squad_ids = {player.player_id for player in self.squad}
        for player_id in raw_sale_ids:
            if player_id not in squad_ids or player_id in selected_sales:
                continue
            if len(selected_sales) >= max_sales:
                break
            candidate_sales = [*selected_sales, player_id]
            if self._has_valid_formation_after_sales(candidate_sales):
                selected_sales.append(player_id)
        return selected_sales

    def select_best_formation(self, use_llm: bool = True) -> tuple[str, list[PlayerAgent], list[PlayerAgent]]:
        """Busca la formación legal que maximiza el potencial del once."""
        players_by_position: dict[str, list[PlayerAgent]] = {position: [] for position in POSITION_ORDER}
        for player in self.squad:
            players_by_position[player.position].append(player)

        for position in POSITION_ORDER:
            players_by_position[position].sort(key=self.player_score, reverse=True)

        # Como base, nos quedamos con los 11 mejores sin imponer formación.
        formation_options: list[dict[str, Any]] = []

        for formation_name, requirements in FORMATIONS:
            # Solo probamos formaciones para las que haya jugadores suficientes por puesto.
            if any(len(players_by_position[position]) < amount for position, amount in requirements.items()):
                continue

            lineup: list[PlayerAgent] = []
            for position, amount in requirements.items():
                lineup.extend(players_by_position[position][:amount])

            lineup = sorted(lineup, key=self.player_score, reverse=True)
            score = sum(self.player_score(player) for player in lineup)
            lineup_ids = {player.player_id for player in lineup}
            bench = [player for player in sorted(self.squad, key=self.player_score, reverse=True) if player.player_id not in lineup_ids]
            formation_options.append(
                {
                    "name": formation_name,
                    "lineup": lineup,
                    "bench": bench,
                    "score": score,
                }
            )

        if not formation_options:
            raise RuntimeError(f"No existe ninguna formacion valida con portero para {self.name}")

        fallback_option = max(formation_options, key=lambda option: option["score"])
        selected_option = self._select_lineup_with_llm(formation_options, fallback_option) if use_llm else fallback_option
        return selected_option["name"], selected_option["lineup"], selected_option["bench"]

    def select_preferred_formation(self) -> tuple[str, list[PlayerAgent], list[PlayerAgent]] | None:
        """Construye el once usando la formación preferida si es válida."""
        if not self.preferred_formation:
            return None

        # Si la configuración pide una formación concreta, intentamos respetarla.
        requirements = dict(FORMATIONS).get(self.preferred_formation)
        if requirements is None:
            return None

        players_by_position: dict[str, list[PlayerAgent]] = {position: [] for position in POSITION_ORDER}
        for player in self.squad:
            players_by_position[player.position].append(player)

        for position in POSITION_ORDER:
            players_by_position[position].sort(key=self.player_score, reverse=True)
            if len(players_by_position[position]) < requirements[position]:
                return None

        lineup: list[PlayerAgent] = []
        for position, amount in requirements.items():
            lineup.extend(players_by_position[position][:amount])

        lineup_ids = {player.player_id for player in lineup}
        bench = [player for player in sorted(self.squad, key=self.player_score, reverse=True) if player.player_id not in lineup_ids]
        return self.preferred_formation, lineup, bench

    def select_seed_lineup(self) -> tuple[str, list[PlayerAgent], list[PlayerAgent]] | None:
        """Usa una alineación fijada por configuración si es válida."""
        if not self.seed_lineup_player_ids:
            return None

        # Recuperamos los objetos PlayerAgent a partir de los IDs definidos en el archivo de config.
        squad_by_id = {player.player_id: player for player in self.squad}
        lineup = [squad_by_id[player_id] for player_id in self.seed_lineup_player_ids if player_id in squad_by_id]
        if len(lineup) != 11 or len({player.player_id for player in lineup}) != 11:
            return None

        # Intentamos reconocer si ese once corresponde exactamente a una formación oficial.
        counts = Counter(player.position for player in lineup)
        for formation_name, requirements in FORMATIONS:
            if all(counts.get(position, 0) == amount for position, amount in requirements.items()):
                lineup_ids = {player.player_id for player in lineup}
                bench = [player for player in self.squad if player.player_id not in lineup_ids]
                return formation_name, lineup, bench

        return None

    def _build_sale_candidate_pool(self) -> tuple[list[PlayerAgent], list[PlayerAgent], int, int]:
        """Prepara el pool de jugadores vendibles para el dia de mercado."""
        if len(self.squad) <= 12:
            return [], [], 0, 0

        _, _, bench = self.select_best_formation(use_llm=False)
        if not bench:
            return [], [], 0, 0

        economic = self._economic_config()
        reserve_size = int(economic["reserve_size"])
        max_sales = min(int(economic["sale_appetite"]), max(0, len(self.squad) - reserve_size))
        if self.cash < int(economic["cash_reserve"]):
            max_sales = max(max_sales, 1)
        if max_sales <= 0:
            return [], [], 0, reserve_size

        sorted_bench = sorted(bench, key=self.player_score)
        candidate_pool = sorted_bench[: min(len(sorted_bench), max(max_sales + 1, MAX_LLM_SALE_CANDIDATES))]
        fallback_candidates = sorted_bench[:max_sales]
        return candidate_pool, fallback_candidates, max_sales, reserve_size

    def _build_llm_market_view(
        self,
        market_listings: list[MarketListing],
        fallback_bid_by_player_id: dict[int, int],
        max_items: int = MAX_LLM_MARKET_CONTEXT,
    ) -> list[dict[str, Any]]:
        """Recorta el contexto del mercado para acelerar las llamadas al LLM."""
        del fallback_bid_by_player_id
        visible_listings = [
            listing
            for listing in market_listings
            if listing.seller is None or listing.seller.unique_id != self.unique_id
        ]
        ranked_listings = sorted(
            visible_listings,
            key=lambda listing: (
                self.player_score(listing.player),
                -listing.ask_price,
            ),
            reverse=True,
        )
        trimmed_listings = ranked_listings[:max(0, max_items)]
        return [
            self._clean_player_payload({
                "id": listing.player.player_id,
                "p": self._position_code(listing.player.position),
                "ask": round(listing.ask_price / 1_000_000, 2),
                "max": round(self._max_reasonable_bid(listing) / 1_000_000, 2),
                "src": "M" if listing.source == "manager" else "L",
                "pts": round(listing.player.expected_points, 1),
                "f": round(listing.player.recent_form, 1),
                "s": round(listing.player.season_projection, 1),
                "fit": round(listing.player.availability_factor, 2),
            })
            for listing in trimmed_listings
        ]

    def _max_reasonable_bid(self, listing: MarketListing) -> int:
        """Limite de cordura para que el LLM no sobrepague jugadores sin senales deportivas."""
        player = listing.player
        economic = self._economic_config()
        base_price = max(listing.ask_price, player.market_value, 1)
        point_signal = max(player.expected_points, player.recent_form, player.season_projection, 0.0)
        if point_signal <= 0.5:
            performance_premium = 0.01
        elif point_signal <= 2.0:
            performance_premium = 0.04
        else:
            performance_premium = min(0.18, point_signal * 0.025)
        fitness_penalty = 0.0 if player.availability_factor >= 0.75 else 0.08
        strategy_premium = max(0.0, float(economic["bid_premium_cap"]))
        premium = max(0.0, strategy_premium + performance_premium - fitness_penalty)
        return max(listing.ask_price, int(round(base_price * (1.0 + premium))))

    def _calculate_fallback_bid(self, listing: MarketListing) -> int | None:
        """Calcula la puja basada en reglas sin consultar al LLM."""
        player = listing.player
        if any(owned.player_id == player.player_id for owned in self.squad):
            return None

        economic = self._economic_config()
        reserve_cash = int(economic["cash_reserve"])
        max_affordable = self.cash - reserve_cash
        if max_affordable < listing.ask_price:
            return None

        position_players = [owned for owned in self.squad if owned.position == player.position]
        position_count = len(position_players)
        squad_space = max(0, MAX_SQUAD_SIZE - len(self.squad))
        position_need = max(0, SQUAD_TEMPLATE[player.position] - position_count)
        if squad_space <= 0:
            return None

        weakest_same_position = min(position_players, key=self.player_score) if position_players else None
        improvement = (
            self.player_score(player) - self.player_score(weakest_same_position)
            if weakest_same_position is not None
            else self.player_score(player)
        )

        min_improvement = float(economic["min_improvement"])
        if position_need <= 0 and improvement < min_improvement:
            return None

        fit_signal = max(0.0, improvement) + (0.28 * position_need) + (0.08 if squad_space > 0 else 0.0)
        premium = min(
            float(economic["bid_premium_cap"]),
            (0.01 if economic["bid_premium_cap"] > 0 else 0.0)
            + (fit_signal * 0.045)
            + (0.01 if listing.source == "manager" else 0.0),
        )
        bid = int(round(listing.ask_price * (1.0 + premium)))
        bid = min(bid, self._max_reasonable_bid(listing))
        bid = min(bid, max_affordable)
        return bid if bid >= listing.ask_price else None

    def propose_market_day_sales(self, official_listings: list[MarketListing]) -> list[PlayerAgent]:
        """Decide una propuesta inicial de ventas usando solo el mercado oficial del dia."""
        del official_listings
        candidate_pool, fallback_candidates, max_sales, reserve_size = self._build_sale_candidate_pool()
        if max_sales <= 0:
            self.proposed_sale_player_ids = []
            return []

        del candidate_pool, reserve_size
        self.proposed_sale_player_ids = [player.player_id for player in fallback_candidates]
        return fallback_candidates

    def decide_market_day(self, market_listings: list[MarketListing]) -> dict[str, Any]:
        """Toma una decision global del dia: ventas propias y pujas sobre el mercado abierto."""
        candidate_pool, fallback_candidates, max_sales, reserve_size = self._build_sale_candidate_pool()
        fallback_sale_ids = list(self.proposed_sale_player_ids) if self.proposed_sale_player_ids else [player.player_id for player in fallback_candidates]
        fallback_sale_ids = self._validated_sale_ids(fallback_sale_ids, max_sales)

        fallback_bid_by_player_id: dict[int, int] = {}
        for listing in market_listings:
            if listing.seller is not None and listing.seller.unique_id == self.unique_id:
                continue
            bid = self._calculate_fallback_bid(listing)
            if bid is not None:
                fallback_bid_by_player_id[listing.player.player_id] = bid

        use_llm_market = (
            self.llm_engine is not None
            and self.model.current_market_day <= LLM_MARKET_DAYS_PER_ROUND
            and (self.llm_engine.supports("sale_candidates") or self.llm_engine.supports("market_bid"))
        )
        if not use_llm_market:
            self.market_day_plan = {
                "sale_player_ids": fallback_sale_ids,
                "bid_by_player_id": fallback_bid_by_player_id,
            }
            return self.market_day_plan

        is_light_market_day = self.model.current_market_day > 1
        llm_market_limit = MAX_LLM_LIGHT_MARKET_CONTEXT if is_light_market_day else MAX_LLM_MARKET_CONTEXT
        llm_sale_limit = MAX_LLM_LIGHT_SALE_CANDIDATES if is_light_market_day else MAX_LLM_SALE_CANDIDATES
        llm_max_bids = 1 if is_light_market_day else 2
        llm_max_sales = min(max_sales, 1) if is_light_market_day else max_sales
        llm_market_view = self._build_llm_market_view(
            market_listings,
            fallback_bid_by_player_id,
            max_items=llm_market_limit,
        )
        response = self.llm_engine.choose_market_day_plan(
            {
                "objective": self._llm_objective_payload(),
                "manager": {
                    **self._llm_manager_payload(),
                    "market_day": self.model.current_market_day,
                },
                "market_rules": {
                    "mode": "light_refresh" if is_light_market_day else "full_market_day",
                    "max_sales": llm_max_sales,
                    "keep_min_players": 11,
                    "max_squad": MAX_SQUAD_SIZE,
                    "bid_units": "euros",
                    "price_units_in_context": "million_eur",
                    "max_bids": llm_max_bids,
                },
                "strategy": self._strategy_payload(),
                "squad_summary": self._squad_summary_payload(),
                "sale_candidates": [self._player_payload_for_llm(player) for player in candidate_pool[:llm_sale_limit]],
                "market_open": llm_market_view,
            }
        )

        final_sale_ids = fallback_sale_ids
        final_bid_by_player_id = dict(fallback_bid_by_player_id)
        if isinstance(response, dict):
            raw_sale_ids = response.get("sell_player_ids", [])
            selected_sales: list[int] = []
            if isinstance(raw_sale_ids, list):
                selected_sales = self._validated_sale_ids(
                    [player_id for player_id in raw_sale_ids if isinstance(player_id, int)],
                    llm_max_sales,
                )
            final_sale_ids = selected_sales

            raw_bids = response.get("bids", [])
            final_bid_by_player_id = {}
            bid_adjustments: list[dict[str, Any]] = []
            if isinstance(raw_bids, list):
                listing_by_player_id = {listing.player.player_id: listing for listing in market_listings}
                max_purchase_count = max(0, MAX_SQUAD_SIZE - len(self.squad) + len(final_sale_ids))
                squad_by_id = {player.player_id: player for player in self.squad}
                bid_budget = self.cash + sum(squad_by_id[player_id].market_value for player_id in final_sale_ids if player_id in squad_by_id)
                committed_bid_budget = 0
                for item in raw_bids:
                    if not isinstance(item, dict):
                        continue
                    player_id = item.get("player_id")
                    bid = item.get("bid")
                    if not isinstance(player_id, int) or not isinstance(bid, int):
                        continue
                    listing = listing_by_player_id.get(player_id)
                    if listing is None:
                        continue
                    if listing.seller is not None and listing.seller.unique_id == self.unique_id:
                        continue
                    if any(owned.player_id == player_id for owned in self.squad):
                        continue
                    if bid < listing.ask_price or bid <= 0:
                        continue
                    original_bid = bid
                    max_reasonable_bid = self._max_reasonable_bid(listing)
                    if bid > max_reasonable_bid:
                        bid = max_reasonable_bid
                        bid_adjustments.append(
                            {
                                "player_id": player_id,
                                "player": listing.player.name,
                                "original_bid": original_bid,
                                "accepted_bid": bid,
                                "ask_eur": listing.ask_price,
                                "market_value_eur": listing.player.market_value,
                                "reason": "sobrepuja_recortada",
                            }
                        )
                    if bid < listing.ask_price:
                        continue
                    if len(final_bid_by_player_id) >= min(max_purchase_count, llm_max_bids):
                        break
                    if committed_bid_budget + bid > bid_budget:
                        continue
                    committed_bid_budget += bid
                    final_bid_by_player_id[player_id] = bid

        self.market_day_plan = {
            "sale_player_ids": final_sale_ids,
            "bid_by_player_id": final_bid_by_player_id,
        }
        self._append_llm_decision_log(
            decision_type="market_day_plan",
            final_decision={
                "sale_player_ids": final_sale_ids,
                "bid_by_player_id": final_bid_by_player_id,
            },
            fallback_used=not isinstance(response, dict),
            raw_response=response if isinstance(response, dict) else None,
            context={
                "visible_market_size": len(llm_market_view),
                "squad_size": len(self.squad),
                "max_sales": llm_max_sales,
                "llm_market_mode": "light_refresh" if is_light_market_day else "full_market_day",
                "llm_max_bids": llm_max_bids,
                "bid_adjustments": bid_adjustments if isinstance(response, dict) else [],
                "fallback_used_only_if_llm_invalid": not isinstance(response, dict),
            },
        )
        self.remaining_market_purchase_capacity = max(0, MAX_SQUAD_SIZE - len(self.squad) + len(final_sale_ids))
        return self.market_day_plan

    def planned_bid_for_listing(self, listing: MarketListing) -> int | None:
        """Recupera la puja decidida para una ficha del mercado abierto del dia."""
        if self.remaining_market_purchase_capacity <= 0:
            return None
        bid_by_player_id = self.market_day_plan.get("bid_by_player_id", {})
        if not isinstance(bid_by_player_id, dict):
            return None
        bid = bid_by_player_id.get(listing.player.player_id)
        return bid if isinstance(bid, int) else None

    def choose_sale_candidates(self) -> list[PlayerAgent]:
        """Selecciona jugadores prescindibles para poner a la venta en el mercado."""
        if len(self.squad) <= 12:
            return []

        _, _, bench = self.select_best_formation(use_llm=False)
        if not bench:
            return []

        economic = self._economic_config()
        reserve_size = int(economic["reserve_size"])
        max_sales = min(int(economic["sale_appetite"]), max(0, len(self.squad) - reserve_size))
        if self.cash < int(economic["cash_reserve"]):
            max_sales = max(max_sales, 1)
        if max_sales <= 0:
            return []

        sorted_bench = sorted(bench, key=self.player_score)
        fallback_candidates = sorted_bench[:max_sales]

        if self.llm_engine is None or not self.llm_engine.supports("sale_candidates"):
            return fallback_candidates

        llm_candidate_pool = sorted_bench[: min(len(sorted_bench), max(max_sales + 2, 5))]
        selected_ids = self.llm_engine.choose_sale_candidates(
            {
                "manager": {
                    "name": self.name,
                    "sport_strategy": self.sport_strategy,
                    "economic_strategy": self.economic_strategy,
                    "cash": self.cash,
                    "round": self.model.current_round,
                    "max_sales": max_sales,
                    "reserve_size": reserve_size,
                },
                "candidates": [
                    {
                        "player_id": player.player_id,
                        "name": player.name,
                        "position": player.position,
                        "team": player.team_name,
                        "market_value": player.market_value,
                        "score_for_manager": round(self.player_score(player), 4),
                        "expected_points": round(player.expected_points, 2),
                    }
                    for player in llm_candidate_pool
                ],
            }
        )
        if not selected_ids:
            return fallback_candidates

        candidate_by_id = {player.player_id: player for player in llm_candidate_pool}
        validated_players: list[PlayerAgent] = []
        for player_id in selected_ids:
            player = candidate_by_id.get(player_id)
            if player is not None and player not in validated_players:
                validated_players.append(player)
            if len(validated_players) >= max_sales:
                break
        return validated_players or fallback_candidates

    def calculate_market_bid(self, listing: MarketListing) -> int | None:
        """Calcula una puja para un jugador del mercado según encaje y agresividad."""
        player = listing.player
        if any(owned.player_id == player.player_id for owned in self.squad):
            return None

        economic = self._economic_config()
        reserve_cash = int(economic["cash_reserve"])
        max_affordable = self.cash - reserve_cash
        if max_affordable < listing.ask_price:
            return None

        position_players = [owned for owned in self.squad if owned.position == player.position]
        position_count = len(position_players)
        squad_space = max(0, MAX_SQUAD_SIZE - len(self.squad))
        position_need = max(0, SQUAD_TEMPLATE[player.position] - position_count)

        # Si no queda hueco en plantilla, primero debe vender antes de poder comprar.
        if squad_space <= 0:
            return None

        weakest_same_position = min(position_players, key=self.player_score) if position_players else None
        improvement = (
            self.player_score(player) - self.player_score(weakest_same_position)
            if weakest_same_position is not None
            else self.player_score(player)
        )

        # Si la plantilla ya está completa, solo pujamos por mejoras reales o por carencias de profundidad.
        min_improvement = float(economic["min_improvement"])
        if position_need <= 0 and improvement < min_improvement:
            return None

        fit_signal = max(0.0, improvement) + (0.28 * position_need) + (0.08 if squad_space > 0 else 0.0)
        premium = min(
            float(economic["bid_premium_cap"]),
            (0.01 if economic["bid_premium_cap"] > 0 else 0.0)
            + (fit_signal * 0.045)
            + (0.01 if listing.source == "manager" else 0.0),
        )
        fallback_bid = int(round(listing.ask_price * (1.0 + premium)))
        max_reasonable_bid = self._max_reasonable_bid(listing)
        fallback_bid = min(fallback_bid, max_reasonable_bid)
        fallback_bid = min(fallback_bid, max_affordable)
        if fallback_bid < listing.ask_price:
            return None

        if self.llm_engine is None or not self.llm_engine.supports("market_bid"):
            return fallback_bid

        llm_bid = self.llm_engine.choose_market_bid(
            {
                "manager": {
                    "name": self.name,
                    "sport_strategy": self.sport_strategy,
                    "economic_strategy": self.economic_strategy,
                    "cash": self.cash,
                    "reserve_cash": reserve_cash,
                    "max_affordable": max_affordable,
                    "round": self.model.current_round,
                },
                "listing": {
                    "player_id": player.player_id,
                    "player": player.name,
                    "position": player.position,
                    "team": player.team_name,
                    "ask_price": listing.ask_price,
                    "source": listing.source,
                    "market_value": player.market_value,
                    "max_reasonable_bid": max_reasonable_bid,
                    "score_for_manager": round(self.player_score(player), 4),
                    "expected_points": round(player.expected_points, 2),
                    "position_need": position_need,
                    "fallback_bid": fallback_bid,
                },
                "rules": {
                    "minimum_bid": listing.ask_price,
                    "maximum_bid": min(max_affordable, max_reasonable_bid),
                    "return_null_if_not_buying": True,
                },
            }
        )
        if llm_bid is None:
            return fallback_bid
        if llm_bid < listing.ask_price or llm_bid > min(max_affordable, max_reasonable_bid):
            LOGGER.warning(
                "Puja LLM invalida para %s en %s: %s. Se usa fallback.",
                self.name,
                player.name,
                llm_bid,
            )
            return fallback_bid
        return llm_bid

    def step(self) -> None:
        """Ejecuta la l?gica del manager en una jornada."""
        # Los fichajes y ventas ya se resuelven antes en el agente mercado.
        if self.model.current_round == self.model.initial_config_round:
            # Solo en la primera jornada respetamos alineaciones o formaciones fijadas por configuración.
            seed_lineup = self.select_seed_lineup()
            if seed_lineup is not None:
                self.current_formation, self.lineup, self.bench = seed_lineup
            else:
                preferred_lineup = self.select_preferred_formation()
                if preferred_lineup is not None:
                    self.current_formation, self.lineup, self.bench = preferred_lineup
                else:
                    self.current_formation, self.lineup, self.bench = self.select_best_formation()
        else:
            self.current_formation, self.lineup, self.bench = self.select_best_formation()
        # El once queda fijado al inicio de la jornada y no cambia mientras esa jornada puntua.
        self.points_round = sum(player.current_points for player in self.lineup)
        self.points_total += self.points_round


class FantasyLeagueModel(Model):
    """Modelo principal que coordina managers, jugadores y jornadas."""

    def __init__(
        self,
        players_json_path: str | Path,
        manager_configs: list[dict[str, Any]],
        start_round: int = 30,
        max_rounds: int = 10,
        seed: int | None = None,
        transfer_limit_per_round: int = 1,
        days_per_round: int = DEFAULT_MARKET_DAYS_PER_ROUND,
        restored_state: dict[str, Any] | None = None,
    ) -> None:
        """Construye el modelo completo desde configuracion nueva o estado guardado."""
        super().__init__(rng=seed)
        self.random_state = self.random
        self.players_json_path = Path(players_json_path)
        self.seed = seed
        # Estos atributos controlan desde qu? jornada arrancamos y cu?ntos ciclos ejecutamos en esta sesi?n.
        self.start_round = start_round
        self.current_round = start_round
        self.initial_config_round = start_round
        self.max_rounds = max_rounds
        self.end_round = start_round + max_rounds
        self.transfer_limit_per_round = transfer_limit_per_round
        self.days_per_round = days_per_round
        self.current_market_day = 0

        players_data = json.loads(self.players_json_path.read_text(encoding="utf-8"))
        self.player_agents = [
            PlayerAgent(model=self, player_data=player_data)
            for index, player_data in enumerate(players_data)
        ]
        self.players_by_id = {player.player_id: player for player in self.player_agents}
        self.players_by_team: dict[str, list[PlayerAgent]] = {}
        for player in self.player_agents:
            self.players_by_team.setdefault(player.team_name, []).append(player)
        self.fixtures_by_round = self._build_fixtures_by_round()
        self.fixture_by_round_team = self._build_fixture_lookup_by_team()
        self._team_context_cache: dict[int, dict[str, dict[str, float]]] = {}

        self.manager_agents = [
            ManagerAgent(model=self, config=config)
            for config in manager_configs
        ]
        # Este diccionario indica qu? manager es el due?o actual de cada jugador.
        self.owner_by_player_id: dict[int, str] = {}
        # El agente mercado gestiona subastas diarias y bonificaciones por jornada.
        self.market_agent = MarketAgent(model=self)

        if restored_state is not None:
            self._restore_state(restored_state)
        else:
            # Primero cargamos plantillas predefinidas y luego completamos el draft restante.
            self._initialize_squads()

        self.datacollector = DataCollector(
            model_reporters={
                "round": lambda m: m.current_round,
                "leader": lambda m: m.get_leaderboard()[0]["name"],
                "leader_points": lambda m: m.get_leaderboard()[0]["points_total"],
                "average_round_points": lambda m: round(mean(agent.points_round for agent in m.manager_agents), 2),
                "market_days": lambda m: len(m.market_agent.last_round_market_days),
                "market_listings": lambda m: sum(len(day["listings"]) for day in m.market_agent.last_round_market_days),
                "market_sales": lambda m: sum(
                    1
                    for day in m.market_agent.last_round_market_days
                    for sale in day["sales"]
                    if sale["status"] != "unsold"
                ),
                "bonus_paid": lambda m: m.market_agent.last_bonus_total,
            },
            agenttype_reporters={
                ManagerAgent: {
                    "name": lambda agent: agent.name,
                    "strategy": lambda agent: agent.strategy,
                    "sport_strategy": lambda agent: agent.sport_strategy,
                    "economic_strategy": lambda agent: agent.economic_strategy,
                    "points_total": lambda agent: agent.points_total,
                    "points_round": lambda agent: agent.points_round,
                    "cash": lambda agent: agent.cash,
                    "squad_value": lambda agent: agent.squad_value,
                    "formation": lambda agent: agent.current_formation,
                    "transfers_made": lambda agent: agent.transfers_made,
                }
            },
        )
        self.running = True

    def _build_fixtures_by_round(self) -> dict[int, list[dict[str, Any]]]:
        """Reconstruye el calendario a partir del historial de puntos de los jugadores."""
        fixtures: dict[int, dict[tuple[str, str], dict[str, Any]]] = {}
        for player in self.player_agents:
            for entry in player.points_history:
                round_number = entry.get("round")
                home_team = entry.get("homeTeam")
                away_team = entry.get("awayTeam")
                if not isinstance(round_number, int) or not home_team or not away_team:
                    continue
                fixtures.setdefault(round_number, {})
                key = (home_team, away_team)
                fixtures[round_number].setdefault(
                    key,
                    {
                        "round": round_number,
                        "date": entry.get("date"),
                        "home_team": home_team,
                        "away_team": away_team,
                        "score": entry.get("score", ""),
                    },
                )
        return {
            round_number: list(round_fixtures.values())
            for round_number, round_fixtures in fixtures.items()
        }

    def _build_fixture_lookup_by_team(self) -> dict[int, dict[str, dict[str, Any]]]:
        """Indexa cada partido por jornada y por equipo para consulta rápida."""
        lookup: dict[int, dict[str, dict[str, Any]]] = {}
        for round_number, fixtures in self.fixtures_by_round.items():
            round_lookup: dict[str, dict[str, Any]] = {}
            for fixture in fixtures:
                round_lookup[fixture["home_team"]] = fixture
                round_lookup[fixture["away_team"]] = fixture
            lookup[round_number] = round_lookup
        return lookup

    def _compute_team_contexts(self, current_round: int) -> dict[str, dict[str, float]]:
        """Calcula forma, fortaleza e impacto de bajas para todos los equipos."""
        cached = self._team_context_cache.get(current_round)
        if cached is not None:
            return cached

        completed_matches: dict[str, list[dict[str, float]]] = {team: [] for team in self.players_by_team}
        for round_number in sorted(round_number for round_number in self.fixtures_by_round if round_number < current_round):
            for fixture in self.fixtures_by_round.get(round_number, []):
                parsed_score = parse_score(str(fixture.get("score", "")))
                if parsed_score is None:
                    continue
                home_goals, away_goals = parsed_score
                home_team = fixture["home_team"]
                away_team = fixture["away_team"]
                home_points = 3 if home_goals > away_goals else 1 if home_goals == away_goals else 0
                away_points = 3 if away_goals > home_goals else 1 if home_goals == away_goals else 0
                completed_matches.setdefault(home_team, []).append(
                    {
                        "gf": float(home_goals),
                        "ga": float(away_goals),
                        "table_points": float(home_points),
                        "home": 1.0,
                    }
                )
                completed_matches.setdefault(away_team, []).append(
                    {
                        "gf": float(away_goals),
                        "ga": float(home_goals),
                        "table_points": float(away_points),
                        "home": 0.0,
                    }
                )

        contexts: dict[str, dict[str, float]] = {}
        for team_name, roster in self.players_by_team.items():
            matches = completed_matches.get(team_name, [])
            recent_matches = matches[-5:]

            season_ppg = mean(match["table_points"] for match in matches) if matches else 1.0
            recent_ppg = mean(match["table_points"] for match in recent_matches) if recent_matches else season_ppg
            season_gf = mean(match["gf"] for match in matches) if matches else 1.1
            season_ga = mean(match["ga"] for match in matches) if matches else 1.1
            recent_gf = mean(match["gf"] for match in recent_matches) if recent_matches else season_gf
            recent_ga = mean(match["ga"] for match in recent_matches) if recent_matches else season_ga

            player_quality = sorted(
                (
                    (0.55 * player.season_projection)
                    + (0.35 * player.recent_form)
                    + (0.10 * math.log1p(player.market_value / 1_000_000.0))
                )
                for player in roster
            )
            key_core = player_quality[-8:] if len(player_quality) >= 8 else player_quality
            core_quality = mean(key_core) if key_core else 3.0

            important_absences = 0.0
            for player in roster:
                unavailability = 1.0 - player.availability_factor
                if unavailability <= 0.15:
                    continue
                player_impact = (
                    (0.60 * player.season_projection)
                    + (0.30 * player.recent_form)
                    + (0.10 * math.log1p(player.market_value / 1_000_000.0))
                )
                important_absences += player_impact * unavailability

            injury_impact = clamp(safe_div(important_absences, (core_quality * 5.0), 0.0), 0.0, 0.55)
            attack_strength = (
                (0.50 * recent_gf)
                + (0.30 * season_gf)
                + (0.20 * core_quality / 4.0)
                - (0.45 * injury_impact)
            )
            defense_strength = (
                (0.50 * (2.2 - recent_ga))
                + (0.30 * (2.2 - season_ga))
                + (0.20 * core_quality / 4.5)
                - (0.35 * injury_impact)
            )
            overall_strength = (
                (0.45 * recent_ppg)
                + (0.25 * season_ppg)
                + (0.20 * attack_strength)
                + (0.10 * defense_strength)
                - (0.80 * injury_impact)
            )

            contexts[team_name] = {
                "season_ppg": season_ppg,
                "recent_ppg": recent_ppg,
                "season_gf": season_gf,
                "season_ga": season_ga,
                "recent_gf": recent_gf,
                "recent_ga": recent_ga,
                "injury_impact": injury_impact,
                "core_quality": core_quality,
                "attack_strength": attack_strength,
                "defense_strength": defense_strength,
                "overall_strength": overall_strength,
            }

        self._team_context_cache[current_round] = contexts
        return contexts

    def build_player_round_context(self, player: PlayerAgent, current_round: int) -> dict[str, float]:
        """Genera el contexto del partido para ajustar la predicción fantasy del jugador."""
        fixture = self.fixture_by_round_team.get(current_round, {}).get(player.team_name)
        if fixture is None:
            return {"fixture_adjustment": 0.0, "matchup_ceiling": 0.0, "volatility": 0.05}

        is_home = fixture["home_team"] == player.team_name
        opponent = fixture["away_team"] if is_home else fixture["home_team"]
        team_contexts = self._compute_team_contexts(current_round)
        team = team_contexts.get(player.team_name, {})
        rival = team_contexts.get(opponent, {})

        team_strength = team.get("overall_strength", 1.0)
        rival_strength = rival.get("overall_strength", 1.0)
        team_attack = team.get("attack_strength", 1.0)
        team_defense = team.get("defense_strength", 1.0)
        rival_attack = rival.get("attack_strength", 1.0)
        rival_defense = rival.get("defense_strength", 1.0)

        strength_delta = team_strength - rival_strength + (HOME_ADVANTAGE if is_home else -0.05)
        win_probability = sigmoid(strength_delta * 0.9)
        draw_probability = clamp(0.24 - abs(strength_delta) * 0.06, 0.12, 0.28)
        loss_probability = max(0.0, 1.0 - win_probability - draw_probability)
        if loss_probability == 0.0:
            total = win_probability + draw_probability
            win_probability = safe_div(win_probability, total, 0.65)
            draw_probability = safe_div(draw_probability, total, 0.25)
            loss_probability = max(0.0, 1.0 - win_probability - draw_probability)

        result_signal = (win_probability * 1.15) + (draw_probability * 0.25) - (loss_probability * 0.70)
        clean_sheet_chance = clamp(
            0.28 + ((team_defense - rival_attack) * 0.12) + (result_signal * 0.08),
            0.05,
            0.65,
        )
        attacking_return_chance = clamp(
            0.16 + ((team_attack - rival_defense) * 0.15) + (result_signal * 0.10),
            0.05,
            0.72,
        )
        opponent_difficulty = clamp((rival_strength - team_strength) * 0.45, -1.0, 1.0)

        if player.position == "Portero":
            fixture_adjustment = (2.3 * clean_sheet_chance) + (0.60 * result_signal) - (0.55 * max(0.0, rival_attack - team_defense))
            matchup_ceiling = 0.15 * attacking_return_chance
        elif player.position == "Defensa":
            fixture_adjustment = (1.90 * clean_sheet_chance) + (0.45 * result_signal) - (0.35 * max(0.0, rival_attack - team_defense))
            matchup_ceiling = 0.45 * attacking_return_chance
        elif player.position == "Mediocampista":
            fixture_adjustment = (1.10 * result_signal) + (0.55 * clean_sheet_chance) - (0.20 * opponent_difficulty)
            matchup_ceiling = 1.35 * attacking_return_chance
        else:
            fixture_adjustment = (0.85 * result_signal) - (0.15 * opponent_difficulty)
            matchup_ceiling = 1.80 * attacking_return_chance

        return {
            "fixture_adjustment": fixture_adjustment,
            "matchup_ceiling": matchup_ceiling,
            "volatility": 0.08 + abs(opponent_difficulty) * 0.10 + team.get("injury_impact", 0.0) * 0.10,
        }

    @classmethod
    def from_saved_state(
        cls,
        state_path: str | Path,
        players_json_path: str | Path | None = None,
        max_rounds: int = 1,
    ) -> "FantasyLeagueModel":
        """Reconstruye el modelo a partir de un estado guardado previamente."""
        state = json.loads(Path(state_path).read_text(encoding="utf-8"))
        manager_configs = [
            {
                "name": manager_state["name"],
                "strategy": manager_state.get("strategy", "balanced"),
                "sport_strategy": manager_state.get("sport_strategy"),
                "economic_strategy": manager_state.get("economic_strategy"),
                "decision_engine": manager_state.get("decision_engine", "rules"),
                "llm_backend": manager_state.get("llm_backend", "ollama"),
                "llm_model": manager_state.get("llm_model"),
                "llm_base_url": manager_state.get("llm_base_url"),
                "llm_controls": manager_state.get("llm_controls", ["sale_candidates", "market_bid", "formation"]),
                "cash": manager_state["cash"],
                "current_points": manager_state["points_total"],
                "preferred_formation": manager_state.get("preferred_formation"),
                "squad_player_ids": manager_state["squad_player_ids"],
                "lineup_player_ids": manager_state.get("lineup_player_ids", []),
                "_cash_is_current": True,
            }
            for manager_state in state["managers"]
        ]
        dataset_path = Path(players_json_path or state["players_json_path"])
        return cls(
            players_json_path=dataset_path,
            manager_configs=manager_configs,
            start_round=int(state["current_round"]),
            max_rounds=max_rounds,
            seed=state.get("seed"),
            transfer_limit_per_round=int(state.get("transfer_limit_per_round", 1)),
            days_per_round=int(state.get("days_per_round", DEFAULT_MARKET_DAYS_PER_ROUND)),
            restored_state=state,
        )

    def _restore_state(self, state: dict[str, Any]) -> None:
        """Restaura plantillas, mercado e historial para continuar desde otra ejecuci?n."""
        self.current_round = int(state["current_round"])
        self.initial_config_round = int(state.get("initial_config_round", self.start_round))
        self.start_round = self.current_round
        self.end_round = self.current_round + self.max_rounds
        self.current_market_day = int(state.get("current_market_day", 0))
        self.owner_by_player_id = {int(player_id): owner for player_id, owner in state["owner_by_player_id"].items()}

        player_states = {int(player_state["player_id"]): player_state for player_state in state["players"]}
        for player in self.player_agents:
            payload = player_states.get(player.player_id)
            if payload is None:
                continue
            player.market_value = int(payload["market_value"])
            player.current_price = int(payload.get("current_price", player.market_value))
            player.current_points = float(payload.get("current_points", 0.0))
            player.expected_points = float(payload.get("expected_points", 0.0))
            player.expected_price_delta = float(payload.get("expected_price_delta", 0.0))

        managers_by_name = {manager.name: manager for manager in self.manager_agents}
        for manager_state in state["managers"]:
            manager = managers_by_name[manager_state["name"]]
            manager.sport_strategy, manager.economic_strategy = resolve_manager_strategies(manager_state)
            manager._refresh_strategy_label()
            manager.decision_engine = str(manager_state.get("decision_engine", manager.decision_engine) or "rules").strip().lower()
            manager.llm_backend = str(manager_state.get("llm_backend", manager.llm_backend) or "ollama").strip().lower()
            manager.llm_model = str(manager_state.get("llm_model") or manager.llm_model or "").strip() or None
            manager.llm_base_url = str(manager_state.get("llm_base_url") or manager.llm_base_url or "").strip() or None
            manager.llm_controls = list(manager_state.get("llm_controls", manager.llm_controls))
            manager.llm_engine = (
                LLMDecisionEngine(
                    manager_name=manager.name,
                    model_name=manager.llm_model,
                    controls=manager.llm_controls,
                    backend=manager.llm_backend,
                    base_url=manager.llm_base_url,
                )
                if manager.decision_engine == "llm" and not FORCE_RULES_DECISION_ENGINE
                else None
            )
            manager.cash = int(manager_state["cash"])
            manager.points_total = float(manager_state["points_total"])
            manager.points_round = float(manager_state.get("points_round", 0.0))
            manager.transfers_made = int(manager_state.get("transfers_made", 0))
            manager.transfer_history = list(manager_state.get("transfer_history", []))
            manager.bonus_history = list(manager_state.get("bonus_history", []))
            manager.lineup_history = list(manager_state.get("lineup_history", []))
            manager.llm_decision_history = list(manager_state.get("llm_decision_history", []))
            manager.current_formation = str(manager_state.get("current_formation", ""))
            manager.preferred_formation = manager_state.get("preferred_formation")
            manager.seed_cash_is_current = True
            manager.seed_squad_player_ids = list(manager_state["squad_player_ids"])
            manager.seed_lineup_player_ids = list(manager_state.get("lineup_player_ids", []))
            manager.squad = [self.players_by_id[player_id] for player_id in manager_state["squad_player_ids"]]
            manager.lineup = [self.players_by_id[player_id] for player_id in manager_state.get("lineup_player_ids", [])]
            lineup_ids = {player.player_id for player in manager.lineup}
            manager.bench = [player for player in manager.squad if player.player_id not in lineup_ids]

        market_state = state.get("market", {})
        self.market_agent.auction_history = list(market_state.get("auction_history", []))
        self.market_agent.bonus_history = list(market_state.get("bonus_history", []))
        self.market_agent.daily_history = list(market_state.get("daily_history", []))
        self.market_agent.last_round_market_days = list(market_state.get("last_round_market_days", []))
        self.market_agent.last_completed_sales = list(market_state.get("last_completed_sales", []))
        self.market_agent.last_bonus_total = int(market_state.get("last_bonus_total", 0))

        if state.get("random_state"):
            self.random_state.setstate(literal_eval(state["random_state"]))

    def export_state(self) -> dict[str, Any]:
        """Serializa el estado completo del modelo para reanudar en otra ejecuci?n."""
        return {
            "players_json_path": str(self.players_json_path),
            "seed": self.seed,
            "current_round": self.current_round,
            "current_market_day": self.current_market_day,
            "initial_config_round": self.initial_config_round,
            "transfer_limit_per_round": self.transfer_limit_per_round,
            "days_per_round": self.days_per_round,
            "random_state": repr(self.random_state.getstate()),
            "owner_by_player_id": self.owner_by_player_id,
            "players": [
                {
                    "player_id": player.player_id,
                    "market_value": player.market_value,
                    "current_price": player.current_price,
                    "current_points": player.current_points,
                    "expected_points": player.expected_points,
                    "expected_price_delta": player.expected_price_delta,
                }
                for player in self.player_agents
            ],
            "managers": [
                {
                    "name": manager.name,
                    "strategy": manager.strategy,
                    "sport_strategy": manager.sport_strategy,
                    "economic_strategy": manager.economic_strategy,
                    "decision_engine": manager.decision_engine,
                    "llm_backend": manager.llm_backend,
                    "llm_model": manager.llm_model,
                    "llm_base_url": manager.llm_base_url,
                    "llm_controls": manager.llm_controls,
                    "cash": manager.cash,
                    "points_total": manager.points_total,
                    "points_round": manager.points_round,
                    "current_formation": manager.current_formation,
                    "preferred_formation": manager.preferred_formation,
                    "transfers_made": manager.transfers_made,
                    "transfer_history": manager.transfer_history,
                    "bonus_history": manager.bonus_history,
                    "lineup_history": manager.lineup_history,
                    "llm_decision_history": manager.llm_decision_history,
                    "squad_player_ids": [player.player_id for player in manager.squad],
                    "lineup_player_ids": [player.player_id for player in manager.lineup],
                }
                for manager in self.manager_agents
            ],
            "market": {
                "auction_history": self.market_agent.auction_history,
                "bonus_history": self.market_agent.bonus_history,
                "daily_history": self.market_agent.daily_history,
                "last_round_market_days": self.market_agent.last_round_market_days,
                "last_completed_sales": self.market_agent.last_completed_sales,
                "last_bonus_total": self.market_agent.last_bonus_total,
            },
        }

    def save_state(self, path: str | Path) -> None:
        """Guarda en disco el estado serializado del modelo."""
        Path(path).write_text(json.dumps(self.export_state(), ensure_ascii=False, indent=2), encoding="utf-8")

    def _available_candidates(self, position: str) -> list[PlayerAgent]:
        """Devuelve jugadores libres de una posición concreta."""
        # Un jugador está libre si no aparece en owner_by_player_id.
        return [
            player
            for player in self.player_agents
            if player.position == position and player.player_id not in self.owner_by_player_id
        ]

    def _pick_for_manager(self, manager: ManagerAgent, position: str) -> PlayerAgent | None:
        """Elige el mejor fichaje posible para un manager durante el draft."""
        candidates = self._available_candidates(position)
        if not candidates:
            return None

        # Reservamos presupuesto mínimo para completar los huecos restantes.
        remaining_slots = sum(SQUAD_TEMPLATE.values()) - len(manager.squad) - 1
        minimum_reserve = remaining_slots * 300_000
        affordable = [
            player
            for player in candidates
            if player.market_value <= max(manager.cash - minimum_reserve, 0)
        ]
        if not affordable:
            affordable = [player for player in candidates if player.market_value <= manager.cash]
        if not affordable:
            return None

        for player in affordable:
            player.project_round(self.random_state, self.current_round)

        def draft_score(player: PlayerAgent) -> float:
            """Puntua candidatos de draft equilibrando rendimiento y liquidez."""
            # Penalizamos compras que dejen sin liquidez al manager.
            cost_penalty = player.market_value / max(manager.cash, 1)
            future_cash = manager.cash - player.market_value
            liquidity_ratio = safe_div(future_cash, max((remaining_slots + 1) * 4_000_000, 1), 0.0)
            return manager.player_score(player) - (1.75 * cost_penalty) + (0.20 * liquidity_ratio)

        return max(affordable, key=draft_score)

    def _initialize_squads(self) -> None:
        """Construye las plantillas iniciales de todos los managers."""
        preset_assigned = set()
        for manager in self.manager_agents:
            # Respetamos primero los jugadores que vengan ya fijados desde una liga real.
            for player_id in manager.seed_squad_player_ids:
                player = self.players_by_id.get(player_id)
                if player is None or player.player_id in preset_assigned:
                    continue
                manager.add_player(player, charge_budget=not manager.seed_cash_is_current)
                self.owner_by_player_id[player.player_id] = manager.unique_id
                preset_assigned.add(player.player_id)

        # El resto de la plantilla se completa con un draft automático por posiciones.
        draft_order = list(self.manager_agents)
        self.random_state.shuffle(draft_order)
        total_slots = sum(SQUAD_TEMPLATE.values())

        for position, needed in SQUAD_TEMPLATE.items():
            for _ in range(needed):
                for manager in draft_order:
                    position_count = Counter(player.position for player in manager.squad)
                    if position_count[position] >= SQUAD_TEMPLATE[position]:
                        continue
                    player = self._pick_for_manager(manager, position)
                    if player is None:
                        continue
                    if player.player_id in self.owner_by_player_id:
                        continue
                    manager.add_player(player)
                    self.owner_by_player_id[player.player_id] = manager.unique_id

        for manager in self.manager_agents:
            # Validación final para asegurar que todas las plantillas están completas.
            if len(manager.squad) < total_slots:
                raise RuntimeError(f"No se pudo completar la plantilla de {manager.name}")

    def available_players(self, position: str | None = None, excluded_manager: ManagerAgent | None = None) -> list[PlayerAgent]:
        """Lista de jugadores libres, opcionalmente filtrada por posición."""
        del excluded_manager
        # Esta función actúa como el "mercado libre" actual del sistema.
        return [
            player
            for player in self.player_agents
            if player.player_id not in self.owner_by_player_id and (position is None or player.position == position)
        ]

    def _effective_squad_size_for_market(self, manager: ManagerAgent) -> int:
        """Tamano efectivo de plantilla descontando ventas propias aun abiertas ese dia."""
        pending_sales = self.market_agent.pending_sale_slots(manager)
        return max(0, len(manager.squad) - pending_sales)

    def transfer_player(self, manager: ManagerAgent, outgoing: PlayerAgent, incoming: PlayerAgent) -> None:
        """Realiza una transferencia y actualiza la propiedad de los jugadores."""
        # Validamos que el manager sea el dueño del jugador saliente y que el entrante siga libre.
        owner = self.owner_by_player_id.get(outgoing.player_id)
        if owner != manager.unique_id:
            raise RuntimeError("Transferencia inválida: el jugador saliente no pertenece al manager")
        if incoming.player_id in self.owner_by_player_id:
            raise RuntimeError("Transferencia inválida: el jugador entrante ya tiene dueño")

        manager.remove_player(outgoing)
        del self.owner_by_player_id[outgoing.player_id]

        manager.add_player(incoming)
        self.owner_by_player_id[incoming.player_id] = manager.unique_id

    def purchase_player_from_market(self, manager: ManagerAgent, player: PlayerAgent, price: int) -> None:
        """Compra un jugador libre al mercado pagando el precio final de subasta."""
        if player.player_id in self.owner_by_player_id:
            raise RuntimeError("Compra inv?lida: el jugador ya tiene due?o")
        if self._effective_squad_size_for_market(manager) >= MAX_SQUAD_SIZE:
            raise RuntimeError("Compra inv?lida: la plantilla del manager ya est? completa")
        manager.add_player(player, purchase_price=price)
        manager.remaining_market_purchase_capacity = max(0, manager.remaining_market_purchase_capacity - 1)
        self.owner_by_player_id[player.player_id] = manager.unique_id
        manager.transfers_made += 1
        manager.transfer_history.append(
            {
                "round": self.current_round,
                "out": None,
                "in": player.name,
                "strategy": manager.strategy,
                "sport_strategy": manager.sport_strategy,
                "economic_strategy": manager.economic_strategy,
                "kind": "buy_from_market",
                "price": price,
            }
        )

    def transfer_player_between_managers(
        self,
        seller: ManagerAgent,
        buyer: ManagerAgent,
        player: PlayerAgent,
        price: int,
    ) -> None:
        """Ejecuta una venta entre managers a trav?s del mercado."""
        owner = self.owner_by_player_id.get(player.player_id)
        if owner != seller.unique_id:
            raise RuntimeError("Venta inv?lida: el jugador no pertenece al manager vendedor")
        if self._effective_squad_size_for_market(buyer) >= MAX_SQUAD_SIZE:
            raise RuntimeError("Compra inv?lida: la plantilla del manager comprador ya est? completa")

        seller.remove_player(player, sale_price=price)
        del self.owner_by_player_id[player.player_id]

        buyer.add_player(player, purchase_price=price)
        buyer.remaining_market_purchase_capacity = max(0, buyer.remaining_market_purchase_capacity - 1)
        self.owner_by_player_id[player.player_id] = buyer.unique_id
        seller.transfers_made += 1
        buyer.transfers_made += 1

        seller.transfer_history.append(
            {
                "round": self.current_round,
                "out": player.name,
                "in": None,
                "strategy": seller.strategy,
                "sport_strategy": seller.sport_strategy,
                "economic_strategy": seller.economic_strategy,
                "kind": "sale_to_manager",
                "price": price,
                "buyer": buyer.name,
            }
        )
        buyer.transfer_history.append(
            {
                "round": self.current_round,
                "out": None,
                "in": player.name,
                "strategy": buyer.strategy,
                "sport_strategy": buyer.sport_strategy,
                "economic_strategy": buyer.economic_strategy,
                "kind": "buy_from_manager",
                "price": price,
                "seller": seller.name,
            }
        )

    def sell_player_to_market(self, manager: ManagerAgent, player: PlayerAgent, price: int) -> None:
        """Vende un jugador al agente mercado y lo deja libre para futuras jornadas."""
        owner = self.owner_by_player_id.get(player.player_id)
        if owner != manager.unique_id:
            raise RuntimeError("Venta al mercado inválida: el jugador no pertenece al manager")

        manager.remove_player(player, sale_price=price)
        del self.owner_by_player_id[player.player_id]
        manager.transfers_made += 1
        manager.transfer_history.append(
            {
                "round": self.current_round,
                "out": player.name,
                "in": None,
                "strategy": manager.strategy,
                "sport_strategy": manager.sport_strategy,
                "economic_strategy": manager.economic_strategy,
                "kind": "sale_to_market",
                "price": price,
            }
        )

    def _record_round_lineups(self) -> None:
        """Guarda el once real y el banquillo con el que cada manager jugo la jornada."""
        for manager in self.manager_agents:
            manager.lineup_history.append(
                {
                    "round": self.current_round,
                    "sport_strategy": manager.sport_strategy,
                    "economic_strategy": manager.economic_strategy,
                    "formation": manager.current_formation,
                    "points_round": round(manager.points_round, 2),
                    "lineup": [
                        {
                            "player_id": player.player_id,
                            "player": player.name,
                            "position": player.position,
                        }
                        for player in manager.lineup
                    ],
                    "bench": [
                        {
                            "player_id": player.player_id,
                            "player": player.name,
                            "position": player.position,
                        }
                        for player in manager.bench
                    ],
                    "squad": [
                        {
                            "player_id": player.player_id,
                            "player": player.name,
                            "position": player.position,
                        }
                        for player in manager.squad
                    ],
                }
            )

    def step(self) -> None:
        """Simula una jornada completa para jugadores y managers."""
        if self.current_round >= self.end_round:
            self.running = False
            return

        # Cada ejecuci?n representa una jornada completa con varios d?as de mercado previos.
        self.current_market_day = 0
        self.market_agent.run_market_round(self.days_per_round)

        # Despu?s de cerrar el mercado semanal, simulamos el rendimiento deportivo de la jornada.
        for player in self.player_agents:
            player.project_round(self.random_state, self.current_round)

        # Los managers se procesan por orden de peor clasificaci?n actual a mejor.
        for manager in sorted(self.manager_agents, key=lambda agent: agent.points_total):
            manager.step()

        self._record_round_lineups()

        # Al cerrar la jornada, el mercado reparte premios econ?micos por rendimiento.
        self.current_market_day = self.days_per_round
        self.market_agent.distribute_round_bonuses()

        # Guardamos m?tricas agregadas y avanzamos a la jornada siguiente.
        self.datacollector.collect(self)
        self.current_round += 1
        self.current_market_day = 0
        if self.current_round >= self.end_round:
            self.running = False

    def run(self) -> None:
        """Avanza la simulación hasta completar todas las jornadas previstas."""
        while self.running:
            self.step()

    def get_leaderboard(self) -> list[dict[str, Any]]:
        """Genera la clasificación ordenada de los managers."""
        leaderboard = [
            {
                "name": manager.name,
                "strategy": manager.strategy,
                "sport_strategy": manager.sport_strategy,
                "economic_strategy": manager.economic_strategy,
                "points_total": round(manager.points_total, 2),
                "points_round": round(manager.points_round, 2),
                "cash": manager.cash,
                "squad_value": manager.squad_value,
                "formation": manager.current_formation,
                "transfers_made": manager.transfers_made,
            }
            for manager in self.manager_agents
        ]
        leaderboard.sort(key=lambda item: item["points_total"], reverse=True)
        return leaderboard

    def strategy_summary(self) -> dict[str, list[dict[str, Any]]]:
        """Agrupa resultados medios por estrategia deportiva, economica y combinada."""

        def summarize(grouped: dict[str, list[ManagerAgent]], field_name: str) -> list[dict[str, Any]]:
            """Convierte grupos de managers en filas agregadas ordenadas por puntos."""
            rows: list[dict[str, Any]] = []
            for key, managers in grouped.items():
                rows.append(
                    {
                        field_name: key,
                        "avg_points_total": round(mean(manager.points_total for manager in managers), 2),
                        "avg_cash": round(mean(manager.cash for manager in managers), 2),
                        "avg_transfers": round(mean(manager.transfers_made for manager in managers), 2),
                        "managers": [manager.name for manager in managers],
                    }
                )
            rows.sort(key=lambda item: item["avg_points_total"], reverse=True)
            return rows

        by_sport: dict[str, list[ManagerAgent]] = {}
        by_economic: dict[str, list[ManagerAgent]] = {}
        by_combo: dict[str, list[ManagerAgent]] = {}

        for manager in self.manager_agents:
            by_sport.setdefault(manager.sport_strategy, []).append(manager)
            by_economic.setdefault(manager.economic_strategy, []).append(manager)
            by_combo.setdefault(manager.strategy, []).append(manager)

        return {
            "by_sport_strategy": summarize(by_sport, "sport_strategy"),
            "by_economic_strategy": summarize(by_economic, "economic_strategy"),
            "by_combination": summarize(by_combo, "strategy"),
        }
