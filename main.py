import os
import time
from datetime import datetime, timedelta
from typing import Dict, Any

import jwt
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from passlib.context import CryptContext

from database import db, create_document, get_documents
from schemas import (
    UserRegister,
    UserLogin,
    User,
    SaveAllocationRequest,
    Receipt,
    DemoPayRequest,
    RazorpayOrderRequest,
    RazorpayOrderResponse,
    TokenResponse,
    ReceiptsResponse,
    Message,
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change")
JWT_ALG = "HS256"

app = FastAPI(title="TaxPay Backend", version="1.0.0")

# CORS setup
frontend_url = os.environ.get("FRONTEND_URL")
origins = [frontend_url] if frontend_url else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Helpers

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)


def create_token(data: Dict[str, Any], expires_minutes: int = 60 * 24) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=expires_minutes)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALG)


def decode_token(token: str) -> Dict[str, Any]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def get_current_user(authorization: str = Header(None)) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization.split()[1]
    payload = decode_token(token)
    email = payload.get("sub")
    if not email:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    # Fetch user
    users = await get_documents("user", {"email": email}, limit=1)
    if not users:
        raise HTTPException(status_code=401, detail="User not found")
    u = users[0]
    return User(id=str(u.get("_id")), email=u["email"], name=u["name"], pan=u["pan"])  # type: ignore


@app.get("/test")
async def test():
    # Verifies DB connectivity via helper
    await create_document("ping", {"ok": True, "ts": time.time()})
    docs = await get_documents("ping", {}, limit=1)
    return {"ok": True, "count": len(docs)}


# Auth endpoints
@app.post("/auth/register", response_model=Message)
async def register(payload: UserRegister):
    # Check existing
    existing = await get_documents("user", {"email": payload.email}, limit=1)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user_doc = {
        "email": payload.email,
        "password_hash": hash_password(payload.password),
        "name": payload.name,
        "pan": payload.pan,
    }
    await create_document("user", user_doc)
    return Message(message="Registered successfully")


@app.post("/auth/login", response_model=TokenResponse)
async def login(payload: UserLogin):
    users = await get_documents("user", {"email": payload.email}, limit=1)
    if not users:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    user = users[0]
    if not verify_password(payload.password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token({"sub": user["email"]})
    return TokenResponse(access_token=token)


@app.get("/me", response_model=User)
async def me(user: User = Depends(get_current_user)):
    return user


# Allocation persistence
@app.get("/allocations")
async def get_allocation(user: User = Depends(get_current_user)):
    docs = await get_documents("allocation", {"user_email": user.email}, limit=1)
    if not docs:
        return {"sectors": {}}
    return {"sectors": docs[0].get("sectors", {})}


@app.post("/allocations", response_model=Message)
async def save_allocation(payload: SaveAllocationRequest, user: User = Depends(get_current_user)):
    # Upsert by user
    existing = await get_documents("allocation", {"user_email": user.email}, limit=1)
    doc = {"user_email": user.email, "sectors": payload.sectors}
    if existing:
        # Simple replace via create_document with same filter not available; insert new version
        await create_document("allocation", doc)
    else:
        await create_document("allocation", doc)
    return Message(message="Allocation saved")


# Receipts
@app.get("/receipts", response_model=ReceiptsResponse)
async def list_receipts(user: User = Depends(get_current_user)):
    docs = await get_documents("receipt", {"user_email": user.email}, limit=100)
    items = []
    for r in docs:
        items.append(
            Receipt(
                id=str(r.get("_id")),
                user_email=r["user_email"],
                amount=r["amount"],
                currency=r.get("currency", "INR"),
                regime=r.get("regime", "new"),
                allocation=r.get("allocation", {}),
                payment_method=r.get("payment_method", "demo"),
                reference=r.get("reference"),
            )
        )
    return ReceiptsResponse(items=items)


@app.post("/pay/demo", response_model=Receipt)
async def pay_demo(payload: DemoPayRequest, user: User = Depends(get_current_user)):
    rec = {
        "user_email": user.email,
        "amount": int(payload.amount),
        "currency": "INR",
        "regime": payload.regime,
        "allocation": payload.allocation,
        "payment_method": "demo",
        "reference": f"DEMO-{int(time.time())}",
    }
    await create_document("receipt", rec)
    return Receipt(**rec)


# Razorpay integration (order creation)
@app.post("/pay/razorpay/order", response_model=RazorpayOrderResponse)
async def create_razorpay_order(payload: RazorpayOrderRequest, user: User = Depends(get_current_user)):
    key_id = os.environ.get("RAZORPAY_KEY_ID")
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET")
    if not key_id or not key_secret:
        raise HTTPException(status_code=400, detail="Razorpay keys not configured")
    try:
        import razorpay  # imported here to avoid import if unused
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Razorpay import failed: {e}")

    client = razorpay.Client(auth=(key_id, key_secret))
    order = client.order.create(
        {
            "amount": int(payload.amount),
            "currency": payload.currency,
            "receipt": payload.receipt or f"rcpt_{int(time.time())}",
            "notes": payload.notes or {},
        }
    )
    return RazorpayOrderResponse(id=order["id"], amount=order["amount"], currency=order["currency"], status=order.get("status", "created"))
