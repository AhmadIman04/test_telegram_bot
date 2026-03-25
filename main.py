from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, 
    CallbackQueryHandler, ConversationHandler, filters, ContextTypes
)
import gspread
import pandas as pd
from google.oauth2.service_account import Credentials
import os
from dotenv import load_dotenv
import json
from keep_alive import keep_alive
import numpy as np

keep_alive()

load_dotenv()

allowed_groups = os.getenv("ALLOWED_GROUPS", "")
# convert string to list of ints
allowed_groups =[int(x) for x in allowed_groups.split(",") if x]

g_sheet_url = os.getenv("g_sheet_link")
telegram_token = os.getenv("telegram_token")

scope =[
    "https://www.googleapis.com/auth/spreadsheets"
]

# Load credentials
creds_json = os.getenv("GOOGLE_CREDS_JSON")
creds_dict = json.loads(creds_json)
creds = Credentials.from_service_account_info(creds_dict, scopes=scope)

# Authorize client
client = gspread.authorize(creds)

# Open the Google Sheet by URL
sheet = client.open_by_url(g_sheet_url)

# Define conversation states
CHOOSING_PANEL, TYPING_MEDICINE = range(2)


def get_data():
    worksheet = sheet.get_worksheet(1)
    data = worksheet.get_all_values()
    raw_headers = [col.strip() for col in data[0]]
    new_headers =[]
    last_valid = None
    for col in raw_headers:
        if col != '':
            # normal column
            new_headers.append(col)
            last_valid = col
        else:
            # merged/empty column → treat as "_limit"
            new_headers.append(f"{last_valid}_limit")

    df = pd.DataFrame(data[1:], columns=new_headers)
    df = df.replace("", np.nan)
    if 'None_limit' in df.columns:
        df.drop(columns=['None_limit'], inplace=True)
        
    df = df[df["PANEL NAME"].notna()]
    df = df[df["PANEL NAME"].astype(str).str.strip() != ""] # drop rows where panel name is empty
    df = df[df.isna().sum(axis=1) < 12] # remove rows with more than 12 nan values
    df = df[df["PANEL NAME"] != "CONSULTATION (RM)"]
    df = df.reset_index(drop=True)
    
    return df


def get_medicine(medicine_name: str, panel_name: str, df: pd.DataFrame = None):
    # Pass df as argument so we don't have to fetch the Google Sheet twice in one go
    if df is None:
        df = get_data()
        
    panel_with_limits =['MICARE (FFS)', 'MICARE (HMO)', 'EMAS']
    
    # Make the search case-insensitive
    temp_row = df[df["PANEL NAME"].astype(str).str.strip().str.upper() == medicine_name.strip().upper()]
    
    if temp_row.empty:
        raise ValueError(f"Medicine '{medicine_name}' not found in the DataFrame")
    
    if panel_name in panel_with_limits:
        price = temp_row.iloc[0][panel_name]
        limit = temp_row.iloc[0].get(f"{panel_name}_limit", np.nan)
        return {"price": price, "limit": limit}
    else:
        price = temp_row.iloc[0][panel_name]
        return {"price": price}


# 1. Start command - Show buttons
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in allowed_groups:
        await update.message.reply_text("⛔ You are not authorized to use this bot.")
        return 

    message = update.message if update.message else update.callback_query.message
    
    await message.reply_text("Fetching panels, please wait... ⏳")
    
    df = get_data()
    panel_names =[col for col in df.columns if "_limit" not in col and col != "PANEL NAME"]
    
    # Build inline keyboard buttons
    keyboard =[]
    for i in range(0, len(panel_names), 2):
        row =[InlineKeyboardButton(name, callback_data=f"panel_{name}") for name in panel_names[i:i+2]]
        keyboard.append(row)
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = (
        "Assalamualaikum / Hello 👋\n"
        "Selamat datang ke *Semakan Panel Klinik* 🏥\n\n"
        "Sila pilih panel di bawah 👇:"
    )
    
    await message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")
    return CHOOSING_PANEL


# 2. Button clicked - Save panel, ask for medicine
async def panel_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in allowed_groups:
        await update.message.reply_text("⛔ You are not authorized to use this bot.")
        return 
    
    query = update.callback_query
    await query.answer() 
    
    selected_panel = query.data.replace("panel_", "")
    context.user_data['selected_panel'] = selected_panel 
    
    instruction_text = (
        f"✅ Panel dipilih: *{selected_panel}*\n\n"
        "💊 Sila taip nama ubat atau servis yang anda ingin semak.\n"
        "Contoh:\n"
        "🔹 `omeprazole`\n"
        "🔹 `bisacodyl`\n"
        "🔹 `pronex`"

    )
    
    await query.edit_message_text(instruction_text, parse_mode="Markdown")
    return TYPING_MEDICINE


# 3. Search for available medicine (When staff types partial text)
async def search_medicine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in allowed_groups:
        await update.message.reply_text("⛔ You are not authorized to use this bot.")
        return 
    
    medicine_query = update.message.text.strip().upper()
    panel_name = context.user_data.get('selected_panel')
    
    if not panel_name:
        await update.message.reply_text("⚠️ Sila pilih panel terlebih dahulu dengan menaip /start")
        return ConversationHandler.END

    await update.message.reply_text("Mencari maklumat... 🔍")
    
    df = get_data()
    # Case insensitive partial match
    temp_row = df[df["PANEL NAME"].astype(str).str.upper().str.contains(medicine_query, na=False)]
    list_medicine = temp_row["PANEL NAME"].unique().tolist()
    
    # Scenario A: Not found
    if len(list_medicine) == 0:
        await update.message.reply_text("❌ *Maklumat tidak dijumpai.*\nSila semak ejaan anda atau rujuk panel admin 👩‍💻.", parse_mode="Markdown")
        return TYPING_MEDICINE
        
    # Scenario B: Exact 1 match
    elif len(list_medicine) == 1:
        exact_item = list_medicine[0]
        # Notice is_auto_match=True is passed here so it prints the disclaimer
        await send_coverage_details(update.message, context, exact_item, panel_name, df, is_auto_match=True)
        return TYPING_MEDICINE
        
    # Scenario C: Multiple possible matches
    else:
        top_matches = list_medicine[:15]
        
        keyboard =[]
        for idx, item in enumerate(top_matches):
            cb_data = f"item_{idx}"
            context.user_data[cb_data] = item
            keyboard.append([InlineKeyboardButton(f"💊 {item}", callback_data=cb_data)])
            
        # Add the "Not Found" option at the bottom
        keyboard.append([InlineKeyboardButton("❌ Ubat tidak dijumpai", callback_data="item_not_found")])
            
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        text = "🎯 Carian anda jumpa beberapa item. Sila pilih item yang betul di bawah 👇:"
        if len(list_medicine) > 15:
            text = f"🎯 Carian anda jumpa {len(list_medicine)} item. Ini adalah 15 yang teratas. Sila pilih 👇:"
            
        await update.message.reply_text(text, reply_markup=reply_markup)
        return TYPING_MEDICINE


# 4. Medicine button selected from suggestions
async def item_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in allowed_groups:
        await update.message.reply_text("⛔ You are not authorized to use this bot.")
        return  
    
    query = update.callback_query
    await query.answer()
    cb_data = query.data

    # Handle the "Not Found" button click
    if cb_data == "item_not_found":
        await query.edit_message_text(
            "❌ *Ubat tidak dijumpai dalam senarai ini.*\n\n"
            "Sila semak semula ejaan anda dan taip nama ubat/servis baharu, atau rujuk panel admin 👩‍💻.",
            parse_mode="Markdown"
        )
        return TYPING_MEDICINE

    selected_item = context.user_data.get(cb_data)
    panel_name = context.user_data.get('selected_panel')
    
    if not selected_item or not panel_name:
        await query.edit_message_text("⚠️ Sesi tamat. Sila taip /start untuk mula semula.")
        return ConversationHandler.END

    await query.edit_message_text("Mengambil data... ⏳")
    
    # Fetch details (is_auto_match default is False, so no disclaimer here)
    await send_coverage_details(query.message, context, selected_item, panel_name, edit=True)
    return TYPING_MEDICINE


# Helper function to print out coverage limit
async def send_coverage_details(message_obj, context, item_name, panel_name, df=None, edit=False, is_auto_match=False):
    try:
        med_data = get_medicine(item_name, panel_name, df)
        price = med_data.get("price")
        
        reply = f"🏢 Panel: *{panel_name}*\n📦 Item: *{item_name}*\n"
        
        # Check if Not Covered (blank or NaN)
        if pd.isna(price) or str(price).strip() == "" or str(price).strip().upper() == "NAN":
            reply += "⚠️ Status: *Not covered*\n\n_Sila rujuk panel admin jika perlu pengesahan lanjut._"
        else:
            reply += f"✅ Coverage (RM): *{price}*"
            
            # Check limits if applicable
            if "limit" in med_data:
                limit = med_data.get("limit")
                if not pd.isna(limit) and str(limit).strip() != "" and str(limit).strip().upper() != "NAN":
                    reply += f"\n🛑 Limit: *{limit}*"

        # Add the disclaimer ONLY if the bot automatically assumed a single match
        if is_auto_match:
            reply += "\n\n_💡 P/S: Jika ini bukan ubat atau servis yang dicari, sila semak semula ejaan anda atau rujuk panel admin._"
                    
        if edit:
            await message_obj.edit_text(reply, parse_mode="Markdown")
        else:
            await message_obj.reply_text(reply, parse_mode="Markdown")
            
    except Exception as e:
        error_msg = f"❌ Ralat: Maklumat tidak dijumpai. ({str(e)})"
        if edit:
            await message_obj.edit_text(error_msg)
        else:
            await message_obj.reply_text(error_msg)


# Fallback command to cancel
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in allowed_groups:
        await update.message.reply_text("⛔ You are not authorized to use this bot.")
        return 
    await update.message.reply_text("🛑 Sesi dibatalkan. Taip /start untuk mula semula.")
    return ConversationHandler.END


# ------------- BOT EXECUTION -------------
application = ApplicationBuilder().token(telegram_token).build()

conv_handler = ConversationHandler(
    entry_points=[CommandHandler('start', start)],
    states={
        CHOOSING_PANEL:[
            CallbackQueryHandler(panel_selected, pattern="^panel_")
        ],
        TYPING_MEDICINE:[
            # When user types a word
            MessageHandler(filters.TEXT & ~filters.COMMAND, search_medicine),
            # When user clicks a suggestion button (this will also catch "item_not_found")
            CallbackQueryHandler(item_selected, pattern="^item_")
        ]
    },
    fallbacks=[
        CommandHandler('start', start),
        CommandHandler('cancel', cancel)
    ]
)

application.add_handler(conv_handler)

print("Bot is up and running... 🚀")
application.run_polling()
