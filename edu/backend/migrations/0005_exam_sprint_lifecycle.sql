-- Sprint exam lifecycle. Status: 0=draft, 1=published, 2=withdrawn.
ALTER TABLE exams ADD COLUMN pass_score INT NOT NULL DEFAULT 60;
ALTER TABLE exams ADD COLUMN published_at BIGINT NOT NULL DEFAULT 0;

UPDATE exams SET published_at = created_at WHERE status = 1 AND published_at = 0;
CREATE INDEX exams_creator_status ON exams(created_by, status, is_mock);
