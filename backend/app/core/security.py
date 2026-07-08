from passlib.context import CryptContext
from jose import jwt 
from datetime import datetime, timedelta

pwd_context=CryptContext(schemes=["bcrypt"],deprecated="auto")

SECRET_KEY="testnova_secret_key"
ALGORITHM="HS256"

def hash_password(password):
    return pwd_context.hash(password)

def verify_password(password, hashed):
    return pwd_context.verify(password,hashed)

def create_acess_token(data:dict):
    payload =data.copy()

    expire =datetime.utcnow()+timedelta(hours=24)
    payload.update({"exp":expire})

    return jwt.encode(payload,SECRET_KEY,algorithm=ALGORITHM)