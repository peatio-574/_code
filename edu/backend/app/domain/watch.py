"""视频观看可信计时与完成判定规则。

统一集中阈值常量，处理器与前端不得各自散落硬编码。
"""
from __future__ import annotations

# 建议心跳上报间隔（秒）
REPORT_INTERVAL_SECONDS = 15
# 单次上报可累计的观看时长上限（秒）
MAX_SINGLE_ACCUMULATION_SECONDS = 30
# 会话空闲超时（秒），超过即视为关闭
SESSION_IDLE_TIMEOUT_SECONDS = 300
# 完成阈值：播放位置达到视频时长 95%
COMPLETION_POSITION_PERCENT = 95
# 完成阈值：累计有效观看达到视频时长 90%
COMPLETION_WATCHED_PERCENT = 90
# 视频时长合理上限（秒），一天
MAX_VIDEO_DURATION_SECONDS = 86_400


def valid_duration(duration: int) -> bool:
    """视频时长必须在 (0, 24h] 内。"""
    return 0 < duration <= MAX_VIDEO_DURATION_SECONDS


def valid_position(position: int, duration: int) -> bool:
    """播放位置非负，且不明显超过时长（允许 5 秒误差）。"""
    if position < 0:
        return False
    if duration <= 0:
        return True
    return position <= duration + 5


def effective_seconds(
    server_delta: int,
    position_delta: int,
    cap: int = MAX_SINGLE_ACCUMULATION_SECONDS,
) -> int:
    """计算本次可累计的有效观看秒数。

    取「服务端时间差」「正向播放增量」「单次上限」三者最小值，
    回看（增量<=0）与跳播不计入。
    """
    if server_delta <= 0:
        return 0
    positive = max(position_delta, 0)
    return max(0, min(server_delta, positive, cap))


def is_completed(position: int, duration: int, watched: int) -> bool:
    """完成判定：位置达 95% 或累计观看达 90%，且时长为正。"""
    if duration <= 0:
        return False
    position_reached = position * 100 >= duration * COMPLETION_POSITION_PERCENT
    watched_reached = watched * 100 >= duration * COMPLETION_WATCHED_PERCENT
    return position_reached or watched_reached
