import asyncio
import base64
import hashlib
import io
import json
import os
import re
import secrets
import time
from datetime import datetime
from enum import Enum
from typing import List, Optional, Any

import google.generativeai as genai
import stripe
from fastapi import FastAPI, Header, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from google.auth.transport import requests as google_requests
from google.cloud import firestore
from google.oauth2 import id_token
from PIL import Image
from pydantic import BaseModel, Field

# ==========================================
# 1. Configuration & Constants
# ==========================================

# =========================================================
# GLOBAL EXTRACTION RULES ("PHYSICS")
# =========================================================

BASE_INSTRUCTIONS = """
GLOBAL EXTRACTION RULES (STRICT – FOLLOW EXACTLY):

1. LOCALE DETECTION (3-STEP PRIORITY):
   Determine the locale using the following descending priority:
   (1) Currency symbols (Rp, VND, €, £, $, R$, CHF, etc.)
   (2) Language/address cues (PT-BR, Indonesian, Vietnamese, European formatting)
   (3) Dominant number formatting pattern in the document

   — If locale is IDR, VND, BRL, or EUR:
         DOTS = thousands separators
         COMMAS = decimals
         Examples:
            "27.500"  → 27500.0
            "10,50"   → 10.50

   — If locale is US, UK, or if no locale is clear:
         COMMAS = thousands separators
         DOTS = decimals
         Example:
            "12,500.75" → 12500.75

2. FLOAT NORMALIZATION RULES:
   Convert ALL numeric values into strict float format:
     - digits only + optional single decimal point
     - REMOVE all currency symbols, commas, spaces
     - Example:
         "Rp 27.500,00"   → 27500.0
         "$1,250.99"      → 1250.99

3. NO INFERENCE OR GUESSING:
   - Extract ONLY values explicitly present in the text.
   - If a field is missing → return `null`.
   - NEVER guess names, dates, totals, or items.
   - NEVER infer line items from category/hints.

4. ITEMS SAFETY RULE:
   - List ONLY items explicitly present in the OCR content.
   - No invented or hallucinated items.
   - Preserve exact description words as seen in text.

5. JSON OUTPUT RULES:
   - MUST output valid JSON ONLY.
   - No comments, no markdown, no explanations.
   - Floats must be pure numbers, not strings.
   - Missing values MUST be `null`.
   - Keys MUST match the schema exactly.
   - If a numeric field like 'total' or 'price' is physically illegible (blurred, torn), return `null`. Do NOT return 0.0.

6. AMBIGUITY HANDLING:
   - If any value is unclear or partially unreadable, set the field to `null`.
   - Use the `notes` field to briefly explain uncertainty.
"""

# =========================================================
# DOCUMENT TYPE CLASSIFIER
# =========================================================

DOCUMENT_TYPE_CLASSIFIER = """
Classify the document type BEFORE extraction.

Possible types:
- receipt
- invoice
- purchase_order
- bank_statement
- utility_bill
- payslip
- general

Return ONLY one string from the above (lowercase).
Do not explain.
"""

# =========================================================
# DOCUMENT-SPECIFIC EXTRACTION PROMPTS
# =========================================================

PROMPT_MAP = {

    # ------------------------------------------------------
    # 1. RECEIPT (B2C)
    # ------------------------------------------------------
    "receipt": f"""
    {BASE_INSTRUCTIONS}

    You are analyzing a RECEIPT (B2C consumer transaction).

    CONTEXT CLUES:
    - Top entity is usually the merchant or store name.
    - Look for keywords: TOTAL, AMOUNT, PAID, CASH, CARD.
    - Tax keywords: VAT, GST, PPN, PB1, Service Charge.

    JSON SCHEMA:
    {{
      "merchant": string or null,
      "date": "YYYY-MM-DD" or null,
      "total": float or null,
      "subtotal": float or null,
      "tax": float or null,
      "currency": "ISO currency code" or null,
      "category": "Food & Beverage / Grocery / Retail / Transport / Other" or null,
      "items": [
        {{
          "name": "Exact visible item text",
          "price": float or null,
          "quantity": float or null
        }}
      ],
      "notes": "Short notes about extraction uncertainty" or null,
      "confidence": float (0–1)
    }}
    """,

    # ------------------------------------------------------
    # 2. INVOICE
    # ------------------------------------------------------
    "invoice": f"""
    {BASE_INSTRUCTIONS}

    You are analyzing an INVOICE (B2B).

    CONTEXT CLUES:
    - Sender = merchant.
    - Receiver = bill_to_name.
    - Look for: Invoice #, Inv No, Invoice Date, Due Date.
    - Total must match "Total Due" / "Amount Due" / "Balance Due".

    JSON SCHEMA:
    {{
      "merchant": string or null,
      "bill_to_name": string or null,
      "bill_to_address": string or null,
      "invoice_number": string or null,
      "po_number": string or null,
      "date": "YYYY-MM-DD" or null,
      "due_date": "YYYY-MM-DD" or null,
      "total": float or null,
      "subtotal": float or null,
      "tax": float or null,
      "currency": "ISO code" or null,
      "items": [
        {{
          "name": "Exact item description",
          "price": float or null,
          "quantity": float or null
        }}
      ],
      "notes": string or null,
      "confidence": float (0–1)
    }}
    """,

    # ------------------------------------------------------
    # 3. PURCHASE ORDER (PO)
    # ------------------------------------------------------
    "purchase_order": f"""
    {BASE_INSTRUCTIONS}

    You are analyzing a PURCHASE ORDER.

    CONTEXT CLUES:
    - Vendor = merchant.
    - "Ship To" / "Bill To" = bill_to_name.
    - This is a request to buy — not a billing document.

    JSON SCHEMA:
    {{
      "merchant": string or null,
      "bill_to_name": string or null,
      "bill_to_address": string or null,
      "po_number": string or null,
      "date": "YYYY-MM-DD" or null,
      "total": float or null,
      "currency": "ISO code" or null,
      "items": [
        {{
          "name": "Item description",
          "price": float or null,
          "quantity": float or null
        }}
      ],
      "notes": string or null,
      "confidence": float (0–1)
    }}
    """,

    # ------------------------------------------------------
    # 4. BANK STATEMENT
    # ------------------------------------------------------
    "bank_statement": f"""
    {BASE_INSTRUCTIONS}

    You are analyzing a BANK STATEMENT.

    CONTEXT CLUES:
    - Look for bank name at header.
    - Items = individual transaction rows.
    - Total = closing/ending balance.
    - Preserve sign (+/-) of amounts.

    JSON SCHEMA:
    {{
      "bank_name": string or null,
      "bill_to_name": string or null,
      "bill_to_address": string or null,
      "account_number": string or null,
      "date": "YYYY-MM-DD" or null,
      "total": float or null,
      "currency": "ISO code" or null,
      "items": [
        {{
          "name": "Transaction description",
          "price": float or null,
          "quantity": 1.0
        }}
      ],
      "notes": string or null,
      "confidence": float (0–1)
    }}
    """,

    # ------------------------------------------------------
    # 5. UTILITY BILL
    # ------------------------------------------------------
    "utility_bill": f"""
    {BASE_INSTRUCTIONS}

    You are analyzing a UTILITY BILL (Electricity, Water, Internet, Gas).

    CONTEXT CLUES:
    - Sender/provider = sender_name.
    - Must extract the service address EXACTLY (for KYC).
    - Due date may appear near "Amount Due", "Pay By".

    JSON SCHEMA:
    {{
      "sender_name": string or null,
      "bill_to_name": string or null,
      "bill_to_address": string or null,
      "account_number": string or null,
      "date": "YYYY-MM-DD" or null,
      "due_date": "YYYY-MM-DD" or null,
      "total": float or null,
      "currency": "ISO code" or null,
      "items": [
        {{
          "name": "Line item description",
          "price": float or null,
          "quantity": 1.0
        }}
      ],
      "notes": string or null,
      "confidence": float (0–1)
    }}
    """,

    # ------------------------------------------------------
    # 6. PAYSLIP
    # ------------------------------------------------------
    "payslip": f"""
    {BASE_INSTRUCTIONS}

    You are analyzing a PAYSLIP / PAY STATEMENT.

    CONTEXT CLUES:
    - Employer = sender.
    - Employee = bill_to_name.
    - Subtotal = GROSS PAY (do NOT compute; extract only).
    - Total = NET PAY.
    - Deductions must be explicit if listed.

    JSON SCHEMA:
    {{
      "employer": string or null,
      "bill_to_name": string or null,
      "date": "YYYY-MM-DD" or null,
      "total": float or null,
      "subtotal": float or null,
      "tax": float or null,
      "currency": "ISO code" or null,
      "items": [
        {{
          "name": "Earning or deduction type",
          "price": float or null,
          "quantity": 1.0
        }}
      ],
      "notes": string or null,
      "confidence": float (0–1)
    }}
    """,

    # ------------------------------------------------------
    # 7. GENERAL FALLBACK
    # ------------------------------------------------------
    "general": f"""
    {BASE_INSTRUCTIONS}

    GENERAL DOCUMENT EXTRACTION (Unknown type).

    - Determine the most probable financial document type.
    - Extract only fields that visibly appear.
    - Never infer financial numbers.

    JSON SCHEMA:
    {{
      "doc_type_detected": string or null,
      "merchant": string or null,
      "date": "YYYY-MM-DD" or null,
      "total": float or null,
      "currency": "ISO code" or null,
      "items": [
        {{
          "name": "Description from text",
          "price": float or null
        }}
      ],
      "summary": "1-sentence summary" or null,
      "notes": string or null,
      "confidence": float (0–1)
    }}
    """
}


description_text = """
**AuraParse** is a Universal Financial Document API.

## Supported Document Types
* **Receipts** (B2C)
* **Invoices** (B2B)
* **Purchase Orders**
* **Bank Statements**
* **Utility Bills** (Proof of Address)
* **Payslips** (Proof of Income)

## Rate Limits
* **Free:** 10 RPM
* **Pro:** 60 RPM
* **Enterprise:** 600 RPM
"""

app = FastAPI(
    title="AuraParse API",
    description=description_text,
    version="1.3.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Environment Variables
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
STRIPE_API_KEY = os.environ.get("STRIPE_SECRET_KEY")
PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "promptmail")
ADMIN_SECRET = os.environ.get("ADMIN_SECRET")
CRON_SECRET = os.environ.get("CRON_SECRET")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")

# Services
db = firestore.Client()
stripe.api_key = STRIPE_API_KEY

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# Business Logic - Profitable Tiers
PRICING = {
    "free": {"limit": 50, "price": 0},
    "pro": {"limit": 5000, "price": 2900},       # $29
    "enterprise": {"limit": 100000, "price": 29900} # $299
}

RATE_LIMITS = {
    "free": 10,
    "pro": 60,
    "enterprise": 600
}

# ==========================================
# 2. Data Models (The Superset)
# ==========================================

class DocumentType(str, Enum):
    GENERAL = "general"
    RECEIPT = "receipt"
    INVOICE = "invoice"
    PURCHASE_ORDER = "purchase_order"
    BANK_STATEMENT = "bank_statement"
    UTILITY_BILL = "utility_bill"
    PAYSLIP = "payslip"

class LineItem(BaseModel):
    name: Optional[str] = Field(default="Unknown Item", description="Description")
    price: Optional[float] = Field(None, description="Unit price or Amount")
    quantity: Optional[float] = 1.0

class DocumentRequest(BaseModel):
    file_data: str = Field(..., description="Base64 encoded image or PDF data")
    mime_type: str = Field(..., description="image/jpeg, application/pdf")
    doc_type: DocumentType = Field(default=DocumentType.RECEIPT, description="Type")

class DocumentResponse(BaseModel):
    # Identity
    merchant: Optional[str] = Field(None, description="Vendor / Store Name")
    employer: Optional[str] = Field(None, description="Employer Name")
    bank_name: Optional[str] = Field(None, description="Bank Name")
    sender_name: Optional[str] = Field(None, description="Generic Sender")
    
    # Recipient
    bill_to_name: Optional[str] = Field(None, description="Customer / Employee Name")
    bill_to_address: Optional[str] = Field(None, description="Billing Address")
    
    # Dates
    date: Optional[str] = Field(None, description="Transaction Date")
    due_date: Optional[str] = Field(None, description="Due Date")
    
    # Financials
    total: Optional[float] = Field(None, description="Total / Net Pay")
    subtotal: Optional[float] = Field(None, description="Subtotal / Gross Pay")
    tax: Optional[float] = None
    currency: Optional[str] = "USD"
    
    # Identifiers
    invoice_number: Optional[str] = None
    po_number: Optional[str] = None
    account_number: Optional[str] = None
    
    # Meta
    category: Optional[str] = None
    items: Optional[List[LineItem]] = []
    summary: Optional[str] = None
    notes: Optional[str] = None
    confidence: Optional[float] = None
    processing_time_ms: Optional[int] = None

class CreateKeyRequest(BaseModel):
    email: str
    plan: str = "free"

class ErrorResponse(BaseModel):
    detail: str

# ==========================================
# 3. Helpers (Auth & Rate Limit)
# ==========================================

def generate_api_key() -> tuple[str, str]:
    r = secrets.token_urlsafe(32)
    return f"rcp_live_{r}", hashlib.sha256(f"rcp_live_{r}".encode()).hexdigest()

def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()

async def verify_firebase_token(auth: str) -> dict:
    if not auth or not auth.startswith('Bearer '):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    try:
        return id_token.verify_firebase_token(auth.split(' ')[1], google_requests.Request(), audience=PROJECT_ID)
    except:
        raise HTTPException(status_code=401, detail="Invalid authentication token")

async def get_valid_api_key(x_api_key: str = Header(..., alias="X-API-Key")) -> firestore.DocumentReference:
    """Dependency: Check Key + Enforce RPM Limit."""
    h = hash_api_key(x_api_key)
    results = list(db.collection("api_keys").where("key_hash", "==", h).where("active", "==", True).limit(1).stream())
    
    if not results:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    
    doc = results[0].reference
    data = results[0].to_dict()
    
    # Rate Limit Logic
    now = datetime.utcnow()
    try:
        start = datetime.fromisoformat(data.get("rate_window_start", ""))
    except (ValueError, TypeError):
        start = now # Force reset if invalid
    
    if (now - start).total_seconds() > 60:
        doc.update({
            "rate_window_start": now.isoformat(),
            "rate_request_count": 1
        })
    else:
        limit = RATE_LIMITS.get(data.get("plan"), 10)
        if data.get("rate_request_count", 0) >= limit:
            raise HTTPException(429, detail=f"Rate limit exceeded. Limit: {limit}/min")
        doc.update({"rate_request_count": firestore.Increment(1)})
        
    return doc

# ==========================================
# 4. AI Logic (Retry + Resize + Clean)
# ==========================================

async def extract_document_data(image_data: str, mime_type: str, doc_type: str) -> dict:
    """
    Robust AI Processing:
    1. Resizes Images (if too large).
    2. Retries up to 3 times on AI failure.
    3. Cleans bad characters from JSON response.
    """
    # A. Resize
    try:
        image_bytes = base64.b64decode(image_data)
        if mime_type.startswith("image/"):
            try:
                img = Image.open(io.BytesIO(image_bytes))
                if img.width > 1024 or img.height > 1024:
                    img.thumbnail((1024, 1024))
                    buf = io.BytesIO()
                    if img.mode in ('RGBA', 'P'): img = img.convert('RGB')
                    img.save(buf, format='JPEG', quality=65)
                    image_bytes = buf.getvalue()
                    mime_type = "image/jpeg"
            except: pass
    except Exception as e:
        raise HTTPException(400, f"Invalid Image Data: {str(e)}")

    # B. AI Call with Retry
    model = genai.GenerativeModel('gemini-2.5-flash-lite')
    prompt_text = PROMPT_MAP.get(doc_type, PROMPT_MAP["general"])
    
    max_retries = 3
    last_error = None

    for attempt in range(max_retries):
        try:
            response = model.generate_content([
                prompt_text,
                {"mime_type": mime_type, "data": image_bytes}
            ])
            
            # Clean Output
            txt = response.text.strip()
            if txt.startswith("```"): txt = txt.split("```")[1]
            if txt.startswith("json"): txt = txt[4:]
            
            # Fix: Remove invisible control characters that break JSON
            txt = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', txt)
            
            return json.loads(txt)

        except Exception as e:
            print(f"⚠️ AI Attempt {attempt+1} failed: {e}")
            last_error = e
            if attempt < max_retries - 1:
                await asyncio.sleep(1)

    raise HTTPException(500, f"AI Processing failed after {max_retries} attempts: {str(last_error)}")

# ==========================================
# 5. Endpoints
# ==========================================

@app.get("/", tags=["Health"])
async def root(): return {"status": "healthy", "version": "1.3.0"}

@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "healthy", "gemini": bool(GEMINI_API_KEY), "stripe": bool(stripe.api_key), "firestore": True}

@app.post(
    "/api/v1/extract", 
    response_model=DocumentResponse, 
    tags=["Extraction"],
    response_model_exclude_none=True,  # CLEAN JSON OUTPUT
    responses={
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"}, 
        400: {"model": ErrorResponse, "description": "Bad Request"},
        500: {"model": ErrorResponse, "description": "Server Error"}
    }
)
async def extract(
    req: DocumentRequest,
    key_doc: firestore.DocumentReference = Depends(get_valid_api_key)
):
    start = time.time()
    
    # Monthly Quota Check (With Manual Override Support)
    data = key_doc.get().to_dict()
    
    # 1. Custom Limit? -> 2. Plan Limit -> 3. Default
    monthly_limit = data.get("custom_limit")
    if monthly_limit is None:
        monthly_limit = PRICING.get(data.get("plan"), {}).get("limit", 50)

    if data.get("requests_this_month", 0) >= monthly_limit:
        raise HTTPException(429, "Monthly quota reached")

    if len(req.file_data) > 14_000_000:
        raise HTTPException(400, "File too large")

    try:
        # Extract
        result = await extract_document_data(req.file_data, req.mime_type, req.doc_type.value)
        
        # Update Stats
        key_doc.update({
            "requests_count": firestore.Increment(1),
            "requests_this_month": firestore.Increment(1),
            "last_used": datetime.utcnow().isoformat()
        })
        
        result["processing_time_ms"] = int((time.time() - start) * 1000)
        return DocumentResponse(**result)
        
    except Exception as e:
        if isinstance(e, HTTPException): raise e
        raise HTTPException(500, str(e))

# ==========================================
# 6. Management & Billing
# ==========================================

@app.post("/api/v1/signup", tags=["Management"])
async def signup(body: CreateKeyRequest, authorization: str = Header(None)):
    if not authorization: raise HTTPException(401, "Missing auth")
    user = await verify_firebase_token(authorization)
    email = user.get('email')
    if not email or email.lower() != body.email.lower(): raise HTTPException(400, "Email mismatch")
    
    full_key, key_hash = generate_api_key()
    key_id = f"key_{secrets.token_urlsafe(16)}"
    
    if list(db.collection("api_keys").where("user_email", "==", email).where("active", "==", True).limit(1).stream()):
        return {"key": None, "status": "existing"}

    db.collection("api_keys").document(key_id).set({
        "key_id": key_id, "key_hash": key_hash, "key_suffix": full_key[-4:],
        "user_email": email, "plan": body.plan, "active": True,
        "created_at": datetime.utcnow().isoformat(), "rate_request_count": 0, "requests_this_month": 0
    })
    return {"key": full_key, "key_id": key_id, "status": "created"}

@app.get("/api/v1/key", tags=["Management"])
async def get_key(authorization: str = Header(None)):
    if not authorization: raise HTTPException(401, "Missing auth")
    user = await verify_firebase_token(authorization)
    results = list(db.collection("api_keys").where("user_email", "==", user.get('email')).where("active", "==", True).limit(1).stream())
    if not results: raise HTTPException(404, "No key found")
    data = results[0].to_dict()
    
    # Determine correct limit for UI
    limit = data.get("custom_limit")
    if limit is None:
        limit = PRICING.get(data.get("plan"), {}).get("limit", 50)

    return {
        "key_id": data.get("key_id"),
        "masked_key": f"rcp_live_••••••••{data.get('key_suffix', '****')}",
        "plan": data.get("plan"),
        "requests_this_month": data.get("requests_this_month"),
        "limit": limit
    }

@app.post("/api/v1/regenerate-key", tags=["Management"])
async def rotate_key(authorization: str = Header(None)):
    if not authorization: raise HTTPException(401, "Missing auth")
    user = await verify_firebase_token(authorization)
    results = list(db.collection("api_keys").where("user_email", "==", user.get('email')).where("active", "==", True).limit(1).stream())
    full_key, key_hash = generate_api_key()
    if results: results[0].reference.update({"key_hash": key_hash, "key_suffix": full_key[-4:]})
    else: raise HTTPException(404, "No key")
    return {"key": full_key, "message": "Rotated"}

@app.post("/api/v1/create-checkout", tags=["Billing"])
async def checkout(plan: str, authorization: str = Header(None)):
    """Creates Checkout Session via Auth Token."""
    if plan not in ["pro", "enterprise"]: raise HTTPException(400, "Invalid plan")
    if not authorization: raise HTTPException(401, "Missing auth")
    
    user = await verify_firebase_token(authorization)
    results = list(db.collection("api_keys").where("user_email", "==", user.get('email')).where("active", "==", True).limit(1).stream())
    
    if not results: raise HTTPException(404, "No account found")
    key_data = results[0].to_dict()
    
    # Calculate formatted limit string (e.g., "5,000")
    limit_str = f"{PRICING[plan]['limit']:,}"
    
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'unit_amount': PRICING[plan]["price"],
                    'product_data': {
                        'name': f'AuraParse {plan.title()}',
                        # --- THIS IS THE NEW LINE ---
                        'description': f'Includes {limit_str} requests per month. High-speed GenAI extraction.',
                    },
                    'recurring': {'interval': 'month'},
                },
                'quantity': 1,
            }],
            mode='subscription',
            success_url='https://auraparse.web.app/?success=true',
            cancel_url='https://auraparse.web.app/?canceled=true',
            metadata={'api_key_hash': key_data["key_hash"], 'plan': plan}
        )
        return {"checkout_url": session.url}
    except Exception as e: raise HTTPException(500, str(e))


@app.post("/api/v1/create-portal", tags=["Billing"])
async def portal(authorization: str = Header(None)):
    """Creates Billing Portal Session."""
    if not authorization: raise HTTPException(401, "Missing auth")
    user = await verify_firebase_token(authorization)
    results = list(db.collection("api_keys").where("user_email", "==", user.get('email')).limit(1).stream())
    
    if not results: raise HTTPException(404, "User not found")
    cust_id = results[0].to_dict().get("stripe_customer_id")
    
    if not cust_id: raise HTTPException(400, "No billing history.")
    
    try:
        session = stripe.billing_portal.Session.create(
            customer=cust_id, return_url="https://auraparse.web.app/"
        )
        return {"url": session.url}
    except Exception as e: raise HTTPException(500, str(e))

@app.post("/api/v1/stripe-webhook", tags=["Billing"])
async def webhook(request: Request):
    try: event = stripe.Webhook.construct_event(await request.body(), request.headers.get('stripe-signature'), STRIPE_WEBHOOK_SECRET)
    except: raise HTTPException(400, "Error")
    
    data = event['data']['object']
    
    if event['type'] == 'checkout.session.completed':
        h, p = data['metadata'].get('api_key_hash'), data['metadata'].get('plan')
        cust_id = data.get('customer')
        if h and p:
            for k in db.collection("api_keys").where("key_hash", "==", h).limit(1).stream():
                k.reference.update({"plan": p, "stripe_customer_id": cust_id})
                
    elif event['type'] == 'customer.subscription.deleted':
        cust_id = data.get('customer')
        for k in db.collection("api_keys").where("stripe_customer_id", "==", cust_id).limit(1).stream():
            k.reference.update({"plan": "free"})
            
    return {"status": "ok"}

@app.post("/api/v1/cron/reset-monthly-usage", tags=["Admin"])
async def cron_job(cron_secret: str = Header(..., alias="X-Cron-Secret")):
    if cron_secret != CRON_SECRET: raise HTTPException(403, "Forbidden")
    batch = db.batch()
    c = 0
    for doc in db.collection("api_keys").stream():
        batch.update(doc.reference, {"requests_this_month": 0})
        c += 1
        if c % 400 == 0: batch.commit(); batch = db.batch()
    if c % 400 != 0: batch.commit()
    return {"message": f"Reset {c}"}

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail, "status_code": exc.status_code})

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print(f"Global Error: {exc}")
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error", "status_code": 500})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))