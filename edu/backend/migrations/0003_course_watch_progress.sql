-- Video watch progress tables (docs/VIDEO_WATCHING_PROGRESS.md §2).
-- Design constraints unchanged: primary keys and query indexes only; no
-- foreign keys, unique constraints, CHECKs, or triggers. Uniqueness of
-- (user_id, course_id, chapter_id) and session lifecycle are enforced by
-- application code under named locks.
-- NOTE: the plan draft's `video_file_id BIGINT` is intentionally omitted —
-- chapter_id already identifies the video resource (chapters store `file` as
-- a path string and files.id is a VARCHAR(36) UUID).

CREATE TABLE course_watch_progress (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    course_id BIGINT NOT NULL,
    chapter_id BIGINT NOT NULL,
    first_watched_at BIGINT NOT NULL DEFAULT 0,
    last_watched_at BIGINT NOT NULL DEFAULT 0,
    last_position_seconds BIGINT NOT NULL DEFAULT 0,
    video_duration_seconds BIGINT NOT NULL DEFAULT 0,
    watched_seconds BIGINT NOT NULL DEFAULT 0,
    completed TINYINT NOT NULL DEFAULT 0,
    last_report_sequence BIGINT NOT NULL DEFAULT 0,
    created_at BIGINT NOT NULL DEFAULT 0,
    updated_at BIGINT NOT NULL DEFAULT 0
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

CREATE INDEX course_watch_progress_user_course_chapter
    ON course_watch_progress(user_id, course_id, chapter_id);
CREATE INDEX course_watch_progress_user_updated
    ON course_watch_progress(user_id, updated_at);
CREATE INDEX course_watch_progress_course_updated
    ON course_watch_progress(course_id, updated_at);
CREATE INDEX course_watch_progress_course_completed
    ON course_watch_progress(course_id, completed, updated_at);

-- One row per player session (client generates client_session_id UUID).
-- status: 0 = open, 1 = finished, 2 = closed as timed out by the server.
CREATE TABLE course_watch_sessions (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    course_id BIGINT NOT NULL,
    chapter_id BIGINT NOT NULL,
    client_session_id VARCHAR(64) NOT NULL,
    started_at BIGINT NOT NULL DEFAULT 0,
    last_reported_at BIGINT NOT NULL DEFAULT 0,
    ended_at BIGINT NULL,
    start_position_seconds BIGINT NOT NULL DEFAULT 0,
    last_position_seconds BIGINT NOT NULL DEFAULT 0,
    watched_seconds BIGINT NOT NULL DEFAULT 0,
    last_sequence BIGINT NOT NULL DEFAULT 0,
    status TINYINT NOT NULL DEFAULT 0,
    created_at BIGINT NOT NULL DEFAULT 0,
    updated_at BIGINT NOT NULL DEFAULT 0
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

CREATE INDEX course_watch_sessions_user_client
    ON course_watch_sessions(user_id, client_session_id);
CREATE INDEX course_watch_sessions_user_reported
    ON course_watch_sessions(user_id, last_reported_at);
