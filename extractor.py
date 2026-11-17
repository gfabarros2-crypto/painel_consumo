"""Extrai tabelas mensais dos PDFs textuais da EMPETUR, sem inferir lacunas."""

from __future__ import annotations

import io
import re
from collections import Counter

import pdfplumber

MONTHS = {
    "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
    "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12,
}
ROW = re.compile(
    r"^\s*(jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)\.?\s*[-/\u2013\u2014\u2212\ufffd]\s*(20\d{2}|\d{2})\b(.*)$",
    re.IGNORECASE | re.DOTALL,
)
NUMBER = re.compile(r"(?<!\w)\d[\d.,]*")
MONEY = re.compile(r"R\$\s*([\d.,]+)", re.IGNORECASE)


def br_number(value: str) -> float:
    cleaned = value.strip().replace(".", "").replace(",", ".")
    return float(cleaned)


def period_from_match(match: re.Match) -> str:
    year = int(match[2])
    if year < 100:
        year += 2000
    return f"{year:04d}-{MONTHS[match[1].lower()]:02d}"


def make_row(resource: str, period: str, consumption: float | None, total: float | None) -> dict:
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


def parse_table_row(cells: list[str | None], resource: str) -> dict | None:
    """Lê mês, consumo e fatura das colunas, mesmo com linhas visuais distintas."""
    for index, cell in enumerate(cells):
        match = ROW.match(cell or "")
        if not match:
            continue
        following = cells[index + 1:]
        consumption_cell = (following[0] or "") if following else ""
        numbers = NUMBER.findall(consumption_cell) if "R$" not in consumption_cell.upper() else []
        consumption = br_number(numbers[0]) if len(numbers) == 1 else None
        amounts = [amount for value in following for amount in MONEY.findall(value or "")]
        total = br_number(amounts[0]) if len(amounts) == 1 else None
        return make_row(resource, period_from_match(match), consumption, total)
    return None


def flag_year_outliers(rows: list[dict]) -> bool:
    """Destaca anos misturados sem substituir o que está escrito no PDF."""
    years = Counter(row["period"][:4] for row in rows)
    if len(years) < 2:
        return False
    dominant_year, count = years.most_common(1)[0]
    tied = sum(value == count for value in years.values()) > 1
    for row in rows:
        if tied or row["period"][:4] != dominant_year:
            detail = ("O PDF contém anos diferentes, sem um ano predominante." if tied
                      else f"A maioria dos meses do PDF é de {dominant_year}.")
            row["period_warning"] = f"O PDF informa {row['period'][5:7]}/{row['period'][:4]}. {detail} Confira o ano antes de publicar."
            row["period_review_confirmed"] = False
            row["needs_review"] = True
    return True


def parse_row_line(line: str, resource: str) -> dict | None:
    match = ROW.match(line)
    if not match:
        return None
    period = period_from_match(match)
    remainder = match[3]
    amounts = MONEY.findall(remainder)
    first_money = MONEY.search(remainder)
    before_money = remainder[: first_money.start()] if first_money else remainder
    number = NUMBER.search(before_money)
    consumption = br_number(number.group()) if number else None
    # Se há água, esgoto, encargos etc. na mesma linha, não presumimos qual é o total.
    total = br_number(amounts[0]) if len(amounts) == 1 else None
    return make_row(resource, period, consumption, total)


def parse_pdf(pdf_bytes: bytes, resource: str) -> dict:
    if resource not in ("water", "energy"):
        raise ValueError("Selecione Água ou Energia.")
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
            table_rows = [row for page in pdf.pages for table in page.extract_tables()
                          for cells in table if (row := parse_table_row(cells, resource))]
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
    rows = table_rows
    if not rows:
        pending = None
        for line in text.splitlines():
            if ROW.match(line):
                if pending:
                    rows.append(parse_row_line(pending, resource))
                pending = line
            elif pending and MONEY.search(line):
                rows.append(parse_row_line(f"{pending} {line}", resource))
                pending = None
            if pending and MONEY.search(pending):
                rows.append(parse_row_line(pending, resource))
                pending = None
        if pending:
            rows.append(parse_row_line(pending, resource))
        rows = [row for row in rows if row]
    warnings = []
    if not rows:
        warnings.append("Nenhuma linha mensal reconhecida. Adicione os registros manualmente após conferir o PDF.")
    if flag_year_outliers(rows):
        warnings.append("O PDF contém competências com anos diferentes; confira as linhas destacadas antes de publicar.")
    if any(row["consumption"] is None or row["total_brl"] is None for row in rows):
        warnings.append("Algumas linhas estão incompletas; corrija os campos destacados antes de publicar.")
    return {"rows": rows, "warnings": warnings}
