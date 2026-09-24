"""校区成员类型常量。

member_type 与用户角色码保持一致：principal / homeroom_teacher / student。
授课教师不设账号与角色，故不在此列。
"""

VALID_MEMBER_TYPES = ("principal", "homeroom_teacher", "student")
