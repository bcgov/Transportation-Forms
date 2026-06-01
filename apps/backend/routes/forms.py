"""Form management API endpoints.

Provides RESTful endpoints for form CRUD operations with proper validation,
error handling, and authorization checks.
"""

from typing import Optional, List, Dict
from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, HTTPException, status, Depends, Query, UploadFile, File
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from backend.auth.authorization import require_permission
from backend.database import get_db
from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
from backend.services.forms import FormService
from backend.services import s3_service

# ============================================================================
# Pydantic Models (Request/Response)
# ============================================================================


class BusinessAreaRef(BaseModel):
    """Reference to a business area."""

    id: str
    name: str


class FormCreateRequest(BaseModel):
    """Request model for creating a form."""

    title: str = Field(..., min_length=1, max_length=255, description="Form title")
    description: str = Field(
        ..., min_length=1, max_length=2000, description="Form description (required)"
    )
    is_public: bool = Field(
        default=False, description="Whether form is publicly visible"
    )
    keywords: Optional[List[str]] = Field(default=None, description="Search keywords")
    business_area_id: Optional[str] = Field(
        default=None, description="Associated business area ID"
    )
    effective_date: Optional[datetime] = Field(
        None, description="When form becomes effective"
    )
    # TASK-110C: new fields
    form_source: Optional[str] = Field(
        None, description="Form source type: 'URL' or 'Download'"
    )
    form_source_url: Optional[str] = Field(
        None, max_length=500, description="Source URL (required when form_source='URL')"
    )
    form_attachment_url: Optional[str] = Field(
        None,
        max_length=500,
        description="S3 object key (set after file upload when form_source='Download')",
    )
    form_attachment_filename: Optional[str] = Field(
        None, max_length=255, description="Original filename of the uploaded attachment"
    )
    # FEAT-0002: File type derived from MIME at upload time
    file_type: Optional[str] = Field(
        None,
        max_length=20,
        description="Short file-type label derived from MIME type (e.g. 'pdf', 'docx', 'unknown')",
    )
    # TASK-413: Form number reservation linkage
    form_number_reservation_id: Optional[str] = Field(
        None, description="UUID of approved form number reservation to link (optional)"
    )
    # Personal information collection indicator
    collects_personal_info: Optional[str] = Field(
        default="No",
        description="Does this form collect personal information? ('Yes' or 'No')",
    )

    @model_validator(mode="after")
    def validate_form_source(self) -> "FormCreateRequest":
        """Cross-field validation for form_source and its dependent fields."""
        src = self.form_source
        if src is not None:
            src_upper = src.upper()
            if src_upper not in ("URL", "DOWNLOAD"):
                raise ValueError("form_source must be 'URL' or 'Download'")
            # Normalise to canonical casing per spec: 'URL' or 'Download'
            self.form_source = "URL" if src_upper == "URL" else "Download"
            if src_upper == "URL" and not self.form_source_url:
                raise ValueError(
                    "form_source_url is required when form_source is 'URL'"
                )
            if src_upper == "DOWNLOAD" and not self.form_attachment_url:
                raise ValueError(
                    "form_attachment_url is required when form_source is 'Download'. "
                    "Upload the file first via POST /api/v1/uploads, then provide the returned URL."
                )

        # Validate collects_personal_info field
        if self.collects_personal_info is not None:
            if self.collects_personal_info not in ("Yes", "No"):
                raise ValueError("collects_personal_info must be 'Yes' or 'No'")

        return self


class FormUpdateRequest(BaseModel):
    """Request model for updating a form."""

    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    is_public: Optional[bool] = None
    keywords: Optional[List[str]] = None
    business_area_id: Optional[str] = None
    effective_date: Optional[datetime] = None
    collects_personal_info: Optional[str] = Field(
        None, description="Does this form collect personal information? ('Yes' or 'No')"
    )
    # TASK-416: attachment fields — support updating/clearing file attachment
    form_source: Optional[str] = Field(
        None, description="Form source type: 'URL' or 'Download' (null to clear)"
    )
    form_source_url: Optional[str] = Field(
        None, max_length=500, description="Source URL when form_source is 'URL'"
    )
    form_attachment_url: Optional[str] = Field(
        None,
        max_length=500,
        description="S3 object key when form_source is 'Download' (null to clear attachment)",
    )
    form_attachment_filename: Optional[str] = Field(
        None, max_length=255, description="Original filename of the uploaded attachment"
    )
    # FEAT-0002: File type derived from MIME at upload time
    file_type: Optional[str] = Field(
        None,
        max_length=20,
        description="Short file-type label (e.g. 'pdf', 'docx', 'unknown')",
    )

    @model_validator(mode="after")
    def validate_update_fields(self) -> "FormUpdateRequest":
        if (
            self.collects_personal_info is not None
            and self.collects_personal_info not in ("Yes", "No")
        ):
            raise ValueError("collects_personal_info must be 'Yes' or 'No'")
        # Validate form_source if explicitly provided
        if self.form_source is not None:
            src_upper = self.form_source.upper()
            if src_upper not in ("URL", "DOWNLOAD"):
                raise ValueError("form_source must be 'URL' or 'Download'")
            self.form_source = "URL" if src_upper == "URL" else "Download"
        return self


class FormResponse(BaseModel):
    """Response model for form details."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: Optional[str]
    status: str
    is_public: bool
    current_version: int
    keywords: List[str]
    business_area: Optional[BusinessAreaRef] = None
    created_by: Dict[str, str]
    effective_date: Optional[str]
    # TASK-110C: new fields
    form_source: Optional[str]
    form_source_url: Optional[str]
    form_attachment_url: Optional[str]
    form_attachment_filename: Optional[str]
    # FEAT-0002: file type label
    file_type: Optional[str] = None
    # TASK-413: linked form number reservation display fields
    form_number_reservation_id: Optional[str]
    form_number: Optional[str]
    full_form_number: Optional[str]
    # Personal information collection indicator
    collects_personal_info: str
    created_at: str
    updated_at: str


class FormListResponse(BaseModel):
    """Response model for form list."""

    total: int
    skip: int
    limit: int
    items: List[FormResponse]


class FormListItem(BaseModel):
    """List item for form summaries."""

    id: str
    title: str
    status: str
    is_public: bool
    created_at: str
    updated_at: str


class FormAutocompleteResponse(BaseModel):
    """Autocomplete response model."""

    query: str
    suggestions: List[str]


# ============================================================================
# Router Setup
# ============================================================================

router = APIRouter(
    prefix="/forms",
    tags=["Forms"],
    responses={
        404: {"description": "Form not found"},
        422: {"description": "Validation error"},
    },
)


# ============================================================================
# FILE UPLOAD ENDPOINT (TASK-110C)
# ============================================================================


class FileUploadResponse(BaseModel):
    """Response returned after a successful file upload to S3 object storage."""

    url: str  # S3 object key (e.g. "uploads/<uuid>.pdf") — not a browser URL
    filename: str
    object_key: str
    file_type: str  # FEAT-0002: derived file-type label (e.g. 'pdf', 'unknown')


@router.post(
    "/upload", response_model=FileUploadResponse, status_code=status.HTTP_201_CREATED
)
async def upload_form_attachment(
    file: UploadFile = File(..., description="Form attachment file to upload"),
    current_user: TokenData = Depends(get_current_user),
) -> FileUploadResponse:
    """
    Upload a form attachment file to S3 object storage and return its object key.

    Call this endpoint **before** creating the form when form_source is 'Download'.
    Use the returned `url` as the `form_attachment_url` in the create-form request.

    - **file**: The file to upload (PDF, DOCX, etc.)
    """
    # Read file bytes
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty"
        )

    content_type = file.content_type or "application/octet-stream"
    original_filename = file.filename or "attachment"

    try:
        object_key, object_key_ref = s3_service.upload_file(
            file_bytes=file_bytes,
            original_filename=original_filename,
            content_type=content_type,
        )
        # FEAT-0002: derive file type from MIME
        file_type = s3_service.derive_file_type(content_type)
        return FileUploadResponse(
            url=object_key_ref,
            filename=original_filename,
            object_key=object_key,
            file_type=file_type,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"File upload failed: {exc}",
        )


# ============================================================================
# CRUD ENDPOINTS
# ============================================================================


@router.post("", response_model=FormResponse, status_code=status.HTTP_201_CREATED)
async def create_form(
    request: FormCreateRequest,
    current_user: TokenData = Depends(require_permission("forms", "create")),
    db: Session = Depends(get_db),
) -> FormResponse:
    """
    Create a new form.

    - **title**: Form title (required, 1-255 chars)
    - **description**: Optional form description
    - **is_public**: Whether form is publicly visible
    - **keywords**: List of search keywords
    - **business_area_id**: Associated business area ID
    - **effective_date**: When form becomes effective
    """
    try:
        # Convert string UUIDs to UUID objects
        business_area_id = None
        if request.business_area_id:
            business_area_id = UUID(request.business_area_id)

        form_number_reservation_id = None
        if request.form_number_reservation_id:
            form_number_reservation_id = UUID(request.form_number_reservation_id)

        form = FormService.create_form(
            db=db,
            title=request.title,
            description=request.description,
            is_public=request.is_public,
            keywords=request.keywords,
            business_area_id=business_area_id,
            created_by_id=UUID(current_user.sub),
            effective_date=request.effective_date,
            form_source=request.form_source,
            form_source_url=request.form_source_url,
            form_attachment_url=request.form_attachment_url,
            form_attachment_filename=request.form_attachment_filename,
            file_type=request.file_type if request.form_source == "Download" else None,
            form_number_reservation_id=form_number_reservation_id,
            collects_personal_info=request.collects_personal_info,
        )

        return FormResponse(**FormService.get_form_with_details(db, form.id))

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create form",
        )


@router.get("/autocomplete", response_model=FormAutocompleteResponse)
async def autocomplete_forms(
    q: str = Query(
        ..., min_length=2, description="Autocomplete query (minimum 2 characters)"
    ),
    max_suggestions: int = Query(
        10, ge=1, le=10, description="Maximum suggestions (1-10)"
    ),
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FormAutocompleteResponse:
    """Return autocomplete suggestions for form titles/keywords."""
    # FEAT-0018: Enforce form:read permission
    user_perms = set(current_user.permissions or [])
    if "form:read" not in user_perms:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions for this action",
        )
    suggestions = FormService.get_autocomplete_suggestions(
        db=db,
        query_text=q,
        max_suggestions=max_suggestions,
    )
    return FormAutocompleteResponse(query=q, suggestions=suggestions)


@router.get("/{form_id}", response_model=FormResponse)
async def get_form(
    form_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FormResponse:
    """Get a form by ID."""
    # FEAT-0018: Enforce form:read permission
    user_perms = set(current_user.permissions or [])
    if "form:read" not in user_perms:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions for this action",
        )
    try:
        form_uuid = UUID(form_id)
        form_data = FormService.get_form_with_details(db, form_uuid)

        if not form_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Form not found"
            )

        return FormResponse(**form_data)

    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid form ID format"
        )


@router.put("/{form_id}", response_model=FormResponse)
async def update_form(
    form_id: str,
    request: FormUpdateRequest,
    current_user: TokenData = Depends(require_permission("forms", "update")),
    db: Session = Depends(get_db),
) -> FormResponse:
    """
    Update a form (all fields except status and version).

    Provide only the fields you want to update.
    """
    try:
        form_uuid = UUID(form_id)

        # BR-003: Prevent structural edits while form is in Pending Review state
        form_check = FormService.get_form_by_id(db, form_uuid)
        if form_check and str(form_check.status) == "pending_review":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Form cannot be edited while it is in Pending Review state",
            )

        # Build update kwargs
        update_data = {}
        if request.title is not None:
            update_data["title"] = request.title
        if request.description is not None:
            update_data["description"] = request.description
        if request.is_public is not None:
            update_data["is_public"] = request.is_public
        if request.keywords is not None:
            update_data["keywords"] = request.keywords
        if request.effective_date is not None:
            update_data["effective_date"] = request.effective_date
        if request.business_area_id is not None:
            update_data["business_area_id"] = UUID(request.business_area_id)
        if request.collects_personal_info is not None:
            update_data["collects_personal_info"] = request.collects_personal_info
        # TASK-416: attachment fields — use model_fields_set to support explicit null (clearing)
        for field in (
            "form_source",
            "form_source_url",
            "form_attachment_url",
            "form_attachment_filename",
            "file_type",
        ):
            if field in request.model_fields_set:
                update_data[field] = getattr(request, field)

        form = FormService.update_form(
            db=db,
            form_id=form_uuid,
            updated_by_id=UUID(current_user.sub),
            **update_data,
        )

        if not form:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Form not found"
            )

        return FormResponse(**FormService.get_form_with_details(db, form.id))

    except ValueError as e:
        if "invalid literal" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid form ID or business area ID format",
            )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/{form_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_form(
    form_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """
    Soft delete a form (sets deleted_at timestamp).

    FEAT-0013: Enforces form:delete permission, draft-only state restriction,
    and ownership rules (admin can delete any draft; non-admin own drafts only).
    """
    # ── Permission gate ──────────────────────────────────────────────────
    user_perms = set(current_user.permissions or [])
    if "form:delete" not in user_perms:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions for this action",
        )

    try:
        form_uuid = UUID(form_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid form ID format"
        )

    # ── Fetch form ───────────────────────────────────────────────────────
    form = FormService.get_form_by_id(db, form_uuid)
    if not form:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Form not found"
        )

    # ── State restriction: draft only ────────────────────────────────────
    if form.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only draft forms can be deleted",
        )

    # ── Ownership enforcement ────────────────────────────────────────────
    is_admin = "admin" in (current_user.roles or [])
    if not is_admin and str(form.created_by_id) != current_user.sub:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete your own draft forms",
        )

    deleted = FormService.delete_form(
        db=db, form_id=form_uuid, deleted_by_id=UUID(current_user.sub)
    )

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Form not found"
        )


@router.get("", response_model=FormListResponse)
async def list_forms(
    skip: int = Query(0, ge=0, description="Number of forms to skip"),
    limit: int = Query(
        25, description="Number of forms to return (allowed: 25, 50, 100)"
    ),
    q: Optional[str] = Query(None, description="Keyword full-text search query"),
    status_filter: Optional[List[str]] = Query(
        None, alias="status", description="Filter by status (multi-value, OR logic)"
    ),
    business_area_ids: Optional[List[str]] = Query(
        None, description="Filter by business area IDs (multi-select)"
    ),
    form_source: Optional[List[str]] = Query(
        None, description="Filter by source type (multi-value: Link, Download)"
    ),
    is_public: Optional[bool] = Query(None, description="Filter by public status"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$", description="Sort order"),
    sort_field: str = Query(
        "created_at",
        pattern="^(created_at|form_number)$",
        description="Sort field (created_at or form_number)",
    ),
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FormListResponse:
    """
    List forms with filtering, pagination, and sorting.

    - **skip**: Number of forms to skip (for pagination)
    - **limit**: Max forms to return (25, 50, 100)
    - **q**: Full-text keyword search query (also matches form numbers)
    - **status**: Filter by status (draft, pending_review, published, archived).
      Multi-value with OR logic.
    - **business_area_ids**: Optional list of business area IDs to filter by
    - **form_source**: Filter by source type (Link or Download). Multi-value with OR logic.
    - **is_public**: Filter by public/private status
    - **sort_order**: Sort ascending (asc) or descending (desc)
    - **sort_field**: Sort by created_at (default) or form_number
    """
    # FEAT-0018: Enforce form:read permission
    user_perms = set(current_user.permissions or [])
    if "form:read" not in user_perms:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions for this action",
        )

    if limit not in {25, 50, 100}:
        raise HTTPException(
            status_code=422,
            detail="limit must be one of: 25, 50, 100",
        )

    # Validate status values
    VALID_STATUSES = {"draft", "pending_review", "published", "archived"}
    if status_filter:
        invalid = [s for s in status_filter if s not in VALID_STATUSES]
        if invalid:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid status value(s): {', '.join(invalid)}. "
                f"Allowed: {', '.join(sorted(VALID_STATUSES))}",
            )

    # Validate form_source values
    VALID_SOURCES = {"Link", "Download"}
    if form_source:
        invalid_src = [s for s in form_source if s not in VALID_SOURCES]
        if invalid_src:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid form_source value(s): {', '.join(invalid_src)}. "
                f"Allowed: {', '.join(sorted(VALID_SOURCES))}",
            )

    business_area_uuid_list: Optional[List[UUID]] = None
    if business_area_ids:
        try:
            business_area_uuid_list = [UUID(value) for value in business_area_ids]
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid business area ID format",
            )

    forms, total = FormService.list_forms(
        db=db,
        skip=skip,
        limit=limit,
        q=q,
        status=status_filter or None,
        business_area_ids=business_area_uuid_list,
        form_source=form_source or None,
        is_public=is_public,
        sort_order=sort_order,
        sort_field=sort_field,
    )

    items = [
        FormResponse(**FormService.get_form_with_details(db, form.id)) for form in forms
    ]

    return FormListResponse(
        total=total,
        skip=skip,
        limit=limit,
        items=items,
    )


# ============================================================================
# ARCHIVE & UNARCHIVE ENDPOINTS
# ============================================================================


@router.post("/{form_id}/archive", response_model=FormResponse)
async def archive_form(
    form_id: str,
    current_user: TokenData = Depends(require_permission("forms", "archive")),
    db: Session = Depends(get_db),
) -> FormResponse:
    """Archive a form (mark as archived)."""
    try:
        form_uuid = UUID(form_id)
        form = FormService.archive_form(
            db=db, form_id=form_uuid, archived_by_id=UUID(current_user.sub)
        )

        if not form:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Form not found"
            )

        return FormResponse(**FormService.get_form_with_details(db, form.id))

    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid form ID format"
        )


@router.post("/{form_id}/unarchive", response_model=FormResponse)
async def unarchive_form(
    form_id: str,
    current_user: TokenData = Depends(require_permission("forms", "archive")),
    db: Session = Depends(get_db),
) -> FormResponse:
    """Unarchive a form (restore from archived status)."""
    try:
        form_uuid = UUID(form_id)
        form = FormService.unarchive_form(
            db=db, form_id=form_uuid, unarchived_by_id=UUID(current_user.sub)
        )

        if not form:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Form not found or not in archived status",
            )

        return FormResponse(**FormService.get_form_with_details(db, form.id))

    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid form ID format"
        )
