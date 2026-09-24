-- Each multipart session keeps its selected destination so local, OSS and COS
-- uploads can run concurrently and configuration changes cannot redirect parts.
ALTER TABLE file_uploads
    ADD COLUMN provider VARCHAR(16) NOT NULL DEFAULT 'local' AFTER md5;
