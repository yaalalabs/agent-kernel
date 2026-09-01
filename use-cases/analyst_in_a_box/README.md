Analyst-in-a-Box: Lean Six Sigma Telegram Auditor
An AI-powered multi-agent audit system that processes warehouse operational metrics via Telegram and generates professional Lean Six Sigma analytical reports using Google Gemini.

Features
Telegram Bot Interface: Accepts natural language audit logs or warehouse performance queries directly through mobile or desktop Telegram clients.

Asynchronous Integration: Built using python-telegram-bot and asynchronous Gemini SDK patterns (client.aio) to maintain event loop stability and high concurrency.

Lean Six Sigma Framework: Automatically extracts metrics (cycle time, throughput, defects) and outputs structured DMAIC improvement plans, DPMO calculations, and process capability estimates.

Setup & Installation
Clone the repository and navigate to the project directory:

PowerShell
git clone <repository-url>
cd agent-kernel/use-cases/analyst_in_a_box
Create and activate a Python virtual environment:

PowerShell
python -m venv ak-py
.\ak-py\Scripts\Activate.ps1
Install dependencies:

PowerShell
pip install google-genai python-telegram-bot python-dotenv
Configure Environment Variables:
Create a .env file in the root directory and add your credentials:

Code snippet
GEMINI_API_KEY="your_gemini_api_key_here"
BOT_TOKEN="your_telegram_bot_token_here"
Usage
Run the bot locally using PowerShell:

PowerShell
python main.py
Open your Telegram bot, send /start or paste a warehouse audit request (e.g., Audit request: Warehouse A processed 1500 units today with a cycle time of 4 hours and 42 defects), and receive an instant LSS audit report.