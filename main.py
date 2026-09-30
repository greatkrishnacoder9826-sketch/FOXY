import asyncio
import base64
import datetime
import hmac
import json
import logging
import os
import re
from pathlib import Path

import edge_tts
from elevenlabs.client import ElevenLabs
from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from google.cloud import speech
from google.oauth2 import service_account
from groq import Groq

try:  # local testing ke liye .env padh lo (Render pe zaroorat nahi)
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

log = logging.getLogger("english-coach")
BASE = Path(__file__).parent

ACCESS_CODE = os.environ["ACCESS_CODE"]  # bina iske app start hi nahi hogi
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
ELEVEN_VOICE = os.getenv("ELEVEN_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")
STT_MINUTES_LIMIT = float(os.getenv("STT_MINUTES_LIMIT", "55"))
MAX_UPLOAD = 3 * 1024 * 1024
USAGE_FILE = BASE / "usage.json"

SYSTEM_PROMPT = """You are a friendly English speaking coach for a Hindi-speaking learner.
The learner's sentence comes from speech-to-text, so ignore capitalization and punctuation mistakes.
Reply ONLY with JSON in this exact shape:
{"corrected": "the corrected sentence",
 "explanation": "one or two short lines in simple Hinglish explaining the mistake (say 'Bilkul sahi!' if there was none)",
 "reply": "a short friendly follow-up question in simple English to keep the conversation going"}
If the sentence is already correct, keep corrected the same as the input."""


def make_stt_client() -> speech.SpeechClient:
    raw = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if raw:  # Render: poora service-account JSON env var mein
        creds = service_account.Credentials.from_service_account_info(json.loads(raw))
        return speech.SpeechClient(credentials=creds)
    return speech.SpeechClient()  # local: GOOGLE_APPLICATION_CREDENTIALS file


stt_client = make_stt_client()
groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])
eleven = ElevenLabs(api_key=os.environ["ELEVEN_API_KEY"])

app = FastAPI()


# ---------- Google STT usage counter (best effort) ----------
def _month() -> str:
    return datetime.date.today().strftime("%Y-%m")


def stt_seconds_used() -> float:
    try:
        d = json.loads(USAGE_FILE.read_text())
        return float(d["seconds"]) if d["month"] == _month() else 0.0
    except Exception:
        return 0.0


def add_stt_seconds(seconds: float) -> None:
    try:
        USAGE_FILE.write_text(
            json.dumps({"month": _month(), "seconds": stt_seconds_used() + seconds})
        )
    except Exception:
        pass


# ---------- pipeline steps ----------
def speech_to_text(wav: bytes) -> str:
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=16000,
        language_code="en-IN",
        enable_automatic_punctuation=True,
    )
    resp = stt_client.recognize(config=config, audio=speech.RecognitionAudio(content=wav))
    return " ".join(r.alternatives[0].transcript.strip() for r in resp.results).strip()


def ask_llm(text: str) -> dict:
    r = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        response_format={"type": "json_object"},
        temperature=0.4,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
    )
    return json.loads(r.choices[0].message.content)


def eleven_tts(text: str) -> bytes:
    audio = eleven.text_to_speech.convert(
        voice_id=ELEVEN_VOICE,
        text=text,
        model_id="eleven_flash_v2_5",
        output_format="mp3_44100_128",
    )
    return b"".join(audio)


async def edge_tts_bytes(text: str) -> bytes:
    buf = b""
    async for chunk in edge_tts.Communicate(text, "en-IN-NeerjaNeural").stream():
        if chunk["type"] == "audio":
            buf += chunk["data"]
    return buf


async def text_to_speech(text: str):
    """ElevenLabs pehle. Credits khatam ya error aaye toh edge-tts. Woh bhi fail ho toh None
    (browser apni awaaz se bol dega)."""
    try:
        return await asyncio.to_thread(eleven_tts, text), "elevenlabs"
    except Exception as e:
        log.warning("ElevenLabs failed, falling back to edge-tts: %s", e)
    try:
        return await edge_tts_bytes(text), "edge-tts"
    except Exception as e:
        log.warning("edge-tts failed: %s", e)
    return None, "browser"


def _plain(s: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", "", s.lower()).split())


# ---------- routes ----------
@app.get("/")
def index():
    return FileResponse(BASE / "index.html")


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.post("/api/practice")
async def practice(audio: UploadFile = File(...), x_access_code: str = Header(default="")):
    if not hmac.compare_digest(x_access_code.encode(), ACCESS_CODE.encode()):
        raise HTTPException(401, "Access code galat hai.")

    wav = await audio.read()
    if len(wav) > MAX_UPLOAD:
        raise HTTPException(413, "Recording bahut lambi hai. Ek minute se chhoti rakho.")
    seconds = max(0.0, (len(wav) - 44) / 32000)  # 16 kHz, 16-bit, mono
    if seconds < 0.4:
        raise HTTPException(422, "Recording bahut chhoti thi. Dobara bolo.")
    if (stt_seconds_used() + seconds) / 60 > STT_MINUTES_LIMIT:
        raise HTTPException(429, "Is mahine ki free speech limit khatam ho gayi. Agle mahine try karo.")

    try:
        transcript = await asyncio.to_thread(speech_to_text, wav)
        add_stt_seconds(seconds)
    except Exception as e:
        log.exception("STT failed")
        raise HTTPException(502, f"Speech-to-text mein dikkat aayi: {e}")
    if not transcript:
        raise HTTPException(422, "Awaaz samajh nahi aayi. Mic ke paas saaf bolo aur dobara try karo.")

    try:
        result = await asyncio.to_thread(ask_llm, transcript)
    except Exception as e:
        log.exception("LLM failed")
        raise HTTPException(502, f"AI se jawab lene mein dikkat aayi: {e}")

    corrected = (result.get("corrected") or transcript).strip()
    explanation = (result.get("explanation") or "").strip()
    reply = (result.get("reply") or "").strip()

    # Sirf sahi sentence bulwao, credits bachte hain. Reply text mein dikhta hai.
    if _plain(corrected) == _plain(transcript):
        say = f"Perfect! {corrected}"
    else:
        say = f"You should say: {corrected}"
    mp3, engine = await text_to_speech(say)

    return {
        "transcript": transcript,
        "corrected": corrected,
        "explanation": explanation,
        "reply": reply,
        "say": say,
        "audio": base64.b64encode(mp3).decode() if mp3 else None,
        "engine": engine,
    }
