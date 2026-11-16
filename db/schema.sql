-- civsim PostgreSQL schema（docker compose 啟動時自動建立）
-- 負責人：資料庫組。對應 storage/recorder.py 的 PostgresRecorder。

CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    experiment  TEXT NOT NULL,
    seed        INTEGER NOT NULL,
    config      JSONB NOT NULL,          -- 完整設定，確保可重現
    model       TEXT,                    -- LLM 模型名稱（rule_based 時為 NULL）
    prompt_ver  TEXT,
    started_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS events (
    id       BIGSERIAL PRIMARY KEY,
    run_id   TEXT REFERENCES runs(run_id) ON DELETE CASCADE,
    tick     INTEGER NOT NULL,
    kind     TEXT NOT NULL,              -- action:trade / world:food_shock_forecast ...
    actor    TEXT,
    success  BOOLEAN NOT NULL,
    payload  JSONB,
    message  TEXT
);
CREATE INDEX IF NOT EXISTS events_run_tick ON events (run_id, tick);

CREATE TABLE IF NOT EXISTS agent_snapshots (
    run_id     TEXT REFERENCES runs(run_id) ON DELETE CASCADE,
    tick       INTEGER NOT NULL,
    agent_id   TEXT NOT NULL,
    role       TEXT,
    goal       TEXT,
    health     INTEGER,
    inventory  JSONB,
    PRIMARY KEY (run_id, tick, agent_id)
);

CREATE TABLE IF NOT EXISTS tick_metrics (
    run_id   TEXT REFERENCES runs(run_id) ON DELETE CASCADE,
    tick     INTEGER NOT NULL,
    metrics  JSONB NOT NULL,
    PRIMARY KEY (run_id, tick)
);
