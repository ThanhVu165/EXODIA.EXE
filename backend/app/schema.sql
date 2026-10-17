-- DSA Intelligence — schema (thiết kế (C) theo Mục 6.2–6.6 của BUILD_PROMPT).
-- Idempotent: chạy lại mỗi lần khởi động, dưới advisory lock.

CREATE TABLE IF NOT EXISTS cases (
    id              uuid PRIMARY KEY,
    submission_key  text NOT NULL UNIQUE,              -- khóa theo lần gửi (Idempotency-Key)
    content_hash    text NOT NULL,                     -- sha256(sender + nội dung chuẩn hóa)
    sender          text,
    email_body      text NOT NULL,                     -- bản gốc, không bao giờ UPDATE trong code
    source          text NOT NULL DEFAULT 'PUBLIC' CHECK (source IN ('PUBLIC', 'VERIFY')),
    verify_run_id   uuid,
    status          text NOT NULL CHECK (status IN ('RECEIVED','PROCESSING','AUTO_REPLIED','PENDING_HUMAN',
                                                     'ERROR','HUMAN_REPLIED','CANCELLED','SUPERSEDED')),
    decision        text CHECK (decision IN ('AUTO','ESCALATE')),
    reason_primary  text,
    reasons         text[] NOT NULL DEFAULT '{}',
    flags           text[] NOT NULL DEFAULT '{}',
    agent_output    jsonb,                             -- đầu ra có cấu trúc đã validate
    package         jsonb,                             -- gói quyết định cho nhân viên DSA
    error_code      text,
    error_detail    text,
    model_id        text,
    policy_version  text,
    usage           jsonb,
    attempts        int NOT NULL DEFAULT 0,
    lease_until     timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS cases_status_idx ON cases (source, status, created_at DESC);
CREATE INDEX IF NOT EXISTS cases_hash_idx ON cases (content_hash, created_at DESC);

CREATE TABLE IF NOT EXISTS outbox (
    id               uuid PRIMARY KEY,
    case_id          uuid NOT NULL REFERENCES cases(id),
    kind             text NOT NULL CHECK (kind IN ('AUTO_REPLY','HUMAN_REPLY','CORRECTION')),
    version          int  NOT NULL,
    body             text NOT NULL,
    status           text NOT NULL CHECK (status IN ('SENT','SUPERSEDED')),
    supersedes_id    uuid REFERENCES outbox(id),
    idempotency_key  text NOT NULL UNIQUE,
    created_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (case_id, kind, version)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id              bigserial PRIMARY KEY,
    case_id         uuid,
    at              timestamptz NOT NULL DEFAULT clock_timestamp(),
    actor           text NOT NULL CHECK (actor IN ('system','staff')),
    actor_name      text,
    action          text NOT NULL,
    input_ref       text,                -- tham chiếu bất biến tới email gốc: case:<id> sha256:<hash>
    reason          text,
    clause_ids      text[] NOT NULL DEFAULT '{}',
    status_before   text,
    status_after    text,
    idempotency_key text,
    model_id        text,
    policy_version  text,
    details         jsonb
);
CREATE INDEX IF NOT EXISTS audit_case_idx ON audit_log (case_id, id);

-- audit_log chỉ thêm: chặn UPDATE/DELETE ở tầng DB (mạnh hơn quy ước trong code).
CREATE OR REPLACE FUNCTION audit_log_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only';
END $$;
DROP TRIGGER IF EXISTS audit_log_no_update ON audit_log;
CREATE TRIGGER audit_log_no_update BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_append_only();

CREATE TABLE IF NOT EXISTS usage_counters (
    bucket       text NOT NULL,
    window_start timestamptz NOT NULL,
    count        int NOT NULL DEFAULT 0,
    PRIMARY KEY (bucket, window_start)
);

CREATE TABLE IF NOT EXISTS system_flags (
    key        text PRIMARY KEY,
    value      jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS verify_runs (
    id           uuid PRIMARY KEY,
    kind         text NOT NULL CHECK (kind IN ('GENERAL','ESCALATION','CONTROLS')),
    started_at   timestamptz NOT NULL,
    finished_at  timestamptz,
    duration_ms  int,
    status       text NOT NULL CHECK (status IN ('RUNNING','DONE','FAILED')),
    passed       int,
    total        int,
    results      jsonb,
    usage        jsonb,
    error        text
);

-- Challenge bổ sung: Agent 2 chấm "mức hài lòng DỰ ĐOÁN" cho phản hồi tự động đã ghi outbox.
-- Không phải khảo sát sinh viên. Điểm chỉ có khi status = COMPLETED; lỗi KHÔNG bao giờ thành 0 điểm.
CREATE TABLE IF NOT EXISTS satisfaction_evaluations (
    id               uuid PRIMARY KEY,
    outbox_id        uuid NOT NULL UNIQUE REFERENCES outbox(id),   -- mỗi phản hồi đã gửi chấm đúng một lần
    case_id          uuid NOT NULL REFERENCES cases(id),
    status           text NOT NULL CHECK (status IN ('RUNNING','COMPLETED','EVALUATION_FAILED','INSUFFICIENT_CONTEXT')),
    score            int CHECK (score BETWEEN 0 AND 100),
    reason           text,
    missing_points   text[] NOT NULL DEFAULT '{}',
    error_code       text,
    model_id         text,
    rubric_version   text NOT NULL,
    usage            jsonb,
    attempts         int NOT NULL DEFAULT 1,
    started_at       timestamptz NOT NULL DEFAULT now(),
    evaluated_at     timestamptz,
    review_verdict   text CHECK (review_verdict IN ('AGREE','DISAGREE')),
    review_comment   text,
    reviewer         text,
    reviewed_at      timestamptz,
    CHECK ((status = 'COMPLETED') = (score IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS sat_eval_time_idx ON satisfaction_evaluations (evaluated_at DESC);
