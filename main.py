from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import gspread
import pandas as pd
from google.oauth2.service_account import Credentials
import os
from dotenv import load_dotenv
import json

load_dotenv()

g_sheet_url = os.getenv("g_sheet_link")
telegram_token = os.getenv("telegram_token")

scope = [
    "https://www.googleapis.com/auth/spreadsheets"
]

# Load credentials
#creds = Credentials.from_service_account_file("credentials.json", scopes = scope)

creds_json = os.getenv("GOOGLE_CREDS_JSON")

creds_dict = json.loads(creds_json)

creds = Credentials.from_service_account_info(creds_dict, scopes=scope)


# Authorize client
client = gspread.authorize(creds)

# Open the Google Sheet by URL
sheet = client.open_by_url(g_sheet_url)

# Select the first worksheet
worksheet = sheet.get_worksheet(0)

# Get all data
data = worksheet.get_all_records()

# Convert to DataFrame
df = pd.DataFrame(data)

print("woi")

def get_student(student_id: str):
    df = pd.DataFrame(data)
    row = df[df["Student_ID"] == student_id]
    if len(row) == 0:
        return {"error": "No student found"}
    else:
        # Convert the row to a dictionary
        student_dict = row.iloc[0].to_dict()
        return student_dict



# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello! I'm your bot 🤖")


async def get_student_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # context.args contains the parameters after the command
    if len(context.args) == 0:
        await update.message.reply_text("Please provide a student ID, e.g., /student S005")
        return

    student_id = context.args[0]  # first parameter
    student_data = get_student(student_id)

    # Convert dictionary to pretty string
    response = "\n".join(f"{k}: {v}" for k, v in student_data.items())

    await update.message.reply_text(response)

# Echo messages
async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"I cant reply to your messages")


# Replace 'YOUR_TOKEN_HERE' with your BotFather token
app = ApplicationBuilder().token(telegram_token).build()

# Handlers
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("get_student", get_student_bot))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

print("Bot is running...")
app.run_polling()
