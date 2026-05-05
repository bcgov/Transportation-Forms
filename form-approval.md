Steps to approve a form directly in the DB (future reference)
# Get a shell into the Crunchy primary pod:

kubectl exec <crunchy-db-pod> -- psql -U postgres -d transportation_forms

#Find the pod name with:

kubectl get pods -l postgres-operator.crunchydata.com/cluster=transportation-forms-local-crunchy-crunchy -o name

# Find the form ID by form number:
SELECT f.id, f.status
FROM forms f
JOIN form_number_reservations fnr ON f.form_number_reservation_id = fnr.id
WHERE fnr.full_form_number = 'CVSE0001';

# Find your user ID:
SELECT id, email FROM users WHERE email = 'raghu.mohindru@gov.bc.ca';

# Run the approval in a single transaction:

BEGIN;

UPDATE forms
SET status = 'published', updated_at = NOW()
WHERE id = '<form_id>';

INSERT INTO form_workflow (id, form_id, action, from_status, to_status, triggered_by_id, reason_notes, created_at)
VALUES (gen_random_uuid(), '<form_id>', 'approve', 'pending_review', 'published', '<user_id>', 'Direct DB approval - local dev', NOW());

COMMIT;

# Verify
SELECT f.status, fnr.full_form_number
FROM forms f
JOIN form_number_reservations fnr ON f.form_number_reservation_id = fnr.id
WHERE fnr.full_form_number = 'CVSE0001';
