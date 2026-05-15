"""Wrapper compatible para los lanzadores de simulacion.

Los scripts `nueva_simulacion.py` y `siguiente_jornada.py` importan desde aqui,
asi que reexportamos las funciones publicas del modulo organizado.
"""

from scripts.simulation.simulation_launcher import (
    clear_previous_simulation_outputs,
    main,
    resolve_python_executable,
    run_model,
    run_new_simulation,
    run_next_round,
)


if __name__ == "__main__":
    raise SystemExit(main())
