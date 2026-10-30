"""Form-specific permission, ownership, business-area, and state decisions."""

from dataclasses import dataclass
from typing import Any, Self, Set
from uuid import UUID

from sqlalchemy.orm import Session

from backend.auth.authorization import get_user_permissions
from backend.auth.business_area_scope import qualifying_contact_area_ids
from backend.models import Role, UserRole

_BUSINESS_AREA_SCOPE = ":business_area"


def _needs_business_area_scope(permissions: Set[str]) -> bool:
    return any(
        permission.endswith(_BUSINESS_AREA_SCOPE)
        and f"{permission.removesuffix(_BUSINESS_AREA_SCOPE)}:any" not in permissions
        for permission in permissions
    )


@dataclass(frozen=True)
class FormAuthorizationContext:
    user_id: UUID
    permissions: frozenset[str]
    active_business_area_ids: frozenset[UUID]
    role_names: frozenset[str]

    @classmethod
    async def load(cls, user_id: str, db: Session) -> Self:
        normalized_user_id = UUID(str(user_id))
        permissions = await get_user_permissions(str(normalized_user_id), db)
        role_names = frozenset(
            name.strip().lower()
            for (name,) in (
                db.query(Role.name)
                .join(UserRole, UserRole.role_id == Role.id)
                .filter(
                    UserRole.user_id == normalized_user_id,
                    UserRole.deleted_at.is_(None),
                    Role.is_active.is_(True),
                    Role.deleted_at.is_(None),
                )
                .all()
            )
            if isinstance(name, str) and name.strip()
        )
        # Area membership is only consulted for a ``:business_area`` permission
        # not already covered by its ``:any`` form, so admin, staff_viewer and
        # legacy roles skip the contact lookup entirely.
        active_business_area_ids = (
            qualifying_contact_area_ids(db, normalized_user_id)
            if _needs_business_area_scope(permissions)
            else frozenset()
        )
        return cls(
            user_id=normalized_user_id,
            permissions=frozenset(permissions),
            active_business_area_ids=active_business_area_ids,
            role_names=role_names,
        )

    def _has_scoped_permission(self, permission: str, form: Any) -> bool:
        if f"{permission}:any" in self.permissions:
            return True

        business_area_id = getattr(form, "business_area_id", None)
        if (
            f"{permission}:business_area" in self.permissions
            and business_area_id in self.active_business_area_ids
        ):
            return True

        return (
            f"{permission}:own" in self.permissions
            and getattr(form, "created_by_id", None) == self.user_id
        )

    def can_read(self, form: Any) -> bool:
        form_status = getattr(form, "status", None)
        if form_status == "published":
            return "form:read" in self.permissions
        if form_status == "archived":
            return "form:read_unpublished:any" in self.permissions
        if form_status in {"draft", "pending_review"}:
            return "form:read_unpublished:any" in self.permissions or (
                "form:read_unpublished:business_area" in self.permissions
                and getattr(form, "business_area_id", None)
                in self.active_business_area_ids
            )
        return False

    def has_any_scoped_permission(self, permission: str) -> bool:
        return any(
            f"{permission}:{scope}" in self.permissions
            for scope in ("own", "business_area", "any")
        )

    def can_edit(self, form: Any) -> bool:
        is_draft = getattr(form, "status", None) == "draft"
        return is_draft and self._has_scoped_permission("form:edit", form)

    def can_submit(self, form: Any) -> bool:
        return (
            getattr(form, "status", None) == "draft"
            and self._has_scoped_permission("form:edit", form)
            and self._has_scoped_permission("form:submit_for_review", form)
        )

    def can_view_workflow_state(self) -> bool:
        return (
            "form:view_workflow_state" in self.permissions
            or "form:edit" in self.permissions
        )

    def available_actions(self, form: Any) -> list[str]:
        form_status = getattr(form, "status", None)
        actions: list[str] = []
        if self.can_edit(form):
            actions.append("edit")
        if self.can_submit(form):
            actions.append("submit_for_review")
        if form_status == "published" and "form:archive" in self.permissions:
            actions.append("archive")
        if form_status == "archived" and "form:archive" in self.permissions:
            actions.append("restore")
        if (
            form_status == "draft"
            and "form:delete" in self.permissions
            and (
                getattr(form, "created_by_id", None) == self.user_id
                or "admin" in self.role_names
            )
        ):
            actions.append("delete")
        if form_status == "published":
            if "form:approve" in self.permissions:
                actions.append("unpublish")
            if {
                "form:create",
                "form:edit",
            }.issubset(self.permissions):
                actions.append("revert")
        return actions

    def has_unpublished_any_access(self) -> bool:
        return "form:read_unpublished:any" in self.permissions

    def is_admin(self) -> bool:
        return "admin" in self.role_names


async def load_form_authorization_context(
    user_id: str, db: Session
) -> FormAuthorizationContext:
    return await FormAuthorizationContext.load(user_id, db)


def allowed_unpublished_area_ids(
    context: FormAuthorizationContext,
) -> Set[UUID]:
    if context.has_unpublished_any_access():
        return set()
    if "form:read_unpublished:business_area" in context.permissions:
        return set(context.active_business_area_ids)
    return set()
