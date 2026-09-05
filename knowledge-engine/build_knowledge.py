from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path

TARGET_DEFAULT = 1_000_000

def clean_text(value, max_len=5000):
    if value is None:
        return ""
    text = str(value).replace("\x00", " ").strip()
    if len(text) > max_len:
        text = text[:max_len]
    return text

class Builder:
    def __init__(self, db_path: Path, target: int):
        self.db_path = db_path
        self.target = target
        self.count = 0
        self.source_counts = {}
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=OFF")
        self.conn.execute("PRAGMA temp_store=MEMORY")
        self.conn.execute("PRAGMA cache_size=-64000")
        self.conn.executescript(
            """
            DROP TABLE IF EXISTS qa;
            DROP TABLE IF EXISTS qa_fts;
            DROP TABLE IF EXISTS meta;
            CREATE TABLE qa (
                id INTEGER PRIMARY KEY,
                source TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL
            );
            CREATE TABLE meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        self.batch = []

    def add(self, source, question, answer):
        if self.count >= self.target:
            return False
        q = clean_text(question, 1200)
        a = clean_text(answer, 5000)
        if len(q) < 3 or len(a) < 1:
            return True
        self.batch.append((source, q, a))
        self.count += 1
        self.source_counts[source] = self.source_counts.get(source, 0) + 1
        if len(self.batch) >= 5000:
            self.flush()
        return self.count < self.target

    def flush(self):
        if not self.batch:
            return
        self.conn.executemany(
            "INSERT INTO qa(source,question,answer) VALUES(?,?,?)",
            self.batch,
        )
        self.conn.commit()
        self.batch.clear()

    def finish(self):
        self.flush()
        print(f"Building FTS5 index for {self.count:,} Q&A records...")
        self.conn.executescript(
            """
            CREATE VIRTUAL TABLE qa_fts USING fts5(
                question,
                answer,
                source,
                content='qa',
                content_rowid='id',
                tokenize='unicode61 remove_diacritics 2'
            );
            INSERT INTO qa_fts(qa_fts) VALUES('rebuild');
            """
        )
        self.conn.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES('count',?)",
            (str(self.count),),
        )
        self.conn.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES('sources',?)",
            ("; ".join(f"{k}:{v}" for k, v in sorted(self.source_counts.items())),),
        )
        self.conn.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES('built_at',datetime('now'))"
        )
        self.conn.commit()
        self.conn.execute("PRAGMA optimize")
        self.conn.commit()
        self.conn.close()

def iter_split(dataset_id, split, config=None):
    from datasets import load_dataset
    kwargs = {"split": split, "streaming": True}
    if config:
        return load_dataset(dataset_id, config, **kwargs)
    return load_dataset(dataset_id, **kwargs)

def add_squad(builder):
    print("Adding SQuAD general Q&A...")
    for split in ("train", "validation"):
        try:
            ds = iter_split("rajpurkar/squad", split)
            for row in ds:
                answers = (row.get("answers") or {}).get("text") or []
                if answers:
                    if not builder.add("squad", row.get("question"), answers[0]):
                        return False
        except Exception as exc:
            print(f"SQuAD {split} skipped: {exc}", file=sys.stderr)
    return True

def add_trivia(builder):
    print("Adding TriviaQA general knowledge...")
    for split in ("train", "validation", "test"):
        try:
            ds = iter_split("mandarjoshi/trivia_qa", split, "rc.nocontext")
            for row in ds:
                ans = row.get("answer") or {}
                value = ans.get("value") or ans.get("normalized_value")
                if value:
                    if not builder.add("trivia_qa", row.get("question"), value):
                        return False
        except Exception as exc:
            print(f"TriviaQA {split} skipped: {exc}", file=sys.stderr)
    return True

def add_wikiqa(builder):
    print("Adding WikiQA...")
    for split in ("train", "validation", "test"):
        try:
            ds = iter_split("microsoft/wiki_qa", split)
            for row in ds:
                label = row.get("label")
                # Keep only annotated correct answers.
                if label in (1, "1", True):
                    if not builder.add("wiki_qa", row.get("question"), row.get("answer")):
                        return False
        except Exception as exc:
            print(f"WikiQA {split} skipped: {exc}", file=sys.stderr)
    return True

def add_math_fill(builder):
    print(f"Filling remaining slots with Math-1M reasoning Q&A ({builder.count:,}/{builder.target:,})...")
    try:
        ds = iter_split("apsua/Math-1M", "train")
        for row in ds:
            if not builder.add("math_1m", row.get("prompt"), row.get("response")):
                return False
    except Exception as exc:
        print(f"Math-1M failed: {exc}", file=sys.stderr)
        return False
    return True

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/knowledge_1m.db")
    parser.add_argument("--target", type=int, default=TARGET_DEFAULT)
    args = parser.parse_args()

    db_path = Path(args.db).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    partial = db_path.with_suffix(db_path.suffix + ".building")
    if partial.exists():
        partial.unlink()

    print(f"Building Apex local knowledge pack: target {args.target:,} Q&A records")
    print("Sources: SQuAD + TriviaQA + WikiQA + Math-1M fill")

    builder = Builder(partial, args.target)
    started = time.time()

    # Put general knowledge first; then use the 1M math/reasoning set only as a filler
    # to reach exactly the requested target count.
    for fn in (add_squad, add_trivia, add_wikiqa):
        if builder.count >= builder.target:
            break
        fn(builder)

    if builder.count < builder.target:
        add_math_fill(builder)

    if builder.count < builder.target:
        builder.finish()
        print(f"ERROR: only built {builder.count:,} rows; target was {builder.target:,}.", file=sys.stderr)
        sys.exit(2)

    builder.finish()
    if db_path.exists():
        db_path.unlink()
    partial.rename(db_path)

    elapsed = time.time() - started
    print(f"Knowledge pack ready: {args.target:,} Q&A records in {db_path}")
    print(f"Build time: {elapsed/60:.1f} minutes")

if __name__ == "__main__":
    main()
