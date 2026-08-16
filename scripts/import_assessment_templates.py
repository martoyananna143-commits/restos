"""One-shot company-private assessment template import command.

Examples:
    python scripts/import_assessment_templates.py --company-id UUID
    python scripts/import_assessment_templates.py --company-id UUID --apply

Dry-run is the default. The command never logs connection settings, source
paths, answers, or personal data.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from app.infra.database.models import AssessmentTemplateVersion  # noqa: E402
from app.internal.services.assessment_template_import_service import (  # noqa: E402
    AssessmentTemplateImportService,
    AssessmentLibraryImportService,
    ReviewedManifest,
)
from app.internal.services.assessment_template_service import (  # noqa: E402
    AssessmentTemplateService,
    PublishMethodology,
    PublishTemplateVersion,
)
from app.settings import config  # noqa: E402


DATA = ROOT / "app/internal/data/assessment_template_import"
MANIFESTS = DATA / "manifests"


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--company-id", type=UUID)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--library",
        action="store_true",
        help="populate the global RestOS library with publication-ready manifests",
    )
    parser.add_argument(
        "--publish-valid",
        action="store_true",
        help="publish verified imports except waiter-kln; requires --apply",
    )
    return parser.parse_args()


def reviewed_manifests() -> list[ReviewedManifest]:
    inventory = json.loads((DATA / "source_inventory.json").read_text("utf-8"))
    if (
        set(inventory) != {"schema_version", "sources"}
        or inventory["schema_version"] != 1
    ):
        raise RuntimeError("source inventory contract invalid")
    sources = inventory["sources"]
    if not isinstance(sources, list) or len(sources) != 9:
        raise RuntimeError("source inventory must contain exactly nine sources")
    allowed = {
        (value["filename"], value["sha256"])
        for value in sources
        if isinstance(value, dict)
        and set(value) == {"filename", "sha256", "provenance", "usage"}
        and value["provenance"] == "read_only_methodology_source"
    }
    if len(allowed) != 9:
        raise RuntimeError("source inventory contains duplicates or invalid fields")
    manifests = [
        ReviewedManifest.parse(path.read_bytes())
        for path in sorted(MANIFESTS.glob("*.json"))
    ]
    if len(manifests) != 8:
        raise RuntimeError("reviewed import requires exactly eight manifests")
    if any(
        (
            value.document["source"]["filename"],
            value.document["source"]["sha256"],
        )
        not in allowed
        for value in manifests
    ):
        raise RuntimeError("manifest source is absent from reviewed inventory")
    return manifests


async def run(
    company_id: UUID | None, apply: bool, publish_valid: bool, library: bool
) -> None:
    if publish_valid and not apply:
        raise RuntimeError("--publish-valid requires --apply")
    if not library and company_id is None:
        raise RuntimeError("--company-id is required for company import")
    engine = create_async_engine(config.DATABASE_URL, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            service = AssessmentTemplateImportService(session)
            library_service = AssessmentLibraryImportService(session)
            manifests = reviewed_manifests()
            if not apply:
                for manifest in manifests:
                    plan = (
                        await library_service.plan(manifest)
                        if library
                        else await service.plan(company_id, manifest)  # type: ignore[arg-type]
                    )
                    print(
                        json.dumps(
                            {
                                "action": plan.action,
                                "template_code": plan.template_code,
                                "next_version": plan.next_version,
                                "section_count": plan.section_count,
                                "item_count": plan.item_count,
                                "source_filename": plan.source_filename,
                                "source_sha256": plan.source_sha256,
                                "manifest_sha256": plan.manifest_sha256,
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                    )
                await session.rollback()
                return
            from datetime import datetime, timezone

            rows = []
            blocked = []
            async with session.begin():
                lifecycle = AssessmentTemplateService(session)
                for manifest in manifests:
                    now = datetime.now(timezone.utc)
                    if library and not manifest.publication_ready():
                        blocked.append(manifest.document["template"]["code"])
                        continue
                    value = (
                        await library_service.apply(manifest, now)
                        if library and manifest.publication_ready()
                        else await service.apply(company_id, manifest, now)  # type: ignore[arg-type]
                    )
                    template_code = manifest.document["template"]["code"]
                    version = await session.get(
                        AssessmentTemplateVersion, value.template_version_id
                    )
                    if version is None:
                        raise RuntimeError("imported version is unavailable")
                    publication = version.status
                    if library:
                        publication = (
                            "published"
                            if manifest.publication_ready()
                            else "blocked_missing_weights"
                        )
                    elif publish_valid and manifest.publication_ready():
                        if version.status == "draft":
                            await lifecycle.publish_methodology(
                                PublishMethodology(version.methodology_id, now)
                            )
                            await lifecycle.publish_template_version(
                                PublishTemplateVersion(
                                    value.template_id,
                                    value.template_version_id,
                                    now,
                                )
                            )
                        publication = "published"
                    elif publish_valid:
                        if version.status != "draft":
                            raise RuntimeError(
                                "incomplete weighted template is already published"
                            )
                        publication = "blocked_missing_weights"
                    rows.append((value, publication, template_code))
            for template_code in blocked:
                print(
                    json.dumps(
                        {
                            "action": "blocked_missing_weights",
                            "template_code": template_code,
                            "publication": "blocked_missing_weights",
                        },
                        sort_keys=True,
                    )
                )
            for value, publication, template_code in rows:
                print(
                    json.dumps(
                        {
                            "action": value.action,
                            "template_code": template_code,
                            "template_id": str(value.template_id),
                            "template_version_id": str(value.template_version_id),
                            "version": value.version,
                            "section_count": value.section_count,
                            "item_count": value.item_count,
                            "mapping_count": value.mapping_count,
                            "publication": publication,
                        },
                        sort_keys=True,
                    )
                )
    finally:
        await engine.dispose()


def main() -> None:
    value = arguments()
    try:
        asyncio.run(run(value.company_id, value.apply, value.publish_valid, value.library))
    except Exception as error:
        print(type(error).__name__, file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
