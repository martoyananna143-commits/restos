"""Sync criterion sets from Google Sheets into PostgreSQL."""

from __future__ import annotations

import time
from typing import Optional

from app.infra.database.connection.postgresql.connection import (
    _get_connection as get_connection,
)
from app.infra.database.repository.criterion.dto import CreateCriterionDTO, UpdateCriterionDTO
from app.infra.database.repository.criterion_set.dto import UpdateCriterionSetDTO
from app.internal.services.criterion_service import CriterionService
from app.internal.services.criterion_set_service import CriterionSetService
from app.internal.services.google_sheet_service import (
    GoogleSheetError,
    GoogleSheetService,
    ParsedSheetResult,
    slugify,
)


class GoogleCriterionSyncService:
    """Fetch Google Sheet rows and upsert categories/criteria for a criterion set."""

    MIN_FETCH_INTERVAL_SEC = 30

    def __init__(
        self,
        sheet_service: GoogleSheetService,
        criterion_set_service: CriterionSetService,
        criterion_service: CriterionService,
    ):
        self.sheet_service = sheet_service
        self.criterion_set_service = criterion_set_service
        self.criterion_service = criterion_service

    async def preview(self, url: str) -> ParsedSheetResult:
        return await self.sheet_service.fetch_and_parse(url)

    async def sync_set(
        self,
        criterion_set_id: int,
        organization_id: int,
        *,
        force: bool = False,
    ) -> list[int]:
        """Refresh criteria for a google-linked set. Returns criterion ids."""
        crit_set = await self.criterion_set_service.get_by_id(criterion_set_id)
        if not crit_set or crit_set.organization_id != organization_id:
            raise GoogleSheetError("Набор критериев не найден")

        source_type = getattr(crit_set, "source_type", None) or "internal"
        if source_type not in ("google_sheet", "google_drive_folder"):
            return crit_set.criterion_ids or []

        meta = dict(getattr(crit_set, "source_meta", None) or {})
        if not force:
            last = meta.get("last_fetch_at")
            if isinstance(last, (int, float)) and time.time() - float(last) < self.MIN_FETCH_INTERVAL_SEC:
                return crit_set.criterion_ids or []

        url = crit_set.source_url or ""
        spreadsheet_id = meta.get("spreadsheet_id")
        gid = meta.get("sheet_gid")

        try:
            if spreadsheet_id:
                parsed = await self.sheet_service.fetch_and_parse(
                    url or spreadsheet_id,
                    spreadsheet_id=spreadsheet_id,
                    gid=gid,
                )
            else:
                parsed = await self.sheet_service.fetch_and_parse(url)
        except GoogleSheetError as exc:
            meta["last_error"] = str(exc)
            await self._update_meta(criterion_set_id, meta, success=False)
            raise

        criterion_ids = await self._upsert_rows(
            organization_id=organization_id,
            criterion_set_id=criterion_set_id,
            parsed=parsed,
        )

        meta.update(
            {
                "spreadsheet_id": parsed.spreadsheet_id,
                "sheet_gid": parsed.sheet_gid,
                "last_fetch_at": int(time.time()),
                "last_error": None,
                "rows_count": len(parsed.rows),
                "blocks": parsed.blocks,
            }
        )
        await self.criterion_set_service.update(
            criterion_set_id,
            UpdateCriterionSetDTO(
                criterion_ids=criterion_ids,
                source_meta=meta,
            ),
        )
        return criterion_ids

    async def _update_meta(
        self,
        criterion_set_id: int,
        meta: dict,
        *,
        success: bool,
    ) -> None:
        if not success:
            meta["last_fetch_at"] = int(time.time())
        await self.criterion_set_service.update(
            criterion_set_id,
            UpdateCriterionSetDTO(source_meta=meta),
        )

    async def _upsert_rows(
        self,
        *,
        organization_id: int,
        criterion_set_id: int,
        parsed: ParsedSheetResult,
    ) -> list[int]:
        org_criteria = await self.criterion_service.get_by_organization_id(organization_id)
        by_code = {c.code: c for c in org_criteria}

        category_ids: dict[str, int] = {}
        criterion_ids: list[int] = []

        for row in parsed.rows:
            cat_id = await self._ensure_category(
                organization_id, row.block, category_ids
            )
            code = self.sheet_service.criterion_code(
                parsed.spreadsheet_id, row.block, row.criterion
            )
            existing = by_code.get(code)
            if existing:
                await self.criterion_service.update(
                    existing.id,
                    UpdateCriterionDTO(
                        name=row.criterion,
                        category_id=cat_id,
                        value_type=row.value_type,
                        sort_order=row.sort_order,
                        is_active=True,
                    ),
                )
                criterion_ids.append(existing.id)
            else:
                created = await self.criterion_service.create(
                    CreateCriterionDTO(
                        organization_id=organization_id,
                        name=row.criterion,
                        code=code,
                        category_id=cat_id,
                        description=f"Блок: {row.block}",
                        sort_order=row.sort_order,
                        value_type=row.value_type,
                        is_required=True,
                        is_active=True,
                    )
                )
                by_code[code] = created
                criterion_ids.append(created.id)

        return criterion_ids

    async def _ensure_category(
        self,
        organization_id: int,
        block_name: str,
        cache: dict[str, int],
    ) -> Optional[int]:
        key = block_name or "Общее"
        if key in cache:
            return cache[key]

        code = f"org{organization_id}_{slugify(key)}"[:50]
        pool = await self.criterion_service.repository._get_pool()
        async with get_connection(pool) as conn:
            row = await conn.fetchrow_b(
                """
                SELECT id FROM categories
                WHERE code = :code AND parent_id IS NULL AND deleted_at IS NULL
                LIMIT 1
                """,
                code=code,
            )
            if row:
                cache[key] = row["id"]
                return row["id"]

            row = await conn.fetchrow_b(
                """
                INSERT INTO categories (name, code, description, sort_order, is_active)
                VALUES (:name, :code, :description, 0, true)
                RETURNING id
                """,
                name=key[:100],
                code=code,
                description=f"Блок из Google Таблицы (org {organization_id})",
            )
            cat_id = row["id"]
            cache[key] = cat_id
            return cat_id
