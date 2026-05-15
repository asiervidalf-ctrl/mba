# Configuracion de managers

El archivo principal es `config/managers.json`.

Campos soportados por manager:

- `name`: nombre del manager.
- `sport_strategy`: una de `cracks`, `mejor_forma`, `arriesgado`, `grandes_clubes`, `equipos_pequenos`.
- `economic_strategy`: una de `fichar_a_toda_costa`, `balanceado`, `tacano`.
- `decision_engine`: `rules` o `llm`. Por defecto `rules`.
- `llm_backend`: `ollama` o `openai`. Si no indicas nada, el proyecto usa `ollama`.
- `llm_model`: opcional. Modelo a usar si `decision_engine` es `llm`.
- `llm_base_url`: opcional. URL base del servidor LLM local, por ejemplo `http://127.0.0.1:11434`.
- `llm_controls`: lista opcional entre `sale_candidates`, `market_bid`, `formation`.
- `strategy`: campo legacy opcional. Si lo usas, el cargador lo traduce automaticamente a las dos estrategias nuevas.
- `cash`: dinero restante actual del manager.
- `budget`: presupuesto inicial antes de comprar la plantilla.
- `current_points`: puntos con los que empieza la simulacion si `USE_INITIAL_POINTS_FROM_MANAGER_CONFIG = True` en `personal_lineup.py`.
- `preferred_formation`: formacion preferida para la primera jornada si es valida.
- `squad_player_ids`: jugadores que ya pertenecen al manager al iniciar. Puedes poner IDs o nombres.
- `lineup_player_ids`: titulares para la primera jornada. Puedes poner IDs o nombres.

Notas:

- Las estrategias no son reglas rigidas; actuan como pesos y umbrales flexibles en la valoracion deportiva y en la agresividad de mercado.
- Si activas `decision_engine: "llm"` con `llm_backend: "ollama"`, no necesitas API key.
- El modelo local recomendado es `mistral:latest`; si falta, instalalo con `ollama pull mistral`.
- Si activas `decision_engine: "llm"` con `llm_backend: "openai"`, entonces si necesitas `OPENAI_API_KEY`.
- Si falta el backend o el modelo no responde, el manager vuelve automaticamente al motor actual basado en reglas.
- `llm_controls` te permite contener el coste. Por ejemplo, puedes usar solo `["market_bid"]` para delegar unicamente las pujas.
- Las decisiones de mercado con LLM se toman por dia de mercado sobre el mercado abierto completo: jugadores de la liga, ventas de otros managers y posibles ventas propias.
- Las trazas se escriben en `data/simulation_results/llm_decisions.json` y los logs aparecen en consola al ejecutar el runner.
- El maximo de plantilla permitido durante la simulacion es de 22 jugadores.
- Si usas `cash`, el modelo entiende que ese dinero ya es el saldo restante y no vuelve a descontar el coste de `squad_player_ids`.
- Si usas `budget` con `squad_player_ids`, el modelo descuenta el coste de esos jugadores al crear la plantilla.
- Si `lineup_player_ids` no es valida, el modelo cae automaticamente a `preferred_formation` o a la mejor alineacion calculada.
- Si dejas `squad_player_ids` vacio, el modelo completara la plantilla mediante el draft inicial.
- Si usas nombres de jugadores, deben coincidir con el `name` del dataset.
- Si un nombre existe en varios equipos, el cargador marcara error por ambigüedad.

- Por defecto, las simulaciones nuevas arrancan con todos los managers a 0 puntos. Para dar ventaja o desventaja inicial, edita `DEFAULT_INITIAL_POINTS`, `INITIAL_POINTS_BY_MANAGER` o `USE_INITIAL_POINTS_FROM_MANAGER_CONFIG` en `personal_lineup.py`.
- La puntuacion de una jornada suma solo los puntos del jugador en esa jornada. Si el dataset trae `points_history` para esa ronda, se usa ese valor exacto; si no, el modelo usa una proyeccion simulada para la jornada.

- Para una ejecucion rapida sin consultar al LLM, define `MBA_FORCE_RULES=1`. Esto respeta estrategias, mercado y restricciones, pero usa el motor determinista aunque el manager este configurado como `llm`.
- Para Ollama/Mistral el contexto LLM se envia en formato ultracompacto. Por defecto se usa `MBA_OLLAMA_NUM_CTX=2048`, `MBA_OLLAMA_NUM_PREDICT=700`, `MBA_LLM_TIMEOUT_SECONDS=120`, JSON Schema activo y los 7 dias de mercado usan LLM (`MBA_LLM_MARKET_DAYS_PER_ROUND=7`).
- En el dia 1 de mercado, Mistral recibe hasta 2 jugadores abiertos y hasta 2 ventas propias candidatas, con precio, puntuacion, forma, posicion, club y valoracion breve. En los dias 2 a 7 recibe una decision ligera: hasta 1 jugador abierto, hasta 1 venta propia candidata, 1 venta maxima y 1 puja maxima.
- Si quieres volver al modo mas rapido y ya probado, define `MBA_LLM_MARKET_DAYS_PER_ROUND=1`; asi solo decide mercado el dia 1 y la alineacion al final de la jornada.

Ejecucion:

```powershell
.\mba\Scripts\python.exe model\model_run_fantasy.py
```

Tambien puedes apuntar a otro archivo:

```powershell
.\mba\Scripts\python.exe model\model_run_fantasy.py --manager-config config/managers.example.json
```
