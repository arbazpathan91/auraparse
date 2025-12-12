# AuraParse MCP Server

This is the official [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server for **AuraParse**.

It turns your LLM (Claude, Cursor, Zed) into a **Financial Document Expert**. You can drag-and-drop Receipts, Invoices, Bank Statements, or W-2s into your chat, and the AI will extract structured data (Merchant, Total, Tax, Line Items) with 99% accuracy.

---

## 🔑 Step 1: Get your API Key
Before installing, you need an API Key.
1. Go to **[https://auraparse.web.app](https://auraparse.web.app)**.
2. Sign in (Free).
3. Copy the key from the dashboard. It looks like: `rcp_live_...`

---

## 💻 Step 2: Installation

### Option A: Claude Desktop (Recommended)
You do not need to install Python or pip manually. We use `uvx` to run the tool instantly.

1. Open your Claude Desktop configuration file:
   - **Mac:** `~/Library/Application Support/Claude/claude_desktop_config.json`
   - **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

2. Add this to the `mcpServers` list:

```json
{
  "mcpServers": {
    "auraparse": {
      "command": "uvx",
      "args": ["auraparse-mcp"],
      "env": {
        "AURAPARSE_API_KEY": "rcp_live_YOUR_API_KEY_HERE"
      }
    }
  }
}
```
3. Save and **Restart Claude Desktop**. Look for the 🔌 plug icon.

---

### Option B: Cursor (AI Code Editor)
You can give Cursor the ability to read receipt files inside your project.

1. Open Cursor Settings > **Features** > **MCP Servers**.
2. Click **+ Add New MCP Server**.
3. Enter these details:
   - **Name:** `auraparse`
   - **Type:** `command`
   - **Command:** `uvx auraparse-mcp`
4. **Crucial Step:** You must set the API Key in the Environment Variables section or pass it inline (if supported), but currently, the easiest way for Cursor is to use a wrapper command or ensure `AURAPARSE_API_KEY` is in your system environment.

*Alternative for Cursor users without system env vars:*
```bash
# Command to enter in Cursor
uvx --env AURAPARSE_API_KEY=rcp_live_YOUR_API_KEY_HERE auraparse-mcp
```

---

### Option C: Manual / Pip Install (Advanced)
Use this if you are building your own MCP client or want to manage the package manually.

1. **Install:**
   ```bash
   pip install auraparse-mcp
   ```

2. **Run:**
   The server communicates over Stdio (standard input/output). You cannot run it interactively. You must run it inside an MCP Client configuration.

   **Configuration Example (generic):**
   ```json
   {
     "command": "python3",
     "args": ["-m", "auraparse_mcp"],
     "env": {
       "AURAPARSE_API_KEY": "rcp_live_YOUR_API_KEY_HERE"
     }
   }
   ```

---

## 🚀 Features
*   **Universal Parsing:** Auto-detects Receipts vs Invoices vs Bank Statements.
*   **Privacy First:** Files are processed in RAM and deleted instantly.
*   **Smart Formatting:** Handles complex currencies (e.g. Indonesian `27.500` vs US `27,500`).

## 🛠️ Troubleshooting
**I don't see the tool in Claude:**
1. Check the logs: `tail -f ~/Library/Logs/Claude/mcp.log`
2. Ensure you installed `uv` (`brew install uv` on Mac or via pip).
3. Ensure your API Key starts with `rcp_live_`.

**I get a 429 Error:**
You are on the Free Plan (10 requests/min). Please upgrade to Pro on the [AuraParse Dashboard](https://auraparse.web.app) for higher limits.
