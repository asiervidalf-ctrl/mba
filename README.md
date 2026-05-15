# Simulación Fantasy con managers LLM

Este repositorio contiene una práctica de simulación basada en agentes para una liga Fantasy de fútbol. Cada manager dispone de plantilla, presupuesto, estrategia deportiva, estrategia económica y capacidad de tomar decisiones de mercado y alineación. El proyecto incorpora un LLM local mediante Ollama/Mistral para delegar parte de esas decisiones y registrar su razonamiento de forma explicable.

El objetivo de los managers es maximizar la puntuación acumulada entre las jornadas configuradas de la simulación, normalmente desde la jornada 30 o 33 hasta la jornada 38.

## Contenido del repositorio

```text
.
├── config/
│   ├── managers.json
│   ├── managers.example.json
│   └── README.md
├── data/
│   └── players_dataset.json
├── demo/
│   ├── index.html
│   ├── app.js
│   ├── styles.css
│   └── demo_data.js
├── model/
│   ├── llm_strategy.py
│   ├── market_agent.py
│   ├── model_fantasy.py
│   └── model_run_fantasy.py
├── scripts/
│   ├── reporting/
│   └── simulation/
├── GUIA_EJECUCION.md
├── personal_lineup.py
├── requirements.txt
└── README.md
```

El repositorio no incluye el scraper, datos crudos, entornos virtuales ni salidas completas de simulaciones. Solo se incluyen los archivos necesarios para ejecutar y visualizar la práctica.

## Requisitos

- Python 3.10 o superior.
- PowerShell o terminal equivalente.
- Dependencias de `requirements.txt`.
- Ollama instalado para usar el modo LLM.
- Modelo recomendado: `mistral:latest`.

Instalación recomendada:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
ollama pull mistral
```

## Ejecución básica

La simulación se lanza desde `model/model_run_fantasy.py`.

Ejemplo de ejecución desde la jornada 33 hasta la 38 con 5 managers:

```powershell
$env:MBA_LLM_TIMEOUT_SECONDS="180"
$env:MBA_LLM_MARKET_DAYS_PER_ROUND="7"
python model\model_run_fantasy.py --start-round 33 --end-round 38 --managers 5
```

Parámetros principales:

- `--start-round`: jornada inicial.
- `--end-round`: última jornada incluida.
- `--rounds`: número de jornadas si no se indica `--end-round`.
- `--days-per-round`: días de mercado por jornada. Por defecto son 7.
- `--managers`: número de managers usados desde `config/managers.json`.
- `--budget`: presupuesto inicial base.
- `--seed`: semilla para pruebas reproducibles.
- `--resume`: reanuda desde `data/simulation_results/current_state.json`.

## Managers y estrategias

La configuración principal está en:

```text
config/managers.json
```

Cada manager puede definir:

- Estrategia deportiva: `cracks`, `mejor_forma`, `grandes_clubes`, `equipos_pequenos` o `arriesgado`.
- Estrategia económica: `balanceado`, `tacano` o `fichar_a_toda_costa`.
- Motor de decisión: `llm` o `rules`.
- Presupuesto, caja, plantilla inicial y alineación inicial.
- Backend LLM, modelo y controles delegados.

El archivo `personal_lineup.py` normaliza esa configuración, resuelve jugadores por ID o nombre y permite modificar los puntos iniciales.

## Puntos iniciales

Los puntos iniciales se ajustan en `personal_lineup.py`:

```python
DEFAULT_INITIAL_POINTS = 0
INITIAL_POINTS_BY_MANAGER: dict[str, int] = {}
USE_INITIAL_POINTS_FROM_MANAGER_CONFIG = False
```

Ejemplo para iniciar a un manager con desventaja:

```python
INITIAL_POINTS_BY_MANAGER = {"Manager 4": -80}
```

También puede activarse `USE_INITIAL_POINTS_FROM_MANAGER_CONFIG = True` para leer el campo `current_points` desde `config/managers.json`.

## Uso del LLM

El proyecto está preparado para Ollama con `mistral:latest`. Las variables de entorno más relevantes son:

- `MBA_LLM_BACKEND`: backend LLM. Por defecto, `ollama`.
- `MBA_LLM_MODEL`: modelo usado. Por defecto, `mistral:latest`.
- `MBA_LLM_TIMEOUT_SECONDS`: tiempo máximo por llamada.
- `MBA_OLLAMA_NUM_CTX`: ventana de contexto.
- `MBA_OLLAMA_NUM_PREDICT`: máximo de tokens generados.
- `MBA_LLM_MARKET_DAYS_PER_ROUND`: días de mercado en los que decide el LLM.
- `MBA_LLM_LINEUP_START_ROUND`: jornada desde la que el LLM decide alineaciones.

En el modo actual, el LLM puede decidir todos los días de mercado. El día 1 recibe un contexto algo más amplio; los días intermedios reciben un contexto ligero para reducir errores de parseo y tiempos de ejecución.

Las respuestas del LLM se validan antes de aplicarse. Si una respuesta no es válida, el simulador puede usar una decisión determinista de respaldo y dejarlo registrado.

## Outputs generados

Al ejecutar una simulación se crea `data/simulation_results/`, que no se incluye en el repositorio por ser salida generada. Los archivos principales son:

- `current_state.json`: estado completo de la liga.
- `leaderboard.json`: clasificación.
- `lineups_history.json`: plantillas y alineaciones.
- `market_days.json`: mercados diarios y operaciones.
- `llm_decisions.json`: decisiones del LLM, contexto, salida cruda, parseo y decisión final.
- `llm_decisions_explained.md`: explicación en lenguaje natural.

Para generar el informe explicable:

```powershell
python explain_llm_decisions.py
```

Para actualizar los datos de la demo después de una nueva simulación:

```powershell
python build_interactive_demo.py
```

## Demo interactiva

La carpeta `demo/` contiene una visualización HTML/CSS/JavaScript. El archivo `demo/demo_data.js` incluye datos embebidos de una ejecución ya realizada, por lo que la demo puede consultarse sin relanzar la simulación.

Para abrirla de forma local:

```powershell
python -m http.server 8090 --bind 127.0.0.1
```

Después abrir:

```text
http://127.0.0.1:8090/demo/index.html
```

La demo permite consultar:

- Clasificación final.
- Estrategias de los managers.
- Evolución de plantillas y onces sobre un campo de fútbol.
- Mercados diarios.
- Evolución de valor y puntos de jugadores.
- Decisiones LLM por jornada, con resumen, factores, riesgos, traza, propuesta original y decisión final aplicada.

## Archivos principales

- `model/model_fantasy.py`: núcleo de la simulación.
- `model/market_agent.py`: mercado diario, ventas, compras, pujas y bonus.
- `model/llm_strategy.py`: comunicación con Ollama/OpenAI, prompts, parseo y logs.
- `model/model_run_fantasy.py`: entrada por línea de comandos.
- `personal_lineup.py`: carga de managers, plantillas y puntos iniciales.
- `scripts/reporting/explain_llm_decisions.py`: generación del informe explicable.
- `scripts/reporting/build_interactive_demo.py`: generación de `demo/demo_data.js`.

## Comprobación rápida

Tras una ejecución, se puede revisar el estado del LLM con:

```powershell
python -c "import json; d=json.load(open('data/simulation_results/llm_decisions.json',encoding='utf-8-sig')); logs=[x for m in d for x in m.get('llm_decision_history',[])]; print('logs',len(logs),'fallbacks',sum(1 for x in logs if x.get('fallback_used')),'errores',sum(1 for x in logs if (x.get('llm_request') or {}).get('error')))"
```

Una ejecución limpia debería mostrar `fallbacks = 0` y `errores = 0`.

## Guía de ejecución

El archivo `GUIA_EJECUCION.md` contiene el proceso recomendado para preparar y ejecutar una prueba de forma ordenada.
