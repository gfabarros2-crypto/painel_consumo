"""Regras e normalização únicas para o painel de consumo da EMPETUR."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

RESOURCES = {"water": "Água", "energy": "Energia"}
PERIOD_RE = re.compile(r"^(20\d{2})-(0[1-9]|1[0-2])$")


def shift_month(period: str, offset: int) -> str:
    match = PERIOD_RE.fullmatch(period)
    if not match:
        raise ValueError("Período inválido; use AAAA-MM.")
    index = int(match[1]) * 12 + int(match[2]) - 1 + offset
    year, month = divmod(index, 12)
    return f"{year:04d}-{month + 1:02d}"


def to_decimal(value, field: str, required: bool = False) -> Decimal | None:
    if value is None or value == "":
        if required:
            raise ValueError(f"{field} é obrigatório.")
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field} deve ser um número.")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"{field} deve ser um número.") from exc
    if not number.is_finite() or number < 0:
        raise ValueError(f"{field} deve ser zero ou maior.")
    return number


def valid_url(value: str, field: str, allow_local: bool = False) -> str:
    if not value:
        return ""
    if allow_local and re.fullmatch(r"planilhas/[A-Za-z0-9._-]+\.pdf", value):
        return value
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"{field} deve ser uma URL HTTPS.")
    return value


def normalize_record(raw: dict) -> dict:
    resource = raw.get("resource")
    period = raw.get("period", "")
    if resource not in RESOURCES:
        raise ValueError("Recurso inválido.")
    if not PERIOD_RE.fullmatch(period):
        raise ValueError("Período inválido; use AAAA-MM.")
    consumption = to_decimal(raw.get("consumption"), "Consumo")
    total = to_decimal(raw.get("total_brl"), "Total faturado")
    if consumption is None and total is None:
        raise ValueError("Informe ao menos consumo ou valor faturado.")
    consumption_missing_confirmed = raw.get("consumption_missing_confirmed") is True
    total_missing_confirmed = raw.get("total_missing_confirmed") is True
    if consumption is None and not consumption_missing_confirmed:
        raise ValueError("Confirme que o consumo não consta na fonte ou corrija a leitura.")
    if total is None and not total_missing_confirmed:
        raise ValueError("Confirme que o valor faturado não consta na fonte ou corrija a leitura.")
    water = to_decimal(raw.get("water_brl"), "Valor da água")
    sewage = to_decimal(raw.get("sewage_brl"), "Valor do esgoto")
    if resource == "energy" and (water is not None or sewage is not None):
        raise ValueError("Água e esgoto só se aplicam à aba Água.")
    source_url = valid_url(str(raw.get("source_url") or "").strip(), "Link da planilha", allow_local=True)
    receipt_url = valid_url(str(raw.get("receipt_url") or "").strip(), "Link do comprovante")
    receipt_approved = raw.get("receipt_approved") is True
    if receipt_approved and not receipt_url:
        raise ValueError("Informe o link do comprovante aprovado.")
    return {
        "resource": resource,
        "period": period,
        "consumption": float(consumption) if consumption is not None else None,
        "total_brl": float(total) if total is not None else None,
        "water_brl": float(water) if water is not None else None,
        "sewage_brl": float(sewage) if sewage is not None else None,
        "source_url": source_url or None,
        "receipt_url": receipt_url or None,
        "receipt_approved": receipt_approved,
        "consumption_missing_confirmed": consumption_missing_confirmed,
        "total_missing_confirmed": total_missing_confirmed,
    }


def classify(consumption: Decimal, average: Decimal) -> dict:
    """Lei 16.847/2020, art. 2º. Lacunas/choques literais ficam pendentes.

    A lei não define (10%, 11%) nem resolve a sobreposição em 50%.
    Sem regra institucional, não atribuímos cor nesses casos.
    """
    if average <= 0:
        return {"code": "unavailable", "label": "Comparação indisponível"}
    delta = (consumption / average - 1) * 100
    if delta < 0:
        return {"code": "conscious", "label": "Consciente"}
    if delta <= 10:
        return {"code": "adequate", "label": "Adequado"}
    if delta < 11:
        return {"code": "pending", "label": "Classificação pendente"}
    if delta < 50:
        return {"code": "alert", "label": "Em alerta"}
    if delta == 50:
        return {"code": "pending", "label": "Classificação pendente"}
    return {"code": "abusive", "label": "Abusivo"}


def analyze(records: list[dict], resource: str, period: str) -> dict:
    if resource not in RESOURCES:
        raise ValueError("Recurso inválido.")
    if not PERIOD_RE.fullmatch(period):
        raise ValueError("Período inválido.")
    by_period = {r["period"]: r for r in records if r["resource"] == resource}
    months = [shift_month(period, -offset) for offset in range(6, 0, -1)]
    history = [{"period": month, "record": by_period.get(month)} for month in months]
    selected = by_period.get(period)
    complete = all(item["record"] is not None and item["record"].get("consumption") is not None for item in history)
    average = None
    variation = None
    status = {"code": "unavailable", "label": "Comparação indisponível"}
    comparison_reason = None
    if not complete:
        comparison_reason = "Faltam valores de consumo em um ou mais dos seis meses-calendário anteriores."
    else:
        average_decimal = sum(
            Decimal(str(item["record"]["consumption"])) for item in history
        ) / 6
        average = float(average_decimal)
        if average_decimal == 0:
            comparison_reason = "A média dos seis meses anteriores é zero."
        elif selected is not None and selected.get("consumption") is not None:
            consumption = Decimal(str(selected["consumption"]))
            variation = float((consumption / average_decimal - 1) * 100)
            status = classify(consumption, average_decimal)
            if status["code"] == "pending":
                comparison_reason = "A lei deixa esta faixa sem definição única; aguarda critério institucional."
    if selected is not None and selected.get("consumption") is None:
        comparison_reason = "O demonstrativo informa o valor faturado, mas não o consumo em kWh; não é possível calcular variação ou classificação."
    return {
        "resource": resource,
        "period": period,
        "selected": selected,
        "history": history,
        "average": average,
        "variation_percent": variation,
        "status": status,
        "comparison_reason": comparison_reason,
    }


def public_record(record: dict) -> dict:
    result = {key: record.get(key) for key in (
        "resource", "period", "consumption", "total_brl", "water_brl",
        "sewage_brl", "source_url", "receipt_approved"
    )}
    result["receipt_url"] = record.get("receipt_url") if record.get("receipt_approved") else None
    return result
