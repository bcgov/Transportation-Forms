# BC Transportation Forms - Technical Specification

**Document Version:** 1.0.0  
**Date:** February 13, 2026  
**Status:** Draft  
**Governed By:** [CONSTITUTION.md](CONSTITUTION.md)

---

## Table of Contents
1. [Executive Summary](#1-executive-summary)
2. [Product Overview](#2-product-overview)
3. [User Personas & Stories](#3-user-personas--stories)
4. [Functional Requirements](#4-functional-requirements)
5. [System Architecture](#5-system-architecture)
6. [Data Model](#6-data-model)
7. [API Specification](#7-api-specification)
8. [User Interface Design](#8-user-interface-design)
9. [Security & Authentication](#9-security--authentication)
10. [Workflow & Business Logic](#10-workflow--business-logic)
11. [Search & Discovery](#11-search--discovery)
12. [Performance Requirements](#12-performance-requirements)
13. [Implementation Phases](#13-implementation-phases)
14. [Testing Strategy](#14-testing-strategy)
15. [Deployment Strategy](#15-deployment-strategy)

---

## 1. EXECUTIVE SUMMARY

### 1.1 Project Name
**BC Transportation Forms** - Centralized Forms Catalog

### 1.2 Purpose
A web-based forms management and discovery platform that enables public users and internal staff to search, preview, and download the latest approved transportation forms. The system includes workflow management for form review and publishing, with role-based access control for staff and administrators.

### 1.3 Key Features
- **Public Access:** Anonymous search, preview, and download of public forms
- **Staff Portal:** Authenticated access to all forms
- **Admin Portal:** User management, permission configuration, business area management
- **Semantic Search:** Natural language search capabilities
- **Form Preview:** In-browser preview without downloading
- **Workflow Management:** Review and publishing workflow for forms
- **Multi-format Support:** PDF, Word, Excel, and other document formats
- **Business Area Management:** Organize forms by business areas
- **KeyCloak Authentication:** User authentication via OIDC (Phase 1)
- **Azure AD Integration:** User lookup and profile enrichment (Phase 2)

### 1.4 Technology Alignment
All technology decisions align with [CONSTITUTION.md](CONSTITUTION.md) requirements:
- Frontend: jQuery, CSS/SCSS, Bootstrap 5
- Backend: Python 3.12 LTS with FastAPI
- Database: PostgreSQL 16 LTS
- Storage: AWS S3 or compatible
- Authentication: KeyCloak OIDC (Phase 1), Azure AD user lookup (Phase 2), JWT tokens (RS256)
- API Documentation: OpenAPI/Swagger

---

## 2. PRODUCT OVERVIEW

### 2.1 Vision Statement
Create a centralized, accessible, and user-friendly platform where the public and internal staff can efficiently discover and download the latest approved transportation forms, while providing staff with powerful tools to manage form lifecycle and governance.

### 2.2 Success Criteria
- 📊 **User Adoption:** 80% of staff use platform within 3 months
- 🚀 **Performance:** Search results in < 500ms, preview loads in < 2s
- ✅ **Quality:** Zero critical bugs in production, 80%+ test coverage
- ♿ **Accessibility:** WCAG 2.1 AA compliance verified
- 📈 **Usage:** 1000+ monthly downloads, 500+ searches per day
- 😊 **Satisfaction:** 4.5/5 user satisfaction score

### 2.3 Out of Scope (V1)
- Electronic form filling/submission
- E-signature capabilities
- Payment processing
- Multi-language support (English only in V1)
- Mobile native applications (responsive web only)
- Offline access
- Advanced analytics dashboard
- Third-party integrations (except Azure AD)

---

## 3. USER PERSONAS & STORIES

### 3.1 Persona: Public User (Anonymous)
**Background:** A citizen or business operator needing transportation forms for licensing, permits, or applications.

**Goals:**
- Find relevant forms quickly
- Preview forms
- View additional information of forms as entered by the staff
- Download forms as-is

**User Stories:**
```
As a public user,
- I want to search for forms using keywords so I can find relevant documents
- I want to preview forms without downloading so I can verify it's the right form
- I want to filter forms by status, category and/or business area so I can narrow my search
- I want to see form metadata so I know I'm getting current info
- I want to download forms so I can use them in my workflow
```

### 3.2 Persona: Staff User (Backend Portal)
**Background:** Transportation department employee responsible for creating, updating, and publishing forms.

**Goals:**
- Maintain accurate, up-to-date forms catalog
- Ensure forms go through proper review process
- Organize forms by business areas and/or categories
- Track form versions and changes

**User Stories:**
```
As a staff user,
- I want to create new forms with metadata so they can be cataloged
- I want to upload form so they're securely stored on s3
- I want to edit form details and upload new versions so forms stay current
- I want to submit forms for review so they can be approved
- I want to publish approved forms so they become available to users
- I want to link forms to business areas so they're properly organized
- I want to archive outdated forms so they don't clutter search results
- I want to view all forms (public + internal) so I can assist users
- I want to see audit history so I can track changes
```

### 3.3 Persona: Administrator
**Background:** System administrator responsible for user management, permissions, and system configuration.

**Goals:**
- Control who has access to backend portal
- Manage permissions and roles
- Configure business areas
- Ensure system security and compliance
- Do everything that Staff User can do

**User Stories:**
```
As an administrator,
- I want to search for users in Azure AD (Phase 2) or manually add users (Phase 1) so I can grant system access
- I want to assign roles to users so they have appropriate permissions
- I want to define custom permissions so I can control feature access
- I want to manage business areas so staff can categorize forms properly
- I want to manage categories so staff can categorize forms properly
- I want to view audit logs so I can monitor system activity
- I want to deactivate user access so former staff lose access
- I want to configure system settings so the platform operates correctly
- I want to manage form source so staff can associate the correct organization which owns the form
```

---

## 4. FUNCTIONAL REQUIREMENTS

### 4.1 Public Frontend (Anonymous Access)

#### 4.1.1 Form Search
- **FR-PUB-001:** Semantic search using natural language queries
- **FR-PUB-002:** Keyword-based search with autocomplete
- **FR-PUB-003:** Filter by category, business area, status
- **FR-PUB-004:** Sort by relevance, date updated, business area, category, title (A-Z)
- **FR-PUB-005:** Search results display: title, description, last updated
- **FR-PUB-006:** Pagination support (30 results per page)
- **FR-PUB-007:** "No results" state with search suggestions

#### 4.1.2 Form Preview
- **FR-PUB-008:** In-browser PDF preview
- **FR-PUB-009:** Preview for supported formats (PDF)
- **FR-PUB-010:** Preview unavailable message for unsupported formats
- **FR-PUB-011:** Preview includes form metadata sidebar
- **FR-PUB-012:** Option to download from preview modal

#### 4.1.3 Form Download
- **FR-PUB-013:** One-click download button
- **FR-PUB-014:** Download counts tracked (anonymous)
- **FR-PUB-015:** Multiple format options if available
- **FR-PUB-016:** Download initiates within 100ms

#### 4.1.4 Form Details
- **FR-PUB-017:** Title, description, version number
- **FR-PUB-018:** Last updated date, published date, status
- **FR-PUB-019:** Business area(s) associated
- **FR-PUB-020:** File format, file size
- **FR-PUB-021:** Forms keywords
- **FR-PUB-022:** Form source

#### 4.1.5 Favorite Form (Authenticated users only)
- **FR-PUB-023:** Mark form as favorite for quick access
- **FR-PUB-024:** View all forms marked as favorite
- **FR-PUB-025:** Display temporary notification banner when a form is favorited or unfavorited

### 4.2 Staff Portal (Authenticated Internal Access)

#### 4.2.1 Authentication
- **FR-STAFF-001:** Login via KeyCloak using OIDC (Authorization Code Flow with PKCE)
- **FR-STAFF-002:** JWT token-based session (2-day expiry)
- **FR-STAFF-003:** Automatic token refresh
- **FR-STAFF-004:** Logout and session termination
- **FR-STAFF-005:** Role-based dashboard display

#### 4.2.2 Form Management (CRUD)
- **FR-STAFF-006:** View all forms list (public + internal)
- **FR-STAFF-007:** Create new form with metadata:
  - Title (required)
  - Description (required)
  - Category (required)
  - Business area(s) - multiple selection
  - Version number (auto-incremented)
  - Form access (public/internal) (required)
  - Status - 'Active' or 'Archived' (set Active by default)
  - Keywords
  - Effective date
  - Form source
  - Format Type (URL/File)
  - Form URL (if Format Type = URL)
  - Revision Date (Default to current date)
- **FR-STAFF-008:** Upload form document(s) to S3 (max 50MB per file)
- **FR-STAFF-009:** Supported formats: PDF, DOC, DOCX, XLS, XLSX, PNG, JPG
- **FR-STAFF-010:** Upload multiple format versions of same form
- **FR-STAFF-011:** Edit form metadata
- **FR-STAFF-012:** Upload new version of form (version history maintained)
- **FR-STAFF-013:** Delete form (soft delete with confirmation)
- **FR-STAFF-014:** Archive/unarchive forms
- **FR-STAFF-015:** Bulk operations (archive, delete, change status)
- **FR-STAFF-016:** Display form to public users only if 'Form access' is set to 'Public'

#### 4.2.3 Form Workflow
- **FR-STAFF-016:** Workflow statuses: Draft, Pending Review, Approved, Published, Archived
- **FR-STAFF-017:** Submit form for review (Draft → Pending Review)
- **FR-STAFF-018:** Review form with notes/comments
- **FR-STAFF-019:** Approve form (Pending Review → Approved)
- **FR-STAFF-020:** Reject form with feedback (Pending Review → Draft)
- **FR-STAFF-021:** Publish approved form (Approved → Published)
- **FR-STAFF-022:** Unpublish form (remove from public access)
- **FR-STAFF-023:** Email notifications for workflow transitions
- **FR-STAFF-024:** Workflow history and audit trail

#### 4.2.4 Business Area Management
- **FR-STAFF-025:** View business areas list
- **FR-STAFF-026:** View forms count per business area

#### 4.2.4 Categories Management
- **FR-STAFF-025:** View categories list
- **FR-STAFF-026:** View forms count per categories

#### 4.2.5 Search & Filter (Staff)
- **FR-STAFF-028:** Same search capabilities as public plus internal forms
- **FR-STAFF-029:** Filter by status (all statuses)
- **FR-STAFF-030:** Filter by category (all categories)
- **FR-STAFF-031:** Filter by business area (all business area)
- **FR-STAFF-032:** Advanced filters: date range, version, file type

### 4.3 Admin Portal

#### 4.3.1 User Management
- **FR-ADMIN-001:** Manually create users (Phase 1), Search Azure AD for user enrichment (Phase 2)
- **FR-ADMIN-002:** Add user to system with role assignment
- **FR-ADMIN-003:** View all system users list
- **FR-ADMIN-004:** Edit user roles and permissions
- **FR-ADMIN-005:** Deactivate/reactivate user account
- **FR-ADMIN-006:** View user activity log
- **FR-ADMIN-007:** Remove user from system

#### 4.3.2 Role & Permission Management (RBAC)
- **FR-ADMIN-008:** Default roles: Admin, Staff Manager, Staff Viewer, Reviewer
- **FR-ADMIN-009:** Create custom roles
- **FR-ADMIN-010:** Define granular permissions:
  - Create forms
  - Edit forms
  - Delete forms
  - Archive forms
  - Submit for review
  - Review forms
  - Approve forms
  - Publish forms
  - Manage business areas
  - Manage categories
  - Manage users
  - View audit logs
- **FR-ADMIN-011:** Assign multiple roles to user
- **FR-ADMIN-012:** Permission inheritance and override
- **FR-ADMIN-013:** View role-permission matrix

#### 4.3.3 Business Area Management
- **FR-ADMIN-014:** Create business area (name, description, contact person (multiple))
- **FR-ADMIN-015:** Edit business area details
- **FR-ADMIN-016:** Deactivate business area (prevent new assignments)
- **FR-ADMIN-017:** Delete business area (if no forms linked)
- **FR-ADMIN-018:** Reorder business areas (display order)

#### 4.3.4 System Configuration
- **FR-ADMIN-019:** Configure system settings (site name, logo, contact, faq)
- **FR-ADMIN-020:** Configure email notification templates
- **FR-ADMIN-021:** Configure allowed file types and size limits
- **FR-ADMIN-022:** View system health dashboard
- **FR-ADMIN-023:** Audit log viewer with filters

#### 4.3.5 Audit & Reporting
- **FR-ADMIN-024:** View comprehensive audit log
- **FR-ADMIN-025:** Filter logs by: user, action, date range, entity type
- **FR-ADMIN-026:** Export audit logs (CSV, JSON)
- **FR-ADMIN-027:** Form usage statistics: downloads, previews, searches
- **FR-ADMIN-028:** User activity reports

---

## 5. SYSTEM ARCHITECTURE

### 5.1 Component Responsibilities

#### 5.1.1 Frontend Components
- **Public Portal:** Anonymous form discovery and download
- **Staff Portal:** Authenticated form management and workflow
- **Admin Portal:** System configuration and user management
- **Shared Components:** Search, preview modal, form cards, navigation

#### 5.1.2 Backend Services
- **API Gateway:** Request routing, rate limiting, CORS
- **Auth Service:** KeyCloak OIDC integration, JWT generation/validation (RS256)
- **Form Service:** CRUD operations, metadata management
- **Search Service:** Semantic and keyword search implementation
- **S3 Service:** File upload/download, pre-signed URLs
- **Workflow Service:** Status transitions, notifications
- **User Service:** User management, role assignment
- **Audit Service:** Activity logging, compliance tracking

#### 5.1.3 Data Layer
- **PostgreSQL:** Relational data, transactional integrity
- **S3 Storage:** Document repository, scalable storage
- **KeyCloak:** Identity provider, user authentication (Phase 1)
- **Azure AD:** User directory for profile enrichment (Phase 2)

### 5.2 Integration Points

```
┌──────────────────┐       ┌──────────────────┐
│   KeyCloak       │       │   Azure AD       │
│   (OIDC)         │       │   (Phase 2)      │
└────────┬─────────┘       └────────┬─────────┘
         │ OIDC Auth               │ User Lookup
         │ (Phase 1)               │ (Phase 2)
         ▼                         ▼
┌──────────────────┐       ┌──────────────────┐
│   FastAPI        │◄─────►│   PostgreSQL     │
│   Backend        │       │   Database       │
└────────┬─────────┘       └──────────────────┘
         │
         │ S3 API
         ▼
┌──────────────────┐
│   AWS S3 /       │
│   Compatible     │
└──────────────────┘
```

---

## 6. API SPECIFICATION

### 6.1 API Design Principles
- RESTful conventions
- JSON request/response bodies
- API versioning via URL prefix (`/api/v1`)
- Consistent error responses
- OpenAPI 3.0 documentation
- Pagination for list endpoints
- Rate limiting: 10 download requests/minute per IP

### 6.2 Authentication Headers
```
Public endpoints: No authentication required
Protected endpoints: 
  Authorization: Bearer <JWT_TOKEN>
```

## 7. USER INTERFACE DESIGN

### 7.1 Design Principles
- BC Government Bootstrap 5 theme compliance
- Mobile-first responsive design
- WCAG 2.1 AA accessibility
- Consistent navigation and layout
- Progressive enhancement
- Fast page loads (< 2 seconds)

### 7.2 Component Library
#### 7.2.1 Reusable Components
- **SearchBar:** Autocomplete search input
- **FormCard:** Display form with thumbnail, title, metadata
- **FilterSidebar:** Collapsible filter panel
- **PreviewModal:** Full-screen preview with sidebar
- **DataTable:** Sortable, filterable data table
- **StatusBadge:** Color-coded status indicators
- **WorkflowTimeline:** Visual workflow history
- **FileUploader:** Drag-and-drop file upload
- **UserPicker:** Manual user creation (Phase 1), Azure AD user search (Phase 2)
- **PermissionMatrix:** Visual role-permission editor

#### 7.2.2 Workflow Status Badge Colors (Bootstrap)
```
Draft:           badge-secondary (gray)
Pending Review:  badge-warning (yellow)
Approved:        badge-info (blue)
Published:       badge-success (green)
Archived:        badge-dark (dark gray)
```
#### 7.2.2 Form Status Badge Colors (Bootstrap)
```
Active:          badge-success (green)
Archived:        badge-dark (dark gray)
```

### 7.3 Accessibility Features
- Skip to main content link
- Keyboard navigation support (Tab, Enter, Esc)
- ARIA labels on all interactive elements
- Focus indicators (visible outline)
- Alt text for images
- Form labels associated with inputs
- Color contrast 4.5:1 minimum
- Error messages linked to fields
- Screen reader announcements for dynamic content

### 7.4 Responsive Breakpoints
```
Mobile:     < 768px  (Single column, collapsed filters)
Tablet:     768-1024px (Sidebar + main content)
Desktop:    > 1024px (Full layout)
```

---

## 8. SECURITY & AUTHENTICATION

### 8.1 Authentication Flow

```
1. User clicks "Login" on public portal
   ↓
2. Frontend redirects to KeyCloak login page
   ↓
3. User authenticates with organization credentials
   ↓
4. KeyCloak redirects back with authorization code
   ↓
5. Backend exchanges code for SAML assertion/OIDC tokens
   ↓
6. Backend validates token and looks up/creates user record
   ↓
7. Backend generates JWT with user claims and roles
   ↓
8. Frontend stores JWT in sessionStorage
   ↓
9. All subsequent requests include JWT in Authorization header
   ↓
10. Backend validates JWT on each request
```

### 8.2 Security Measures
- HTTPS only in production
- JWT tokens expire after 1440 minutes
- Refresh tokens for seamless UX (7-day expiry)
- CORS configured for trusted origins only
- CSRF protection on state-changing operations
- Rate limiting: 20 download requests/minute per IP
- File upload validation (type, size, content)
- SQL injection prevention (parameterized queries)
- XSS prevention (output encoding)
- Secrets stored in environment variables
- Regular security audits
- Dependency vulnerability scanning

---

## 9. WORKFLOW & BUSINESS LOGIC

### 9.1 Form Lifecycle States

```
┌─────────┐
│  DRAFT  │ (Initial creation, editable by creator)
└────┬────┘
     │
     │ Submit for Review
     ▼
┌──────────────┐
│PENDING_REVIEW│ (Awaiting reviewer approval)
└──────┬───────┘
       │
       ├───► Reject (Back to DRAFT on reject)
       │               
       │ Approve       
       ▼               
┌──────────┐           
│ APPROVED │           
└────┬─────┘           
     │                 
     │ Publish         
     ▼                 
┌───────────┐          
│ PUBLISHED │ 
└─────┬─────┘
      │
      │ Unpublish or Archive
      ▼
┌──────────┐
│ ARCHIVED │
└──────────┘
```

### 9.2 Workflow Transition Rules

| From Status      | To Status         | Required Permission | Notes                          |
|------------------|-------------------|---------------------|--------------------------------|
| (none)           | draft             | forms.create        | Initial creation               |
| draft            | pending_review    | forms.submit_review | Form must be complete          |
| pending_review   | approved          | forms.approve       | Reviewer role required         |
| pending_review   | draft             | forms.reject        | Returns to creator             |
| approved         | published         | forms.publish       | Makes public/internal visible  |
| published        | archived          | forms.archive       | Removes from active catalog    |
| published        | draft             | forms.unpublish     | Returns to editing             |
| archived         | published         | forms.publish       | Restore from archive           |


### 9.3 Workflow Validation Rules
- **Draft → Pending Review:**
  - Title, description, category required
  - At least one file uploaded
  - At least one business area selected
  
- **Pending Review → Approved:**
  - User must have reviewer role
  - Cannot be the form creator (separation of duties)
  
- **Approved → Published:**
  - Form must have approved status
  - All required metadata complete
  - File must be accessible in S3

- **Published → Archived:**
  - Optional reason field
  - Cannot delete published forms, only archive

### 9.4 Business Rules

#### 9.4.1 Form Visibility Rules
- **Public Users:** Only see forms where `is_public = true` AND `workflow_status = 'published'`
- **Staff Users:** See all forms where `workflow_status = 'published'` (public + internal)
- **Staff Backend:** See all forms regardless of status (filtered by permissions)

#### 9.4.2 Version Management
- Version number auto-increments on new file upload
- Previous versions stored in `form_versions` table
- S3 versioning enabled for audit trail
- Users can download previous versions (staff only)

#### 9.4.3 Soft Delete
- Forms are never hard-deleted
- `deleted_at` timestamp marks deletion
- `deleted_by` captures the user identifier who performed deletion
- Queries filter out deleted forms by default
- Admins can view deleted forms for audit purposes

#### 9.4.4 Business Area Rules
- Forms can have 0 to N business areas (many-to-many)
- Business areas cannot be deleted if forms are linked
- Deactivated business areas hidden from filters but remain linked to forms

#### 9.4.5 Audit Logging Rules
- All CRUD operations logged
- Workflow transitions logged
- User authentication events logged
- Download and preview events logged (anonymized for public)
- Logs are immutable (append-only)

---

## 10. SEARCH & DISCOVERY

### 10.1 Search Implementation Strategy

#### 10.1.1 Semantic Search
**Technology:** PostgreSQL with pgvector extension + sentence transformers

**Implementation:**
```sql
-- Add vector column to forms table
ALTER TABLE forms ADD COLUMN embedding vector(384);

-- Create index for fast similarity search
CREATE INDEX ON forms USING ivfflat (embedding vector_cosine_ops);
```

**Python Service:**
```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer('all-MiniLM-L6-v2')

def semantic_search(query: str, limit: int = 20):
    # Generate embedding for query
    query_embedding = model.encode(query)
    
    # Search database
    sql = """
        SELECT *, embedding <=> %s::vector AS distance
        FROM forms
        WHERE is_public = true 
          AND workflow_status = 'published'
          AND deleted_at IS NULL
        ORDER BY distance
        LIMIT %s
    """
    results = db.execute(sql, (query_embedding.tolist(), limit))
    return results
```

**Embedding Generation:**
- Generate embeddings on form creation/update
- Combine title + description + keywords for embedding
- Background job for bulk re-embedding if model changes

#### 10.1.2 Keyword Search (Full-Text Search)
```sql
-- Using tsvector (already in schema)
SELECT *
FROM forms
WHERE search_vector @@ plainto_tsquery('english', 'driver license')
  AND is_public = true
  AND workflow_status = 'published'
  AND deleted_at IS NULL
ORDER BY ts_rank(search_vector, plainto_tsquery('english', 'driver license')) DESC
LIMIT 20;
```

#### 10.1.3 Hybrid Search (Semantic + Keyword)
```python
def hybrid_search(query: str, limit: int = 20):
    # Get semantic results
    semantic_results = semantic_search(query, limit=50)
    
    # Get keyword results
    keyword_results = keyword_search(query, limit=50)
    
    # Combine and rerank using reciprocal rank fusion
    combined = reciprocal_rank_fusion([semantic_results, keyword_results])
    
    return combined[:limit]
```

### 10.2 Search Features

#### 10.2.1 Autocomplete
```
GET /api/v1/forms/autocomplete?q=driver

Response:
{
  "suggestions": [
    "driver license application",
    "driver abstract request",
    "commercial driver permit"
  ]
}
```

**Implementation:**
- Trigram similarity search on title field
- Cache popular queries
- Return top 10 suggestions

#### 10.2.2 Filters
- **Category:** Exact match filter
- **Business Area:** Multiple selection (OR logic)
- **Date Range:** Last updated within range
- **File Format:** PDF, DOC, XLSX, etc.

#### 10.2.3 Sorting
- **Relevance:** Default (semantic similarity score)
- **Date Updated:** Newest first
- **Title:** Alphabetical A-Z
- **Downloads:** Most popular first

### 10.3 Search Performance
- Response time: < 500ms for semantic search
- Index refresh: Real-time for keyword, background for embeddings
- Caching: Popular searches cached for 5 minutes (future)
- Pagination: Cursor-based for large result sets

---

## 11. PERFORMANCE REQUIREMENTS

### 11.1 Response Time Targets
| Operation | Target | Maximum |
|-----------|--------|---------|
| API endpoint response | < 200ms | 500ms |
| Form search (semantic) | < 500ms | 1s |
| Form preview load | < 2s | 3s |
| Form download initiate | < 100ms | 200ms |
| Page load (public) | < 2s | 3s |
| Page load (staff portal) | < 3s | 5s |

### 11.2 Scalability Targets
- **Concurrent Users:** 100+
- **Forms Catalog Size:** 100+ forms
- **Daily Downloads:** 200+
- **Daily Searches:** 1000+
- **Database Queries/Second:** 50+
- **API Requests/Second:** 50+

### 11.3 Optimization Techniques
- Database query optimization with EXPLAIN ANALYZE
- Connection pooling (min 5, max 20)
- Response compression (gzip)
- Static asset CDN (future)
- Image optimization (thumbnails)
- Lazy loading for images
- API response caching (Redis - future)
- Database read replicas (future)

### 11.4 Monitoring Metrics
- Response time percentiles (p50, p95, p99)
- Error rate (4xx, 5xx)
- Request rate (requests/second)
- Database connection pool usage
- S3 upload/download latency
- Search query performance
- JWT validation time
- Memory and CPU usage

---

## 12. IMPLEMENTATION PHASES

### Phase 1: MVP - Core Functionality (Weeks 1-8)

#### Week 1-2: Foundation
- [ ] Database schema implementation
- [ ] Alembic migration setup
- [ ] FastAPI project structure
- [ ] Authentication skeleton (Keycloak integration)
- [ ] S3 service setup

#### Week 3-4: Public Portal
- [ ] Frontend structure (HTML/CSS/JS)
- [ ] Form search API (keyword only)
- [ ] Form details API
- [ ] Form download API
- [ ] Public portal UI (search, results, details)
- [ ] Form preview modal

#### Week 5-6: Staff Portal - Part 1
- [ ] Authentication UI (login/logout)
- [ ] Staff dashboard
- [ ] Form listing (all forms)
- [ ] Create form (CRUD)
- [ ] Edit form
- [ ] Delete form (soft delete)
- [ ] File upload to S3

#### Week 7-8: Staff Portal - Part 2
- [ ] Workflow implementation (status transitions)
- [ ] Workflow history viewer
- [ ] Business area management (basic)
- [ ] Form version management
- [ ] Testing and bug fixes

**MVP Deliverable:** Public users can search and download forms. Staff can manage forms with basic workflow.

---

### Phase 2: Admin & Advanced Features (Weeks 9-12)

#### Week 9-10: Admin Portal
- [ ] Admin dashboard
- [ ] User management (manual user creation in Phase 1, Azure AD search in Phase 2)
- [ ] Role assignment
- [ ] Permission management
- [ ] Business area CRUD
- [ ] Audit log viewer

#### Week 11-12: Semantic Search
- [ ] pgvector extension setup
- [ ] Sentence transformer integration
- [ ] Embedding generation service
- [ ] Semantic search API
- [ ] Hybrid search implementation
- [ ] Search autocomplete

**Phase 2 Deliverable:** Full admin capabilities, advanced semantic search.

---

### Phase 3: Polish & Production (Weeks 13-16)

#### Week 13: Testing & Quality
- [ ] Comprehensive unit tests (80%+ coverage)
- [ ] Integration tests
- [ ] E2E tests (critical user flows)
- [ ] Accessibility audit (WCAG 2.1 AA)
- [ ] Performance testing and optimization
- [ ] Security audit

#### Week 14: Documentation
- [ ] API documentation (Swagger)
- [ ] User guides (public, staff, admin)
- [ ] Admin runbooks
- [ ] Database documentation
- [ ] Deployment guide

#### Week 15: DevOps & Deployment
- [ ] GitHub Actions CI/CD pipeline
- [ ] Docker containerization
- [ ] DEV environment deployment
- [ ] TEST environment deployment
- [ ] Monitoring and logging setup
- [ ] Backup and recovery testing

#### Week 16: Production Launch
- [ ] PROD environment deployment
- [ ] User acceptance testing
- [ ] Training for staff and admins
- [ ] Go-live preparation
- [ ] Post-launch monitoring

**Phase 3 Deliverable:** Production-ready application with full testing, documentation, and deployment.

---

### Phase 4: Future Enhancements (Post-Launch)

- Email notifications for workflow transitions
- Advanced analytics dashboard
- Conversational search with AI
- Form templates
- Bulk import/export
- API rate limiting dashboard

---

## 13. TESTING STRATEGY

### 13.1 Unit Testing
**Framework:** Pytest with coverage.py

**Coverage Target:** 80%+ per module

**Key Areas:**
- Service layer functions
- Utility functions
- Permission checking logic
- Workflow validation
- Search algorithms

**Example:**
```python
def test_form_search_filters_public_forms_only():
    """Verify search returns only public published forms"""
    # Arrange
    mock_db = MagicMock()
    service = FormService(mock_db)
    
    # Act
    results = service.search_public_forms(query="driver license")
    
    # Assert
    assert all(form.is_public for form in results)
    assert all(form.status == "published" for form in results)
```

### 13.2 Integration Testing
**Scope:** API endpoints with test database

**Test Database:** PostgreSQL with test fixtures

**Key Scenarios:**
- Authentication flow end-to-end
- Form CRUD operations
- Workflow transitions
- File upload to S3 (mocked or test bucket)
- Search functionality

**Example:**
```python
def test_create_form_workflow():
    """Test complete form creation workflow"""
    # Authenticate
    token = login_as_staff_user()
    
    # Create form
    response = client.post("/api/v1/staff/forms", 
                          headers={"Authorization": f"Bearer {token}"},
                          data=form_data)
    assert response.status_code == 201
    form_id = response.json()["data"]["id"]
    
    # Submit for review
    response = client.post(f"/api/v1/staff/forms/{form_id}/workflow",
                          headers={"Authorization": f"Bearer {token}"},
                          json={"action": "submit_review"})
    assert response.status_code == 200
    assert response.json()["data"]["new_status"] == "pending_review"
```

### 13.3 End-to-End Testing
**Tool:** Playwright (future implementation)

**Critical User Flows:**
1. Public user searches and downloads form
2. Staff user creates form and submits for review
3. Reviewer approves and publishes form
4. Admin adds new user and assigns roles

**Example Scenario:**
```python
def test_public_user_download_flow(browser):
    page = browser.new_page()
    
    # Navigate to public portal
    page.goto("https://forms-test.gov.bc.ca")
    
    # Search for form
    page.fill("#search-input", "driver license")
    page.click("#search-button")
    
    # Verify results
    assert page.is_visible(".form-card")
    
    # Click download
    page.click(".download-button")
    
    # Verify download initiated
    assert page.is_visible(".download-success-message")
```

### 13.4 Accessibility Testing
**Tools:**
- Axe DevTools (automated)
- NVDA/JAWS (manual screen reader testing)
- Keyboard navigation testing

**Checklist:**
- [ ] All interactive elements keyboard accessible
- [ ] Focus indicators visible
- [ ] ARIA labels on custom controls
- [ ] Form labels associated with inputs
- [ ] Color contrast 4.5:1 minimum
- [ ] Alt text for all images
- [ ] Skip to main content link
- [ ] Screen reader announcements for dynamic content

### 13.5 Performance Testing
**Tool:** Locust

**Scenarios:**
- Load test: 50 concurrent users searching
- Stress test: Gradual increase to 200 users
- Endurance test: 100 users over 1 hour
- Spike test: Sudden spike to 200 users

**Metrics:**
- Response time percentiles
- Error rate
- Requests per second
- Database connection pool saturation

### 13.6 Security Testing
- [ ] OWASP ZAP automated scan
- [ ] SQL injection testing
- [ ] XSS vulnerability testing
- [ ] CSRF protection verification
- [ ] Authentication bypass attempts
- [ ] Authorization boundary testing
- [ ] File upload validation (malicious files)
- [ ] Rate limiting verification
- [ ] JWT token expiration testing

---

## 14. DEPLOYMENT STRATEGY

### 14.1 Environment Configuration

| Environment | Purpose | Database | Update Frequency |
|-------------|---------|-----|----------|------------------|
| DEV | Development | forms_dev_db | Every commit to `main` |
| TEST | QA/Staging | forms_test_db | Manual trigger |
| PROD | Production | forms_prod_db | Manual approval |

### 14.3 Database Migration Strategy
```bash
# Run migrations before deployment
alembic upgrade head

# Rollback if needed
alembic downgrade -1
```

### 14.4 Zero-Downtime Deployment
**Strategy:** Blue-Green Deployment

1. Deploy new version (green) alongside current version (blue)
2. Run smoke tests on green
3. Route traffic to green
4. Monitor for errors
5. If successful, decommission blue
6. If errors, roll back to blue

### 14.5 Rollback Procedure
1. Identify issue via monitoring alerts
2. Execute rollback command:
   ```bash
   kubectl rollout undo deployment/transportation-forms
   ```
3. Verify application health
4. Investigate root cause
5. Fix and redeploy

### 14.6 Post-Deployment Verification
- [ ] Health check endpoint returns 200
- [ ] Database connection successful
- [ ] S3 connectivity verified
- [ ] KeyCloak authentication working (Phase 1)
- [ ] Sample search query returns results
- [ ] Sample download successful
- [ ] Monitoring dashboards show normal metrics

---

## 15. APPENDICES

### Appendix A: Glossary
- **KeyCloak:** Open-source identity and access management, primary authentication provider (Phase 1)
- **Azure AD (Entra):** Microsoft Azure Active Directory, user directory for profile enrichment (Phase 2)
- **JWT:** JSON Web Token, authentication token standard
- **RBAC:** Role-Based Access Control
- **S3:** Simple Storage Service, object storage
- **SAML:** Security Assertion Markup Language
- **OIDC:** OpenID Connect
- **WCAG:** Web Content Accessibility Guidelines
- **Semantic Search:** Natural language understanding search

### Appendix B: References
- [CONSTITUTION.md](CONSTITUTION.md) - Governing technical standards
- [BC Gov Bootstrap Theme](https://bcgov.github.io/bootstrap-v5-theme/demo.html)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [PostgreSQL pgvector](https://github.com/pgvector/pgvector)
- [WCAG 2.1 Guidelines](https://www.w3.org/WAI/WCAG21/quickref/)

### Appendix C: Open Questions
1. Email notification service selection (SendGrid, AWS SES, etc.)
2. Specific KeyCloak realm/client credentials (provided via environment variables)
3. S3 bucket naming and region
4. Production domain name
5. Monitoring tool selection (Prometheus + Grafana vs. managed solution)

---

**Document Control:**
- **Created By:** AI Assistant + Raghu Mohindru
- **Review Cycle:** Every sprint or on major changes
- **Approval Required:** Technical Lead, Product Owner
- **Next Review Date:** End of Phase 1 (Week 8)

---

*This specification is aligned with and governed by the standards defined in [CONSTITUTION.md](CONSTITUTION.md). All implementation decisions must adhere to the constitution's technical requirements and architectural principles.*
