"""Registration and login."""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status

from app.database import fetch_one, get_db
from app.schemas import LoginIn, RegisterIn
from app.security import create_token, current_user, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(body: RegisterIn, conn: sqlite3.Connection = Depends(get_db)):
    if fetch_one(conn, "SELECT id FROM users WHERE email = ?", (body.email,)):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    # Self-registration always creates an engineer; admins are provisioned by the seed/admin.
    user_id = conn.execute(
        "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, 'engineer')",
        (body.name.strip(), body.email, hash_password(body.password)),
    ).lastrowid
    user = {"id": user_id, "name": body.name.strip(), "email": body.email, "role": "engineer"}
    return {"token": create_token(user_id, "engineer"), "user": user}


@router.post("/login")
def login(body: LoginIn, conn: sqlite3.Connection = Depends(get_db)):
    row = fetch_one(conn, "SELECT * FROM users WHERE email = ?", (body.email.strip().lower(),))
    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    user = {k: row[k] for k in ("id", "name", "email", "role")}
    return {"token": create_token(row["id"], row["role"]), "user": user}


@router.get("/me")
def me(user: dict = Depends(current_user)):
    return user
