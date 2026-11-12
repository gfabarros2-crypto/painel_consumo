"""Extrai tabelas mensais dos PDFs textuais da EMPETUR, sem inferir lacunas."""

from __future__ import annotations

import io
import re

import pdfplumber

MONTHS = {
    "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
    "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12,
}
ROW = re.compile(
    r"^\s*(jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)\.?\s*[-/]\s*(\d{2}|20\d{2})\b(.*)$",
    re.IGNORECASE,
)
NUMBER = re.compile(r"(?<!\w)\d[\d.,]*")
MONEY = re.compile(r"R\$\s*([\d.,]+)", re.IGNORECASE)


def br_number(value: str) -> float:
    cleaned = value.strip().replace(".", "").replace(",", ".")
    return float(cleaned)


def parse_row_line(line: str, resource: str) -> dict | None:
    match = ROW.match(line)
    if not match:
        return None
    year = int(match[2])
    if year < 100:
        year += 2000
    period = f"{year:04d}-{MONTHS[match[1].lower()]:02d}"
    remainder = match[3]
    amounts = MONEY.findall(remainder)
    first_money = MONEY.search(remainder)
    before_money = remainder[: first_money.start()] if first_money else remainder
    number = NUMBER.search(before_money)
    consumption = br_number(number.group()) if number else None
    # Se há água, esgoto, encargos etc. na mesma linha, não presumimos qual é o total.
    total = br_number(amounts[0]) if len(amounts) == 1 else None
    return {
        "resource": resource,
        "period": period,
        "consumption": consumption,
        "total_brl": total,
        "water_brl": None,
        "sewage_brl": None,
        "source_url": "",
        "receipt_url": "",
        "receipt_approved": False,
        "needs_review": consumption is None or total is None,
    }


def parse_pdf(pdf_bytes: bytes, resource: str) -> dict:
    if resource not in ("water", "energy"):
        raise ValueError("Selecione Água ou Energia.")
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    except Exception as exc:
        raise ValueError("O arquivo não pôde ser lido como PDF.") from exc
    if not text.strip():
        return {"rows": [], "warnings": [
            "O PDF não contém texto selecionável. Use a inclusão manual ou gere uma versão com OCR."
        ]}
    lower = text.lower()
    if resource == "water" and ("energia" in lower or "kwh" in lower) and "água" not in lower and "�gua" not in lower:
        raise ValueError("O documento parece ser de energia; confira o recurso selecionado.")
    if resource == "energy" and ("água" in lower or "�gua" in lower) and "energia" not in lower and "kwh" not in lower:
        raise ValueError("O documento parece ser de água; confira o recurso selecionado.")
    rows = []
    for line in text.splitlines():
        row = parse_row_line(line, resource)
        if row:
            rows.append(row)
    warnings = []
    if not rows:
        warnings.append("Nenhuma linha mensal reconhecida. Adicione os registros manualmente após conferir o PDF.")
    if any(row["needs_review"] for row in rows):
        warnings.append("Algumas linhas estão incompletas; corrija os campos destacados antes de publicar.")
    return {"rows": rows, "warnings": warnings}
