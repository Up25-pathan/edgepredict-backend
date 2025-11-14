from database import SessionLocal, engine
import models, security
import sys

# Create the database tables if they don't exist
models.Base.metadata.create_all(bind=engine)

def create_super_admin():
    db = SessionLocal()
    
    print("--- Create EdgePredict Super Admin ---")
    email = input("Enter Admin Email: ")
    password = input("Enter Admin Password: ")
    
    # Check if user exists
    existing_user = db.query(models.User).filter(models.User.email == email).first()
    if existing_user:
        print(f"Error: User {email} already exists!")
        return

    # Create the Admin User
    salt = security.get_random_salt()
    hashed_password = security.hash_password(password, salt)
    
    # Set is_admin=True and give a long subscription (e.g., 10 years)
    import datetime
    expiry = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=3650)
    
    admin_user = models.User(
        email=email,
        hashed_password=hashed_password,
        salt=salt,
        is_admin=True, # <--- THIS IS THE KEY
        subscription_expiry=expiry
    )
    
    db.add(admin_user)
    db.commit()
    print(f"SUCCESS: Admin user {email} created! You can now log in.")
    db.close()

if __name__ == "__main__":
    create_super_admin()