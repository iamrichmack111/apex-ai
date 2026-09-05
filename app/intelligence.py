from __future__ import annotations

import ast
import json
import math
import operator
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

import httpx


class IntelligenceEngine:
    """Local-only intelligence layer for Apex AI.

    Never installs, pulls, removes, unloads, or prunes Ollama models.
    It only reads /api/tags and uses already-installed models through HTTP.
    """

    def __init__(self, *, db_path: Path, knowledge_db: Path, ollama_base_url: str, keep_alive: str = "30m"):
        self.db_path = Path(db_path)
        self.knowledge_db = Path(knowledge_db)
        self.ollama_base_url = ollama_base_url.rstrip("/")
        self.keep_alive = keep_alive
        self._model_cache: list[dict] = []
        self._model_cache_at = 0.0
        self._embedding_model_cache: str | None | bool = False
        self._embedding_model_cache_at = 0.0

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def ensure_schema(self) -> None:
        # Additive only. No DROP, TRUNCATE, or DELETE operations.
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'general',
                    content TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 1.0,
                    source TEXT NOT NULL DEFAULT 'manual',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(user_id, content)
                );
                CREATE INDEX IF NOT EXISTS idx_memories_user_updated
                ON memories(user_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS conversation_summaries (
                    conversation_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    message_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_summaries_user
                ON conversation_summaries(user_id, updated_at DESC);
                """
            )

    async def installed_models(self, max_age: float = 60.0) -> list[dict]:
        now = time.monotonic()
        if self._model_cache and now - self._model_cache_at < max_age:
            return self._model_cache
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{self.ollama_base_url}/api/tags")
                r.raise_for_status()
                models = r.json().get("models") or []
        except Exception:
            models = []
        self._model_cache = models
        self._model_cache_at = now
        return models

    @staticmethod
    def _parameter_billions(model: dict) -> float:
        details = model.get("details") or {}
        raw = str(details.get("parameter_size") or "")
        m = re.search(r"([\d.]+)\s*B", raw, re.I)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
        name = str(model.get("name") or model.get("model") or "")
        matches = re.findall(r"(?:^|[:\-_])(\d+(?:\.\d+)?)b(?:$|[:\-_])", name, re.I)
        if matches:
            try:
                return float(matches[-1])
            except ValueError:
                pass
        return 0.0

    @staticmethod
    def _is_chat_model(name: str) -> bool:
        n = name.lower()
        excluded = ("embed", "embedding", "nomic", "mxbai", "bge-", "snowflake-arctic-embed", "clip", "rerank")
        return not any(x in n for x in excluded)

    @staticmethod
    def complexity(prompt: str) -> int:
        p = prompt.lower()
        words = len(prompt.split())
        score = 0
        if words > 45:
            score += 1
        if words > 120:
            score += 1
        if words > 260:
            score += 1
        if "```" in prompt or re.search(r"\b(traceback|exception|stack trace|yaml|dockerfile|terraform|kubernetes)\b", p):
            score += 2
        high_reasoning = (
            "analyze", "compare", "design", "architect", "debug", "troubleshoot", "root cause",
            "tradeoff", "trade-off", "why does", "prove", "derive", "strategy", "migration",
            "security review", "review this", "optimize", "refactor", "plan", "evaluate", "diagnose",
        )
        score += min(3, sum(1 for x in high_reasoning if x in p))
        if len(re.findall(r"\b(?:first|second|third|also|then|and then|step \d+)\b", p)) >= 3:
            score += 1
        if re.search(r"\d+\s*[-+*/^%]\s*\d+", prompt):
            score += 1
        if any(x in p for x in ("simple terms", "short answer", "briefly", "one sentence")):
            score -= 2
        return max(0, min(score, 10))

    @staticmethod
    def effective_mode(requested: str, complexity: int) -> str:
        mode = (requested or "auto").lower()
        if mode in {"quick", "smart", "deep"}:
            return mode
        if complexity >= 8:
            return "deep"
        if complexity >= 3:
            return "smart"
        return "quick"

    async def route_model(self, selected_model: str, *, complexity: int, mode: str, enabled: bool, max_billions: float) -> tuple[str, dict]:
        if not enabled or mode == "quick":
            return selected_model, {"routed": False, "selected_model": selected_model}
        models = await self.installed_models()
        candidates = []
        for item in models:
            name = str(item.get("name") or item.get("model") or "")
            if not name or not self._is_chat_model(name):
                continue
            size = self._parameter_billions(item)
            if size <= 0 or size > max_billions:
                continue
            candidates.append((size, name))
        if not candidates:
            return selected_model, {"routed": False, "selected_model": selected_model}
        selected_size = 0.0
        for item in models:
            name = str(item.get("name") or item.get("model") or "")
            if name == selected_model:
                selected_size = self._parameter_billions(item)
                break
        if mode == "smart" and complexity < 5:
            return selected_model, {"routed": False, "selected_model": selected_model, "selected_size_b": selected_size}
        candidates.sort(reverse=True)
        best_size, best_name = candidates[0]
        if selected_size and selected_size >= best_size:
            return selected_model, {"routed": False, "selected_model": selected_model, "selected_size_b": selected_size}
        return best_name, {
            "routed": best_name != selected_model,
            "selected_model": selected_model,
            "selected_size_b": selected_size,
            "routed_size_b": best_size,
        }

    async def embedding_model(self) -> str | None:
        now = time.monotonic()
        if self._embedding_model_cache is not False and now - self._embedding_model_cache_at < 120:
            return self._embedding_model_cache or None
        models = await self.installed_models(max_age=0)
        names = [str(m.get("name") or m.get("model") or "") for m in models]
        priorities = ("embeddinggemma", "nomic-embed-text", "mxbai-embed-large", "bge-m3", "bge-large", "snowflake-arctic-embed")
        chosen = None
        for preferred in priorities:
            for name in names:
                if preferred in name.lower():
                    chosen = name
                    break
            if chosen:
                break
        if not chosen:
            chosen = next((n for n in names if "embed" in n.lower()), None)
        self._embedding_model_cache = chosen
        self._embedding_model_cache_at = now
        return chosen

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        return dot / (na * nb) if na and nb else 0.0

    async def rerank_with_embeddings(self, query: str, candidates: list[dict], limit: int) -> tuple[list[dict], str | None]:
        if not candidates:
            return [], None
        model = await self.embedding_model()
        if not model:
            return candidates[:limit], None
        inputs = [query] + [f"{c.get('question','')}\n{str(c.get('answer',''))[:1200]}" for c in candidates]
        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                r = await client.post(f"{self.ollama_base_url}/api/embed", json={"model": model, "input": inputs, "truncate": True})
                r.raise_for_status()
                vectors = r.json().get("embeddings") or []
            if len(vectors) != len(inputs):
                return candidates[:limit], None
        except Exception:
            return candidates[:limit], None
        qv = vectors[0]
        rescored = []
        total = max(1, len(candidates) - 1)
        for idx, (candidate, vec) in enumerate(zip(candidates, vectors[1:])):
            semantic = self._cosine(qv, vec)
            lexical_bonus = 0.08 * (1.0 - idx / total)
            item = dict(candidate)
            item["_combined_score"] = semantic + lexical_bonus
            rescored.append(item)
        rescored.sort(key=lambda x: x["_combined_score"], reverse=True)
        return rescored[:limit], model

    @staticmethod
    def _fts_query(text: str) -> str:
        stop = {"the","a","an","and","or","of","to","in","on","for","with","is","are","was","were","what","who","when","where","why","how","do","does","did","can","could","would","should","i","you","me","my","your","it","this","that","these","those","about","tell","explain"}
        terms, seen = [], set()
        for word in re.findall(r"[A-Za-z0-9_+\-]{2,}", text.lower()):
            if word in stop or word in seen:
                continue
            seen.add(word)
            terms.append(word)
            if len(terms) >= 12:
                break
        return " OR ".join(f'"{t}"' for t in terms)

    def search_knowledge_lexical(self, query: str, limit: int = 25) -> list[dict]:
        if not self.knowledge_db.is_file():
            return []
        fts = self._fts_query(query)
        if not fts:
            return []
        try:
            conn = sqlite3.connect(f"file:{self.knowledge_db}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT q.source, q.question, q.answer, bm25(qa_fts, 4.0, 1.0, 0.15) AS score
                FROM qa_fts JOIN qa q ON q.id=qa_fts.rowid
                WHERE qa_fts MATCH ? ORDER BY score LIMIT ?
                """,
                (fts, max(1, min(int(limit), 40))),
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception:
            return []

    async def knowledge_matches(self, query: str, *, limit: int, embedding_rerank: bool) -> tuple[list[dict], str | None]:
        lexical = self.search_knowledge_lexical(query, max(20, limit * 4))
        if embedding_rerank and lexical:
            return await self.rerank_with_embeddings(query, lexical, limit)
        return lexical[:limit], None

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {x for x in re.findall(r"[a-z0-9_+\-]{2,}", text.lower()) if x not in {"the","and","for","with","that","this","from","your","you","are","was","have","what","when","where","why","how","about","into","want","need"}}

    def save_memory(self, user_id: str, content: str, *, category: str = "general", confidence: float = 1.0, source: str = "manual", now_iso: str) -> bool:
        content = " ".join(str(content).split()).strip()
        if len(content) < 3:
            return False
        content = content[:1200]
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO memories(user_id,category,content,confidence,source,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(user_id,content) DO UPDATE SET
                    updated_at=excluded.updated_at,
                    confidence=MAX(memories.confidence, excluded.confidence)
                """,
                (user_id, category[:80], content, float(confidence), source[:40], now_iso, now_iso),
            )
        return True

    def save_explicit_memories(self, user_id: str, text: str, now_iso: str) -> int:
        patterns = ((r"\bremember\s+(?:that\s+)?(.+)", "explicit"), (r"\bfrom now on[,\s:]+(.+)", "instruction"), (r"\bmy preference is\s+(.+)", "preference"))
        count = 0
        for pattern, category in patterns:
            m = re.search(pattern, text, re.I | re.S)
            if not m:
                continue
            value = m.group(1).strip().rstrip(".")
            if 3 <= len(value) <= 1000:
                count += int(self.save_memory(user_id, value, category=category, confidence=1.0, source="explicit", now_iso=now_iso))
        return count

    def list_memories(self, user_id: str, limit: int = 200) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id,category,content,confidence,source,created_at,updated_at FROM memories WHERE user_id=? ORDER BY updated_at DESC LIMIT ?",
                (user_id, max(1, min(limit, 500))),
            ).fetchall()
        return [dict(r) for r in rows]

    def relevant_memories(self, user_id: str, query: str, limit: int = 5) -> list[dict]:
        rows = self.list_memories(user_id, limit=500)
        if not rows:
            return []
        q = self._tokens(query)
        scored = []
        for idx, item in enumerate(rows):
            mt = self._tokens(item["content"])
            overlap = len(q & mt)
            union = max(1, len(q | mt))
            jaccard = overlap / union
            substring = 0.5 if item["content"].lower() in query.lower() or query.lower() in item["content"].lower() else 0
            explicit = 0.16 if item["source"] == "explicit" else 0
            recency = max(0.0, 0.12 - idx * 0.00025)
            score = jaccard * 2.2 + substring + explicit + recency
            if overlap or explicit:
                scored.append((score, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[: max(1, min(limit, 12))]]

    def conversation_summary(self, conversation_id: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT summary,message_count,updated_at FROM conversation_summaries WHERE conversation_id=?", (conversation_id,)).fetchone()
        return dict(row) if row else None

    _BIN_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
    _UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}

    @classmethod
    def _eval_ast(cls, node):
        if isinstance(node, ast.Expression):
            return cls._eval_ast(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in cls._BIN_OPS:
            left, right = cls._eval_ast(node.left), cls._eval_ast(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 12:
                raise ValueError("exponent too large")
            return cls._BIN_OPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in cls._UNARY_OPS:
            return cls._UNARY_OPS[type(node.op)](cls._eval_ast(node.operand))
        raise ValueError("unsupported expression")

    @classmethod
    def calculator_result(cls, prompt: str) -> str | None:
        p = prompt.strip()
        if not re.search(r"\d", p):
            return None
        candidates = []
        m = re.search(r"(?:calculate|compute|evaluate|what is|what's)\s+([0-9\s\.\+\-\*\/%\(\)\^]+)", p, re.I)
        if m:
            candidates.append(m.group(1))
        if re.fullmatch(r"[0-9\s\.\+\-\*\/%\(\)\^]+[=?]?", p):
            candidates.append(p.rstrip("=? "))
        for expr in candidates:
            expr = expr.strip().replace("^", "**")
            if len(expr) > 120:
                continue
            try:
                value = cls._eval_ast(ast.parse(expr, mode="eval"))
                rendered = f"{value:.12g}" if isinstance(value, float) else str(value)
                return f"{expr} = {rendered}"
            except Exception:
                continue
        return None

    @staticmethod
    def thinking_value(model: str, enabled: bool, mode: str):
        if "gpt-oss" in model.lower():
            return "high" if enabled and mode == "deep" else ("medium" if enabled else "low")
        return bool(enabled)

    async def prepare(self, *, user_id: str, conversation_id: str, prompt: str, selected_model: str, requested_mode: str, auto_model_routing: bool, max_auto_model_b: float, adaptive_thinking: bool, manual_thinking: bool, use_memory: bool, use_summary: bool, use_knowledge: bool, knowledge_results: int, memory_results: int, embedding_rerank: bool, now_iso: str) -> dict:
        self.save_explicit_memories(user_id, prompt, now_iso)
        complexity = self.complexity(prompt)
        mode = self.effective_mode(requested_mode, complexity)
        effective_model, route_meta = await self.route_model(selected_model, complexity=complexity, mode=mode, enabled=auto_model_routing, max_billions=max_auto_model_b)
        thinking_enabled = bool(manual_thinking) or (adaptive_thinking and mode in {"smart", "deep"} and complexity >= 4)

        context_messages: list[dict] = [{"role": "system", "content": "APEX INTELLIGENCE LAYER:\nAnswer the user's actual request directly. Check assumptions, preserve continuity, prefer grounded context over guesses, and say when information is uncertain. Do not expose hidden reasoning or internal review steps."}]
        memory_matches, knowledge_matches, embedding_model = [], [], None
        summary_used = False

        summary = self.conversation_summary(conversation_id) if use_summary else None
        if summary and summary.get("summary"):
            summary_used = True
            context_messages.append({"role": "system", "content": f"LONG-CONVERSATION SUMMARY:\n{summary['summary']}\n\nUse this to preserve continuity. Prefer newer direct user messages if they conflict."})

        if use_memory:
            memory_matches = self.relevant_memories(user_id, prompt, memory_results)
            if memory_matches:
                lines = ["LOCAL USER MEMORY:", "Use only relevant items. Do not mention the memory system unless asked."]
                lines += [f"[{i}] ({item['category']}) {item['content']}" for i, item in enumerate(memory_matches, 1)]
                context_messages.append({"role": "system", "content": "\n".join(lines)})

        if use_knowledge:
            knowledge_matches, embedding_model = await self.knowledge_matches(prompt, limit=knowledge_results, embedding_rerank=embedding_rerank and mode != "quick")
            if knowledge_matches:
                lines = ["LOCAL RETRIEVAL KNOWLEDGE:", "Use these records only when relevant. They may be incomplete; reason beyond them and do not invent unsupported facts."]
                for i, item in enumerate(knowledge_matches, 1):
                    lines.append(f"[{i}] Source: {item.get('source','local')}\nQ: {str(item.get('question') or '')[:800]}\nA: {str(item.get('answer') or '')[:1600]}")
                context_messages.append({"role": "system", "content": "\n\n".join(lines)})

        calc = self.calculator_result(prompt)
        if calc:
            context_messages.append({"role": "system", "content": f"DETERMINISTIC LOCAL CALCULATOR RESULT:\n{calc}\nUse this instead of estimating arithmetic."})

        meta = {"mode": mode, "complexity": complexity, "model": effective_model, "knowledge_count": len(knowledge_matches), "memory_count": len(memory_matches), "summary_used": summary_used, "embedding_model": embedding_model, "calculator": bool(calc), **route_meta}
        return {"mode": mode, "complexity": complexity, "model": effective_model, "thinking": self.thinking_value(effective_model, thinking_enabled, mode), "context_messages": context_messages, "meta": meta}

    async def chat_once(self, *, model: str, messages: list[dict], thinking, num_predict: int = 700, num_ctx: int = 8192, temperature: float = 0.25, output_format: dict | str | None = None) -> str:
        payload: dict[str, Any] = {"model": model, "messages": messages, "stream": False, "think": thinking, "keep_alive": self.keep_alive, "options": {"num_predict": num_predict, "num_ctx": num_ctx, "temperature": temperature, "top_p": 0.9}}
        if output_format is not None:
            payload["format"] = output_format
        async with httpx.AsyncClient(timeout=180.0) as client:
            r = await client.post(f"{self.ollama_base_url}/api/chat", json=payload)
            r.raise_for_status()
            return str((r.json().get("message") or {}).get("content") or "").strip()

    async def deep_draft(self, *, model: str, messages: list[dict], thinking, max_tokens: int, context_window: int) -> str:
        try:
            return await self.chat_once(model=model, messages=[{"role": "system", "content": "Create a strong internal draft for the requested answer. Focus on correctness, completeness, code validity when applicable, and the user's actual goal. This draft will be reviewed before display."}, *messages], thinking=thinking, num_predict=min(max(350, max_tokens), 1200), num_ctx=max(4096, context_window), temperature=0.35)
        except Exception:
            return ""

    @staticmethod
    def _safe_memory_content(text: str) -> bool:
        low = text.lower()
        forbidden = ("password", "passcode", "api key", "secret key", "private key", "social security", "ssn", "credit card", "cvv", "bank account")
        return not any(x in low for x in forbidden)

    async def learn_conversation(self, *, user_id: str, conversation_id: str, model: str, auto_memory: bool, use_summaries: bool) -> None:
        if not (auto_memory or use_summaries):
            return
        with self.connect() as conn:
            rows = conn.execute("SELECT role,content FROM messages WHERE conversation_id=? AND message_type='text' ORDER BY id DESC LIMIT 24", (conversation_id,)).fetchall()
            count_row = conn.execute("SELECT COUNT(*) AS n FROM messages WHERE conversation_id=? AND message_type='text'", (conversation_id,)).fetchone()
        message_count = int(count_row["n"] if count_row else 0)
        if message_count < 6:
            return
        existing = self.conversation_summary(conversation_id)
        if existing and int(existing.get("message_count") or 0) >= message_count:
            return
        if message_count % 4 not in {0, 1}:
            return
        transcript = "\n".join(f"{r['role'].upper()}: {r['content'][:2200]}" for r in reversed(rows))
        schema = {"type": "object", "properties": {"summary": {"type": "string"}, "memories": {"type": "array", "items": {"type": "object", "properties": {"category": {"type": "string"}, "content": {"type": "string"}, "confidence": {"type": "number"}}, "required": ["category", "content", "confidence"]}}}, "required": ["summary", "memories"]}
        prompts = [{"role": "system", "content": "You are Apex's private local continuity engine. Return JSON matching the schema. Summarize durable project state, decisions, unresolved work, and useful conversation context. Extract only durable memories that improve future assistance, such as stable preferences, project choices, recurring requirements, or explicit remember instructions. Do NOT extract passwords, credentials, API keys, financial account data, exact home addresses, or highly sensitive personal information. Avoid transient one-off details."}, {"role": "user", "content": transcript}]
        try:
            raw = await self.chat_once(model=model, messages=prompts, thinking=self.thinking_value(model, False, "quick"), num_predict=650, num_ctx=8192, temperature=0.0, output_format=schema)
            data = json.loads(raw)
        except Exception:
            return
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        summary = str(data.get("summary") or "").strip()
        if use_summaries and summary:
            with self.connect() as conn:
                conn.execute("""
                    INSERT INTO conversation_summaries(conversation_id,user_id,summary,message_count,updated_at)
                    VALUES(?,?,?,?,?)
                    ON CONFLICT(conversation_id) DO UPDATE SET summary=excluded.summary,message_count=excluded.message_count,updated_at=excluded.updated_at
                """, (conversation_id, user_id, summary[:6000], message_count, now))
        if auto_memory:
            for item in data.get("memories") or []:
                content = " ".join(str(item.get("content") or "").split()).strip()
                if not (5 <= len(content) <= 1000) or not self._safe_memory_content(content):
                    continue
                try:
                    confidence = float(item.get("confidence", 0.0))
                except Exception:
                    confidence = 0.0
                if confidence < 0.68:
                    continue
                self.save_memory(user_id, content, category=str(item.get("category") or "learned")[:80], confidence=confidence, source="learned", now_iso=now)

    async def status(self, user_id: str) -> dict:
        with self.connect() as conn:
            memory_count = conn.execute("SELECT COUNT(*) AS n FROM memories WHERE user_id=?", (user_id,)).fetchone()["n"]
            summary_count = conn.execute("SELECT COUNT(*) AS n FROM conversation_summaries WHERE user_id=?", (user_id,)).fetchone()["n"]
        models = await self.installed_models()
        embedding = await self.embedding_model()
        return {"memory_count": int(memory_count), "summary_count": int(summary_count), "embedding_model": embedding, "installed_chat_models": [str(m.get("name") or m.get("model")) for m in models if self._is_chat_model(str(m.get("name") or m.get("model") or ""))], "ollama_inventory_modified": False}
