# Transportation Forms - Complete CRUD Testing Guide

## 🚀 System Status

All services are deployed and running:

- **Frontend UI**: http://localhost:8000 (FastAPI serving static files)
- **Backend API**: http://localhost:8000 (FastAPI)
- **Database**: localhost:6432 (PostgreSQL)

---

## 📋 CRUD Operations Testing

### **1. GET Forms (READ)**

#### Test via Frontend:
1. Open http://localhost:3000
2. You'll see the "Manage Forms" page with a list of all forms
3. Use search and category filter to narrow results

#### Test via API (curl):
```bash
# List all forms
curl -X GET "http://localhost:8000/api/v1/forms?skip=0&limit=10"

# Get specific form
curl -X GET "http://localhost:8000/api/v1/forms/{form_id}"
```

---

### **2. CREATE Form (CREATE)**

#### Test via Frontend:
1. Click "Create Form" button in navigation
2. Fill in required fields:
   - **Title**: "New Transportation Form"
   - **Category**: Select from dropdown
   - **Business Areas**: Check desired areas
   - **Keywords**: Add search keywords (press Enter)
   - **Effective Date**: Choose optional date
   - **Public**: Check to make publicly visible
3. Click "Create Form" button
4. Success message appears, returns to list view

#### Test via API (curl):
```bash
curl -X POST "http://localhost:8000/api/v1/forms" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Permit Application Form",
    "description": "Form for permit applications",
    "category": "permits",
    "is_public": true,
    "keywords": ["permit", "application"],
    "business_area_ids": ["area1", "area2"],
    "effective_date": "2026-03-01"
  }'
```

---

### **3. UPDATE Form (UPDATE)**

#### Test via Frontend:
1. Click "Edit" button on any form in the list
2. Form loads with existing data
3. Modify any field:
   - Title
   - Description
   - Category
   - Business areas
   - Keywords
   - Public visibility
4. Click "Update Form" button
5. Success message confirms changes saved

#### Test via API (curl):
```bash
curl -X PUT "http://localhost:8000/api/v1/forms/{form_id}" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Updated Form Title",
    "description": "Updated description",
    "is_public": false,
    "keywords": ["updated", "keywords"]
  }'
```

---

### **4. DELETE Form (Soft Delete)**

#### Test via Frontend:
1. Click "Delete" button on any form in the list
2. Confirmation dialog appears
3. Click "Yes" to confirm deletion
4. Form is removed from list (soft-deleted in DB)
5. Success message confirms deletion

#### Test via API (curl):
```bash
curl -X DELETE "http://localhost:8000/api/v1/forms/{form_id}"
```

---

## 📊 Advanced Features

### **Filtering & Search**

#### Via Frontend:
- **Category Filter**: Click dropdown to filter by category
- **Search**: Type in search box and click search button

#### Via API:
```bash
# Filter by category
curl "http://localhost:8000/api/v1/forms?category=permits"

# Filter by public status
curl "http://localhost:8000/api/v1/forms?is_public=true"

# With pagination
curl "http://localhost:8000/api/v1/forms?skip=0&limit=5"

# Sorting
curl "http://localhost:8000/api/v1/forms?sort_by=created_at&sort_order=desc"
```

### **Form Details View**

#### Via Frontend:
1. Click "View" button on any form
2. Modal popup shows complete form details:
   - Title, Description, Category
   - Status, Public flag
   - Keywords, Business areas
   - Created/Updated timestamps

---

## 🔒 Database Integration

Forms are persisted in PostgreSQL database with:

- **Complete CRUD**: All operations saved to database
- **Soft Deletes**: Deleted forms marked with timestamp, not removed
- **Audit Logging**: All operations tracked in audit_log table
- **Relationships**: Forms linked to business areas
- **Timestamps**: Automatic created_at and updated_at

---

## 📝 API Endpoints

### Forms API

| Method | Endpoint | Description |
|--------|----------|-------------|
| **POST** | `/api/v1/forms` | Create new form |
| **GET** | `/api/v1/forms` | List all forms (paginated) |
| **GET** | `/api/v1/forms/{id}` | Get form details |
| **PUT** | `/api/v1/forms/{id}` | Update form |
| **DELETE** | `/api/v1/forms/{id}` | Delete form (soft delete) |
| **POST** | `/api/v1/forms/{id}/archive` | Archive form |
| **POST** | `/api/v1/forms/{id}/unarchive` | Unarchive form |

### System Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| **GET** | `/health` | System health check |
| **GET** | `/api/v1/` | API root information |

---

## 🧪 Test Scenarios

### Scenario 1: Create and Retrieve
1. Create a new form via Frontend
2. Verify form appears in list immediately
3. Click "View" to confirm all data saved correctly
4. Make API call to `/api/v1/forms/{id}` to verify database persistence

### Scenario 2: Update Form
1. Create a form with title "Original Title"
2. Click "Edit" and change to "Updated Title"
3. Save changes
4. Verify updated name appears in list
5. Click "View" to confirm all fields updated

### Scenario 3: Delete and Soft Delete
1. Create a form
2. Click "Delete" and confirm
3. Form disappears from list view
4. API call still shows deleted form with `deleted_at` timestamp
5. Database still contains the record (soft delete)

### Scenario 4: Complex Form
1. Create form with:
   - All required fields filled
   - Multiple keywords (add 5+)
   - Multiple business areas selected
   - Set as public
   - Set effective date 1 month in future
2. Verify all data saved and displays correctly

---

## 🐛 Troubleshooting

### Frontend Not Loading
```bash
# Check frontend container status
docker-compose ps | grep frontend

# View frontend logs
docker logs transportation-forms-frontend
```

### API Not Responding
```bash
# Check API container status
docker compose ps | grep app

# View API logs
docker logs transportation-forms-app

# Test API directly
curl http://localhost:8000/health
```

### Database Connection Error
```bash
# Check database status
docker-compose ps | grep postgres

# Verify database
docker exec transportation-forms-db psql -U transportation -d transportation_forms -c "SELECT COUNT(*) FROM forms;"
```

---

## 📱 Browser Compatibility

The frontend is built with:
- HTML5 with Bootstrap 5
- JavaScript ES6+
- Responsive design (mobile & desktop)
- Works in modern browsers (Chrome, Firefox, Safari, Edge)

---

## 🔗 Integration Summary

✅ **Frontend-to-API Integration**:
- JavaScript makes HTTP requests to API
- CORS headers configured for cross-origin requests
- Authentication tokens passed in headers
- Async/await for smooth UX
- Error handling with user-friendly messages

✅ **Database Integration**:
- All CRUD operations save to PostgreSQL
- Relationships properly configured
- Audit logging tracks all changes
- Soft deletes preserve data integrity

✅ **Complete CRUD Coverage**:
- Create: New forms saved to database
- Read: Forms retrieved from database
- Update: Changes persisted to database
- Delete: Soft-deleted with timestamps

---

## 📈 Next Steps

- **Testing**: Use the frontend to create, update, delete forms
- **API Testing**: Call endpoints directly with curl/Postman
- **Database Verification**: Query PostgreSQL directly
- **Production**: Deploy to Kubernetes with persistent storage

---

**Great job! TASK-110 Form CRUD operations are now fully integrated and ready for testing! 🎉**
