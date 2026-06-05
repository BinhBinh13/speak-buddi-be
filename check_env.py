import sys
import os

print("=" * 50)
print("SpeakBuddi Backend - Environment Check")
print("=" * 50)

# 1. Check Python version
print(f"\n✅ Python: {sys.version}")

# 2. Check required packages
packages = ["fastapi", "uvicorn", "dotenv", "anthropic", "elevenlabs", "pydantic"]
print("\n📦 Packages:")
for pkg in packages:
    try:
        __import__(pkg if pkg != "dotenv" else "dotenv")
        import importlib.metadata
        version = importlib.metadata.version(pkg if pkg != "dotenv" else "python-dotenv")
        print(f"  ✅ {pkg} ({version})")
    except Exception:
        print(f"  ❌ {pkg} — MISSING")

# 3. Check .env file
print("\n🔑 Environment Variables:")
from dotenv import load_dotenv
load_dotenv()

keys = ["ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID", "JWT_SECRET", "ALLOWED_ORIGINS"]
for key in keys:
    val = os.getenv(key)
    if val:
        masked = val[:8] + "..." if len(val) > 8 else val
        print(f"  ✅ {key} = {masked}")
    else:
        print(f"  ❌ {key} — NOT SET")

print("\n" + "=" * 50)