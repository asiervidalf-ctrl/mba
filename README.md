# Practica MBA

Simulador de una liga fantasy de futbol con managers-agente. Cada manager tiene una
plantilla, presupuesto, estrategia deportiva y estrategia economica. El motor simula
jornadas, mercado, fichajes, ventas, alineaciones, puntos y evolucion economica.

El proyecto puede funcionar solo con reglas internas, pero el flujo actual esta
preparado para delegar decisiones concretas a un LLM local con Ollama y
`mistral:latest`.

Estado actual del proyecto:

- Jornada inicial por defecto: `30`.
- Dias de mercado por jornada: `7`.
- Objetivo de los agentes LLM: maximizar puntos acumulados desde la jornada 30
  hasta la 38.
- Backend LLM por defecto: `ollama`.
- Modelo LLM por defecto: `mistral:latest`.
- Salidas principales: `data/simulation_results`.

## Indice

- [Flujo general](#flujo-general)
- [Ejecucion rapida](#ejecucion-rapida)
- [Requisitos](#requisitos)
- [Estructura del proyecto](#estructura-del-proyecto)
- [Que hace cada archivo](#que-hace-cada-archivo)
- [Datos de entrada](#datos-de-entrada)
- [Configuracion de managers](#configuracion-de-managers)
- [Logica de la simulacion](#logica-de-la-simulacion)
- [Sistema LLM](#sistema-llm)
- [Contexto que recibe Mistral](#contexto-que-recibe-mistral)
- [Validaciones sobre el LLM](#validaciones-sobre-el-llm)
- [Outputs generados](#outputs-generados)
- [Como explicar las decisiones del LLM](#como-explicar-las-decisiones-del-llm)
- [Dashboard](#dashboard)
- [Tiempos de ejecucion](#tiempos-de-ejecucion)
- [Comandos utiles](#comandos-utiles)
- [Problemas frecuentes](#problemas-frecuentes)

## Flujo general

El flujo completo del proyecto es:

1. Descargar datos crudos de FutbolFantasy.
2. Construir un dataset agregado de jugadores.
3. Cargar managers desde `config/managers.json`.
4. Inicializar plantillas, caja y puntos.
5. Ejecutar mercado y jornadas.
6. Pedir al LLM decisiones de mercado y alineacion, si el manager usa LLM.
7. Validar las decisiones del LLM.
8. Guardar estado, clasificacion, historicos y trazas.
9. Generar un informe explicable en lenguaje natural.

## Ejecucion rapida

Usa siempre el Python del entorno virtual:

```powershell
.\mba\Scripts\python.exe
```

Simulacion nueva desde cero:

```powershell
.\mba\Scripts\python.exe nueva_simulacion.py
```

Avanzar una jornada desde el estado guardado:

```powershell
.\mba\Scripts\python.exe siguiente_jornada.py
```

Reanudar manualmente desde el estado actual:

```powershell
.\mba\Scripts\python.exe model\model_run_fantasy.py --resume --rounds 1
```

Ejecutar hasta cerrar la jornada 38 desde un estado en jornada 30:

```powershell
.\mba\Scripts\python.exe model\model_run_fantasy.py --resume --rounds 8
```

Generar el informe explicable del LLM:

```powershell
.\mba\Scripts\python.exe explain_llm_decisions.py
```

## Requisitos

- Windows con PowerShell.
- Python y entorno virtual en `mba`.
- Dependencias instaladas desde `requirements.txt`.
- Dataset de jugadores en `data/players_dataset.json`.
- Para LLM local: Ollama instalado y ejecutandose.
- Modelo local recomendado:

```powershell
ollama pull mistral
```

Comprobacion:

```powershell
ollama list
ollama show mistral:latest
```

## Estructura del proyecto

```text
.
|-- build_players_dataset.py
|-- explain_llm_decisions.py
|-- fantasy_scraper.py
|-- generate_simulation_dashboard.py
|-- nueva_simulacion.py
|-- personal_lineup.py
|-- scrape_fantasy_data.py
|-- siguiente_jornada.py
|-- simulation_launcher.py
|-- config/
|   |-- managers.json
|   |-- managers.example.json
|   `-- README.md
|-- data/
|   |-- players_dataset.json
|   |-- fantasy_raw/
|   |-- simulation_results/
|   `-- tmp/
|-- model/
|   |-- llm_strategy.py
|   |-- market_agent.py
|   |-- model_fantasy.py
|   `-- model_run_fantasy.py
|-- scripts/
|   |-- data/
|   |   |-- build_players_dataset.py
|   |   |-- fantasy_scraper.py
|   |   `-- scrape_fantasy_data.py
|   |-- reporting/
|   |   |-- explain_llm_decisions.py
|   |   `-- generate_simulation_dashboard.py
|   `-- simulation/
|       `-- simulation_launcher.py
`-- mba/
```

## Que hace cada archivo

### Scripts de datos

- `scripts/data/scrape_fantasy_data.py`: lanza el scraping completo. Ejecuta
  `scripts/data/fantasy_scraper.py` y despues reconstruye `data/players_dataset.json`.
- `scripts/data/fantasy_scraper.py`: contiene la logica de descarga de datos de
  FutbolFantasy. Guarda datos crudos en `data/fantasy_raw`.
- `scripts/data/build_players_dataset.py`: lee los JSON crudos de jugadores y genera
  `data/players_dataset.json`, que es el dataset que consume el simulador.
- Los archivos `scrape_fantasy_data.py`, `fantasy_scraper.py` y
  `build_players_dataset.py` de la raiz son wrappers de compatibilidad.

### Scripts de simulacion

- `nueva_simulacion.py`: atajo para iniciar una simulacion nueva. Borra las
  salidas anteriores en `data/simulation_results` y llama al runner.
- `siguiente_jornada.py`: atajo para reanudar desde
  `data/simulation_results/current_state.json`.
- `scripts/simulation/simulation_launcher.py`: utilidades compartidas por los dos atajos
  anteriores. Resuelve el Python del entorno virtual, limpia outputs y llama al
  runner.
- `simulation_launcher.py`: wrapper de compatibilidad que reexporta el lanzador
  organizado.
- `model/model_run_fantasy.py`: runner principal por linea de comandos. Carga
  datos, crea o reanuda el modelo, ejecuta jornadas y exporta resultados.

### Modelo

- `model/model_fantasy.py`: archivo central. Define jugadores, managers,
  estrategias, formaciones, inicializacion, simulacion de puntos, mercado,
  seleccion de alineacion, serializacion de estado y ranking.
- `model/market_agent.py`: agente de mercado. Abre mercado diario, crea
  listings, recoge pujas, resuelve subastas, ventas entre managers, ventas al
  mercado y bonus economicos.
- `model/llm_strategy.py`: capa LLM. Gestiona llamadas a Ollama u OpenAI,
  prompts, esquemas JSON, parseo, logs tecnicos y metadatos de decision.

### Configuracion y explicabilidad

- `config/managers.json`: configuracion real de managers: estrategia,
  presupuesto, puntos, plantilla inicial, once inicial y backend LLM.
- `config/managers.example.json`: ejemplo minimo de configuracion.
- `config/README.md`: notas especificas de configuracion.
- `personal_lineup.py`: carga y normaliza `config/managers.json`. Tambien
  corrige nombres con problemas de codificacion y asigna jugadores iniciales.
- `scripts/reporting/explain_llm_decisions.py`: transforma `llm_decisions.json` en
  `llm_decisions_explained.md`, un informe legible en lenguaje natural.
- `scripts/reporting/generate_simulation_dashboard.py`: genera un dashboard HTML y graficas desde
  los resultados exportados.
- `explain_llm_decisions.py` y `generate_simulation_dashboard.py` en la raiz son
  wrappers para mantener los comandos antiguos.

## Datos de entrada

### `data/players_dataset.json`

Dataset agregado de jugadores. Cada jugador contiene, entre otros:

- `id`: identificador numerico.
- `name`: nombre.
- `position`: posicion.
- `teamName`: equipo.
- `marketValue`: valor de mercado.
- `points`: puntos acumulados reales del dataset.
- `averagePoints`: media de puntos.
- `status`: disponibilidad general.
- `availability`: porcentaje de disponibilidad si existe.
- `points_history`: historico de puntos.
- `marketValue_history`: historico de valor.
- `analytics`: metricas derivadas como forma reciente, cambios de precio,
  puntos por millon, riesgo de lesion o tarjetas.

Este archivo se genera desde:

```powershell
.\mba\Scripts\python.exe build_players_dataset.py
```

O desde el pipeline completo:

```powershell
.\mba\Scripts\python.exe scrape_fantasy_data.py
```

## Configuracion de managers

El archivo principal es `config/managers.json`.

Campos principales:

- `name`: nombre del manager.
- `sport_strategy`: estrategia deportiva.
- `economic_strategy`: estrategia economica.
- `decision_engine`: `llm` o reglas normales.
- `llm_backend`: `ollama` u `openai`.
- `llm_model`: modelo usado, por ejemplo `mistral:latest`.
- `llm_controls`: decisiones que se delegan al LLM.
- `cash`: caja disponible.
- `budget`: presupuesto inicial alternativo.
- `current_points`: puntos iniciales.
- `preferred_formation`: formacion preferida de arranque.
- `squad_player_ids`: plantilla inicial.
- `lineup_player_ids`: once inicial.

Notas:

- Si se define `cash`, el sistema lo interpreta como caja actual.
- Si se define `budget`, el sistema puede descontar la plantilla inicial.
- Si faltan jugadores, el proyecto completa plantillas mediante draft.
- Plantilla objetivo inicial: 15 jugadores.
- Maximo durante la simulacion: 22 jugadores.

### Estrategias deportivas

- `cracks`: prioriza futbolistas diferenciales, proyeccion alta y techo.
- `mejor_forma`: prioriza forma reciente y dinamica.
- `arriesgado`: acepta mas incertidumbre si el techo de puntos es alto.
- `grandes_clubes`: favorece jugadores de clubes fuertes.
- `equipos_pequenos`: busca oportunidades infravaloradas y cruces favorables.

### Estrategias economicas

- `fichar_a_toda_costa`: puede usar caja de forma agresiva si mejora puntos.
- `balanceado`: equilibra mejora deportiva, liquidez y profundidad.
- `tacano`: protege caja y exige valor claro para comprar.

Estas estrategias se usan internamente en reglas y tambien se pasan al LLM como
preferencias en lenguaje natural, no como formula exacta.

## Logica de la simulacion

Cada jornada sigue este ciclo:

1. Se abren 7 dias de mercado.
2. En cada dia, el mercado oficial publica jugadores libres.
3. Los managers proponen ventas propias.
4. Se crea un mercado tentativo con jugadores libres y ventas de managers.
5. Cada manager decide ventas y pujas.
6. El mercado valida y resuelve operaciones.
7. Al cerrar el mercado de la jornada, se proyectan puntos y precios.
8. Cada manager elige formacion y once.
9. Se calculan puntos de jornada.
10. Se reparten bonus economicos por ranking de jornada.
11. Se guarda el estado para poder reanudar.

Formaciones legales:

```text
3-4-3, 3-5-2, 4-3-3, 4-4-2, 4-5-1, 5-3-2, 5-4-1
```

Posiciones:

```text
Portero, Defensa, Mediocampista, Delantero
```

## Sistema LLM

El LLM no ejecuta transferencias directamente. Propone decisiones y el simulador
las valida.

Backend por defecto en `model/llm_strategy.py`:

```text
MBA_LLM_BACKEND=ollama
MBA_LLM_MODEL=mistral:latest
MBA_OLLAMA_BASE_URL=http://127.0.0.1:11434
MBA_LLM_TIMEOUT_SECONDS=120
MBA_OLLAMA_NUM_PREDICT=700
MBA_OLLAMA_NUM_CTX=8192
MBA_OLLAMA_USE_JSON_SCHEMA=1
```

Variables utiles:

```powershell
$env:MBA_LLM_MODEL="mistral:latest"
$env:MBA_OLLAMA_NUM_CTX="8192"
$env:MBA_OLLAMA_NUM_PREDICT="700"
$env:MBA_LLM_TIMEOUT_SECONDS="120"
```

Para ver prompt y payload en logs:

```powershell
$env:MBA_LLM_LOG_PROMPTS="1"
.\mba\Scripts\python.exe model\model_run_fantasy.py --resume --llm-log-level DEBUG
```

### Decisiones delegadas al LLM

En el flujo actual se usa principalmente:

- `market_day_plan`: plan completo de mercado diario.
- `lineup`: formacion y once titular.

Tambien existen funciones compatibles para:

- `sale_candidates`: candidatos de venta.
- `market_bid`: puja individual.
- `formation`: formacion aislada.

### Esquemas JSON

El LLM debe responder con JSON estricto. Para mercado:

```json
{
  "sell_player_ids": [123],
  "bids": [
    {"player_id": 456, "bid": 750000}
  ],
  "summary": "...",
  "key_factors": ["..."],
  "risk_flags": ["..."],
  "decision_trace": ["..."],
  "confidence": 0.85
}
```

Para alineacion:

```json
{
  "formation": "4-3-3",
  "lineup_player_ids": [1,2,3,4,5,6,7,8,9,10,11],
  "summary": "...",
  "key_factors": ["..."],
  "risk_flags": ["..."],
  "decision_trace": ["..."],
  "confidence": 0.85
}
```

Las claves `summary`, `key_factors`, `risk_flags` y `decision_trace` se guardan
para explicabilidad.

## Contexto que recibe Mistral

El contexto se guarda completo en:

```text
data/simulation_results/llm_decisions.json
```

Dentro de cada decision:

```json
"llm_request": {
  "backend": "ollama",
  "model": "mistral:latest",
  "elapsed_seconds": 7.5,
  "system_prompt": "...",
  "input_payload": {},
  "raw_output": "...",
  "parsed_output": {},
  "error": null
}
```

### Contexto comun

Todas las decisiones LLM reciben:

```json
{
  "objective": {
    "goal": "maximizar puntos acumulados de J30 a J38",
    "current_round": 30,
    "final_round": 38,
    "remaining_rounds": 9
  },
  "manager": {
    "name": "Manager 1",
    "cash": 19743327,
    "squad_size": 15,
    "team_value": 438157030,
    "points": 1419.0
  },
  "strategy": {
    "sport": "cracks",
    "sport_preference": "Prioriza futbolistas diferenciales y con techo alto...",
    "economic": "balanceado",
    "economic_preference": "Debe equilibrar mejora deportiva, liquidez..."
  },
  "squad_summary": {
    "by_position": {
      "Portero": 2,
      "Defensa": 5,
      "Mediocampista": 5,
      "Delantero": 3
    },
    "legal_lineup_required": {
      "Portero": 1,
      "total": 11
    }
  },
  "squad": []
}
```

### Jugadores en plantilla

Cada jugador de `squad` se envia compacto:

```json
{
  "id": 16735,
  "n": "Javi Navarro",
  "pos": "Portero",
  "team": "Real Madrid",
  "price_eur": 707928,
  "pts": 0.0,
  "form": 0.0,
  "season": 0.0,
  "fit": 1.0,
  "value": 0.0
}
```

Significado:

- `id`: identificador que el LLM debe devolver como `player_id`.
- `n`: nombre.
- `pos`: posicion.
- `team`: equipo.
- `price_eur`: valor/precio actual del jugador.
- `pts`: puntos esperados de la jornada simulada.
- `form`: forma reciente.
- `season`: proyeccion media de temporada.
- `fit`: disponibilidad, entre 0 y 1.
- `status`: solo aparece si el jugador no esta disponible.
- `value`: rendimiento estimado por coste.

### Contexto de alineacion

Ademas del contexto comun, recibe:

```json
"lineup_rules": {
  "lineup_size": 11,
  "use_only_squad_players": true,
  "formations": [
    {"name": "3-4-3", "req": "P1 D3 M4 F3"},
    {"name": "4-3-3", "req": "P1 D4 M3 F3"}
  ]
}
```

Leyenda:

- `P`: Portero.
- `D`: Defensa.
- `M`: Mediocampista.
- `F`: Delantero.

El LLM debe elegir una formacion legal y exactamente 11 jugadores de su
plantilla.

### Contexto de mercado

Ademas del contexto comun, recibe:

```json
"market_rules": {
  "may_sell_player_ids": [16735, 4397],
  "constraints": [
    "vender como maximo 4 jugadores propios",
    "mantener al menos 11 jugadores tras ventas",
    "no superar 22 jugadores en plantilla",
    "cada puja debe cubrir ask_eur, caber en cash y no superar max_bid_eur",
    "evitar sobrepagar suplentes, lesionados o jugadores con pts/form/season bajos",
    "no pujar por jugadores propios",
    "maximo 5 pujas; arrays vacios significan no operar"
  ]
}
```

Y el mercado abierto:

```json
"market_open": [
  {
    "id": 8134,
    "n": "Vedat Muriqi",
    "pos": "Delantero",
    "team": "Mallorca",
    "ask_eur": 59942941,
    "market_value_eur": 59942941,
    "max_bid_eur": 69309026,
    "source": "market",
    "seller": "market",
    "pts": 6.5,
    "form": 5.2,
    "season": 5.8,
    "fit": 1.0,
    "value": 0.1
  }
]
```

Significado de precios:

- `ask_eur`: precio minimo para poder comprar.
- `market_value_eur`: valor de mercado del jugador.
- `max_bid_eur`: limite de cordura calculado por el simulador.

El LLM puede decidir no comprar devolviendo `bids: []`.

## Validaciones sobre el LLM

El LLM tiene libertad para decidir, pero el simulador no acepta cualquier cosa.

Validaciones de parseo:

- La respuesta debe ser JSON.
- Ollama recibe un esquema JSON estricto.
- Se extrae JSON aunque venga envuelto en markdown.
- Si no se puede parsear, se usa fallback.

Validaciones de alineacion:

- La formacion debe existir.
- Debe haber exactamente 11 jugadores.
- Todos los IDs deben pertenecer a la plantilla.
- Debe haber 1 portero.
- Las posiciones deben cumplir la formacion elegida.

Validaciones de ventas:

- Solo puede vender jugadores propios.
- No puede superar el maximo de ventas del dia.
- No puede dejar plantilla menor de 11.
- No puede romper la posibilidad de alinear una formacion legal.

Validaciones de pujas:

- No se puede pujar por jugadores propios.
- La puja debe ser igual o superior a `ask_eur`.
- La puja debe caber en caja.
- No se puede superar la capacidad maxima de plantilla.
- La puja final no puede superar `max_bid_eur`.
- Si el LLM propone una sobrepuja, el simulador la recorta y lo registra como
  `bid_adjustments`.

Ejemplo de ajuste:

```text
Inigo Lekue: 7.000.000 -> 736.917
```

## Outputs generados

Todos los resultados se guardan en:

```text
data/simulation_results
```

### `current_state.json`

Estado completo del modelo para reanudar. Incluye:

- jornada actual,
- jornada inicial,
- numero de jornadas configurado,
- dias de mercado por jornada,
- jugadores con puntos, precio y estado,
- managers con caja, plantilla, once, banquillo, historial y estrategia,
- estado del mercado,
- historicos acumulados.

Es el archivo que usa:

```powershell
.\mba\Scripts\python.exe model\model_run_fantasy.py --resume
```

### `leaderboard.json`

Clasificacion actual/final. Cada entrada contiene:

- `name`,
- `strategy`,
- `sport_strategy`,
- `economic_strategy`,
- `points_total`,
- `points_round`,
- `cash`,
- `squad_value`,
- `formation`,
- `transfers_made`.

### `strategy_summary.json`

Resumen agregado por estrategia. Permite comparar:

- estrategias deportivas,
- estrategias economicas,
- puntos,
- caja,
- valor de plantilla,
- numero de managers por grupo.

### `market_auctions.json`

Historial de operaciones de mercado. Contiene:

- jornada,
- dia de mercado,
- jugador,
- vendedor,
- comprador,
- precio,
- estado de venta,
- pujas recibidas.

Estados habituales:

- `sold`: vendido a un manager.
- `unsold`: no vendido.
- `sold_to_market`: jugador de manager vendido al mercado.

### `market_bonuses.json`

Bonus economicos entregados al cierre de jornada. Incluye:

- jornada,
- manager,
- posicion en puntos de la jornada,
- bonus recibido,
- puntos de jornada.

### `market_days.json`

Trazabilidad diaria del mercado. Cada dia incluye:

- jornada,
- dia de mercado,
- listings publicados,
- ventas resueltas.

Sirve para reconstruir que jugadores estuvieron disponibles cada dia.

### `market_days/round_XXX.json`

Detalle de mercado de la ultima jornada exportada, separado por jornada. Por
ejemplo:

```text
data/simulation_results/market_days/round_038.json
```

### `lineups_history.json`

Historico de alineaciones. Incluye:

- jornada,
- manager,
- formacion,
- once titular,
- banquillo,
- puntos,
- estrategia.

### `llm_decisions.json`

Archivo mas importante para auditar el LLM. Para cada manager guarda:

- nombre,
- estrategia,
- `llm_decision_history`.

Cada decision incluye:

- `round`: jornada.
- `market_day`: dia de mercado.
- `manager`: manager.
- `decision_type`: `lineup`, `market_day_plan`, etc.
- `backend`: `ollama` u otro.
- `model`: modelo usado.
- `fallback_used`: si se uso fallback.
- `summary`: resumen declarado por el LLM.
- `key_factors`: factores clave declarados.
- `risk_flags`: riesgos declarados.
- `decision_trace`: rastro resumido de decision.
- `confidence`: confianza declarada.
- `elapsed_seconds`: tiempo de la llamada.
- `context`: contexto de validacion del simulador.
- `final_decision`: decision final validada por el simulador.
- `raw_response`: respuesta parseada del LLM.
- `llm_request`: prompt, payload, salida cruda y salida parseada.

Este archivo permite responder preguntas como:

- Que contexto recibio Mistral.
- Que propuso.
- Que acepto el simulador.
- Si hubo fallback.
- Si hubo recortes de puja.
- Cuanto tardo cada llamada.

### `llm_decisions_explained.md`

Informe en lenguaje natural generado desde `llm_decisions.json`.

Incluye:

- decision por jornada y dia de mercado,
- ventas propuestas,
- pujas propuestas,
- alineaciones,
- motivos resumidos,
- factores clave,
- riesgos,
- rastro declarado,
- confianza,
- estado tecnico de la llamada,
- ajustes de puja por precio cuando existen.

Se genera con:

```powershell
.\mba\Scripts\python.exe explain_llm_decisions.py
```

### `rounds.csv`

CSV con metricas por jornada. Util para graficas y analisis tabular.

Suele incluir:

- jornada,
- lider,
- puntos del lider,
- numero de dias de mercado,
- listados de mercado,
- ventas.

### `agents.csv`

CSV con metricas por manager y jornada:

- jornada,
- manager,
- puntos,
- caja,
- valor de plantilla,
- formacion,
- fichajes acumulados,
- estrategia.

### `charts/`

Carpeta creada por `generate_simulation_dashboard.py`. Contiene dashboard HTML y
graficas si se genera el panel.

## Como explicar las decisiones del LLM

El archivo tecnico es:

```text
data/simulation_results/llm_decisions.json
```

El archivo legible es:

```text
data/simulation_results/llm_decisions_explained.md
```

Regenerar:

```powershell
.\mba\Scripts\python.exe explain_llm_decisions.py
```

El script mapea IDs de jugadores a nombres usando el propio payload enviado al
LLM (`squad` y `market_open`). Por eso puede explicar pujas y alineaciones sin
tener que buscar manualmente cada ID.

## Dashboard

Generar dashboard:

```powershell
.\mba\Scripts\python.exe generate_simulation_dashboard.py
```

Por defecto lee:

- `data/players_dataset.json`,
- `config/managers.json`,
- `data/simulation_results/current_state.json`,
- `data/simulation_results/market_days.json`.

Y escribe en:

```text
data/simulation_results/charts
```

## Tiempos de ejecucion

En esta maquina, con Ollama y `mistral:latest`, una jornada completa con 7 dias
de mercado tarda aproximadamente:

```text
9-10 minutos
```

En una ejecucion real desde jornada 31 hasta cerrar jornada 38:

```text
8 jornadas
tiempo total aproximado: 68 min 53 s
logs LLM generados: 601
respuestas no parseables: 0
```

El cuello de botella es el LLM. El simulador puro pesa poco comparado con las
llamadas a Mistral.

## Comandos utiles

### Simulacion nueva

```powershell
.\mba\Scripts\python.exe nueva_simulacion.py
```

### Reanudar una jornada

```powershell
.\mba\Scripts\python.exe siguiente_jornada.py
```

### Reanudar varias jornadas

```powershell
.\mba\Scripts\python.exe model\model_run_fantasy.py --resume --rounds 8
```

### Simular con parametros explicitos

```powershell
.\mba\Scripts\python.exe model\model_run_fantasy.py --start-round 30 --rounds 1 --days-per-round 7
```

### Usar menos dias de mercado para pruebas rapidas

```powershell
.\mba\Scripts\python.exe model\model_run_fantasy.py --start-round 30 --rounds 1 --days-per-round 2
```

### Ver trazas verbosas del LLM

```powershell
$env:MBA_LLM_LOG_PROMPTS="1"
.\mba\Scripts\python.exe model\model_run_fantasy.py --resume --llm-log-level DEBUG
```

### Cambiar modelo Ollama

```powershell
$env:MBA_LLM_MODEL="mistral:latest"
.\mba\Scripts\python.exe model\model_run_fantasy.py --resume
```

### Cambiar ventana de contexto

```powershell
$env:MBA_OLLAMA_NUM_CTX="8192"
```

### Regenerar explicacion

```powershell
.\mba\Scripts\python.exe explain_llm_decisions.py
```

### Generar dashboard

```powershell
.\mba\Scripts\python.exe generate_simulation_dashboard.py
```

## Parametros del runner

`model/model_run_fantasy.py` acepta:

- `--dataset`: dataset de jugadores. Por defecto `data/players_dataset.json`.
- `--start-round`: jornada inicial si no se reanuda. Por defecto `30`.
- `--rounds`: numero de jornadas a ejecutar. Por defecto `1`.
- `--days-per-round`: dias de mercado por jornada. Por defecto `7`.
- `--managers`: numero de managers si no se usa configuracion cerrada.
- `--budget`: presupuesto inicial si se autogeneran managers.
- `--seed`: semilla aleatoria opcional.
- `--use-real-league`: activa carga basada en configuracion real.
- `--manager-config`: ruta al JSON de managers.
- `--state-file`: ruta del estado serializado.
- `--resume`: reanuda desde `current_state.json`.
- `--llm-log-level`: `DEBUG`, `INFO`, `WARNING` o `ERROR`.

## Problemas frecuentes

### Mistral devuelve JSON raro o no parseable

El proyecto usa esquemas JSON y parseo robusto. Si aun ocurre:

- revisa `llm_request.raw_output` en `llm_decisions.json`,
- sube `MBA_OLLAMA_NUM_CTX`,
- reduce dias de mercado para pruebas,
- comprueba que Ollama no esta saturado.

### El LLM puja demasiado

El contexto de mercado incluye:

- `ask_eur`,
- `market_value_eur`,
- `max_bid_eur`.

Ademas, el simulador recorta pujas que superen `max_bid_eur` y lo guarda en:

```json
"context": {
  "bid_adjustments": []
}
```

### El informe Markdown no aparece

Ejecuta:

```powershell
.\mba\Scripts\python.exe explain_llm_decisions.py
```

### Quiero comprobar si hubo respuestas no parseables

```powershell
.\mba\Scripts\python.exe -c "import json; d=json.load(open('data/simulation_results/llm_decisions.json',encoding='utf-8-sig')); logs=[x for m in d for x in m.get('llm_decision_history',[]) if x.get('llm_request')]; print(sum(1 for x in logs if not (x.get('llm_request') or {}).get('parsed_output')), 'no parseables de', len(logs))"
```

### Quiero comprobar si hay sobrepujas finales

El simulador ya valida `max_bid_eur`, pero puedes auditarlo en
`llm_decisions.json` comparando `final_decision.bid_by_player_id` con
`llm_request.input_payload.market_open`.

## Resultado de la ultima ejecucion guardada

La ultima ejecucion guardada fue una simulacion nueva de comprobacion y cerro la
jornada 30. Ranking:

```text
1. Manager 1 | 1490 pts | cracks + balanceado
2. Manager 5 | 1397 pts | grandes_clubes + tacano
3. Manager 3 | 1369 pts | equipos_pequenos + tacano
4. Manager 6 | 1338 pts | arriesgado + fichar_a_toda_costa
5. Manager 2 | 1312 pts | mejor_forma + balanceado
6. Manager 4 | 1106 pts | cracks + fichar_a_toda_costa
```

Archivos clave:

- `data/simulation_results/current_state.json`
- `data/simulation_results/leaderboard.json`
- `data/simulation_results/llm_decisions.json`
- `data/simulation_results/llm_decisions_explained.md`
