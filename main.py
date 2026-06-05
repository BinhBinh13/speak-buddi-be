import os
import io
import json
import time
import logging
from functools import lru_cache
from urllib.parse import quote
from dotenv import load_dotenv
import anthropic
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import base64, hashlib, hmac
from elevenlabs.client import ElevenLabs
from pydantic import BaseModel

# ─── Config ───────────────────────────────────────────────────────────────────
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger("speakbuddi")

ANTHROPIC_API_KEY   = os.getenv("ANTHROPIC_API_KEY", "")
ELEVENLABS_API_KEY  = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "pNInz6obpgDQGcFmaJgB")
JWT_SECRET          = os.getenv("JWT_SECRET", "speakbuddi-secret-change-in-prod")
ALLOWED_ORIGINS     = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",")
MAX_HISTORY_TURNS = 10

# ─── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(title="SpeakBuddi API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Reply-Text"],
)

# ─── API Clients ──────────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def get_claude_client() -> anthropic.Anthropic:
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set in .env")
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

@lru_cache(maxsize=1)
def get_elevenlabs_client() -> ElevenLabs:
    if not ELEVENLABS_API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY not set in .env")
    return ElevenLabs(api_key=ELEVENLABS_API_KEY)

# ─── Auth (JWT minimal, no external lib) ──────────────────────────────────────
def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

def _sign(payload: dict) -> str:
    header = _b64url(b'{"alg":"HS256","typ":"JWT"}')
    body   = _b64url(json.dumps(payload).encode())
    sig    = _b64url(hmac.new(JWT_SECRET.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest())
    return f"{header}.{body}.{sig}"

def _verify(token: str) -> dict:
    try:
        h, b, s = token.split(".")
        expected = _b64url(hmac.new(JWT_SECRET.encode(), f"{h}.{b}".encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(s, expected):
            raise ValueError("bad signature")
        payload = json.loads(base64.urlsafe_b64decode(b + "=="))
        if payload.get("exp", 0) < time.time():
            raise ValueError("token expired")
        return payload
    except Exception as exc:
        raise HTTPException(status_code=401, detail=str(exc))

security = HTTPBearer(auto_error=False)

def current_user(creds: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    if not creds:
        raise HTTPException(status_code=401, detail="Missing token")
    return _verify(creds.credentials)

# ─── Mock user store ──────────────────────────────────────────────────────────
MOCK_USERS = {
    "demo@speakbuddi.com": {
        "id":            "u_001",
        "name":          "Demo User",
        "email":         "demo@speakbuddi.com",
        "password_hash": hashlib.sha256("password123".encode()).hexdigest(),
        "level":         "B1",
        "streak":        7,
        "goal":          "IELTS 7.0",
    }
}

# ─── Pydantic schemas ─────────────────────────────────────────────────────────
class TopicData(BaseModel):
    label:         str
    words:         list[str] | None = None
    grammarTopics: list[str] | None = None

class HistoryMessage(BaseModel):
    """Một lượt hội thoại: role là 'user' hoặc 'assistant'"""
    role:    str   # "user" | "assistant"
    content: str

class SpeakRequest(BaseModel):
    text:    str
    context: str | None            = None
    topic:   TopicData | None      = None
    history: list[HistoryMessage]  = []   # ← THÊM: lịch sử hội thoại từ frontend

class TTSRequest(BaseModel):
    text: str

class LoginRequest(BaseModel):
    email:    str
    password: str

# ─── TTS helper ───────────────────────────────────────────────────────────────
def text_to_audio_bytes(text: str) -> bytes:
    client = get_elevenlabs_client()
    audio_chunks = client.text_to_speech.convert(
        voice_id=ELEVENLABS_VOICE_ID,
        text=text,
        model_id="eleven_multilingual_v2",
        output_format="mp3_44100_128",
    )
    return b"".join(audio_chunks)

# ─── Claude helper ────────────────────────────────────────────────────────────
_PROMPT_BASE = """You are SpeakBuddi AI — a friendly English speaking coach.

Rules:
- Always reply in English only.
- Keep it SHORT: 2-3 sentences max — this is a voice conversation.
- End with a short question to keep the conversation going.
- Natural, friendly tone.
- If the user makes a grammar mistake, gently correct it once.
- NO markdown, bullet points, or special characters — plain prose only."""

def _build_system_prompt(topic: TopicData | None, context: str | None) -> str:
    # ── GREETING MODE ─────────────────────────────────────────────────────────
    if context and context.startswith("GREETING_MODE:"):
        vocab   = ", ".join(topic.words[:6])         if topic and topic.words         else ""
        grammar = ", ".join(topic.grammarTopics[:3]) if topic and topic.grammarTopics else ""
        label   = topic.label if topic else "bài học này"

        return f"""You are SpeakBuddi AI — a friendly English speaking coach.

Your task: Generate an OPENING GREETING for the lesson "{label}".

The greeting should:
1. Welcome the user and introduce the topic "{label}" (1 sentence).
2. Mention 2-3 key words to practice: {vocab if vocab else "related vocabulary"}.
3. Ask an opening question to start the conversation (1 sentence).

Rules: English only, NO markdown, max 4 sentences, natural tone."""

    # ── TOPIC MODE ────────────────────────────────────────────────────────────
    if topic:
        vocab   = ", ".join(topic.words[:8])     if topic.words         else ""
        grammar = ", ".join(topic.grammarTopics) if topic.grammarTopics else ""
        extra   = f"""

Bài học đang luyện: "{topic.label}"
{f"Từ vựng cần dùng trong hội thoại: {vocab}" if vocab else ""}
{f"Ngữ pháp cần luyện tập: {grammar}" if grammar else ""}

Nhiệm vụ: tự nhiên lồng ghép các từ vựng và cấu trúc ngữ pháp trên vào câu hỏi để người học thực hành."""
        return _PROMPT_BASE + extra

    # ── FREE TOPIC MODE ───────────────────────────────────────────────────────
    if context:
        return _PROMPT_BASE + f'\n\nChủ đề tự do người dùng chọn: "{context}". Hãy dẫn dắt hội thoại xung quanh chủ đề này.'

    return _PROMPT_BASE


def _trim_history(history: list[HistoryMessage]) -> list[HistoryMessage]:
    """
    Giữ tối đa MAX_HISTORY_TURNS lượt gần nhất.
    Mỗi lượt = 1 user + 1 assistant → tối đa MAX_HISTORY_TURNS * 2 messages.
    Đảm bảo message đầu tiên luôn là role='user' (yêu cầu của Anthropic API).
    """
    max_msgs = MAX_HISTORY_TURNS * 2
    trimmed  = history[-max_msgs:] if len(history) > max_msgs else history

    # Nếu message đầu tiên là assistant thì bỏ đi để tránh lỗi API
    if trimmed and trimmed[0].role == "assistant":
        trimmed = trimmed[1:]

    return trimmed


def get_ai_reply(
    user_text: str,
    context:   str | None,
    topic:     TopicData | None,
    history:   list[HistoryMessage],
) -> str:
    client     = get_claude_client()
    system_msg = _build_system_prompt(topic, context)

    # Cắt history để tránh vượt context window
    trimmed_history = _trim_history(history)

    # Build messages: history cũ + tin nhắn hiện tại
    messages = [
        {"role": msg.role, "content": msg.content}
        for msg in trimmed_history
    ] + [{"role": "user", "content": user_text}]

    log.info("HISTORY  %d messages sent to Claude", len(messages))

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        system=system_msg,
        messages=messages,
    )
    return message.content[0].text.strip()

# ─── Routes ───────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "service": "speakbuddi-backend"}


@app.post("/speak")
async def speak(req: SpeakRequest):
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Empty text")

    mode = f"topic:{req.topic.label}" if req.topic else f"free:{req.context}"
    log.info("SPEAK  mode=%s  text=%r  history_len=%d", mode, req.text[:80], len(req.history))

    try:
        reply_text = get_ai_reply(req.text, req.context, req.topic, req.history)
    except Exception as exc:
        log.error("Claude error: %s", exc)
        raise HTTPException(status_code=502, detail="AI service error")

    try:
        audio_bytes = text_to_audio_bytes(reply_text)
    except Exception as exc:
        log.error("TTS error: %s", exc)
        raise HTTPException(status_code=502, detail="TTS service error")

    log.info("REPLY  %r", reply_text[:120])
    encoded_reply = quote(reply_text, safe="")

    return StreamingResponse(
        io.BytesIO(audio_bytes),
        media_type="audio/mpeg",
        headers={"X-Reply-Text": encoded_reply},
    )


@app.post("/tts")
async def tts(req: TTSRequest):
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Empty text")

    log.info("TTS  text=%r", req.text[:80])

    try:
        audio_bytes = text_to_audio_bytes(req.text)
    except Exception as exc:
        log.error("TTS error: %s", exc)
        raise HTTPException(status_code=502, detail="TTS service error")

    return StreamingResponse(io.BytesIO(audio_bytes), media_type="audio/mpeg")


@app.post("/api/auth/login")
async def login(req: LoginRequest):
    user = MOCK_USERS.get(req.email)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    pw_hash = hashlib.sha256(req.password.encode()).hexdigest()
    if not hmac.compare_digest(pw_hash, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = _sign({
        "sub":   user["id"],
        "email": user["email"],
        "name":  user["name"],
        "exp":   int(time.time()) + 86400 * 7,
    })

    return {
        "token": token,
        "user": {
            "id":     user["id"],
            "name":   user["name"],
            "email":  user["email"],
            "level":  user["level"],
            "streak": user["streak"],
            "goal":   user["goal"],
        }
    }


@app.get("/api/auth/me")
async def me(user: dict = Depends(current_user)):
    return user


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)