"""register, login (JSON or form), token (OAuth2 form), me (GET/PATCH), change-password."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from pydantic import ValidationError
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models import User
from schemas import (AuthOut, ChangePasswordIn, LoginIn, RegisterIn, RegisterOut, UpdateMeIn, UserOut,
                     split_name)
from security import create_access_token, get_current_user, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _find_user(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))


def _token_fields(user: User) -> dict:
    return {"access_token": create_access_token(user.user_id), "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60}


def _issue_token(db: Session, email: str, password: str) -> AuthOut:
    user = _find_user(db, email)
    # verify_password runs bcrypt even when user is None (constant-ish timing)
    if not verify_password(password, user.password_hash if user else None) or user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return AuthOut(**_token_fields(user), user=UserOut.of(user))


@router.post("/register", response_model=RegisterOut, status_code=status.HTTP_201_CREATED)
def register(body: RegisterIn, db: Session = Depends(get_db)) -> RegisterOut:
    """201: the user object (as before) + access_token/token_type/expires_in + nested `user`."""
    if _find_user(db, body.email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    user = User(
        first_name=body.first_name.strip(),
        last_name=(body.last_name or "").strip(),
        email=body.email,
        password_hash=hash_password(body.password),
        role="analyst",
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:  # race on the unique email index
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    db.refresh(user)
    u = UserOut.of(user)
    return RegisterOut(**u.model_dump(), **_token_fields(user), user=u)


_LOGIN_BODY = {
    "required": True,
    "content": {
        "application/json": {"schema": LoginIn.model_json_schema()},
        "application/x-www-form-urlencoded": {"schema": {
            "type": "object", "required": ["username", "password"],
            "properties": {"username": {"type": "string", "description": "email"},
                           "password": {"type": "string"}}}},
    },
}


@router.post("/login", response_model=AuthOut, openapi_extra={"requestBody": _LOGIN_BODY})
async def login(request: Request, db: Session = Depends(get_db)) -> AuthOut:
    """JSON {"email","password"} (preferred) or an OAuth2-style form (username=<email>, password)."""
    ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if ctype in ("application/x-www-form-urlencoded", "multipart/form-data"):
        form = await request.form()
        raw = {"email": form.get("username") or form.get("email"), "password": form.get("password")}
    else:
        try:
            raw = await request.json()
        except ValueError:
            raise RequestValidationError([{"type": "json_invalid", "loc": ("body",), "msg": "JSON body required",
                                           "input": None}])
    try:
        body = LoginIn.model_validate(raw)
    except ValidationError as e:
        raise RequestValidationError([{**err, "loc": ("body", *err["loc"])} for err in e.errors()])
    return await run_in_threadpool(_issue_token, db, body.email, body.password)


@router.post("/token", response_model=AuthOut)
def token(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)) -> AuthOut:
    """OAuth2 password form (username=<email>, password=...). Used by the /docs Authorize button."""
    return _issue_token(db, form.username, form.password)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.of(user)


@router.patch("/me", response_model=UserOut)
def update_me(body: UpdateMeIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> UserOut:
    if body.name is not None:
        first, last = split_name(body.name)
        if not first:
            raise HTTPException(status_code=422, detail="name must not be blank")
        if len(first) > 50 or len(last) > 50:
            raise HTTPException(status_code=422, detail="first/last name must be at most 50 characters")
        user.first_name, user.last_name = first, last
    if body.first_name is not None:
        if not body.first_name.strip():
            raise HTTPException(status_code=422, detail="first_name must not be blank")
        user.first_name = body.first_name.strip()
    if body.last_name is not None:
        user.last_name = body.last_name.strip()
    db.commit()
    db.refresh(user)
    return UserOut.of(user)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(body: ChangePasswordIn, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)) -> Response:
    # 400 (not 401) so frontends that auto-logout on 401 don't kick the user out for a typo
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if body.new_password == body.current_password:
        raise HTTPException(status_code=400, detail="New password must be different from the current one")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
