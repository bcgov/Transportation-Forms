"""
Sample data script for BC Transportation Forms
Creates initial roles, business areas, and sample user data
Run after database migrations: python backend/sample_data.py
"""

from backend.database import SessionLocal, engine
from backend.models import Role, BusinessArea, User, UserRole
from datetime import datetime
import uuid

def create_sample_data():
    """Create sample data for development/testing"""
    db = SessionLocal()
    
    try:
        print("🌱 Creating sample data...")
        
        # ====================================================
        # 1. Create Default Roles
        # ====================================================
        print("\n📋 Creating default roles...")
        
        roles_data = [
            {
                'name': 'admin',
                'description': 'Full system access',
                'permissions': [
                    'user.create', 'user.read', 'user.update', 'user.delete',
                    'role.create', 'role.read', 'role.update', 'role.delete',
                    'form.create', 'form.read', 'form.update', 'form.delete',
                    'form.publish', 'form.archive',
                    'audit.read', 'report.read'
                ],
                'is_system': True,
            },
            {
                'name': 'staff_manager',
                'description': 'Manages forms and staff users',
                'permissions': [
                    'form.create', 'form.read', 'form.update', 'form.delete',
                    'form.submit_review', 'form.approve', 'form.publish',
                    'user.read', 'user.update',
                    'businessarea.read',
                    'audit.read',
                ],
                'is_system': True,
            },
            {
                'name': 'reviewer',
                'description': 'Reviews and approves forms',
                'permissions': [
                    'form.read', 'form.approve', 'form.reject',
                    'user.read',
                    'audit.read',
                ],
                'is_system': True,
            },
            {
                'name': 'staff_viewer',
                'description': 'Views published forms',
                'permissions': [
                    'form.read',
                    'businessarea.read',
                ],
                'is_system': True,
            },
        ]
        
        for role_data in roles_data:
            existing_role = db.query(Role).filter_by(name=role_data['name']).first()
            if not existing_role:
                role = Role(**role_data)
                db.add(role)
                print(f"  ✓ Created role: {role_data['name']}")
            else:
                print(f"  ℹ Role already exists: {role_data['name']}")
        
        db.commit()
        
        # ====================================================
        # 2. Create Business Areas
        # ====================================================
        print("\n🏢 Creating business areas...")
        
        business_areas_data = [
            {'name': 'Vehicle Registration', 'description': 'Forms for vehicle registration services', 'sort_order': 1},
            {'name': 'Driver Licensing', 'description': 'Forms for driver licensing and permits', 'sort_order': 2},
            {'name': 'Commercial Transport', 'description': 'Forms for commercial vehicle operations', 'sort_order': 3},
            {'name': 'Parking & Violations', 'description': 'Forms for parking and traffic violations', 'sort_order': 4},
            {'name': 'Transit Services', 'description': 'Forms related to public transit', 'sort_order': 5},
            {'name': 'Road Safety', 'description': 'Road safety and compliance forms', 'sort_order': 6},
        ]
        
        for ba_data in business_areas_data:
            existing_ba = db.query(BusinessArea).filter_by(name=ba_data['name']).first()
            if not existing_ba:
                ba = BusinessArea(**ba_data)
                db.add(ba)
                print(f"  ✓ Created business area: {ba_data['name']}")
            else:
                print(f"  ℹ Business area already exists: {ba_data['name']}")
        
        db.commit()
        
        # ====================================================
        # 3. Create Sample Users
        # ====================================================
        print("\n👥 Creating sample users...")
        
        users_data = [
            {
                'azure_id': 'admin@bcgov.onmicrosoft.com',
                'email': 'admin@transportation.bc.ca',
                'first_name': 'Admin',
                'last_name': 'User',
                'is_active': True,
                'roles': ['admin'],
            },
            {
                'azure_id': 'manager@bcgov.onmicrosoft.com',
                'email': 'manager@transportation.bc.ca',
                'first_name': 'Manager',
                'last_name': 'User',
                'is_active': True,
                'roles': ['staff_manager'],
            },
            {
                'azure_id': 'reviewer@bcgov.onmicrosoft.com',
                'email': 'reviewer@transportation.bc.ca',
                'first_name': 'Reviewer',
                'last_name': 'User',
                'is_active': True,
                'roles': ['reviewer'],
            },
            {
                'azure_id': 'staff@bcgov.onmicrosoft.com',
                'email': 'staff@transportation.bc.ca',
                'first_name': 'Staff',
                'last_name': 'User',
                'is_active': True,
                'roles': ['staff_viewer'],
            },
        ]
        
        for user_data in users_data:
            existing_user = db.query(User).filter_by(email=user_data['email']).first()
            if not existing_user:
                user_roles = user_data.pop('roles', [])
                user = User(**user_data)
                db.add(user)
                db.flush()  # Flush to get user ID
                
                # Assign roles
                for role_name in user_roles:
                    role = db.query(Role).filter_by(name=role_name).first()
                    if role:
                        user_role = UserRole(
                            user_id=user.id,
                            role_id=role.id,
                            assigned_by_id=user.id,  # Self-assigned
                        )
                        db.add(user_role)
                
                print(f"  ✓ Created user: {user_data['email']} (roles: {', '.join(user_roles)})")
            else:
                print(f"  ℹ User already exists: {user_data['email']}")
        
        db.commit()
        print("\n✅ Sample data created successfully!")
        
    except Exception as e:
        print(f"\n❌ Error creating sample data: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == '__main__':
    print("BC Transportation Forms - Sample Data Script")
    print("=" * 50)
    create_sample_data()
