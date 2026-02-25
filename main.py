import os
import aiohttp
from fastapi import FastAPI, Request
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

# Carrega .env
load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
MY_CHAT_ID = os.environ["MY_CHAT_ID"]
API_URL = os.environ["API_URL"]

BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

app = FastAPI()

state = "IDLE"
data = {}

# ---------- util ----------

def today():
    return datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y")

async def send(text, reply_markup=None):
    payload = {
        "chat_id": MY_CHAT_ID,
        "text": text
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    async with aiohttp.ClientSession() as s:
        await s.post(f"{BASE}/sendMessage", json=payload)

async def answer_callback(callback_id):
    async with aiohttp.ClientSession() as s:
        await s.post(f"{BASE}/answerCallbackQuery", json={"callback_query_id": callback_id})

# ---------- google ----------

async def post_google():
    async with aiohttp.ClientSession() as s:
        await s.post(API_URL, json={
            "nome": data["nome"],
            "valor": data["valor"],
            "data": today(),
            "categoria": data["cat"],
            "conta": "Cartão" if data["cc"] else data["bank"],
            "pai": data["pai"],
            "cc": data["cc"]
        })

async def check_google():
    async with aiohttp.ClientSession() as s:
        async with s.get(API_URL, params={
            "action": "check",
            "nome": data["nome"],
            "valor": data["valor"],
            "data": today(),
            "cc": data["cc"]
        }) as r:
            j = await r.json()
            if j.get("encontrado"):
                await send("Confirmado na planilha!")
            else:
                await send("Google recebeu, mas não confirmou.")

# ---------- perguntas ----------

async def ask_pai():
    kb = {
        "inline_keyboard": [[
            {"text": "Sim", "callback_data": "pai_sim"},
            {"text": "Não", "callback_data": "pai_nao"}
        ]]
    }
    await send("Gasto com o Pai?", kb)

async def ask_cc():
    kb = {
        "inline_keyboard": [[
            {"text": "Sim", "callback_data": "cc_sim"},
            {"text": "Não", "callback_data": "cc_nao"}
        ]]
    }
    await send("Cartão de crédito?", kb)

async def ask_bank():
    kb = {
        "inline_keyboard": [
            [
                {"text": "BB", "callback_data": "bank_BB"},
                {"text": "Itaú", "callback_data": "bank_Itau"}
            ],
            [
                {"text": "XP", "callback_data": "bank_XP"},
                {"text": "Infinite", "callback_data": "bank_Infinite"}
            ]
        ]
    }
    await send("Qual conta?", kb)

async def ask_category():
    kb = {
        "keyboard": [
            ["Comida", "Moradia", "Transporte"],
            ["Pessoal", "Higiene/Saúde", "Tech"],
            ["Carro", "Internet", "Academia"]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": True
    }
    await send("Escolha a categoria:", kb)

# ---------- mensagens ----------

async def handle_message(text):
    global state

    if text == "/cancelar":
        state = "IDLE"
        await send("Cancelado.")
        return

    if text == "/novo" and state == "IDLE":
        state = "WAITING_PAI"
        await ask_pai()
        return

    if state == "WAITING_DESC":
        try:
            nome, valor = text.split(",", 1)
            data["nome"] = nome.strip()
            data["valor"] = valor.strip()
            state = "WAITING_CAT"
            await ask_category()
        except:
            await send("Formato inválido!\nExemplo: mercado,-150,00")

    elif state == "WAITING_CAT":
        data["cat"] = text
        if data["cc"]:
            await send("Enviando...")
            await post_google()
            await check_google()
            state = "IDLE"
        else:
            state = "WAITING_BANK"
            await ask_bank()

# ---------- callbacks ----------

async def handle_callback(data_cb, callback_id):
    global state

    await answer_callback(callback_id)

    if data_cb.startswith("pai_"):
        data["pai"] = data_cb == "pai_sim"
        state = "WAITING_CC"
        await ask_cc()
        return

    if data_cb.startswith("cc_"):
        data["cc"] = data_cb == "cc_sim"
        state = "WAITING_DESC"
        await send("Digite no formato:\nmercado,-150,00")
        return

    if data_cb.startswith("bank_"):
        data["bank"] = data_cb.split("_")[1]
        await send("Enviando...")
        await post_google()
        await check_google()
        state = "IDLE"

# ---------- webhook ----------

@app.post("/webhook")
async def webhook(req: Request):
    body = await req.json()

    if "callback_query" in body:
        cb = body["callback_query"]
        if str(cb["from"]["id"]) != MY_CHAT_ID:
            return {"ok": True}
        await handle_callback(cb["data"], cb["id"])
        return {"ok": True}

    if "message" in body:
        msg = body["message"]
        if str(msg["chat"]["id"]) != MY_CHAT_ID:
            return {"ok": True}
        text = msg.get("text", "")
        await handle_message(text)

    return {"ok": True}