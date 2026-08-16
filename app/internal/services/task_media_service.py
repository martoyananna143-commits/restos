"""Private task-photo validation and storage-boundary orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import struct
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database.models.employee_profile import EmployeeProfile
from app.infra.database.models.organization_workflow import (
    Task,
    TaskAssignment,
    TaskPhoto,
)
from app.internal.services.access_decision_service import AccessDecisionService
from app.internal.services.organization_workflow_service import (
    OrganizationWorkflowInvalid,
    OrganizationWorkflowNotFound,
)


MAX_PHOTO_BYTES = 10 * 1024 * 1024
MAX_TASK_PHOTOS = 5


class PrivateMediaStore(Protocol):
    """Private object-store boundary; implementations never expose credentials."""

    async def verify_security(self) -> None: ...

    async def put_temporary(
        self, object_key: str, content: bytes, mime_type: str
    ) -> None: ...

    async def promote(self, temporary_key: str, final_key: str) -> None: ...

    async def get(self, object_key: str, max_bytes: int) -> bytes: ...

    async def delete(self, object_key: str) -> None: ...

    async def list_temporary(self, older_than: datetime, limit: int) -> list[str]: ...


@dataclass(frozen=True)
class ReserveTaskPhoto:
    actor_account_id: UUID
    company_id: UUID
    task_id: UUID
    task_assignment_id: UUID | None
    declared_mime_type: str
    content: bytes
    now: datetime


@dataclass(frozen=True)
class ReservedTaskPhoto:
    photo_id: UUID
    temporary_object_key: str
    final_object_key: str
    mime_type: str
    content: bytes
    digest: bytes


@dataclass(frozen=True)
class DeleteTaskPhoto:
    photo: dict[str, object]
    object_key: str
    already_deleted: bool


@dataclass(frozen=True)
class ExpiredTaskPhoto:
    photo_id: UUID
    company_id: UUID
    object_key: str


@dataclass(frozen=True)
class AuthorizedTaskPhoto:
    object_key: str
    mime_type: str
    byte_size: int
    digest: bytes


class TaskMediaService:
    """Authorize and persist media metadata without owning transaction commits."""

    def __init__(self, session: AsyncSession):
        self._session = session
        self._access = AccessDecisionService(session)

    async def reserve(self, command: ReserveTaskPhoto) -> ReservedTaskPhoto:
        now = self._aware(command.now)
        content, mime_type, extension = sanitize_image(
            command.content, command.declared_mime_type
        )
        task = (
            await self._session.execute(
                select(Task)
                .where(
                    Task.id == command.task_id,
                    Task.company_id == command.company_id,
                    Task.status.in_(("draft", "assigned")),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if task is None:
            raise OrganizationWorkflowNotFound("task is unavailable")
        if command.task_assignment_id is None:
            if task.author_account_id != command.actor_account_id:
                allowed = await self._access.can_for_venue(
                    command.actor_account_id,
                    command.company_id,
                    "task.manage",
                    task.venue_id,
                    now,
                )
                if not allowed:
                    raise OrganizationWorkflowNotFound("task is unavailable")
        else:
            assignment = (
                await self._session.execute(
                    select(TaskAssignment)
                    .join(
                        EmployeeProfile,
                        (EmployeeProfile.id == TaskAssignment.employee_profile_id)
                        & (EmployeeProfile.company_id == TaskAssignment.company_id),
                    )
                    .where(
                        TaskAssignment.id == command.task_assignment_id,
                        TaskAssignment.task_id == task.id,
                        TaskAssignment.company_id == task.company_id,
                        TaskAssignment.status.in_(("assigned", "changes_requested")),
                        EmployeeProfile.account_id == command.actor_account_id,
                        EmployeeProfile.employment_status == "active",
                        EmployeeProfile.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if assignment is None:
                raise OrganizationWorkflowNotFound("task assignment is unavailable")
        count = (
            await self._session.execute(
                select(func.count(TaskPhoto.id)).where(
                    TaskPhoto.task_id == task.id,
                    TaskPhoto.task_assignment_id == command.task_assignment_id,
                    TaskPhoto.media_status != "deleted",
                )
            )
        ).scalar_one()
        if count >= MAX_TASK_PHOTOS:
            raise OrganizationWorkflowInvalid("task photo limit is reached")
        photo_id = uuid4()
        relative_key = (
            f"companies/{command.company_id.hex}/tasks/{task.id.hex}/"
            f"{photo_id.hex}.{extension}"
        )
        temporary_object_key = f"temporary/{relative_key}"
        final_object_key = f"evidence/{relative_key}"
        digest = hashlib.sha256(content).digest()
        self._session.add(
            TaskPhoto(
                id=photo_id,
                task_id=task.id,
                task_assignment_id=command.task_assignment_id,
                company_id=task.company_id,
                uploaded_by_account_id=command.actor_account_id,
                object_key=temporary_object_key,
                mime_type=mime_type,
                byte_size=len(content),
                sha256_digest=digest,
                media_status="pending",
                created_at=now,
                updated_at=now,
            )
        )
        await self._session.flush()
        return ReservedTaskPhoto(
            photo_id,
            temporary_object_key,
            final_object_key,
            mime_type,
            content,
            digest,
        )

    async def mark_ready(
        self,
        company_id: UUID,
        photo_id: UUID,
        digest: bytes,
        now: datetime,
        final_object_key: str | None = None,
    ) -> dict[str, object]:
        checked_now = self._aware(now)
        photo = (
            await self._session.execute(
                select(TaskPhoto)
                .where(
                    TaskPhoto.id == photo_id,
                    TaskPhoto.company_id == company_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if (
            photo is None
            or photo.media_status != "pending"
            or not isinstance(digest, bytes)
            or len(digest) != 32
            or not hmac.compare_digest(photo.sha256_digest, digest)
        ):
            raise OrganizationWorkflowNotFound("task photo is unavailable")
        expected_final_key = photo.object_key.replace("temporary/", "evidence/", 1)
        if (
            not photo.object_key.startswith("temporary/")
            or final_object_key is not None
            and final_object_key != expected_final_key
        ):
            raise OrganizationWorkflowNotFound("task photo is unavailable")
        photo.object_key = expected_final_key
        photo.media_status = "ready"
        photo.updated_at = checked_now
        await self._session.flush()
        return self._photo(photo)

    async def begin_delete(
        self,
        actor_account_id: UUID,
        company_id: UUID,
        task_id: UUID,
        photo_id: UUID,
        now: datetime,
    ) -> DeleteTaskPhoto:
        """Authorize deletion and persist a retryable deleting state."""
        checked_now = self._aware(now)
        row = (
            await self._session.execute(
                select(TaskPhoto, Task)
                .join(
                    Task,
                    (Task.id == TaskPhoto.task_id)
                    & (Task.company_id == TaskPhoto.company_id),
                )
                .where(
                    TaskPhoto.id == photo_id,
                    TaskPhoto.company_id == company_id,
                    TaskPhoto.task_id == task_id,
                    TaskPhoto.media_status.in_(
                        ("pending", "ready", "deleting", "deleted")
                    ),
                )
                .with_for_update(of=TaskPhoto)
            )
        ).one_or_none()
        if row is None:
            raise OrganizationWorkflowNotFound("task photo is unavailable")
        photo, task = row
        allowed = task.author_account_id == actor_account_id and task.status == "draft"
        if photo.task_assignment_id is not None:
            allowed = (
                await self._session.execute(
                    select(TaskAssignment.id)
                    .join(
                        EmployeeProfile,
                        (EmployeeProfile.id == TaskAssignment.employee_profile_id)
                        & (EmployeeProfile.company_id == TaskAssignment.company_id),
                    )
                    .where(
                        TaskAssignment.id == photo.task_assignment_id,
                        TaskAssignment.status.in_(("assigned", "changes_requested")),
                        EmployeeProfile.account_id == actor_account_id,
                        EmployeeProfile.employment_status == "active",
                        EmployeeProfile.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none() is not None
        if not allowed and task.status == "draft":
            allowed = await self._access.can_for_venue(
                actor_account_id, company_id, "task.manage", task.venue_id, checked_now
            )
        if not allowed:
            raise OrganizationWorkflowNotFound("task photo is unavailable")
        if photo.media_status == "deleted":
            return DeleteTaskPhoto(self._photo(photo), photo.object_key, True)
        photo.media_status = "deleting"
        photo.updated_at = checked_now
        await self._session.flush()
        return DeleteTaskPhoto(self._photo(photo), photo.object_key, False)

    async def finalize_delete(
        self, company_id: UUID, photo_id: UUID, now: datetime
    ) -> dict[str, object]:
        checked_now = self._aware(now)
        photo = (
            await self._session.execute(
                select(TaskPhoto)
                .where(
                    TaskPhoto.id == photo_id,
                    TaskPhoto.company_id == company_id,
                    TaskPhoto.media_status.in_(("deleting", "deleted")),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if photo is None:
            raise OrganizationWorkflowNotFound("task photo is unavailable")
        photo.media_status = "deleted"
        photo.updated_at = checked_now
        await self._session.flush()
        return self._photo(photo)

    async def mark_deleted(
        self, company_id: UUID, photo_id: UUID, now: datetime
    ) -> dict[str, object]:
        """Compatibility alias used by cleanup orchestration."""
        return await self.finalize_delete(company_id, photo_id, now)

    async def authorize_delete(
        self,
        actor_account_id: UUID,
        company_id: UUID,
        photo_id: UUID,
        now: datetime,
    ) -> str:
        photo = (
            await self._session.execute(
                select(TaskPhoto.id, TaskPhoto.task_id).where(
                    TaskPhoto.id == photo_id,
                    TaskPhoto.company_id == company_id,
                )
            )
        ).one_or_none()
        if photo is None:
            raise OrganizationWorkflowNotFound("task photo is unavailable")
        result = await self.begin_delete(
            actor_account_id, company_id, photo.task_id, photo_id, now
        )
        return result.object_key

    async def authorize_download(
        self,
        actor_account_id: UUID,
        company_id: UUID,
        photo_id: UUID,
        now: datetime,
        *,
        task_id: UUID | None = None,
    ) -> AuthorizedTaskPhoto:
        checked_now = self._aware(now)
        row = (
            await self._session.execute(
                select(TaskPhoto, Task)
                .join(
                    Task,
                    (Task.id == TaskPhoto.task_id)
                    & (Task.company_id == TaskPhoto.company_id),
                )
                .where(
                    TaskPhoto.id == photo_id,
                    TaskPhoto.company_id == company_id,
                    *((TaskPhoto.task_id == task_id,) if task_id is not None else ()),
                    TaskPhoto.media_status == "ready",
                )
            )
        ).one_or_none()
        if row is None:
            raise OrganizationWorkflowNotFound("task photo is unavailable")
        photo, task = row
        is_employee = False
        if photo.task_assignment_id is not None:
            is_employee = (
                await self._session.execute(
                    select(EmployeeProfile.id)
                    .join(
                        TaskAssignment,
                        (TaskAssignment.employee_profile_id == EmployeeProfile.id)
                        & (TaskAssignment.company_id == EmployeeProfile.company_id),
                    )
                    .where(
                        TaskAssignment.id == photo.task_assignment_id,
                        EmployeeProfile.account_id == actor_account_id,
                        EmployeeProfile.employment_status == "active",
                        EmployeeProfile.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none() is not None
        can_read = (
            task.author_account_id == actor_account_id
            or await self._access.can_for_venue(
                actor_account_id, company_id, "task.read", task.venue_id, checked_now
            )
        )
        if not is_employee and not can_read:
            raise OrganizationWorkflowNotFound("task photo is unavailable")
        return AuthorizedTaskPhoto(
            object_key=photo.object_key,
            mime_type=photo.mime_type,
            byte_size=photo.byte_size,
            digest=photo.sha256_digest,
        )

    async def list_photos(
        self,
        actor_account_id: UUID,
        company_id: UUID,
        task_id: UUID,
        task_assignment_id: UUID | None,
        now: datetime,
    ) -> list[dict[str, object]]:
        """Return only ready photos visible in the requested task scope."""
        checked_now = self._aware(now)
        task = (
            await self._session.execute(
                select(Task).where(
                    Task.id == task_id,
                    Task.company_id == company_id,
                )
            )
        ).scalar_one_or_none()
        if task is None:
            raise OrganizationWorkflowNotFound("task is unavailable")

        requested_assignment_exists = task_assignment_id is None
        employee_assignment_id: UUID | None = None
        if task_assignment_id is not None:
            assignment = (
                await self._session.execute(
                    select(TaskAssignment.id, EmployeeProfile.account_id)
                    .join(
                        EmployeeProfile,
                        (EmployeeProfile.id == TaskAssignment.employee_profile_id)
                        & (EmployeeProfile.company_id == TaskAssignment.company_id),
                    )
                    .where(
                        TaskAssignment.id == task_assignment_id,
                        TaskAssignment.task_id == task.id,
                        TaskAssignment.company_id == task.company_id,
                        EmployeeProfile.employment_status == "active",
                        EmployeeProfile.deleted_at.is_(None),
                    )
                )
            ).one_or_none()
            if assignment is not None:
                requested_assignment_exists = True
                if assignment.account_id == actor_account_id:
                    employee_assignment_id = assignment.id

        can_read = (
            task.author_account_id == actor_account_id
            or await self._access.can_for_venue(
                actor_account_id,
                company_id,
                "task.read",
                task.venue_id,
                checked_now,
            )
        )
        if not requested_assignment_exists:
            raise OrganizationWorkflowNotFound("task assignment is unavailable")
        if employee_assignment_id is None and not can_read:
            raise OrganizationWorkflowNotFound("task is unavailable")

        filters = [
            TaskPhoto.task_id == task.id,
            TaskPhoto.company_id == task.company_id,
            TaskPhoto.media_status == "ready",
        ]
        if employee_assignment_id is not None:
            filters.append(TaskPhoto.task_assignment_id == employee_assignment_id)
        elif task_assignment_id is not None:
            filters.append(TaskPhoto.task_assignment_id == task_assignment_id)
        rows = (
            await self._session.execute(
                select(TaskPhoto)
                .where(*filters)
                .order_by(TaskPhoto.created_at, TaskPhoto.id)
            )
        ).scalars()
        return [self._photo(photo) for photo in rows]

    async def claim_expired_pending(
        self,
        older_than: datetime,
        now: datetime,
        limit: int = 100,
    ) -> list[ExpiredTaskPhoto]:
        """Claim DB-backed temporary objects for retry-safe cleanup."""
        cutoff = self._aware(older_than)
        checked_now = self._aware(now)
        if not 1 <= limit <= 1000:
            raise OrganizationWorkflowInvalid("cleanup limit is invalid")
        rows = (
            await self._session.execute(
                select(TaskPhoto)
                .where(
                    TaskPhoto.object_key.startswith("temporary/"),
                    TaskPhoto.media_status.in_(("pending", "deleting")),
                    TaskPhoto.created_at < cutoff,
                )
                .order_by(TaskPhoto.created_at, TaskPhoto.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).scalars()
        claimed: list[ExpiredTaskPhoto] = []
        for photo in rows:
            photo.media_status = "deleting"
            photo.updated_at = checked_now
            claimed.append(
                ExpiredTaskPhoto(photo.id, photo.company_id, photo.object_key)
            )
        await self._session.flush()
        return claimed

    @staticmethod
    def _photo(photo: TaskPhoto) -> dict[str, object]:
        return {
            "photo_id": photo.id,
            "task_id": photo.task_id,
            "task_assignment_id": photo.task_assignment_id,
            "mime_type": photo.mime_type,
            "byte_size": photo.byte_size,
            "status": photo.media_status,
        }

    @staticmethod
    def _aware(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise OrganizationWorkflowInvalid("now must be timezone-aware")
        return value.astimezone(timezone.utc)


def sanitize_image(content: bytes, declared_mime_type: str) -> tuple[bytes, str, str]:
    """Validate magic bytes and remove metadata without a permissive fallback."""
    if not isinstance(content, bytes) or not 1 <= len(content) <= MAX_PHOTO_BYTES:
        raise OrganizationWorkflowInvalid("task photo size is invalid")
    if declared_mime_type == "image/jpeg" and content.startswith(b"\xff\xd8\xff"):
        sanitized = _strip_jpeg_metadata(content)
        return sanitized, "image/jpeg", "jpg"
    if declared_mime_type == "image/png" and content.startswith(b"\x89PNG\r\n\x1a\n"):
        sanitized = _strip_png_metadata(content)
        return sanitized, "image/png", "png"
    raise OrganizationWorkflowInvalid("task photo type is invalid")


def _strip_jpeg_metadata(content: bytes) -> bytes:
    result = bytearray(content[:2])
    cursor = 2
    saw_scan = False
    while cursor < len(content):
        if content[cursor] != 0xFF:
            raise OrganizationWorkflowInvalid("task photo is malformed")
        marker_start = cursor
        while cursor < len(content) and content[cursor] == 0xFF:
            cursor += 1
        if cursor >= len(content):
            raise OrganizationWorkflowInvalid("task photo is malformed")
        marker = content[cursor]
        cursor += 1
        if marker == 0xDA:
            if cursor + 2 > len(content):
                raise OrganizationWorkflowInvalid("task photo is malformed")
            result.extend(content[marker_start:])
            saw_scan = True
            break
        if marker in {0xD8, 0xD9}:
            result.extend(content[marker_start:cursor])
            if marker == 0xD9:
                break
            continue
        if cursor + 2 > len(content):
            raise OrganizationWorkflowInvalid("task photo is malformed")
        segment_length = int.from_bytes(content[cursor : cursor + 2], "big")
        segment_end = cursor + segment_length
        if segment_length < 2 or segment_end > len(content):
            raise OrganizationWorkflowInvalid("task photo is malformed")
        is_metadata = marker in {0xE1, 0xED, 0xFE}
        if not is_metadata:
            result.extend(content[marker_start:segment_end])
        cursor = segment_end
    if not saw_scan:
        raise OrganizationWorkflowInvalid("task photo is malformed")
    if len(result) > MAX_PHOTO_BYTES:
        raise OrganizationWorkflowInvalid("task photo size is invalid")
    return bytes(result)


def _strip_png_metadata(content: bytes) -> bytes:
    result = bytearray(content[:8])
    cursor = 8
    saw_header = False
    saw_data = False
    saw_end = False
    metadata_chunks = {b"eXIf", b"tEXt", b"zTXt", b"iTXt", b"tIME"}
    while cursor < len(content):
        if cursor + 12 > len(content):
            raise OrganizationWorkflowInvalid("task photo is malformed")
        length = struct.unpack(">I", content[cursor : cursor + 4])[0]
        end = cursor + 12 + length
        if end > len(content):
            raise OrganizationWorkflowInvalid("task photo is malformed")
        chunk_type = content[cursor + 4 : cursor + 8]
        if chunk_type == b"IHDR":
            saw_header = True
        elif chunk_type == b"IDAT":
            saw_data = True
        elif chunk_type == b"IEND":
            saw_end = True
        if chunk_type not in metadata_chunks:
            result.extend(content[cursor:end])
        cursor = end
        if saw_end:
            break
    if not (saw_header and saw_data and saw_end) or cursor != len(content):
        raise OrganizationWorkflowInvalid("task photo is malformed")
    if len(result) > MAX_PHOTO_BYTES:
        raise OrganizationWorkflowInvalid("task photo size is invalid")
    return bytes(result)
