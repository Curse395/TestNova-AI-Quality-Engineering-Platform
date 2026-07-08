from fastapi import APIRouter,Depends,HTTPException
from sqlalchemy.orm import Session
from app.database.connection import get_db
from app.models.user import User
from  app.shemas.user_schema import UserCreate,UserLogin
from app.core.security import hash_password,verify_password,create_acess_token

router=APIRouter(prefix="/auth",tags=["Authentication"])

@router.post("/register")
def register(data:UserCreate,db:Session=Depends(get_db)):

    existing=(db.query(User).filter(User.email==data.email).first())

    if existing:
        raise HTTPException(status_code=400, detail="This E-Mail is already registered ")
    
    user =User(name=data.name,
               email=data.email,
               password_hash=hash_password(data.password))
    
    db.add(user)
    db.commit()
    db.refresh(user)

    return {
        "message":"Account succesfully created",
        "user":user.email
    }


@router.post("/login")
def login(data:UserLogin,db:Session=Depends(get_db)):
    user=db.query(User).filter(User.email==data.email).first()

    if not user:
        raise HTTPException(status_code=401,detail="Invalid  credentials")
    
    if not verify_password(data.password,user.password_hash):
        raise HTTPException(status_code=401,detail="Invalid credentials")
    
    token=create_acess_token({"user_id":user.id})
    return {"access_token":token,
            "token_type":"bearer"}