-- Preserve the campus that owned a business record when it was created.
-- Existing rows are backfilled from the user's primary active campus.
ALTER TABLE courses ADD COLUMN campus_id BIGINT NULL;
ALTER TABLE announcements ADD COLUMN campus_id BIGINT NULL;
ALTER TABLE exam_attempts ADD COLUMN campus_id BIGINT NULL;
ALTER TABLE learning_progress ADD COLUMN campus_id BIGINT NULL;
ALTER TABLE course_watch_progress ADD COLUMN campus_id BIGINT NULL;
ALTER TABLE course_watch_sessions ADD COLUMN campus_id BIGINT NULL;

UPDATE courses c
LEFT JOIN campus_members cm
  ON cm.user_id=c.created_by AND cm.status=1 AND cm.is_primary=1
SET c.campus_id=cm.campus_id
WHERE c.campus_id IS NULL;

UPDATE announcements a
LEFT JOIN campus_members cm
  ON cm.user_id=a.created_user AND cm.status=1 AND cm.is_primary=1
SET a.campus_id=cm.campus_id
WHERE a.campus_id IS NULL;

UPDATE exam_attempts a
LEFT JOIN campus_members cm
  ON cm.user_id=a.user_id AND cm.status=1 AND cm.is_primary=1
SET a.campus_id=cm.campus_id
WHERE a.campus_id IS NULL;

UPDATE learning_progress lp
LEFT JOIN campus_members cm
  ON cm.user_id=lp.user_id AND cm.status=1 AND cm.is_primary=1
SET lp.campus_id=cm.campus_id
WHERE lp.campus_id IS NULL;

UPDATE course_watch_progress wp
LEFT JOIN campus_members cm
  ON cm.user_id=wp.user_id AND cm.status=1 AND cm.is_primary=1
SET wp.campus_id=cm.campus_id
WHERE wp.campus_id IS NULL;

UPDATE course_watch_sessions ws
LEFT JOIN campus_members cm
  ON cm.user_id=ws.user_id AND cm.status=1 AND cm.is_primary=1
SET ws.campus_id=cm.campus_id
WHERE ws.campus_id IS NULL;

CREATE INDEX courses_campus_id ON courses(campus_id);
CREATE INDEX announcements_campus_id ON announcements(campus_id);
CREATE INDEX exam_attempts_campus_id ON exam_attempts(campus_id);
CREATE INDEX learning_progress_campus_id ON learning_progress(campus_id);
CREATE INDEX course_watch_progress_campus_id ON course_watch_progress(campus_id);
CREATE INDEX course_watch_sessions_campus_id ON course_watch_sessions(campus_id);
