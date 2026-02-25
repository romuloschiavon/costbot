# main.py
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from dotenv import load_dotenv
from fastapi import FastAPI, Request

load_dotenv()

from services import Services, today_sp
from state import BotState, normalize_bank, parse_desc_and_value

app = FastAPI()
svc = Services()
bot = BotState()


def chunk(rows: List[str], n: int) -> List[List[str]]:
    return [rows[i : i + n] for i in range(0, len(rows), n)]


async def ask_pai() -> None:
    kb = {
        "inline_keyboard": [
            [
                {"text": "Sim", "callback_data": "pai_sim"},
                {"text": "Não", "callback_data": "pai_nao"},
            ]
        ]
    }
    await svc.send("Gasto com o Pai?", kb)


async def ask_cc() -> None:
    kb = {
        "inline_keyboard": [
            [
                {"text": "Sim", "callback_data": "cc_sim"},
                {"text": "Não", "callback_data": "cc_nao"},
            ]
        ]
    }
    await svc.send("Cartão de crédito?", kb)


async def ask_bank() -> None:
    kb = {
        "inline_keyboard": [
            [
                {"text": "BB", "callback_data": "bank_BB"},
                {"text": "Itaú", "callback_data": "bank_Itau"},
            ],
            [
                {"text": "XP", "callback_data": "bank_XP"},
                {"text": "Infinite", "callback_data": "bank_Infinite"},
            ],
        ]
    }
    await svc.send("Qual conta?", kb)


async def ask_category() -> None:
    cats = await svc.get_categories()
    if not cats:
        cats = [
            "Comida",
            "Moradia",
            "Transporte",
            "Pessoal",
            "Higiene/Saúde",
            "Tech",
            "Carro",
            "Internet",
            "Academia",
        ]

    kb = {
        "keyboard": chunk(cats, 3),
        "resize_keyboard": True,
        "one_time_keyboard": True,
    }
    await svc.send("Escolha a categoria:", kb)


def build_google_post_payload() -> Dict[str, Any]:
    nome = str(bot.data["nome"])
    valor = str(bot.data["valor"])
    cat = str(bot.data["cat"])
    pai = bool(bot.data["pai"])
    cc = bool(bot.data["cc"])
    bank = str(bot.data.get("bank", ""))

    return {
        "nome": nome,
        "valor": valor,
        "data": today_sp(),
        "categoria": cat,
        "conta": "Cartão" if cc else bank,
        "pai": pai,
        "cc": cc,
    }


def build_google_check_params() -> Dict[str, Any]:
    return {
        "action": "check",
        "nome": str(bot.data["nome"]),
        "valor": str(bot.data["valor"]),
        "data": today_sp(),
        "cc": str(bool(bot.data["cc"])).lower(),
    }


async def check_google_with_retry() -> bool:
    for delay in (0.2, 0.6, 1.2, 2.0):
        j = await svc.check_google(build_google_check_params())
        if bool(j.get("encontrado")):
            return True
        await asyncio.sleep(delay)
    return False


async def finalize_send_to_google() -> None:
    await svc.send("Enviando...")
    await svc.post_google(build_google_post_payload())

    ok = await check_google_with_retry()
    if ok:
        await svc.send("Confirmado na planilha!")
    else:
        j = await svc.check_google(build_google_check_params())
        erro = j.get("erro")
        if erro:
            await svc.send(f"Google recebeu, mas não confirmou. Erro: {erro}")
        else:
            await svc.send("Google recebeu, mas não confirmou.")
    bot.reset()


async def handle_message(text: str) -> None:
    if text == "/cancelar":
        bot.reset()
        await svc.send("Cancelado.")
        return

    if text == "/novo" and bot.step == "IDLE":
        bot.step = "WAITING_PAI"
        await ask_pai()
        return

    if bot.step == "WAITING_DESC":
        parsed = parse_desc_and_value(text)
        if not parsed:
            await svc.send("Formato inválido!\nExemplo: mercado,-150,00")
            return

        nome, valor = parsed
        bot.data["nome"] = nome
        bot.data["valor"] = valor
        bot.step = "WAITING_CAT"
        await ask_category()
        return

    if bot.step == "WAITING_CAT":
        bot.data["cat"] = text.strip()
        if bool(bot.data.get("cc", False)):
            await finalize_send_to_google()
        else:
            bot.step = "WAITING_BANK"
            await ask_bank()
        return


async def handle_callback(data_cb: str, callback_id: str) -> None:
    await svc.answer_callback(callback_id)

    if data_cb.startswith("pai_"):
        bot.data["pai"] = data_cb == "pai_sim"
        bot.step = "WAITING_CC"
        await ask_cc()
        return

    if data_cb.startswith("cc_"):
        bot.data["cc"] = data_cb == "cc_sim"
        bot.step = "WAITING_DESC"
        await svc.send("Digite no formato:\nmercado,-150,00")
        return

    if data_cb.startswith("bank_"):
        bank = data_cb.split("_", 1)[1]
        bot.data["bank"] = normalize_bank(bank)
        await finalize_send_to_google()
        return


@app.on_event("startup")
async def on_startup() -> None:
    await svc.start()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await svc.close()


@app.post("/webhook")
async def webhook(req: Request) -> Dict[str, bool]:
    body = await req.json()

    if "callback_query" in body:
        cb = body["callback_query"]
        if str(cb["from"]["id"]) != svc.my_chat_id:
            return {"ok": True}
        await handle_callback(str(cb.get("data", "")), str(cb.get("id", "")))
        return {"ok": True}

    if "message" in body:
        msg = body["message"]
        if str(msg["chat"]["id"]) != svc.my_chat_id:
            return {"ok": True}
        text = str(msg.get("text", "") or "")
        await handle_message(text)

    return {"ok": True}
