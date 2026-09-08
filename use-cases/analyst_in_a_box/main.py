import os
from dotenv import load_dotenv
from google import genai
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    print(f"Received from Telegram: {user_text}")
    
    prompt = f"""
    You are an expert Lean Six Sigma multi-agent warehouse audit system (Analyst-in-a-Box). 
    Process the following audit input, extract metrics, analyze variance, and provide a concise professional summary (under 3000 characters):
    {user_text}
    """
    
    chat = client.aio.chats.create(model="gemini-3.6-flash")
    response = await chat.send_message(prompt)
    
    reply_text = response.text
    if len(reply_text) > 4000:
        reply_text = reply_text[:3997] + "..."
        
    await update.message.reply_text(reply_text)

if __name__ == "__main__":
    print("Starting Analyst-in-a-Box with Gemini API...")
    app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.run_polling()