-- Resumable uploads are staged locally and committed to the configured storage
-- provider only after all parts have been validated. Rows older than the
-- configured TTL are safe to remove together with their staging directory.
CREATE TABLE file_uploads (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    mime_type VARCHAR(100) NOT NULL DEFAULT 'application/octet-stream',
    expected_size BIGINT NOT NULL,
    md5 VARCHAR(64) NOT NULL DEFAULT '',
    status TINYINT NOT NULL DEFAULT 0,
    created_by BIGINT NOT NULL DEFAULT 0,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

CREATE INDEX file_uploads_status_updated ON file_uploads(status, updated_at);

CREATE TABLE file_upload_parts (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    upload_id VARCHAR(36) NOT NULL,
    part_number INT NOT NULL,
    size BIGINT NOT NULL,
    etag VARCHAR(64) NOT NULL,
    storage_path VARCHAR(512) NOT NULL,
    created_at BIGINT NOT NULL
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

CREATE INDEX file_upload_parts_upload_part ON file_upload_parts(upload_id, part_number);
