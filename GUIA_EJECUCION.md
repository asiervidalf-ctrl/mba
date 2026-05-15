# Guía de ejecución de pruebas

Este documento resume el proceso recomendado para ejecutar una prueba de la simulación Fantasy con managers LLM. La idea es preparar la configuración, lanzar la simulación, generar los informes explicables y abrir la demo interactiva.

## 1. Requisitos previos

Antes de ejecutar una prueba, conviene comprobar que existen estos elementos:

- Entorno Python del proyecto: `mba`.
- Dataset de jugadores: `data/players_dataset.json`.
- Configuración de managers: `config/managers.json`.
- Ollama instalado y ejecutándose si se usan managers LLM.
- Modelo local disponible, normalmente `mistral:latest`.

Para preparar Mistral en Ollama:

```powershell
ollama pull mistral
```

Para comprobar que Ollama responde:

```powershell
ollama run mistral:latest "Responde solo OK"
```

## 2. Configurar los managers

El archivo principal es:

```text
config/managers.json
```

Cada manager puede tener:

- `name`: nombre del manager.
- `sport_strategy`: estrategia deportiva, por ejemplo `cracks`, `mejor_forma`, `grandes_clubes`, `equipos_pequenos` o `arriesgado`.
- `economic_strategy`: estrategia económica, por ejemplo `balanceado`, `tacano` o `fichar_a_toda_costa`.
- `decision_engine`: `llm` para usar Mistral/Ollama o `rules` para usar reglas deterministas.
- `llm_backend`: normalmente `ollama`.
- `llm_model`: normalmente `mistral:latest`.
- `llm_controls`: controles delegados al LLM. En el estado actual se usan decisiones de mercado y alineación.
- `cash` o `budget`: dinero disponible o presupuesto inicial.
- `squad_player_ids`: plantilla inicial, con IDs o nombres.
- `lineup_player_ids`: once inicial, con IDs o nombres.
- `current_points`: puntos iniciales si se activa su uso desde configuración.

Si se lanza la simulación con `--managers 5`, solo se usan los primeros 5 managers del archivo.

## 3. Configurar puntos iniciales

Los puntos iniciales se controlan en:

```text
personal_lineup.py
```

Valores importantes:

```python
DEFAULT_INITIAL_POINTS = 0
INITIAL_POINTS_BY_MANAGER: dict[str, int] = {}
USE_INITIAL_POINTS_FROM_MANAGER_CONFIG = False
```

Opciones habituales:

- Todos empiezan a 0:

```python
DEFAULT_INITIAL_POINTS = 0
INITIAL_POINTS_BY_MANAGER = {}
USE_INITIAL_POINTS_FROM_MANAGER_CONFIG = False
```

- Un manager empieza en desventaja:

```python
DEFAULT_INITIAL_POINTS = 0
INITIAL_POINTS_BY_MANAGER = {"Manager 4": -80}
USE_INITIAL_POINTS_FROM_MANAGER_CONFIG = False
```

- Usar los `current_points` escritos en `config/managers.json`:

```python
USE_INITIAL_POINTS_FROM_MANAGER_CONFIG = True
```

## 4. Configurar jornadas

La simulación se lanza desde:

```text
model/model_run_fantasy.py
```

Parámetros principales:

- `--start-round`: jornada inicial.
- `--end-round`: última jornada incluida.
- `--rounds`: número de jornadas a ejecutar si no se usa `--end-round`.
- `--days-per-round`: días de mercado por jornada. Por defecto son 7.
- `--managers`: número de managers.
- `--budget`: presupuesto base.
- `--seed`: semilla aleatoria. Si se indica, ayuda a reproducir pruebas.
- `--resume`: reanuda desde `data/simulation_results/current_state.json`.
- `--manager-config`: permite usar otro archivo de managers.
- `--state-file`: permite usar otro archivo de estado.
- `--llm-log-level`: nivel de logs en consola: `DEBUG`, `INFO`, `WARNING` o `ERROR`.

Ejemplo para ejecutar de la jornada 33 a la 38 con 5 managers:

```powershell
.\mba\Scripts\python.exe model\model_run_fantasy.py --start-round 33 --end-round 38 --managers 5
```

Ejemplo para ejecutar solo dos jornadas desde la jornada 30:

```powershell
.\mba\Scripts\python.exe model\model_run_fantasy.py --start-round 30 --rounds 2 --managers 5
```

## 5. Configurar comportamiento del LLM

El proyecto usa variables de entorno para ajustar Ollama/Mistral sin tocar código.

Variables principales:

- `MBA_LLM_BACKEND`: backend LLM. Por defecto `ollama`.
- `MBA_LLM_MODEL`: modelo LLM. Por defecto `mistral:latest`.
- `MBA_OLLAMA_BASE_URL`: URL de Ollama. Por defecto `http://127.0.0.1:11434`.
- `MBA_LLM_TIMEOUT_SECONDS`: timeout de cada llamada. Por defecto `120`.
- `MBA_OLLAMA_NUM_CTX`: ventana de contexto. Por defecto `2048`.
- `MBA_OLLAMA_NUM_PREDICT`: máximo de tokens generados. Por defecto `700`.
- `MBA_OLLAMA_USE_JSON_SCHEMA`: activa schema JSON. Por defecto `1`.
- `MBA_LLM_LOG_PROMPTS`: si vale `1`, guarda/expone prompts con más detalle.
- `MBA_LLM_MARKET_DAYS_PER_ROUND`: cuántos días de mercado consulta al LLM.
- `MBA_LLM_LINEUP_START_ROUND`: desde qué jornada se consulta al LLM para alineaciones.

Modo actual recomendado, con decisiones de mercado todos los días:

```powershell
$env:MBA_LLM_MARKET_DAYS_PER_ROUND="7"
$env:MBA_LLM_TIMEOUT_SECONDS="180"
```

Modo rápido y más barato, con LLM solo el día 1 de mercado:

```powershell
$env:MBA_LLM_MARKET_DAYS_PER_ROUND="1"
```

Forzar ejecución sin LLM, usando reglas deterministas:

```powershell
$env:MBA_FORCE_RULES="1"
```

## 6. Limpiar resultados anteriores

Si se quiere una prueba desde cero, hay que eliminar el contenido de:

```text
data/simulation_results/
```

No borres la carpeta, solo sus archivos internos. Desde PowerShell:

```powershell
Get-ChildItem .\data\simulation_results -Force | Remove-Item -Recurse -Force
```

Esto evita mezclar resultados nuevos con ejecuciones antiguas.

## 7. Ejecutar la simulación

Una ejecución completa recomendada podría ser:

```powershell
$env:MBA_LLM_TIMEOUT_SECONDS="180"
$env:MBA_LLM_MARKET_DAYS_PER_ROUND="7"
.\mba\Scripts\python.exe model\model_run_fantasy.py --start-round 33 --end-round 38 --managers 5
```

Durante la ejecución se imprimen logs de Mistral/Ollama indicando:

- Manager consultado.
- Tipo de payload.
- Tiempo de respuesta.
- Si el JSON fue válido.

Si aparecen errores, timeouts o fallbacks, quedarán reflejados después en `llm_decisions.json`.

## 8. Outputs generados

La simulación escribe los resultados en:

```text
data/simulation_results/
```

Archivos principales:

- `current_state.json`: estado completo final de la liga.
- `leaderboard.json`: clasificación final.
- `agents.csv`: evolución por manager y jornada.
- `rounds.csv`: resumen por jornada.
- `lineups_history.json`: alineaciones, banquillos y plantillas por jornada.
- `market_days.json`: mercados diarios, ventas, compras y pujas.
- `market_auctions.json`: historial de subastas.
- `market_bonuses.json`: bonus económicos por jornada.
- `strategy_summary.json`: resumen de estrategias.
- `llm_decisions.json`: decisiones LLM, prompts, payloads, respuestas, parseo y decisión final aplicada.
- `llm_decisions_explained.md`: explicación en lenguaje natural de las decisiones LLM.

## 9. Generar explicabilidad y demo

Después de ejecutar una simulación, genera el informe explicable:

```powershell
.\mba\Scripts\python.exe explain_llm_decisions.py
```

Y actualiza los datos embebidos de la demo:

```powershell
.\mba\Scripts\python.exe build_interactive_demo.py
```

Esto actualiza:

```text
data/simulation_results/llm_decisions_explained.md
demo/demo_data.js
```

## 10. Abrir la demo interactiva

Para abrir la demo, levanta un servidor local desde la raíz del proyecto:

```powershell
.\mba\Scripts\python.exe -m http.server 8090 --bind 127.0.0.1
```

Después abre en el navegador:

```text
http://127.0.0.1:8090/demo/index.html
```

La demo permite consultar:

- Clasificación y puntos acumulados.
- Estrategias de cada manager.
- Evolución de plantilla y once sobre campo de fútbol.
- Mercados diarios.
- Valor y puntos de jugadores.
- Decisiones LLM por jornada, con resumen, factores, riesgos, traza, propuesta original y decisión final aplicada.

## 11. Diagnóstico rápido tras una prueba

Para comprobar si hubo fallbacks o respuestas no parseables:

```powershell
.\mba\Scripts\python.exe -c "import json; d=json.load(open('data/simulation_results/llm_decisions.json',encoding='utf-8-sig')); logs=[x for m in d for x in m.get('llm_decision_history',[])]; print('logs',len(logs),'parsed',sum(1 for x in logs if (x.get('llm_request') or {}).get('parsed_output')),'fallback',sum(1 for x in logs if x.get('fallback_used')),'errors',sum(1 for x in logs if (x.get('llm_request') or {}).get('error')))"
```

El objetivo de una ejecución limpia es:

```text
fallback = 0
errors = 0
```

## 12. Reanudar una simulación

Si ya existe `current_state.json`, se puede continuar desde la siguiente jornada con:

```powershell
.\mba\Scripts\python.exe model\model_run_fantasy.py --resume --end-round 38 --managers 5
```

En modo `--resume`, el modelo toma la jornada actual desde el estado guardado. Si el estado dice que la próxima jornada es la 36 y se indica `--end-round 38`, ejecutará 36, 37 y 38.

## 13. Recomendaciones de entrega

Para una prueba final entregable:

1. Configura managers en `config/managers.json`.
2. Ajusta puntos iniciales en `personal_lineup.py` si hace falta.
3. Limpia `data/simulation_results/`.
4. Ejecuta la simulación con `--start-round`, `--end-round` y `--managers`.
5. Genera `llm_decisions_explained.md`.
6. Genera `demo/demo_data.js`.
7. Abre la demo con servidor local.
8. Comprueba que `llm_decisions.json` no tiene fallbacks ni errores.

