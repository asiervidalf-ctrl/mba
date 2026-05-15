# Guía de ejecución

Esta guía describe el proceso recomendado para ejecutar una prueba de la simulación Fantasy con managers LLM y visualizar sus resultados.

## 1. Preparación del entorno

Crear y activar un entorno virtual:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Instalar dependencias:

```powershell
pip install -r requirements.txt
```

Si se desea usar el modo LLM, instalar Ollama y descargar Mistral:

```powershell
ollama pull mistral
```

Comprobación básica:

```powershell
ollama run mistral:latest "Responde solo OK"
```

## 2. Archivos necesarios

El repositorio ya incluye los elementos necesarios para ejecutar la práctica:

- `data/players_dataset.json`: dataset procesado de jugadores.
- `config/managers.json`: configuración de managers.
- `model/`: modelo de simulación.
- `demo/`: visualización interactiva.
- `requirements.txt`: dependencias.

No se incluyen datos crudos del scraper ni salidas completas de simulación, ya que son artefactos generados.

## 3. Configuración de managers

Los managers se definen en:

```text
config/managers.json
```

Campos principales:

- `name`: nombre del manager.
- `sport_strategy`: estrategia deportiva.
- `economic_strategy`: estrategia económica.
- `decision_engine`: `llm` o `rules`.
- `llm_backend`: normalmente `ollama`.
- `llm_model`: normalmente `mistral:latest`.
- `cash` o `budget`: caja disponible o presupuesto base.
- `squad_player_ids`: plantilla inicial.
- `lineup_player_ids`: once inicial.
- `current_points`: puntos iniciales si se activa su lectura.

Si se ejecuta con `--managers 5`, se usan los primeros 5 managers del archivo.

## 4. Puntos iniciales

Los puntos de inicio se configuran en `personal_lineup.py`:

```python
DEFAULT_INITIAL_POINTS = 0
INITIAL_POINTS_BY_MANAGER: dict[str, int] = {}
USE_INITIAL_POINTS_FROM_MANAGER_CONFIG = False
```

Opciones habituales:

- Todos los managers comienzan con 0 puntos:

```python
DEFAULT_INITIAL_POINTS = 0
INITIAL_POINTS_BY_MANAGER = {}
```

- Un manager comienza con ventaja o desventaja:

```python
INITIAL_POINTS_BY_MANAGER = {"Manager 4": -80}
```

- Los puntos iniciales se leen desde `config/managers.json`:

```python
USE_INITIAL_POINTS_FROM_MANAGER_CONFIG = True
```

## 5. Parámetros de simulación

La entrada principal es:

```text
model/model_run_fantasy.py
```

Parámetros más relevantes:

- `--start-round`: jornada inicial.
- `--end-round`: última jornada incluida.
- `--rounds`: número de jornadas si no se usa `--end-round`.
- `--days-per-round`: días de mercado por jornada.
- `--managers`: número de managers.
- `--budget`: presupuesto base.
- `--seed`: semilla aleatoria para reproducibilidad.
- `--resume`: reanuda desde `data/simulation_results/current_state.json`.
- `--llm-log-level`: nivel de logs.

Ejemplo de ejecución entre las jornadas 33 y 38:

```powershell
python model\model_run_fantasy.py --start-round 33 --end-round 38 --managers 5
```

Ejemplo de ejecución corta de dos jornadas:

```powershell
python model\model_run_fantasy.py --start-round 30 --rounds 2 --managers 5
```

## 6. Variables del LLM

El comportamiento del LLM se ajusta con variables de entorno:

- `MBA_LLM_BACKEND`: backend. Por defecto, `ollama`.
- `MBA_LLM_MODEL`: modelo. Por defecto, `mistral:latest`.
- `MBA_LLM_TIMEOUT_SECONDS`: timeout por llamada.
- `MBA_OLLAMA_NUM_CTX`: tamaño de contexto.
- `MBA_OLLAMA_NUM_PREDICT`: máximo de tokens generados.
- `MBA_LLM_MARKET_DAYS_PER_ROUND`: días de mercado con consulta LLM.
- `MBA_LLM_LINEUP_START_ROUND`: jornada desde la que el LLM decide alineaciones.

Configuración recomendada para decisiones LLM todos los días de mercado:

```powershell
$env:MBA_LLM_TIMEOUT_SECONDS="180"
$env:MBA_LLM_MARKET_DAYS_PER_ROUND="7"
```

Configuración más rápida, con LLM solo en el primer día de mercado:

```powershell
$env:MBA_LLM_MARKET_DAYS_PER_ROUND="1"
```

## 7. Limpieza antes de una prueba

Para iniciar una prueba desde cero se debe borrar la carpeta de resultados generados:

```powershell
Remove-Item -Recurse -Force data\simulation_results
```

La carpeta se volverá a crear automáticamente al ejecutar la simulación.

## 8. Ejecución recomendada

Una ejecución completa puede realizarse con:

```powershell
$env:MBA_LLM_TIMEOUT_SECONDS="180"
$env:MBA_LLM_MARKET_DAYS_PER_ROUND="7"
python model\model_run_fantasy.py --start-round 33 --end-round 38 --managers 5
```

Durante la ejecución se muestran logs de consulta al LLM, tiempos de respuesta y validez del JSON recibido.

## 9. Resultados generados

La simulación genera `data/simulation_results/`. Los archivos más relevantes son:

- `current_state.json`: estado final.
- `leaderboard.json`: clasificación.
- `lineups_history.json`: plantillas y alineaciones.
- `market_days.json`: mercados diarios.
- `llm_decisions.json`: decisiones del LLM y validación.
- `llm_decisions_explained.md`: informe explicable en lenguaje natural.

Para generar el informe explicable:

```powershell
python explain_llm_decisions.py
```

Para actualizar la demo con los resultados más recientes:

```powershell
python build_interactive_demo.py
```

## 10. Visualización

La demo está en:

```text
demo/index.html
```

Se recomienda abrirla mediante un servidor local:

```powershell
python -m http.server 8090 --bind 127.0.0.1
```

URL:

```text
http://127.0.0.1:8090/demo/index.html
```

La visualización permite consultar clasificación, plantillas, onces, mercado, evolución de jugadores y decisiones LLM por jornada.

## 11. Comprobación rápida

Para revisar si hubo errores o fallbacks en las decisiones LLM:

```powershell
python -c "import json; d=json.load(open('data/simulation_results/llm_decisions.json',encoding='utf-8-sig')); logs=[x for m in d for x in m.get('llm_decision_history',[])]; print('logs',len(logs),'fallbacks',sum(1 for x in logs if x.get('fallback_used')),'errores',sum(1 for x in logs if (x.get('llm_request') or {}).get('error')))"
```

Una ejecución correcta debería tener:

```text
fallbacks = 0
errores = 0
```

## 12. Demo incluida

El repositorio incluye `demo/demo_data.js`, generado a partir de una ejecución previa. Esto permite revisar la visualización sin relanzar una simulación.
