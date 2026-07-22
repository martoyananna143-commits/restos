"""Fetch and parse Google Sheets used as live criterion sources."""

from __future__ import annotations

import re
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

import httpx
from loguru import logger

from app.settings import config


@dataclass
class ParsedSheetRow:
    """One row from a Google Sheet criterion template."""

    block: str
    criterion: str
    value_type: str  # boolean | number | string
    sort_order: int


@dataclass
class ParsedSheetResult:
    rows: list[ParsedSheetRow]
    blocks: list[str]
    spreadsheet_id: str
    sheet_gid: Optional[str] = None


class GoogleSheetError(Exception):
    """User-facing fetch/parse failure."""


_TYPE_MAPPING = {
    "boolean": "boolean",
    "bool": "boolean",
    "string": "string",
    "str": "string",
    "text": "string",
    "number": "number",
    "num": "number",
    "numeric": "number",
    "integer": "number",
    "int": "number",
    "float": "number",
    "да/нет": "boolean",
    "да нет": "boolean",
    "логический": "boolean",
    "булевый": "boolean",
    "текст": "string",
    "строка": "string",
    "текстовый": "string",
    "число": "number",
    "числовой": "number",
    "цифра": "number",
    "оценка": "number",
    "балл": "number",
    "балльная": "number",
    "балльная система": "number",
    "шкала": "number",
    "1-5": "number",
    "1–5": "number",
}

_HEADER_KW = [
    "блок",
    "block",
    "раздел",
    "критерий",
    "criterion",
    "question",
    "вопрос",
    "тип",
    "type",
]


def slugify(text: str, max_len: int = 80) -> str:
    """ASCII-ish slug for stable criterion codes."""
    s = (text or "").strip().lower()
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    s = re.sub(r"[-\s]+", "_", s).strip("_")
    if not s:
        return "item"
    return s[:max_len]


def parse_spreadsheet_url(url: str) -> tuple[str, Optional[str]]:
    """Extract spreadsheet id and optional gid from a Google Sheets URL."""
    raw = (url or "").strip()
    if not raw:
        raise GoogleSheetError("Укажите ссылку на Google Таблицу")

    # Direct ID passed
    if re.fullmatch(r"[a-zA-Z0-9_-]{20,}", raw):
        return raw, None

    parsed = urlparse(raw)
    host = (parsed.netloc or "").lower()
    if "docs.google.com" not in host and "drive.google.com" not in host:
        raise GoogleSheetError("Ссылка должна вести на Google Таблицу (docs.google.com)")

    path = parsed.path or ""
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", path)
    if not match:
        raise GoogleSheetError("Не удалось определить ID таблицы из ссылки")

    spreadsheet_id = match.group(1)
    qs = parse_qs(parsed.query or "")
    gid = (qs.get("gid") or [None])[0]
    if gid is None and parsed.fragment:
        frag = parse_qs(parsed.fragment.lstrip("#").replace("=", "="))
        gid = (frag.get("gid") or [None])[0]
        if gid is None and parsed.fragment.startswith("gid="):
            gid = parsed.fragment.split("=", 1)[-1]
    return spreadsheet_id, gid


def parse_drive_folder_url(url: str) -> str:
    """Extract folder id from a Google Drive folder URL."""
    raw = (url or "").strip()
    if not raw:
        raise GoogleSheetError("Укажите ссылку на папку Google Drive")

    parsed = urlparse(raw)
    path = parsed.path or ""
    match = re.search(r"/folders/([a-zA-Z0-9_-]+)", path)
    if match:
        return match.group(1)
    qs = parse_qs(parsed.query or "")
    fid = (qs.get("id") or [None])[0]
    if fid:
        return fid
    raise GoogleSheetError("Не удалось определить ID папки из ссылки")


def export_url(spreadsheet_id: str, gid: Optional[str] = None) -> str:
    base = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=xlsx"
    if gid:
        return f"{base}&gid={gid}"
    return base


def _map_type(raw: str) -> str:
    key = (raw or "").strip().lower()
    if not key:
        return "boolean"
    if key in _TYPE_MAPPING:
        return _TYPE_MAPPING[key]
    if "балл" in key or "шкал" in key or "оцен" in key:
        return "number"
    if "да" in key and "нет" in key:
        return "boolean"
    return "boolean"


def _parse_xlsx_bytes(content: bytes, max_rows: int) -> list[list[str]]:
    rows_data: list[list[str]] = []
    num_columns = 3

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        try:
            with zipfile.ZipFile(tmp_path, "r") as zf:
                shared_strings: list[str] = []
                try:
                    with zf.open("xl/sharedStrings.xml") as f:
                        tree = ET.parse(f)
                        ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                        for si in tree.getroot().findall(".//x:si", ns):
                            t = si.find(".//x:t", ns)
                            shared_strings.append(t.text if t is not None and t.text else "")
                except KeyError:
                    pass

                with zf.open("xl/worksheets/sheet1.xml") as f:
                    tree = ET.parse(f)
                    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                    for row in tree.getroot().findall(".//x:row", ns):
                        cells: dict[int, str] = {}
                        for cell in row.findall(".//x:c", ns):
                            ref = cell.get("r")
                            if not ref:
                                continue
                            col_num = 0
                            for ch in ref:
                                if ch.isalpha():
                                    col_num = col_num * 26 + (ord(ch.upper()) - ord("A") + 1)
                                else:
                                    break
                            col_num -= 1
                            v = cell.find("x:v", ns)
                            val = ""
                            if v is not None and v.text:
                                if cell.get("t") == "s":
                                    idx = int(v.text)
                                    val = shared_strings[idx] if idx < len(shared_strings) else ""
                                else:
                                    val = v.text
                            cells[col_num] = val
                        row_vals = [cells.get(i, "") for i in range(num_columns)]
                        rows_data.append([str(v).strip() for v in row_vals])
        except Exception as zip_err:
            logger.warning("Google sheet ZIP parse failed: {}", zip_err)
            from openpyxl import load_workbook

            wb = load_workbook(tmp_path, read_only=True, data_only=True)
            ws = wb.active
            rows_data = []
            for row_tuple in ws.iter_rows(values_only=True):
                vals = list(row_tuple) + [""] * num_columns
                rows_data.append([str(v).strip() if v else "" for v in vals[:num_columns]])
            wb.close()
    finally:
        tmp_path.unlink(missing_ok=True)

    if len(rows_data) > max_rows:
        rows_data = rows_data[:max_rows]
    return rows_data


def parse_sheet_rows(rows_data: list[list[str]]) -> list[ParsedSheetRow]:
    """Parse raw 3-column rows into criterion rows."""
    start_idx = 0
    if rows_data:
        cols_lower = [str(c).lower().strip() for c in rows_data[0]]
        # Treat row as header only when first two columns both look like labels.
        is_header = (
            any(kw in cols_lower[0] for kw in _HEADER_KW)
            and any(kw in cols_lower[1] for kw in _HEADER_KW)
        )
        if is_header:
            start_idx = 1

    parsed: list[ParsedSheetRow] = []
    current_block = "Общее"
    order = 0
    for row in rows_data[start_idx:]:
        block, criterion, raw_type = (row + ["", "", ""])[:3]
        if not criterion and block:
            current_block = block
            continue
        if not criterion:
            continue
        if block:
            current_block = block
        order += 1
        parsed.append(
            ParsedSheetRow(
                block=current_block or "Общее",
                criterion=criterion,
                value_type=_map_type(raw_type),
                sort_order=order,
            )
        )
    return parsed


class GoogleSheetService:
    """Download public/shared Google Sheets and parse criterion templates."""

    def __init__(
        self,
        timeout: float | None = None,
        max_rows: int | None = None,
    ):
        self.timeout = timeout or float(getattr(config, "GOOGLE_SHEETS_FETCH_TIMEOUT", 15))
        self.max_rows = max_rows or int(getattr(config, "GOOGLE_SHEETS_MAX_ROWS", 500))

    async def fetch_and_parse(
        self,
        url: str,
        *,
        spreadsheet_id: Optional[str] = None,
        gid: Optional[str] = None,
    ) -> ParsedSheetResult:
        sid, url_gid = parse_spreadsheet_url(url) if spreadsheet_id is None else (spreadsheet_id, gid)
        effective_gid = gid if gid is not None else url_gid
        export = export_url(sid, effective_gid)

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
            ) as client:
                resp = await client.get(export)
        except httpx.HTTPError as exc:
            raise GoogleSheetError(
                "Не удалось подключиться к Google Таблице. Проверьте ссылку и доступ."
            ) from exc

        if resp.status_code in (401, 403):
            raise GoogleSheetError(
                "Таблица недоступна. Откройте доступ «по ссылке — просмотр» "
                "или подключите сервисный Google-аккаунт (см. настройки)."
            )
        if resp.status_code == 404:
            raise GoogleSheetError("Таблица не найдена. Проверьте ссылку.")
        if resp.status_code >= 400:
            raise GoogleSheetError(f"Google вернул ошибку {resp.status_code}")

        content = resp.content
        if not content or len(content) < 100:
            raise GoogleSheetError("Пустой ответ от Google — проверьте, что в таблице есть данные.")

        rows_data = _parse_xlsx_bytes(content, self.max_rows)
        rows = parse_sheet_rows(rows_data)
        if not rows:
            raise GoogleSheetError(
                "В таблице не найдено критериев. Ожидаются 3 столбца: Блок | Критерий | Тип."
            )

        blocks: list[str] = []
        seen: set[str] = set()
        for r in rows:
            if r.block not in seen:
                seen.add(r.block)
                blocks.append(r.block)

        return ParsedSheetResult(
            rows=rows,
            blocks=blocks,
            spreadsheet_id=sid,
            sheet_gid=effective_gid,
        )

    def criterion_code(self, spreadsheet_id: str, block: str, criterion: str) -> str:
        """Stable code for upsert within an org."""
        prefix = f"gs_{spreadsheet_id[:12]}_{slugify(block)}_{slugify(criterion)}"
        return prefix[:100]
