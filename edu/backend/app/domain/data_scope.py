"""数据范围与校区范围谓词。

把 self/direct/tree/all 的用户关系范围与「共同启用校区」范围，
组装为可嵌入 SQL 的谓词片段，供列表/统计/导出统一使用。
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..domain.rbac import (
    DATA_SCOPE_ALL,
    DATA_SCOPE_DIRECT,
    DATA_SCOPE_SELF,
    DATA_SCOPE_TREE,
    data_scope_rank,
)


@dataclass
class DataScopeContext:
    """操作者的数据范围上下文。"""

    actor_id: int
    scope: str
    campus_ids: list[int]

    def campus_predicate(self, alias: str) -> str:
        """校区谓词：目标用户与操作者存在共同启用校区。alias 需能访问 .id。"""
        if self.scope == DATA_SCOPE_ALL:
            return "1 = 1"
        if not self.campus_ids:
            return "1 = 0"
        ids = ",".join(str(int(value)) for value in self.campus_ids)
        return (
            "EXISTS (SELECT 1 FROM campus_members scope_cm "
            "JOIN campuses scope_c ON scope_c.id = scope_cm.campus_id "
            f"WHERE scope_cm.user_id = {alias}.id AND scope_cm.status = 1 "
            f"AND scope_c.status = 1 AND scope_cm.campus_id IN ({ids}))"
        )

    def user_predicate(self, alias: str) -> str:
        """用户关系谓词：self/direct/tree/all。"""
        actor = int(self.actor_id)
        if self.scope == DATA_SCOPE_ALL:
            return "1 = 1"
        if self.scope == DATA_SCOPE_TREE:
            return (
                f"{alias}.id IN (WITH RECURSIVE scoped(id) AS ("
                f"SELECT {actor} "
                f"UNION SELECT id FROM users WHERE created_by = {actor} "
                f"UNION SELECT u.id FROM users u JOIN scoped s ON u.manager_id = s.id) "
                "SELECT id FROM scoped)"
            )
        if self.scope == DATA_SCOPE_DIRECT:
            return (
                f"({alias}.id = {actor} OR {alias}.manager_id = {actor} "
                f"OR {alias}.created_by = {actor})"
            )
        return f"{alias}.id = {actor}"

    def combined_user_predicate(self, alias: str) -> str:
        """用户关系范围 AND 校区范围，业务列表统一使用。"""
        return f"({self.campus_predicate(alias)}) AND ({self.user_predicate(alias)})"

    def campus_record_predicate(self, column: str) -> str:
        """业务记录校区快照谓词：记录 campus_id 为空或落在操作者校区内。"""
        if self.scope == DATA_SCOPE_ALL:
            return "1 = 1"
        if not self.campus_ids:
            return "1 = 0"
        ids = ",".join(str(int(value)) for value in self.campus_ids)
        return f"({column} IS NULL OR {column} IN ({ids}))"


def context(connection: Connection, actor_id: int) -> DataScopeContext:
    """构建操作者的数据范围上下文：最大范围 + 所有启用校区。"""
    scopes = [
        row[0]
        for row in connection.execute(
            text(
                "SELECT r.data_scope FROM roles r JOIN user_roles ur ON ur.role_id = r.id "
                "WHERE ur.user_id = :actor AND r.status = 1"
            ),
            {"actor": actor_id},
        ).fetchall()
    ]
    scope = max(scopes, key=data_scope_rank) if scopes else DATA_SCOPE_SELF
    campus_ids = [
        row[0]
        for row in connection.execute(
            text(
                "SELECT DISTINCT cm.campus_id FROM campus_members cm "
                "JOIN campuses c ON c.id = cm.campus_id "
                "WHERE cm.user_id = :actor AND cm.status = 1 AND c.status = 1 "
                "ORDER BY cm.campus_id"
            ),
            {"actor": actor_id},
        ).fetchall()
    ]
    return DataScopeContext(actor_id=actor_id, scope=scope, campus_ids=campus_ids)


def primary_campus_id(connection: Connection, user_id: int) -> int | None:
    """取用户主校区 ID。"""
    return connection.execute(
        text(
            "SELECT campus_id FROM campus_members "
            "WHERE user_id = :user_id AND status = 1 AND is_primary = 1 "
            "ORDER BY id LIMIT 1"
        ),
        {"user_id": user_id},
    ).scalar()
