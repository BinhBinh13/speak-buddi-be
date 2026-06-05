# SpeakBuddi Backend 🎤

API backend cho ứng dụng luyện nói tiếng Anh **SpeakBuddi**, xây dựng bằng FastAPI + Claude AI + ElevenLabs TTS.

---

## Tech Stack

| Layer | Công nghệ |
|-------|-----------|
| Framework | FastAPI |
| AI | Anthropic Claude (claude-haiku-4-5) |
| Text-to-Speech | ElevenLabs (eleven_multilingual_v2) |
| Auth | JWT (tự implement, không dùng thư viện ngoài) |

---

## Tính năng

- **`POST /speak`** — Nhận transcript từ user, gọi Claude tạo AI reply, convert sang audio qua ElevenLabs, trả về MP3 stream kèm header `X-Reply-Text`
- **`POST /tts`** — Convert text thành audio (dùng cho intro greeting, không qua Claude)
- **`POST /api/auth/login`** — Đăng nhập bằng email/password, trả về JWT token
- **`GET /api/auth/me`** — Lấy thông tin user từ JWT token
- **`GET /health`** — Health check endpoint

---

## Cài đặt

### 1. Clone repo

```bash
git clone https://github.com/your-username/speak-buddi-be.git
cd speak-buddi-be
```

### 2. Tạo virtual environment

```bash
python -m venv .venv
source .venv/bin/activate      # Mac/Linux
.venv\Scripts\activate         # Windows
```

### 3. Cài dependencies

```bash
pip install fastapi uvicorn python-dotenv anthropic elevenlabs pydantic
```

### 4. Tạo file `.env`

```env
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxx
ELEVENLABS_API_KEY=xxxxxxxxxx
ELEVENLABS_VOICE_ID=pNInz6obpgDQGcFmaJgB
JWT_SECRET=your-secret-key
ALLOWED_ORIGINS=http://localhost:5173,http://localhost:3000
```

### 5. Chạy server

```bash
uvicorn main:app --reload --port 8000
```

Server chạy tại: `http://localhost:8000`

---

## Cấu trúc request

### `POST /speak`

```json
{
  "text": "Hello, how are you?",
  "context": "Daily conversation",
  "topic": {
    "label": "Greetings",
    "words": ["hello", "hi", "good morning"],
    "grammarTopics": ["Basic greetings structure"]
  }
}
```

Response: `audio/mpeg` stream + header `X-Reply-Text` (URL-encoded)

### `POST /tts`

```json
{
  "text": "Let's talk about your weekend plans!"
}
```

Response: `audio/mpeg` stream

### `POST /api/auth/login`

```json
{
  "email": "demo@speakbuddi.com",
  "password": "password123"
}
```

---

## Môi trường Demo

| Email | Password |
|-------|----------|
| demo@speakbuddi.com | password123 |

---

## Frontend

Frontend repo: [speak-buddi-fe](https://github.com/BinhBinh13/speak-buddi) — React + Vite