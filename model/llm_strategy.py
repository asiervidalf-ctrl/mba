from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

import requests

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - dependencia opcional
    OpenAI = None


LOGGER = logging.getLogger(__name__)
DEFAULT_LLM_BACKEND = os.getenv("MBA_LLM_BACKEND", "ollama").strip().lower()
DEFAULT_LLM_MODEL = os.getenv("MBA_LLM_MODEL", "mistral:latest")
DEFAULT_OLLAMA_BASE_URL = os.getenv("MBA_OLLAMA_BASE_URL", "http://127.0.0.1:11434")
REQUEST_TIMEOUT = int(os.getenv("MBA_LLM_TIMEOUT_SECONDS", "120"))
OLLAMA_NUM_PREDICT = int(os.getenv("MBA_OLLAMA_NUM_PREDICT", "700"))
OLLAMA_NUM_CTX = int(os.getenv("MBA_OLLAMA_NUM_CTX", "2048"))
OLLAMA_USE_JSON_SCHEMA = os.getenv("MBA_OLLAMA_USE_JSON_SCHEMA", "1").strip().lower() in {"1", "true", "yes", "si"}
LOG_PROMPTS = os.getenv("MBA_LLM_LOG_PROMPTS", "").strip().lower() in {"1", "true", "yes", "si"}
SUPPORTED_LLM_CONTROLS = {"sale_candidates", "market_bid", "formation", "lineup"}

MARKET_DAY_PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "sell_player_ids": {"type": "array", "items": {"type": "integer"}, "maxItems": 4},
        "bids": {
            "type": "array",
            "maxItems": 2,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "player_id": {"type": "integer"},
                    "bid": {"type": "integer"},
                },
                "required": ["player_id", "bid"],
            },
        },
        "summary": {"type": "string", "maxLength": 180},
        "key_factors": {"type": "array", "maxItems": 3, "items": {"type": "string", "maxLength": 90}},
        "risk_flags": {"type": "array", "maxItems": 3, "items": {"type": "string", "maxLength": 90}},
        "decision_trace": {"type": "array", "maxItems": 3, "items": {"type": "string", "maxLength": 90}},
        "confidence": {"type": "number"},
    },
    "required": ["sell_player_ids", "bids", "summary", "key_factors", "risk_flags", "decision_trace", "confidence"],
}

LINEUP_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "formation": {"type": "string"},
        "lineup_player_ids": {"type": "array", "items": {"type": "integer"}, "minItems": 11, "maxItems": 11},
        "summary": {"type": "string", "maxLength": 180},
        "key_factors": {"type": "array", "maxItems": 3, "items": {"type": "string", "maxLength": 90}},
        "risk_flags": {"type": "array", "maxItems": 3, "items": {"type": "string", "maxLength": 90}},
        "decision_trace": {"type": "array", "maxItems": 3, "items": {"type": "string", "maxLength": 90}},
        "confidence": {"type": "number"},
    },
    "required": ["formation", "lineup_player_ids", "summary", "key_factors", "risk_flags", "decision_trace", "confidence"],
}

FORMATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "formation": {"type": "string"},
        "summary": {"type": "string", "maxLength": 180},
        "key_factors": {"type": "array", "maxItems": 3, "items": {"type": "string", "maxLength": 90}},
        "risk_flags": {"type": "array", "maxItems": 3, "items": {"type": "string", "maxLength": 90}},
        "decision_trace": {"type": "array", "maxItems": 3, "items": {"type": "string", "maxLength": 90}},
        "confidence": {"type": "number"},
    },
    "required": ["formation", "summary", "key_factors", "risk_flags", "decision_trace", "confidence"],
}

BID_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "bid": {"type": ["integer", "null"]},
        "summary": {"type": "string", "maxLength": 180},
        "key_factors": {"type": "array", "maxItems": 3, "items": {"type": "string", "maxLength": 90}},
        "risk_flags": {"type": "array", "maxItems": 3, "items": {"type": "string", "maxLength": 90}},
        "decision_trace": {"type": "array", "maxItems": 3, "items": {"type": "string", "maxLength": 90}},
        "confidence": {"type": "number"},
    },
    "required": ["bid", "summary", "key_factors", "risk_flags", "decision_trace", "confidence"],
}

SALE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "sell_player_ids": {"type": "array", "items": {"type": "integer"}, "maxItems": 4},
        "summary": {"type": "string", "maxLength": 180},
        "key_factors": {"type": "array", "maxItems": 3, "items": {"type": "string", "maxLength": 90}},
        "risk_flags": {"type": "array", "maxItems": 3, "items": {"type": "string", "maxLength": 90}},
        "decision_trace": {"type": "array", "maxItems": 3, "items": {"type": "string", "maxLength": 90}},
        "confidence": {"type": "number"},
    },
    "required": ["sell_player_ids", "summary", "key_factors", "risk_flags", "decision_trace", "confidence"],
}


def _extract_json_payload(raw_text: str) -> dict[str, Any] | None:
    """Intenta recuperar un JSON valido incluso si llega envuelto en markdown."""
    text = raw_text.strip()
    if not text:
        return None

    if text.startswith("```"):
        parts = text.split("```")
        text = next((part for part in parts if "{" in part), text).strip()
        if text.startswith("json"):
            text = text[4:].strip()

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return _salvage_partial_json_payload(text)

    return payload if isinstance(payload, dict) else None


def _extract_int_array(text: str, key: str) -> list[int]:
    """Extrae una lista de enteros aunque el JSON venga truncado."""
    match = re.search(rf'"{re.escape(key)}"\s*:\s*\[([^\]]*)', text, flags=re.DOTALL)
    if not match:
        return []
    return [int(value) for value in re.findall(r"-?\d+", match.group(1))]


def _extract_string_value(text: str, key: str) -> str | None:
    """Extrae una cadena simple y tolera cierres truncados al final de linea."""
    match = re.search(rf'"{re.escape(key)}"\s*:\s*"([^"\n\r]*)', text, flags=re.DOTALL)
    if not match:
        return None
    value = match.group(1).strip()
    return value if value else None


def _extract_string_array(text: str, key: str) -> list[str]:
    """Extrae arrays de texto cuando al menos parte de la lista es legible."""
    match = re.search(rf'"{re.escape(key)}"\s*:\s*\[([^\]]*)', text, flags=re.DOTALL)
    if not match:
        value = _extract_string_value(text, key)
        return [value] if value else []
    return [item.strip() for item in re.findall(r'"([^"]+)', match.group(1)) if item.strip()]


def _extract_bid_objects(text: str) -> list[dict[str, int]]:
    """Extrae pujas con player_id y bid aunque el resto del JSON falle."""
    bids_section = re.search(r'"bids"\s*:\s*\[([\s\S]*?)(?:\]\s*,|\]\s*}|$)', text)
    if not bids_section:
        return []
    bids: list[dict[str, int]] = []
    for player_id, bid in re.findall(
        r'"player_id"\s*:\s*(-?\d+)[\s\S]*?"bid"\s*:\s*(-?\d+)',
        bids_section.group(1),
    ):
        bids.append({"player_id": int(player_id), "bid": int(bid)})
    return bids


def _salvage_partial_json_payload(text: str) -> dict[str, Any] | None:
    """Recupera los campos accionables de respuestas de Mistral truncadas."""
    payload: dict[str, Any] = {}

    nested_lineup = re.search(r'"lineup"\s*:\s*{([\s\S]*)', text)
    if nested_lineup:
        text = nested_lineup.group(1)

    formation = _extract_string_value(text, "formation")
    if formation:
        payload["formation"] = formation
        payload["lineup_player_ids"] = _extract_int_array(text, "lineup_player_ids")

    if '"sell_player_ids"' in text or '"bids"' in text:
        payload["sell_player_ids"] = _extract_int_array(text, "sell_player_ids")
        payload["bids"] = _extract_bid_objects(text)

    for key in ("summary",):
        value = _extract_string_value(text, key)
        if value:
            payload[key] = value

    for key in ("key_factors", "risk_flags", "decision_trace"):
        values = _extract_string_array(text, key)
        if values:
            payload[key] = values[:3]

    if "confidence" not in payload:
        confidence_match = re.search(r'"confidence"\s*:\s*([01](?:\.\d+)?)', text)
        payload["confidence"] = float(confidence_match.group(1)) if confidence_match else 0.5

    if "formation" in payload or "sell_player_ids" in payload or "bids" in payload:
        return payload
    return None


class LLMDecisionEngine:
    """Capa opcional para delegar decisiones concretas de un manager a un LLM."""

    _availability_warning_emitted: set[str] = set()

    def __init__(
        self,
        *,
        manager_name: str,
        model_name: str | None = None,
        controls: list[str] | None = None,
        backend: str | None = None,
        base_url: str | None = None,
    ) -> None:
        """Configura backend, modelo y tipos de decisiones que puede tomar el LLM."""
        self.manager_name = manager_name
        self.backend = (backend or DEFAULT_LLM_BACKEND).strip().lower()
        self.model_name = (model_name or DEFAULT_LLM_MODEL).strip()
        self.resolved_model_name = self.model_name
        self.base_url = (base_url or DEFAULT_OLLAMA_BASE_URL).rstrip("/")
        self.controls = {
            str(control).strip()
            for control in (controls or sorted(SUPPORTED_LLM_CONTROLS))
            if str(control).strip() in SUPPORTED_LLM_CONTROLS
        }
        self._client = None
        self._last_decision_meta: dict[str, dict[str, Any]] = {}
        self._last_request_log: dict[str, Any] | None = None

    def supports(self, control_name: str) -> bool:
        """Indica si el manager tiene habilitado un control concreto en el LLM."""
        if control_name == "lineup" and "formation" in self.controls:
            return True
        return control_name in self.controls

    def get_last_decision_meta(self, control_name: str) -> dict[str, Any] | None:
        """Recupera resumen, factores, riesgos y confianza de la ultima respuesta."""
        meta = self._last_decision_meta.get(control_name)
        return dict(meta) if isinstance(meta, dict) else None

    def get_last_request_log(self) -> dict[str, Any] | None:
        """Recupera la ultima traza tecnica con prompt, payload y salida."""
        return dict(self._last_request_log) if isinstance(self._last_request_log, dict) else None

    def _store_decision_meta(self, control_name: str, response: dict[str, Any] | None) -> None:
        """Extrae campos explicativos de la respuesta parseada y los normaliza."""
        if not isinstance(response, dict):
            self._last_decision_meta.pop(control_name, None)
            return

        def as_list(value: Any) -> list[str]:
            """Acepta listas o cadenas cuando el modelo simplifica el formato."""
            if isinstance(value, list):
                return [str(item).strip() for item in value if str(item).strip()]
            if isinstance(value, str) and value.strip():
                return [value.strip()]
            return []

        meta: dict[str, Any] = {}
        summary = response.get("summary")
        if isinstance(summary, str) and summary.strip():
            meta["summary"] = summary.strip()

        key_factors = as_list(response.get("key_factors"))
        if key_factors:
            meta["key_factors"] = key_factors[:5]

        risk_flags = as_list(response.get("risk_flags"))
        if risk_flags:
            meta["risk_flags"] = risk_flags[:5]

        decision_trace = as_list(response.get("decision_trace"))
        if decision_trace:
            meta["decision_trace"] = decision_trace[:6]

        confidence = response.get("confidence")
        if isinstance(confidence, (int, float)):
            meta["confidence"] = max(0.0, min(1.0, float(confidence)))

        if meta:
            self._last_decision_meta[control_name] = meta
        else:
            self._last_decision_meta.pop(control_name, None)

    def is_available(self) -> bool:
        """Comprueba que el backend configurado exista y este operativo."""
        if self.backend == "openai":
            if OpenAI is None:
                self._warn_unavailable_once("openai_missing", "La libreria 'openai' no esta instalada; se usaran reglas deterministas.")
                return False
            if not os.getenv("OPENAI_API_KEY"):
                self._warn_unavailable_once("openai_key_missing", "Falta OPENAI_API_KEY; se usaran reglas deterministas.")
                return False
            return True

        if self.backend == "ollama":
            try:
                response = requests.get(f"{self.base_url}/api/tags", timeout=min(REQUEST_TIMEOUT, 10))
                response.raise_for_status()
            except requests.RequestException as exc:
                self._warn_unavailable_once(
                    "ollama_unavailable",
                    f"Ollama no responde en {self.base_url}; se usaran reglas deterministas. Detalle: {exc}",
                )
                return False

            payload = response.json()
            models = payload.get("models", []) if isinstance(payload, dict) else []
            available_names = {
                str(model.get("name", "")).strip()
                for model in models
                if isinstance(model, dict)
            }
            available_aliases = {name.split(":", 1)[0] for name in available_names if name}
            requested_alias = self.model_name.split(":", 1)[0]
            if self.model_name not in available_names and requested_alias not in available_aliases:
                self._warn_unavailable_once(
                    "ollama_model_missing",
                    f"El modelo local {self.model_name!r} no existe en Ollama; se usaran reglas deterministas. "
                    f"Puedes instalarlo con: ollama pull {requested_alias}",
                )
                return False
            if self.model_name not in available_names:
                matching_names = sorted(name for name in available_names if name.split(":", 1)[0] == requested_alias)
                if matching_names:
                    self.resolved_model_name = matching_names[0]
            return True

        self._warn_unavailable_once("backend_unknown", f"Backend LLM desconocido: {self.backend}. Se usaran reglas deterministas.")
        return False

    def _warn_unavailable_once(self, key: str, message: str) -> None:
        """Emite cada aviso de disponibilidad una sola vez por ejecucion."""
        if key not in self.__class__._availability_warning_emitted:
            LOGGER.warning(message)
            self.__class__._availability_warning_emitted.add(key)

    @property
    def client(self) -> Any | None:
        """Construye perezosamente el cliente OpenAI solo cuando se necesita."""
        if not self.is_available():
            return None
        if self.backend != "openai":
            return None
        if self._client is None:
            self._client = OpenAI()
        return self._client

    def _request_json_openai(
        self,
        *,
        system_prompt: str,
        payload: dict[str, Any],
        response_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Llama a OpenAI y devuelve un diccionario JSON parseado o None."""
        del response_schema
        started_at = time.perf_counter()
        client = self.client
        if client is None:
            self._store_request_log("openai", system_prompt, payload, None, None, started_at, error="backend unavailable")
            return None

        self._log_request_start("openai", system_prompt, payload)
        try:
            response = client.responses.create(
                model=self.model_name,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
                ],
            )
        except Exception as exc:  # pragma: no cover - depende de red/API externa
            LOGGER.warning("Fallo consultando OpenAI para %s: %s", self.manager_name, exc)
            self._store_request_log("openai", system_prompt, payload, None, None, started_at, error=str(exc))
            return None

        output_text = getattr(response, "output_text", "") or ""
        parsed = _extract_json_payload(output_text)
        self._store_request_log("openai", system_prompt, payload, output_text, parsed, started_at)
        return parsed

    def _request_json_ollama(
        self,
        *,
        system_prompt: str,
        payload: dict[str, Any],
        response_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Llama a Ollama con JSON Schema cuando esta disponible."""
        started_at = time.perf_counter()
        if not self.is_available():
            self._store_request_log("ollama", system_prompt, payload, None, None, started_at, error="backend unavailable")
            return None

        self._log_request_start("ollama", system_prompt, payload)
        try:
            response = requests.post(
                f"{self.base_url}/api/chat",
                timeout=REQUEST_TIMEOUT,
                json={
                    "model": self.resolved_model_name,
                    "stream": False,
                    "format": response_schema if (OLLAMA_USE_JSON_SCHEMA and response_schema) else "json",
                    "options": {
                        "temperature": 0.2,
                        "num_ctx": OLLAMA_NUM_CTX,
                        "num_predict": OLLAMA_NUM_PREDICT,
                    },
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
                    ],
                },
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            LOGGER.warning("Fallo consultando Ollama para %s: %s", self.manager_name, exc)
            self._store_request_log("ollama", system_prompt, payload, None, None, started_at, error=str(exc))
            return None

        body = response.json()
        message = body.get("message", {}) if isinstance(body, dict) else {}
        output_text = str(message.get("content", "")).strip()
        parsed = _extract_json_payload(output_text)
        self._store_request_log("ollama", system_prompt, payload, output_text, parsed, started_at)
        return parsed

    def _log_request_start(self, backend: str, system_prompt: str, payload: dict[str, Any]) -> None:
        """Registra la llamada y, en DEBUG, el prompt completo enviado."""
        LOGGER.info(
            "LLM %s/%s consultando para %s. Claves payload=%s",
            backend,
            self.resolved_model_name if backend == "ollama" else self.model_name,
            self.manager_name,
            ", ".join(payload.keys()),
        )
        if LOG_PROMPTS:
            LOGGER.debug("Prompt sistema LLM %s: %s", self.manager_name, system_prompt)
            LOGGER.debug("Payload LLM %s: %s", self.manager_name, json.dumps(payload, ensure_ascii=False))

    def _store_request_log(
        self,
        backend: str,
        system_prompt: str,
        payload: dict[str, Any],
        raw_text: str | None,
        parsed: dict[str, Any] | None,
        started_at: float,
        *,
        error: str | None = None,
    ) -> None:
        """Guarda la auditoria completa de una llamada LLM para llm_decisions.json."""
        elapsed_seconds = round(time.perf_counter() - started_at, 3)
        self._last_request_log = {
            "backend": backend,
            "model": self.resolved_model_name if backend == "ollama" else self.model_name,
            "elapsed_seconds": elapsed_seconds,
            "system_prompt": system_prompt,
            "input_payload": payload,
            "raw_output": raw_text,
            "parsed_output": parsed or {},
            "error": error,
        }
        if error:
            LOGGER.info(
                "LLM %s/%s fallo para %s tras %.3fs",
                backend,
                self.resolved_model_name if backend == "ollama" else self.model_name,
                self.manager_name,
                elapsed_seconds,
            )
        else:
            LOGGER.info(
                "LLM %s/%s respondio para %s en %.3fs. JSON valido=%s",
                backend,
                self.resolved_model_name if backend == "ollama" else self.model_name,
                self.manager_name,
                elapsed_seconds,
                parsed is not None,
            )

    def _request_json(
        self,
        *,
        system_prompt: str,
        payload: dict[str, Any],
        response_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Despacha la peticion al backend activo y oculta sus diferencias."""
        if self.backend == "openai":
            return self._request_json_openai(system_prompt=system_prompt, payload=payload, response_schema=response_schema)
        if self.backend == "ollama":
            return self._request_json_ollama(system_prompt=system_prompt, payload=payload, response_schema=response_schema)
        return None

    def choose_sale_candidates(self, payload: dict[str, Any]) -> list[int] | None:
        """Pide al LLM IDs de jugadores vendibles y descarta respuestas no listas."""
        if not self.supports("sale_candidates"):
            return None

        response = self._request_json(
            system_prompt=(
                "Eres el asistente tactico de un manager fantasy. "
                "Debes decidir que jugadores vender segun la estrategia definida, sin romper restricciones de plantilla. "
                "Responde exactamente con el esquema JSON solicitado. "
                "No copies el input, no anides la respuesta y no uses claves extra. "
                "summary, key_factors, risk_flags y decision_trace deben ser muy cortos y en espanol."
            ),
            payload=payload,
            response_schema=SALE_SCHEMA,
        )
        self._store_decision_meta("sale_candidates", response)
        if not response:
            return None
        raw_ids = response.get("sell_player_ids", [])
        if not isinstance(raw_ids, list):
            return None
        parsed_ids: list[int] = []
        for player_id in raw_ids:
            if isinstance(player_id, int):
                parsed_ids.append(player_id)
        return parsed_ids

    def choose_market_day_plan(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Devuelve un plan diario completo: ventas y pujas del manager."""
        response = self._request_json(
            system_prompt=(
                "Manager fantasy. Decide ventas y pujas para maximizar puntos J30-J38. "
                "IDs venta en sale_candidates; IDs compra en market_open. ask/max estan en millones EUR, pero bid debe ir en euros enteros. "
                "Respeta max_sales y max_bids del payload. Responde JSON breve con sell_player_ids, bids, summary, key_factors, risk_flags, decision_trace, confidence."
            ),
            payload=payload,
            response_schema=MARKET_DAY_PLAN_SCHEMA,
        )
        if isinstance(response, dict) and isinstance(response.get("market_day_plan"), dict):
            response = {**response, **response["market_day_plan"]}
        if isinstance(response, dict) and isinstance(response.get("plan"), dict):
            response = {**response, **response["plan"]}
        self._store_decision_meta("market_day_plan", response)
        return response if isinstance(response, dict) else None

    def choose_market_bid(self, payload: dict[str, Any]) -> int | None:
        """Pide al LLM una puja individual expresada en euros."""
        if not self.supports("market_bid"):
            return None

        response = self._request_json(
            system_prompt=(
                "Eres el asistente de pujas de un manager fantasy. "
                "Debes decidir una puja entera en euros o no pujar, respetando presupuesto y estrategia. "
                "Responde exactamente con el esquema JSON solicitado. No uses claves extra."
            ),
            payload=payload,
            response_schema=BID_SCHEMA,
        )
        self._store_decision_meta("market_bid", response)
        if not response or "bid" not in response:
            return None
        bid = response.get("bid")
        return bid if isinstance(bid, int) else None

    def choose_formation(self, payload: dict[str, Any]) -> str | None:
        """Pide al LLM una unica formacion legal."""
        if not self.supports("formation"):
            return None

        response = self._request_json(
            system_prompt=(
                "Eres el asistente tactico de un manager fantasy. "
                "Debes elegir una formacion legal entre las opciones recibidas, segun la estrategia del manager. "
                "Responde exactamente con el esquema JSON solicitado. No uses claves extra."
            ),
            payload=payload,
            response_schema=FORMATION_SCHEMA,
        )
        self._store_decision_meta("formation", response)
        if not response:
            return None
        formation = response.get("formation")
        return formation if isinstance(formation, str) else None

    def choose_lineup(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Pide formacion y once completo, dejando la validacion al modelo."""
        if not self.supports("lineup"):
            return None

        response = self._request_json(
            system_prompt=(
                "Entrenador fantasy. Elige formacion y 11 IDs de squad para maximizar puntos J30-J38. "
                "Respeta posiciones de la formacion. Responde solo JSON con formation, lineup_player_ids, summary, key_factors, risk_flags, decision_trace, confidence."
            ),
            payload=payload,
            response_schema=LINEUP_SCHEMA,
        )
        if isinstance(response, dict) and isinstance(response.get("lineup"), dict):
            response = {**response, **response["lineup"]}
        if isinstance(response, dict) and isinstance(response.get("selection"), dict):
            response = {**response, **response["selection"]}
        self._store_decision_meta("lineup", response)
        return response if isinstance(response, dict) else None

