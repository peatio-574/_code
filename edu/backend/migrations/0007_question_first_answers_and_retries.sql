-- Immutable first-answer facts define learning progress and accuracy. Retry
-- attempts are deliberately separate and never update this baseline.
CREATE TABLE question_first_answers (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    question_id BIGINT NOT NULL,
    answer VARCHAR(4000) NOT NULL DEFAULT '',
    is_correct TINYINT NOT NULL DEFAULT 0,
    answered_at BIGINT NOT NULL
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

CREATE INDEX question_first_answers_user_question ON question_first_answers(user_id, question_id);
CREATE INDEX question_first_answers_user_correct ON question_first_answers(user_id, is_correct);

-- Preserve the current historical answers as the first-answer baseline.
INSERT INTO question_first_answers(user_id, question_id, answer, is_correct, answered_at)
SELECT qr.user_id, qr.question_id, qr.answer, qr.is_correct, qr.updated_at
FROM question_records qr
WHERE qr.answered = 1
  AND qr.id = (SELECT MIN(first_qr.id) FROM question_records first_qr
               WHERE first_qr.user_id=qr.user_id AND first_qr.question_id=qr.question_id AND first_qr.answered=1);

CREATE TABLE question_retry_attempts (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    status TINYINT NOT NULL DEFAULT 0,
    question_count INT NOT NULL DEFAULT 0,
    started_at BIGINT NOT NULL,
    completed_at BIGINT NULL
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

CREATE INDEX question_retry_attempts_user_started ON question_retry_attempts(user_id, started_at);

CREATE TABLE question_retry_answers (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    attempt_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    question_id BIGINT NOT NULL,
    answer VARCHAR(4000) NOT NULL DEFAULT '',
    is_correct TINYINT NOT NULL DEFAULT 0,
    answered_at BIGINT NOT NULL
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

CREATE INDEX question_retry_answers_attempt_question ON question_retry_answers(attempt_id, question_id);
CREATE INDEX question_retry_answers_user_question ON question_retry_answers(user_id, question_id);
