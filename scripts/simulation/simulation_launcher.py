from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# El modulo vive en scripts/simulation; parents[2] apunta a la raiz real del proyecto.
ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_VENV_PYTHON = ROOT_DIR / "mba" / "Scripts" / "python.exe"
RUNNER = ROOT_DIR / "model" / "model_run_fantasy.py"
STATE_FILE = ROOT_DIR / "data" / "simulation_results" / "current_state.json"
OUTPUT_DIR = ROOT_DIR / "data" / "simulation_results"


def resolve_python_executable() -> Path:
    """Usa el Python del entorno virtual del proyecto si existe."""
    if DEFAULT_VENV_PYTHON.exists():
        current = Path(sys.executable).resolve()
        target = DEFAULT_VENV_PYTHON.resolve()
        if current != target:
            return target
    return Path(sys.executable).resolve()


def run_model(extra_args: list[str]) -> int:
    """Ejecuta el runner principal de la simulación."""
    python_executable = resolve_python_executable()
    command = [str(python_executable), str(RUNNER), *extra_args]
    completed = subprocess.run(command, cwd=ROOT_DIR)
    return int(completed.returncode)


def clear_previous_simulation_outputs() -> None:
    """Elimina todos los artefactos generados por simulaciones anteriores."""
    if not OUTPUT_DIR.exists():
        return

    for path in OUTPUT_DIR.iterdir():
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()


def run_new_simulation() -> int:
    """Borra el estado previo y arranca una simulación nueva."""
    clear_previous_simulation_outputs()
    print("Iniciando una simulacion nueva desde cero...", flush=True)
    return run_model([])


def run_next_round() -> int:
    """Avanza una jornada reanudando desde el último estado si existe."""
    if STATE_FILE.exists():
        print("Reanudando simulacion desde el ultimo estado guardado...", flush=True)
        return run_model(["--resume"])

    print("No existe estado previo. Arrancando una simulacion nueva...", flush=True)
    return run_model([])


def parse_args() -> argparse.Namespace:
    """Lee el modo del lanzador cuando se ejecuta este modulo directamente."""
    parser = argparse.ArgumentParser(description="Lanzador sencillo de la simulacion fantasy.")
    parser.add_argument(
        "mode",
        choices=["nueva", "siguiente"],
        help="nueva reinicia la simulacion; siguiente avanza una jornada desde el estado guardado.",
    )
    return parser.parse_args()


def main() -> int:
    """Selecciona entre simulacion nueva o reanudacion segun el argumento CLI."""
    args = parse_args()
    if args.mode == "nueva":
        return run_new_simulation()
    return run_next_round()


if __name__ == "__main__":
    raise SystemExit(main())
