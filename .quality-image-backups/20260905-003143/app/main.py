from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.intelligence import IntelligenceEngine

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "app" / "static"
DATA_DIR = BASE_DIR / "data"
GENERATED_DIR = DATA_DIR / "generated"
DATA_DIR.mkdir(exist_ok=True)
GENERATED_DIR.mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "apex_ai.db"
load_dotenv(BASE_DIR / ".env")

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "huihui_ai/qwen3-abliterated:1.7b")
APP_TITLE = os.getenv("APP_TITLE", "Apex AI")
CHAT_HISTORY_MESSAGES = max(4, int(os.getenv("CHAT_HISTORY_MESSAGES", "16")))
KEEP_ALIVE = os.getenv("KEEP_ALIVE", "30m")
IMAGE_ENGINE_BASE_URL = os.getenv("IMAGE_ENGINE_BASE_URL", "http://127.0.0.1:8189").rstrip("/")
IMAGE_MODEL_NAME = os.getenv("IMAGE_MODEL_NAME", "DreamShaper-7-LCM-Q4")
KNOWLEDGE_DB = Path(os.getenv("KNOWLEDGE_DB", str(DATA_DIR / "knowledge_1m.db")))

app = FastAPI(title=APP_TITLE)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/generated", StaticFiles(directory=GENERATED_DIR), name="generated")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return utcnow().isoformat()


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                title TEXT NOT NULL,
                model TEXT NOT NULL,
                pinned INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                image_url TEXT,
                message_type TEXT DEFAULT 'text'
            );

            CREATE TABLE IF NOT EXISTS user_settings (
                user_id TEXT PRIMARY KEY,
                settings_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL
            );
            """
        )
        ensure_column(conn, "conversations", "user_id", "TEXT")
        ensure_column(conn, "conversations", "pinned", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "messages", "image_url", "TEXT")
        ensure_column(conn, "messages", "message_type", "TEXT DEFAULT 'text'")


init_db()

INTELLIGENCE = IntelligenceEngine(
    db_path=DB_PATH,
    knowledge_db=KNOWLEDGE_DB,
    ollama_base_url=OLLAMA_BASE_URL,
    keep_alive=KEEP_ALIVE,
)
INTELLIGENCE.ensure_schema()


DEFAULT_SETTINGS = {
    "theme": "nebula",
    "accent": "electric",
    "fontSize": 15,
    "density": "comfortable",
    "chatWidth": 780,
    "animations": True,
    "timestamps": False,
    "avatars": True,
    "enterToSend": True,
    "finishSound": False,
    "backgroundMode": "aurora",
    "backgroundIntensity": 0.65,
    "backgroundSpeed": 1.0,
    "glassStrength": 0.72,
    "cursorGlow": True,
    "backgroundBlur": 18,
    "responseMode": "fast",
    "temperature": 0.55,
    "maxTokens": 480,
    "contextWindow": 4096,
    "thinking": False,
    "systemPrompt": "You are Apex AI, a capable private local assistant. Be direct, clear, useful, and concise unless the user asks for detail.",
    "imageSize": "256x256",
    "imageSteps": 4,
    "imageNegativePrompt": "worst quality, low quality, lowres, blurry, deformed, malformed anatomy, extra limbs, extra fingers, fused fingers, bad hands, bad face, duplicate, text, watermark, logo",
    "imageStyle": "auto",
    "useKnowledge": True,
    "knowledgeResults": 5,
    "intelligenceMode": "auto",
    "autoModelRouting": True,
    "maxAutoModelB": 9,
    "adaptiveThinking": True,
    "longTermMemory": True,
    "autoLearnMemory": True,
    "conversationSummaries": True,
    "embeddingRerank": True,
    "memoryResults": 5,
}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    rounds = 310_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, rounds)
    return f"pbkdf2_sha256${rounds}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algo, rounds_s, salt_b64, digest_b64 = encoded.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(rounds_s))
        return hmac.compare_digest(expected, actual)
    except Exception:
        return False


def create_session(user_id: str) -> str:
    token = secrets.token_urlsafe(40)
    created = utcnow()
    expires = created + timedelta(days=30)
    with db() as conn:
        conn.execute(
            "INSERT INTO sessions(token,user_id,expires_at,created_at) VALUES(?,?,?,?)",
            (token, user_id, expires.isoformat(), created.isoformat()),
        )
    return token


def current_user(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Login required")
    token = authorization.split(" ", 1)[1].strip()
    with db() as conn:
        row = conn.execute(
            "SELECT u.id,u.username,s.expires_at FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=?",
            (token,),
        ).fetchone()
    if not row:
        raise HTTPException(401, "Invalid session")
    if datetime.fromisoformat(row["expires_at"]) < utcnow():
        with db() as conn:
            conn.execute("DELETE FROM sessions WHERE token=?", (token,))
        raise HTTPException(401, "Session expired")
    return {"id": row["id"], "username": row["username"], "token": token}


def conversation_for_user(conn: sqlite3.Connection, conversation_id: str, user_id: str):
    row = conn.execute(
        "SELECT * FROM conversations WHERE id=? AND user_id=?",
        (conversation_id, user_id),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Conversation not found")
    return row


def get_settings(user_id: str) -> dict:
    with db() as conn:
        row = conn.execute("SELECT settings_json FROM user_settings WHERE user_id=?", (user_id,)).fetchone()
    saved = {}
    if row:
        try:
            saved = json.loads(row["settings_json"])
        except Exception:
            saved = {}
    return {**DEFAULT_SETTINGS, **saved}


class AuthRequest(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=6, max_length=200)


class NewConversation(BaseModel):
    title: str = "New chat"
    model: str | None = None


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    pinned: bool | None = None


class ChatRequest(BaseModel):
    conversation_id: str
    message: str = Field(min_length=1)
    model: str | None = None
    system_prompt: str | None = None
    response_mode: str = "fast"
    temperature: float = Field(default=0.55, ge=0, le=2)
    max_tokens: int = Field(default=480, ge=64, le=4096)
    context_window: int = Field(default=4096, ge=1024, le=32768)
    thinking: bool = False
    use_knowledge: bool = True
    knowledge_results: int = Field(default=5, ge=1, le=10)
    intelligence_mode: str = "auto"
    auto_model_routing: bool = True
    max_auto_model_b: float = Field(default=9, ge=1, le=70)
    adaptive_thinking: bool = True
    use_memory: bool = True
    auto_learn_memory: bool = True
    use_summary: bool = True
    embedding_rerank: bool = True
    memory_results: int = Field(default=5, ge=1, le=12)


class RegenerateRequest(BaseModel):
    conversation_id: str
    model: str | None = None
    system_prompt: str | None = None
    response_mode: str = "fast"
    temperature: float = Field(default=0.55, ge=0, le=2)
    max_tokens: int = Field(default=480, ge=64, le=4096)
    context_window: int = Field(default=4096, ge=1024, le=32768)
    thinking: bool = False
    use_knowledge: bool = True
    knowledge_results: int = Field(default=5, ge=1, le=10)
    intelligence_mode: str = "auto"
    auto_model_routing: bool = True
    max_auto_model_b: float = Field(default=9, ge=1, le=70)
    adaptive_thinking: bool = True
    use_memory: bool = True
    auto_learn_memory: bool = True
    use_summary: bool = True
    embedding_rerank: bool = True
    memory_results: int = Field(default=5, ge=1, le=12)


class PullModelRequest(BaseModel):
    model: str = Field(min_length=1, max_length=200)


class ImageRequest(BaseModel):
    conversation_id: str
    prompt: str = Field(min_length=1, max_length=3000)
    negative_prompt: str = "blurry, low quality, distorted, malformed"
    width: int = Field(default=512, ge=256, le=768)
    height: int = Field(default=512, ge=256, le=768)
    steps: int = Field(default=6, ge=4, le=12)
    style: str = "auto"


class SettingsPayload(BaseModel):
    settings: dict


class ImportPayload(BaseModel):
    data: dict


class MemoryAdd(BaseModel):
    content: str = Field(min_length=3, max_length=1200)
    category: str = Field(default="manual", max_length=80)


@app.get("/")
async def home():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/config")
async def config():
    return {
        "title": APP_TITLE,
        "default_model": DEFAULT_MODEL,
        "recommended_models": [
            "huihui_ai/qwen3-abliterated:1.7b",
            "huihui_ai/qwen3-abliterated:4b",
            "qwen3:4b",
        ],
        "image_model": IMAGE_MODEL_NAME,
    }


@app.get("/api/health")
async def health():
    out = {"app": "ok", "ollama": "unknown", "image": "unknown"}
    try:
        async with httpx.AsyncClient(timeout=3.5) as client:
            r = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            out["ollama"] = "ok" if r.is_success else f"http_{r.status_code}"
    except Exception:
        out["ollama"] = "unreachable"
    try:
        async with httpx.AsyncClient(timeout=2.5) as client:
            r = await client.get(f"{IMAGE_ENGINE_BASE_URL}/health")
            if r.is_success:
                try:
                    info = r.json()
                except Exception:
                    info = {}
                ready = info.get("status") == "ok" and bool(info.get("model_present"))
                out["image"] = "ok" if ready else "unavailable"
                out["image_detail"] = info
            else:
                out["image"] = f"http_{r.status_code}"
    except Exception as exc:
        out["image"] = "unavailable"
        out["image_detail"] = {"error": str(exc)}
    return out


@app.post("/api/auth/signup")
async def signup(payload: AuthRequest):
    username = payload.username.strip()
    if not username.replace("_", "").replace("-", "").isalnum():
        raise HTTPException(400, "Use letters, numbers, _ or - in usernames")
    uid = str(uuid.uuid4())
    try:
        with db() as conn:
            conn.execute(
                "INSERT INTO users(id,username,password_hash,created_at) VALUES(?,?,?,?)",
                (uid, username, hash_password(payload.password), now_iso()),
            )
            conn.execute(
                "INSERT OR REPLACE INTO user_settings(user_id,settings_json,updated_at) VALUES(?,?,?)",
                (uid, json.dumps(DEFAULT_SETTINGS), now_iso()),
            )
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Username already exists")
    return {"token": create_session(uid), "username": username}


@app.post("/api/auth/login")
async def login(payload: AuthRequest):
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username=? COLLATE NOCASE",
            (payload.username.strip(),),
        ).fetchone()
    if not row or not verify_password(payload.password, row["password_hash"]):
        raise HTTPException(401, "Incorrect username or password")
    return {"token": create_session(row["id"]), "username": row["username"]}


@app.post("/api/auth/logout")
async def logout(user=Depends(current_user)):
    with db() as conn:
        conn.execute("DELETE FROM sessions WHERE token=?", (user["token"],))
    return {"ok": True}


@app.get("/api/me")
async def me(user=Depends(current_user)):
    return {"id": user["id"], "username": user["username"]}


@app.get("/api/settings")
async def read_settings(user=Depends(current_user)):
    return {"settings": get_settings(user["id"])}


@app.put("/api/settings")
async def save_settings(payload: SettingsPayload, user=Depends(current_user)):
    merged = {**DEFAULT_SETTINGS, **payload.settings}
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO user_settings(user_id,settings_json,updated_at) VALUES(?,?,?)",
            (user["id"], json.dumps(merged), now_iso()),
        )
    return {"settings": merged}



@app.get("/api/intelligence/status")
async def intelligence_status(user=Depends(current_user)):
    return await INTELLIGENCE.status(user["id"])


@app.get("/api/memory")
async def list_memory(
    limit: int = Query(default=100, ge=1, le=500),
    user=Depends(current_user),
):
    return {"memories": INTELLIGENCE.list_memories(user["id"], limit=limit)}


@app.post("/api/memory")
async def add_memory(payload: MemoryAdd, user=Depends(current_user)):
    saved = INTELLIGENCE.save_memory(
        user["id"],
        payload.content,
        category=payload.category,
        confidence=1.0,
        source="manual",
        now_iso=now_iso(),
    )
    return {"ok": saved, "memories": INTELLIGENCE.list_memories(user["id"], limit=100)}


@app.get("/api/models")
async def models(user=Depends(current_user)):
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            r.raise_for_status()
            data = r.json()
        names = [
            m.get("name") or m.get("model")
            for m in data.get("models", [])
            if m.get("name") or m.get("model")
        ]
        return {"models": names, "default_model": DEFAULT_MODEL}
    except Exception as exc:
        return {"models": [], "default_model": DEFAULT_MODEL, "warning": str(exc)}


@app.post("/api/models/pull")
async def pull_model(payload: PullModelRequest, user=Depends(current_user)):
    async def stream():
        try:
            timeout = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=30.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST",
                    f"{OLLAMA_BASE_URL}/api/pull",
                    json={"model": payload.model.strip(), "stream": True},
                ) as response:
                    if response.status_code >= 400:
                        body = await response.aread()
                        yield f"data: {json.dumps({'type':'error','error':body.decode('utf-8','replace')})}\n\n"
                        return
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        yield f"data: {json.dumps({'type':'progress', **obj})}\n\n"
            yield f"data: {json.dumps({'type':'done'})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type':'error','error':str(exc)})}\n\n"
    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/api/conversations")
async def list_conversations(
    q: str = Query(default="", max_length=120),
    user=Depends(current_user),
):
    with db() as conn:
        if q.strip():
            rows = conn.execute(
                """
                SELECT * FROM conversations
                WHERE user_id=? AND title LIKE ?
                ORDER BY pinned DESC, updated_at DESC
                """,
                (user["id"], f"%{q.strip()}%"),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM conversations
                WHERE user_id=?
                ORDER BY pinned DESC, updated_at DESC
                """,
                (user["id"],),
            ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/conversations")
async def create_conversation(payload: NewConversation, user=Depends(current_user)):
    cid = str(uuid.uuid4())
    ts = now_iso()
    model = payload.model or DEFAULT_MODEL
    with db() as conn:
        conn.execute(
            "INSERT INTO conversations(id,user_id,title,model,pinned,created_at,updated_at) VALUES(?,?,?,?,0,?,?)",
            (cid, user["id"], payload.title.strip() or "New chat", model, ts, ts),
        )
    return {"id": cid, "title": payload.title, "model": model, "pinned": 0}


@app.get("/api/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, user=Depends(current_user)):
    with db() as conn:
        conv = conversation_for_user(conn, conversation_id, user["id"])
        msgs = conn.execute(
            """
            SELECT id,role,content,created_at,image_url,message_type
            FROM messages WHERE conversation_id=? ORDER BY id
            """,
            (conversation_id,),
        ).fetchall()
    return {"conversation": dict(conv), "messages": [dict(m) for m in msgs]}


@app.patch("/api/conversations/{conversation_id}")
async def update_conversation(
    conversation_id: str,
    payload: ConversationUpdate,
    user=Depends(current_user),
):
    with db() as conn:
        conv = conversation_for_user(conn, conversation_id, user["id"])
        title = conv["title"]
        pinned = int(conv["pinned"] or 0)
        if payload.title is not None:
            title = payload.title.strip() or "Untitled chat"
        if payload.pinned is not None:
            pinned = 1 if payload.pinned else 0
        conn.execute(
            "UPDATE conversations SET title=?,pinned=?,updated_at=? WHERE id=?",
            (title, pinned, now_iso(), conversation_id),
        )
    return {"id": conversation_id, "title": title, "pinned": pinned}


@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str, user=Depends(current_user)):
    with db() as conn:
        conversation_for_user(conn, conversation_id, user["id"])
        conn.execute("DELETE FROM messages WHERE conversation_id=?", (conversation_id,))
        conn.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))
    return {"ok": True}


@app.get("/api/conversations/{conversation_id}/export")
async def export_conversation(conversation_id: str, user=Depends(current_user)):
    with db() as conn:
        conv = conversation_for_user(conn, conversation_id, user["id"])
        msgs = conn.execute(
            "SELECT role,content,created_at,image_url,message_type FROM messages WHERE conversation_id=? ORDER BY id",
            (conversation_id,),
        ).fetchall()
    return JSONResponse({
        "app": APP_TITLE,
        "version": 5,
        "conversation": dict(conv),
        "messages": [dict(m) for m in msgs],
    })


@app.get("/api/export")
async def export_all(user=Depends(current_user)):
    with db() as conn:
        convs = conn.execute(
            "SELECT * FROM conversations WHERE user_id=? ORDER BY updated_at DESC",
            (user["id"],),
        ).fetchall()
        chats = []
        for conv in convs:
            msgs = conn.execute(
                "SELECT role,content,created_at,image_url,message_type FROM messages WHERE conversation_id=? ORDER BY id",
                (conv["id"],),
            ).fetchall()
            chats.append({"conversation": dict(conv), "messages": [dict(m) for m in msgs]})
    return JSONResponse({
        "app": APP_TITLE,
        "version": 5,
        "username": user["username"],
        "settings": get_settings(user["id"]),
        "chats": chats,
    })


@app.post("/api/import")
async def import_data(payload: ImportPayload, user=Depends(current_user)):
    data = payload.data
    chats = data.get("chats") or []
    imported = 0
    with db() as conn:
        for item in chats:
            conv = item.get("conversation") or {}
            messages = item.get("messages") or []
            cid = str(uuid.uuid4())
            ts = now_iso()
            conn.execute(
                "INSERT INTO conversations(id,user_id,title,model,pinned,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (
                    cid,
                    user["id"],
                    str(conv.get("title") or "Imported chat")[:120],
                    str(conv.get("model") or DEFAULT_MODEL),
                    int(bool(conv.get("pinned", False))),
                    ts,
                    ts,
                ),
            )
            for m in messages:
                conn.execute(
                    """
                    INSERT INTO messages(conversation_id,role,content,created_at,image_url,message_type)
                    VALUES(?,?,?,?,?,?)
                    """,
                    (
                        cid,
                        str(m.get("role") or "assistant"),
                        str(m.get("content") or ""),
                        str(m.get("created_at") or ts),
                        m.get("image_url"),
                        str(m.get("message_type") or "text"),
                    ),
                )
            imported += 1
    return {"ok": True, "imported": imported}


@app.delete("/api/conversations")
async def clear_all_chats(user=Depends(current_user)):
    with db() as conn:
        ids = [r["id"] for r in conn.execute("SELECT id FROM conversations WHERE user_id=?", (user["id"],)).fetchall()]
        for cid in ids:
            conn.execute("DELETE FROM messages WHERE conversation_id=?", (cid,))
        conn.execute("DELETE FROM conversations WHERE user_id=?", (user["id"],))
    return {"ok": True, "deleted": len(ids)}



_KNOWLEDGE_STOP = {
    "the","a","an","and","or","of","to","in","on","for","with","is","are","was","were",
    "what","who","when","where","why","how","do","does","did","can","could","would","should",
    "i","you","me","my","your","it","this","that","these","those","about","tell","explain"
}

def knowledge_status() -> dict:
    if not KNOWLEDGE_DB.is_file():
        return {"ready": False, "count": 0, "path": str(KNOWLEDGE_DB)}
    try:
        conn = sqlite3.connect(KNOWLEDGE_DB)
        row = conn.execute("SELECT value FROM meta WHERE key='count'").fetchone()
        sources = conn.execute("SELECT value FROM meta WHERE key='sources'").fetchone()
        conn.close()
        return {
            "ready": True,
            "count": int(row[0]) if row else 0,
            "sources": sources[0] if sources else "",
            "path": str(KNOWLEDGE_DB),
        }
    except Exception as exc:
        return {"ready": False, "count": 0, "error": str(exc), "path": str(KNOWLEDGE_DB)}

def _fts_query(text: str) -> str:
    import re
    words = re.findall(r"[A-Za-z0-9_+\-]{2,}", text.lower())
    terms = []
    seen = set()
    for word in words:
        if word in _KNOWLEDGE_STOP or word in seen:
            continue
        seen.add(word)
        terms.append(word)
        if len(terms) >= 10:
            break
    return " OR ".join(f'"{t}"' for t in terms)

def search_knowledge(query: str, limit: int = 5) -> list[dict]:
    if not KNOWLEDGE_DB.is_file():
        return []
    fts = _fts_query(query)
    if not fts:
        return []
    try:
        conn = sqlite3.connect(KNOWLEDGE_DB)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT q.source, q.question, q.answer,
                   bm25(qa_fts, 4.0, 1.0, 0.15) AS score
            FROM qa_fts
            JOIN qa q ON q.id=qa_fts.rowid
            WHERE qa_fts MATCH ?
            ORDER BY score
            LIMIT ?
            """,
            (fts, max(1, min(int(limit), 10))),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []

def knowledge_system_message(query: str, limit: int) -> str | None:
    matches = search_knowledge(query, limit)
    if not matches:
        return None
    lines = [
        "LOCAL RETRIEVAL KNOWLEDGE:",
        "The following Q&A records were retrieved from Apex's local knowledge database.",
        "Use them only when they are relevant. Do not force an unrelated match into the answer.",
    ]
    for i, item in enumerate(matches, 1):
        q = str(item["question"])[:900]
        a = str(item["answer"])[:1800]
        lines.append(f"[{i}] Source: {item['source']}\\nQ: {q}\\nA: {a}")
    return "\\n\\n".join(lines)

@app.get("/api/knowledge/status")
async def api_knowledge_status(user=Depends(current_user)):
    return knowledge_status()

@app.get("/api/knowledge/search")
async def api_knowledge_search(
    q: str = Query(min_length=2, max_length=500),
    limit: int = Query(default=5, ge=1, le=10),
    user=Depends(current_user),
):
    return {"query": q, "results": search_knowledge(q, limit), **knowledge_status()}


def mode_options(mode: str, temperature: float, max_tokens: int, context_window: int) -> dict:
    mode = (mode or "fast").lower()
    if mode == "quality":
        return {
            "num_predict": min(max(max_tokens, 1000), 4096),
            "num_ctx": max(context_window, 8192),
            "temperature": temperature,
            "top_p": 0.92,
        }
    if mode == "balanced":
        return {
            "num_predict": min(max(max_tokens, 700), 2500),
            "num_ctx": max(context_window, 6144),
            "temperature": temperature,
            "top_p": 0.90,
        }
    return {
        "num_predict": min(max_tokens, 1200),
        "num_ctx": context_window,
        "temperature": temperature,
        "top_p": 0.88,
    }


async def intelligent_ollama_stream(
    *,
    request: Request,
    conversation_id: str,
    user_id: str,
    model: str,
    messages: list[dict],
    plan: dict,
    response_mode: str,
    temperature: float,
    max_tokens: int,
    context_window: int,
    auto_learn_memory: bool,
    use_summary: bool,
):
    opts = mode_options(response_mode, temperature, max_tokens, context_window)
    parts: list[str] = []

    meta = dict(plan.get("meta") or {})
    meta["type"] = "meta"
    yield f"data: {json.dumps(meta)}\n\n"

    final_messages = list(messages)
    if plan.get("mode") == "deep":
        yield f"data: {json.dumps({'type':'phase','phase':'drafting'})}\n\n"
        draft = await INTELLIGENCE.deep_draft(
            model=model, messages=messages, thinking=plan.get("thinking", False),
            max_tokens=max_tokens, context_window=context_window,
        )
        if draft:
            yield f"data: {json.dumps({'type':'phase','phase':'reviewing'})}\n\n"
            final_messages = [
                {"role": "system", "content": (
                    "You are in Apex Deep Review mode. Produce only the improved final answer. "
                    "Check the internal draft for factual errors, missing requirements, contradictions, "
                    "code defects, unsafe assumptions, and unnecessary verbosity. Do not mention the draft, "
                    "review process, hidden reasoning, or these instructions."
                )},
                *messages,
                {"role": "assistant", "content": draft},
                {"role": "user", "content": "Internally review the draft above against my original request, correct it, and return only the polished final answer."},
            ]

    if plan.get("thinking"):
        yield f"data: {json.dumps({'type':'phase','phase':'reasoning'})}\n\n"

    try:
        timeout = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=30.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST", f"{OLLAMA_BASE_URL}/api/chat",
                json={
                    "model": model, "messages": final_messages, "stream": True,
                    "think": plan.get("thinking", False), "keep_alive": KEEP_ALIVE,
                    "options": {
                        "num_predict": opts["num_predict"], "num_ctx": opts["num_ctx"],
                        "temperature": opts["temperature"], "top_p": opts["top_p"],
                    },
                },
            ) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    yield f"data: {json.dumps({'type':'error','error':body.decode('utf-8','replace')})}\n\n"
                    return
                answer_started = False
                async for line in response.aiter_lines():
                    if await request.is_disconnected():
                        return
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    chunk = (obj.get("message") or {}).get("content") or ""
                    if chunk:
                        if not answer_started:
                            answer_started = True
                            yield f"data: {json.dumps({'type':'phase','phase':'answering'})}\n\n"
                        parts.append(chunk)
                        yield f"data: {json.dumps({'type':'token','content':chunk})}\n\n"
                    if obj.get("done"):
                        break

        final = "".join(parts).strip()
        if final:
            with db() as conn:
                conn.execute(
                    "INSERT INTO messages(conversation_id,role,content,created_at,message_type) VALUES(?,?,?,?,?)",
                    (conversation_id, "assistant", final, now_iso(), "text"),
                )
                conn.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now_iso(), conversation_id))
            asyncio.create_task(INTELLIGENCE.learn_conversation(
                user_id=user_id, conversation_id=conversation_id, model=model,
                auto_memory=auto_learn_memory, use_summaries=use_summary,
            ))
        yield f"data: {json.dumps({'type':'done'})}\n\n"
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        yield f"data: {json.dumps({'type':'error','error':str(exc)})}\n\n"


@app.post("/api/chat")
async def chat(payload: ChatRequest, request: Request, user=Depends(current_user)):
    text = payload.message.strip()
    with db() as conn:
        conv = conversation_for_user(conn, payload.conversation_id, user["id"])
        selected_model = (payload.model or conv["model"] or DEFAULT_MODEL).strip()
        if not selected_model:
            raise HTTPException(400, "No model selected")
        conn.execute(
            "INSERT INTO messages(conversation_id,role,content,created_at,message_type) VALUES(?,?,?,?,?)",
            (payload.conversation_id, "user", text, now_iso(), "text"),
        )
        prior = conn.execute(
            """
            SELECT role,content FROM messages
            WHERE conversation_id=? AND message_type='text'
            ORDER BY id DESC LIMIT ?
            """,
            (payload.conversation_id, CHAT_HISTORY_MESSAGES),
        ).fetchall()
        prior = list(reversed(prior))
        title = conv["title"]
        if title == "New chat":
            title = text[:55] + ("…" if len(text) > 55 else "")
        conn.execute(
            "UPDATE conversations SET title=?,model=?,updated_at=? WHERE id=?",
            (title, selected_model, now_iso(), payload.conversation_id),
        )

    plan = await INTELLIGENCE.prepare(
        user_id=user["id"], conversation_id=payload.conversation_id, prompt=text,
        selected_model=selected_model, requested_mode=payload.intelligence_mode,
        auto_model_routing=payload.auto_model_routing, max_auto_model_b=payload.max_auto_model_b,
        adaptive_thinking=payload.adaptive_thinking, manual_thinking=payload.thinking,
        use_memory=payload.use_memory, use_summary=payload.use_summary,
        use_knowledge=payload.use_knowledge, knowledge_results=payload.knowledge_results,
        memory_results=payload.memory_results, embedding_rerank=payload.embedding_rerank,
        now_iso=now_iso(),
    )

    messages = []
    if payload.system_prompt and payload.system_prompt.strip():
        messages.append({"role": "system", "content": payload.system_prompt.strip()})
    messages.extend(plan["context_messages"])
    messages.extend({"role": r["role"], "content": r["content"]} for r in prior)

    return StreamingResponse(
        intelligent_ollama_stream(
            request=request, conversation_id=payload.conversation_id, user_id=user["id"],
            model=plan["model"], messages=messages, plan=plan,
            response_mode=payload.response_mode, temperature=payload.temperature,
            max_tokens=payload.max_tokens, context_window=payload.context_window,
            auto_learn_memory=payload.auto_learn_memory, use_summary=payload.use_summary,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/chat/regenerate")
async def regenerate(payload: RegenerateRequest, request: Request, user=Depends(current_user)):
    with db() as conn:
        conv = conversation_for_user(conn, payload.conversation_id, user["id"])
        selected_model = (payload.model or conv["model"] or DEFAULT_MODEL).strip()
        rows = conn.execute(
            """
            SELECT role,content FROM messages
            WHERE conversation_id=? AND message_type='text'
            ORDER BY id DESC LIMIT ?
            """,
            (payload.conversation_id, CHAT_HISTORY_MESSAGES + 2),
        ).fetchall()
    rows = list(reversed(rows))
    if rows and rows[-1]["role"] == "assistant":
        rows = rows[:-1]
    if not rows or rows[-1]["role"] != "user":
        raise HTTPException(400, "No recent user message to regenerate")

    prompt = rows[-1]["content"]
    plan = await INTELLIGENCE.prepare(
        user_id=user["id"], conversation_id=payload.conversation_id, prompt=prompt,
        selected_model=selected_model, requested_mode=payload.intelligence_mode,
        auto_model_routing=payload.auto_model_routing, max_auto_model_b=payload.max_auto_model_b,
        adaptive_thinking=payload.adaptive_thinking, manual_thinking=payload.thinking,
        use_memory=payload.use_memory, use_summary=payload.use_summary,
        use_knowledge=payload.use_knowledge, knowledge_results=payload.knowledge_results,
        memory_results=payload.memory_results, embedding_rerank=payload.embedding_rerank,
        now_iso=now_iso(),
    )

    messages = []
    if payload.system_prompt and payload.system_prompt.strip():
        messages.append({"role": "system", "content": payload.system_prompt.strip()})
    messages.extend(plan["context_messages"])
    messages.extend({"role": r["role"], "content": r["content"]} for r in rows)

    return StreamingResponse(
        intelligent_ollama_stream(
            request=request, conversation_id=payload.conversation_id, user_id=user["id"],
            model=plan["model"], messages=messages, plan=plan,
            response_mode=payload.response_mode, temperature=payload.temperature,
            max_tokens=payload.max_tokens, context_window=payload.context_window,
            auto_learn_memory=payload.auto_learn_memory, use_summary=payload.use_summary,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/image/generate")
async def generate_image(payload: ImageRequest, user=Depends(current_user)):
    with db() as conn:
        conv = conversation_for_user(conn, payload.conversation_id, user["id"])
        conn.execute(
            "INSERT INTO messages(conversation_id,role,content,created_at,message_type) VALUES(?,?,?,?,?)",
            (payload.conversation_id, "user", payload.prompt.strip(), now_iso(), "image_prompt"),
        )
        title = conv["title"]
        if title == "New chat":
            title = "Image: " + payload.prompt.strip()[:45]
        conn.execute(
            "UPDATE conversations SET title=?,updated_at=? WHERE id=?",
            (title, now_iso(), payload.conversation_id),
        )

    timeout = httpx.Timeout(connect=5.0, read=1200.0, write=30.0, pool=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            h = await client.get(f"{IMAGE_ENGINE_BASE_URL}/health")
            h.raise_for_status()
        except Exception:
            raise HTTPException(
                503,
                "Image engine is not running. Run ./install-image-engine.sh once, then restart Apex AI.",
            )

        image_resp = await client.post(
            f"{IMAGE_ENGINE_BASE_URL}/generate",
            json={
                "prompt": payload.prompt.strip(),
                "negative_prompt": payload.negative_prompt.strip(),
                "width": payload.width,
                "height": payload.height,
                "steps": payload.steps,
                "style": payload.style,
            },
        )
        if image_resp.status_code >= 400:
            try:
                parsed = image_resp.json()
                detail = parsed.get("detail", parsed) if isinstance(parsed, dict) else parsed
            except Exception:
                detail = image_resp.text
            if not isinstance(detail, str):
                try:
                    detail = json.dumps(detail, ensure_ascii=False)
                except Exception:
                    detail = str(detail)
            raise HTTPException(502, f"Image engine error: {detail[:1000]}")

    filename = f"{uuid.uuid4().hex}.png"
    (GENERATED_DIR / filename).write_bytes(image_resp.content)
    url = f"/generated/{filename}"

    with db() as conn:
        conn.execute(
            """
            INSERT INTO messages(conversation_id,role,content,created_at,image_url,message_type)
            VALUES(?,?,?,?,?,?)
            """,
            (
                payload.conversation_id,
                "assistant",
                f"Generated image for: {payload.prompt.strip()}",
                now_iso(),
                url,
                "image",
            ),
        )
        conn.execute(
            "UPDATE conversations SET updated_at=? WHERE id=?",
            (now_iso(), payload.conversation_id),
        )
    return {"image_url": url, "prompt": payload.prompt.strip()}
