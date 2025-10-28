from typing import Optional, Dict, Any, List
from pydantic import BaseModel, EmailStr, Field


class UserRegister(BaseModel):
    email: EmailStr
    password: str
    name: str = Field(..., min_length=2, max_length=80)
    pan: str = Field(..., min_length=10, max_length=10, regex=r"^[A-Z]{5}[0-9]{4}[A-Z]$")


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class User(BaseModel):
    id: Optional[str]
    email: EmailStr
    name: str
    pan: str


class Allocation(BaseModel):
    sectors: Dict[str, float]  # keys like education, health, infra, defense, other (percentages summing ~100)


class SaveAllocationRequest(BaseModel):
    sectors: Dict[str, float]


class Receipt(BaseModel):
    id: Optional[str]
    user_email: EmailStr
    amount: int
    currency: str = "INR"
    regime: str
    allocation: Dict[str, float]
    payment_method: str  # demo | razorpay | phonepe
    reference: Optional[str]  # e.g., order_id or txn id


class DemoPayRequest(BaseModel):
    amount: int
    regime: str
    allocation: Dict[str, float]


class RazorpayOrderRequest(BaseModel):
    amount: int  # in paise
    currency: str = "INR"
    receipt: Optional[str]
    notes: Optional[Dict[str, Any]]


class RazorpayOrderResponse(BaseModel):
    id: str
    amount: int
    currency: str
    status: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class Message(BaseModel):
    message: str


class ReceiptsResponse(BaseModel):
    items: List[Receipt]
