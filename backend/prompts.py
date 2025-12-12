"""
prompts.py
High-fidelity system instructions for safe, deterministic extraction of structured data
from financial documents using OCR + LLM parsing.
"""

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
