from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd

CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

import personal_lineup
from model_fantasy import DEFAULT_MARKET_DAYS_PER_ROUND, FantasyLeagueModel, ManagerAgent

DEFAULT_DATASET = ROOT_DIR / "data" / "players_dataset.json"
OUTPUT_DIR = ROOT_DIR / "data" / "simulation_results"
MARKET_DAYS_DIR = OUTPUT_DIR / "market_days"
DEFAULT_MANAGER_CONFIG = ROOT_DIR / "config" / "managers.json"
DEFAULT_STATE_FILE = OUTPUT_DIR / "current_state.json"


def _merge_csv_history(
    path: Path,
    current_df: pd.DataFrame,
    *,
    dedupe_keys: list[str],
    sort_keys: list[str],
) -> None:
    """Fusiona el export actual con el histórico previo sin duplicar rondas."""
    if path.exists():
        previous_df = pd.read_csv(path)
        current_df = pd.concat([previous_df, current_df], ignore_index=True)
        current_df = current_df.drop_duplicates(subset=dedupe_keys, keep="last")

    current_df = current_df.sort_values(sort_keys).reset_index(drop=True)
    current_df.to_csv(path, index=False)


def parse_args() -> argparse.Namespace:
    """Define los parámetros de entrada de la simulación."""
    parser = argparse.ArgumentParser(description="Simula una liga fantasy basada en agentes.")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--start-round", type=int, default=30)
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--end-round", type=int, default=None, help="Ultima jornada incluida; sobrescribe --rounds.")
    parser.add_argument("--days-per-round", type=int, default=DEFAULT_MARKET_DAYS_PER_ROUND)
    parser.add_argument("--managers", type=int, default=6)
    parser.add_argument("--budget", type=int, default=180_000_000)
    # parser.add_argument("--seed", type=int, default=42)  # Descomenta esta variante si quieres experimentos reproducibles.
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--use-real-league", action="store_true")
    parser.add_argument("--manager-config", default=str(DEFAULT_MANAGER_CONFIG))
    parser.add_argument("--state-file", default=str(DEFAULT_STATE_FILE))
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--llm-log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser.parse_args()


def save_results(model: FantasyLeagueModel, state_path: Path) -> None:
    """Guarda en disco el resumen, el mercado diario y el estado actualizado."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    MARKET_DAYS_DIR.mkdir(parents=True, exist_ok=True)

    leaderboard_path = OUTPUT_DIR / "leaderboard.json"
    strategy_path = OUTPUT_DIR / "strategy_summary.json"
    market_auctions_path = OUTPUT_DIR / "market_auctions.json"
    market_bonuses_path = OUTPUT_DIR / "market_bonuses.json"
    market_days_path = OUTPUT_DIR / "market_days.json"
    lineups_history_path = OUTPUT_DIR / "lineups_history.json"
    llm_decisions_path = OUTPUT_DIR / "llm_decisions.json"
    rounds_path = OUTPUT_DIR / "rounds.csv"
    agents_path = OUTPUT_DIR / "agents.csv"

    leaderboard_path.write_text(json.dumps(model.get_leaderboard(), ensure_ascii=False, indent=2), encoding="utf-8")
    strategy_path.write_text(json.dumps(model.strategy_summary(), ensure_ascii=False, indent=2), encoding="utf-8")
    market_auctions_path.write_text(json.dumps(model.market_agent.auction_history, ensure_ascii=False, indent=2), encoding="utf-8")
    market_bonuses_path.write_text(json.dumps(model.market_agent.bonus_history, ensure_ascii=False, indent=2), encoding="utf-8")
    market_days_path.write_text(json.dumps(model.market_agent.daily_history, ensure_ascii=False, indent=2), encoding="utf-8")
    lineups_history_path.write_text(
        json.dumps(
            [
                {
                    "name": manager.name,
                    "strategy": manager.strategy,
                    "sport_strategy": manager.sport_strategy,
                    "economic_strategy": manager.economic_strategy,
                    "lineup_history": manager.lineup_history,
                }
                for manager in model.manager_agents
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    llm_decisions_path.write_text(
        json.dumps(
            [
                {
                    "name": manager.name,
                    "strategy": manager.strategy,
                    "sport_strategy": manager.sport_strategy,
                    "economic_strategy": manager.economic_strategy,
                    "llm_decision_history": manager.llm_decision_history,
                }
                for manager in model.manager_agents
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    completed_round = model.current_round - 1
    round_market_path = MARKET_DAYS_DIR / f"round_{completed_round:03d}.json"
    round_market_path.write_text(
        json.dumps(model.market_agent.last_round_market_days, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    rounds_df = model.datacollector.get_model_vars_dataframe().reset_index(drop=True)
    if not rounds_df.empty:
        _merge_csv_history(
            rounds_path,
            rounds_df,
            dedupe_keys=["round"],
            sort_keys=["round"],
        )

    agents_df = model.datacollector.get_agenttype_vars_dataframe(ManagerAgent).reset_index()
    if not agents_df.empty:
        agents_df = agents_df.rename(columns={"Step": "step", "AgentID": "agent_id"})
        agents_df["step"] = agents_df["step"].astype(int)
        agents_df["agent_id"] = agents_df["agent_id"].astype(int)
        agents_df["round"] = agents_df["step"].apply(lambda step: model.start_round + step - 1)
        agents_df = agents_df[
            [
                "round",
                "step",
                "agent_id",
                "name",
                "strategy",
                "sport_strategy",
                "economic_strategy",
                "points_total",
                "points_round",
                "cash",
                "squad_value",
                "formation",
                "transfers_made",
            ]
        ]
        _merge_csv_history(
            agents_path,
            agents_df,
            dedupe_keys=["round", "agent_id"],
            sort_keys=["round", "agent_id"],
        )

    model.save_state(state_path)


def build_model_from_args(args: argparse.Namespace, dataset_path: Path, state_path: Path) -> FantasyLeagueModel:
    """Crea un modelo nuevo o reanuda uno ya guardado."""
    rounds = args.rounds
    if args.end_round is not None:
        base_round = args.start_round
        if args.resume and state_path.exists():
            state_data = json.loads(state_path.read_text(encoding="utf-8-sig"))
            base_round = int(state_data.get("current_round", base_round))
        rounds = max(0, int(args.end_round) - int(base_round) + 1)

    if args.resume and state_path.exists():
        return FantasyLeagueModel.from_saved_state(
            state_path=state_path,
            players_json_path=dataset_path,
            max_rounds=rounds,
        )

    players, manager_configs = personal_lineup.load_manager_configs(
        dataset_path=dataset_path,
        num_managers=args.managers,
        budget=args.budget,
        seed=args.seed,
        use_real_league=args.use_real_league,
        manager_config_path=args.manager_config,
    )
    del players

    return FantasyLeagueModel(
        players_json_path=dataset_path,
        manager_configs=manager_configs,
        start_round=args.start_round,
        max_rounds=rounds,
        seed=args.seed,
        days_per_round=args.days_per_round,
    )


def main() -> None:
    """Carga los datos, ejecuta una o varias jornadas y guarda el nuevo estado."""
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.llm_log_level),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    dataset_path = Path(args.dataset)
    state_path = Path(args.state_file)

    model = build_model_from_args(args, dataset_path, state_path)
    model.run()
    save_results(model, state_path)

    executed_until_round = model.current_round - 1
    print(f"Estado guardado. Última jornada simulada: {executed_until_round}")
    print(f"Próxima jornada disponible para reanudar: {model.current_round}")
    print(f"Archivo de estado: {state_path}")
    print(f"Logs de decisiones LLM: {OUTPUT_DIR / 'llm_decisions.json'}")
    print(f"Dias de mercado por jornada: {model.days_per_round}")

    print("\nClasificación actual")
    for index, row in enumerate(model.get_leaderboard(), start=1):
        print(
            f"{index}. {row['name']} | deportiva={row['sport_strategy']} | "
            f"economica={row['economic_strategy']} | "
            f"puntos={row['points_total']} | caja={row['cash']} | "
            f"valor_plantilla={row['squad_value']} | transfers={row['transfers_made']}"
        )


if __name__ == "__main__":
    main()
