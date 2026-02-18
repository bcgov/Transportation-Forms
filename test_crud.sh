#!/bin/bash
# Quick test script for TASK-110 Form CRUD operations

echo "🚀 Starting Transportation Forms CRUD Tests..."
echo ""

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RESET='\033[0m'

# URLs
FRONTEND_URL="http://localhost:8000"
API_BASE_URL="http://localhost:8000/api/v1"

echo -e "${BLUE}=== System Status ===${RESET}"
echo "Frontend: $FRONTEND_URL"
echo "API Base: $API_BASE_URL"
echo ""

# Test API Health
echo -e "${YELLOW}Testing API Health...${RESET}"
response=$(curl -s http://localhost:8000/health)
echo "Response: $response"
echo ""

# Test GET Forms (empty list)
echo -e "${YELLOW}[1] GET - Listing Forms (should be empty)${RESET}"
curl -s "$API_BASE_URL/forms?skip=0&limit=10" | jq .
echo ""

# Test CREATE Form
echo -e "${YELLOW}[2] POST - Creating New Form${RESET}"
FORM_DATA=$(cat <<'EOF'
{
  "title": "Test Transportation Permit",
  "description": "Sample permit form for testing",
  "category": "permits",
  "is_public": true,
  "keywords": ["test", "permit", "transportation"],
  "business_area_ids": ["area1", "area2"],
  "effective_date": "2026-03-01"
}
EOF
)

CREATE_RESPONSE=$(curl -s -X POST "$API_BASE_URL/forms" \
  -H "Content-Type: application/json" \
  -d "$FORM_DATA")

echo "$CREATE_RESPONSE" | jq .
FORM_ID=$(echo "$CREATE_RESPONSE" | jq -r '.id')
echo "Created Form ID: $FORM_ID"
echo ""

# Test GET specific form
echo -e "${YELLOW}[3] GET - Retrieving Created Form${RESET}"
curl -s "$API_BASE_URL/forms/$FORM_ID" | jq .
echo ""

# Test UPDATE Form
echo -e "${YELLOW}[4] PUT - Updating Form${RESET}"
UPDATE_DATA=$(cat <<'EOF'
{
  "title": "UPDATED: Test Transportation Permit",
  "description": "Updated description for testing",
  "is_public": false,
  "keywords": ["updated", "test", "permit"]
}
EOF
)

curl -s -X PUT "$API_BASE_URL/forms/$FORM_ID" \
  -H "Content-Type: application/json" \
  -d "$UPDATE_DATA" | jq .
echo ""

# Test LIST Forms
echo -e "${YELLOW}[5] GET - Listing All Forms${RESET}"
curl -s "$API_BASE_URL/forms?skip=0&limit=10" | jq .
echo ""

# Test FILTER by category
echo -e "${YELLOW}[6] GET - Filtering Forms by Category 'permits'${RESET}"
curl -s "$API_BASE_URL/forms?category=permits" | jq .
echo ""

# Test DELETE Form
echo -e "${YELLOW}[7] DELETE - Soft Deleting Form${RESET}"
DELETE_RESPONSE=$(curl -s -X DELETE "$API_BASE_URL/forms/$FORM_ID")
echo "Delete Response (should be empty for 204 No Content)"
echo ""

# Test LIST after delete
echo -e "${YELLOW}[8] GET - Listing Forms After Delete (should be empty)${RESET}"
curl -s "$API_BASE_URL/forms?skip=0&limit=10" | jq .
echo ""

echo -e "${GREEN}✓ CRUD Testing Complete!${RESET}"
echo ""
echo "Frontend: $FRONTEND_URL"
echo "API Docs: http://localhost:8000/docs"
