import os
import base64
import mimetypes
import httpx
from mcp.server.fastmcp import FastMCP

# 1. Initialize the MCP Server
mcp = FastMCP("AuraParse")

# Configuration
API_URL = "https://auraparse.web.app/api/v1/extract"
API_KEY_NAME = "AURAPARSE_API_KEY"

@mcp.tool()
async def scan_document(file_path: str, doc_type: str = "general") -> str:
    """
    Scans a financial document (Receipt, Invoice, Bank Statement) using AuraParse AI.
    
    Args:
        file_path: Absolute path to the local file (e.g., /Users/name/invoice.pdf)
        doc_type: Type of document. Options: 'receipt', 'invoice', 'bank_statement', 'utility_bill', 'payslip', 'general'.
    """
    
    # 1. Get API Key from Environment
    api_key = os.environ.get(API_KEY_NAME)
    if not api_key:
        return f"Error: {API_KEY_NAME} not set. Please add it to your Claude Desktop config."

    # 2. Validate File
    if not os.path.exists(file_path):
        return f"Error: File not found at {file_path}"

    # 3. Determine Mime Type
    mime_type, _ = mimetypes.guess_type(file_path)
    if not mime_type:
        mime_type = "application/pdf" if file_path.endswith(".pdf") else "image/jpeg"

    try:
        # 4. Read & Encode File
        with open(file_path, "rb") as f:
            file_data = base64.b64encode(f.read()).decode('utf-8')

        # 5. Call AuraParse API
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                API_URL,
                headers={
                    "Content-Type": "application/json",
                    "X-API-Key": api_key
                },
                json={
                    "file_data": file_data,
                    "mime_type": mime_type,
                    "doc_type": doc_type
                }
            )

        # 6. Return Result
        if response.status_code == 200:
            return response.text # Return raw JSON string for Claude to analyze
        else:
            return f"API Error ({response.status_code}): {response.text}"

    except Exception as e:
        return f"Processing Error: {str(e)}"

def main():
    """Entry point for the package."""
    mcp.run()

if __name__ == "__main__":
    main()