-- Campus membership is deliberately application-managed.  The MySQL schema
-- follows the rest of this project and does not use foreign keys, unique
-- constraints, checks, or triggers.
CREATE TABLE campuses (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    code VARCHAR(50) NOT NULL,
    name VARCHAR(100) NOT NULL,
    address VARCHAR(255) NOT NULL DEFAULT '',
    contact_name VARCHAR(100) NOT NULL DEFAULT '',
    contact_mobile VARCHAR(32) NOT NULL DEFAULT '',
    status TINYINT NOT NULL DEFAULT 1,
    created_by BIGINT NULL,
    updated_by BIGINT NULL,
    created_at BIGINT NOT NULL DEFAULT 0,
    updated_at BIGINT NOT NULL DEFAULT 0
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

CREATE INDEX campuses_code ON campuses(code);
CREATE INDEX campuses_status ON campuses(status);

CREATE TABLE campus_members (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    campus_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    member_type VARCHAR(30) NOT NULL,
    is_primary TINYINT NOT NULL DEFAULT 1,
    status TINYINT NOT NULL DEFAULT 1,
    joined_at BIGINT NOT NULL DEFAULT 0,
    left_at BIGINT NULL,
    created_by BIGINT NULL,
    created_at BIGINT NOT NULL DEFAULT 0
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

CREATE INDEX campus_members_campus_id ON campus_members(campus_id);
CREATE INDEX campus_members_user_id ON campus_members(user_id);
CREATE INDEX campus_members_type ON campus_members(member_type);
CREATE INDEX campus_members_status ON campus_members(status);
