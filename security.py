import hashlib
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt

# --- Password Hashing & Salting ---

def get_random_salt(length: int = 16) -> str:
    """Generates a secure random salt and returns it as a hex string."""
    return os.urandom(length).hex()

def hash_password(password: str, salt: str) -> str:
    """Hashes a password using SHA-256 with a provided salt."""
    pwd_bytes = password.encode('utf-8')
    salt_bytes = bytes.fromhex(salt)
    # Combine salt and password bytes
    salted_pwd = salt_bytes + pwd_bytes
    # Hash using SHA-256
    hashed = hashlib.sha256(salted_pwd).hexdigest()
    return hashed

def verify_password(plain_password: str, hashed_password: str, salt: str) -> bool:
    """Verifies a plain password against a stored hash and salt."""
    # Hash the plain password using the *same salt*
    new_hash = hash_password(plain_password, salt)
    # Compare the new hash with the stored hash
    return new_hash == hashed_password


# --- JWT Token Configuration ---
# REMEMBER TO CHANGE THIS IN PRODUCTION AND USE ENVIRONMENT VARIABLES
SECRET_KEY = "YOUR_SUPER_SECRET_KEY_CHANGE_THIS_LATER"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 # Token lasts for one day

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Creates a new JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def decode_access_token(token: str) -> Optional[str]:
    """
    Decodes and validates a JWT access token.
    Returns the subject (email) if valid, otherwise None.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        # 'sub' (subject) should be the user's email
        email: Optional[str] = payload.get("sub")
        if email is None:
            return None
        # We could add more validation here (e.g., check token expiration manually)
        return email
    except JWTError:
        # Token is invalid (expired, wrong signature, etc.)
        return None
