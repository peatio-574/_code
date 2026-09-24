"""文件：单文件与分片上传、本地存储与 Range 播放。"""

from __future__ import annotations


import hashlib
import mimetypes
import os
import uuid
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response
from pydantic import BaseModel
from sqlalchemy import text

from ..common import actor_id, now
from ..config import get_settings
from ..db import get_engine, named_lock
from ..error import conflict, forbidden, not_found, validation
from ..response import ok

router = APIRouter(prefix="/api")

MAX_UPLOAD_MB = 30
MAX_CHUNK_MB = 8


def _storage_dir() -> Path:
    root = Path(get_settings().storage_dir)
    if not root.is_absolute():
        root = Path.cwd() / root
    root.mkdir(parents=True, exist_ok=True)
    return root


def _staging_dir() -> Path:
    root = _storage_dir().parent / "upload-staging"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _mime(name: str) -> str:
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


@router.post("/file/upload")
def upload(request: Request, file: UploadFile = File(...), provider: str = Form("local")):
    if provider != "local":
        raise validation("当前仅支持本地存储")
    name = os.path.basename(file.filename or "")
    if not name:
        raise validation("文件名不能为空")
    data = file.file.read()
    if not data:
        raise validation("文件内容为空")
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise validation(f"文件超过 {MAX_UPLOAD_MB}MB 上限")
    file_id = str(uuid.uuid4())
    target = _storage_dir() / file_id
    target.write_bytes(data)
    md5 = hashlib.md5(data).hexdigest()
    created_by = 0
    try:
        created_by = actor_id(request)
    except Exception:
        created_by = 0
    with get_engine().begin() as connection:
        connection.execute(
            text(
                "INSERT INTO files(id, name, mime_type, size, md5, status, storage_path, created_by, "
                "created_at, updated_at) VALUES(:id, :name, :mime, :size, :md5, 1, :path, :created_by, "
                ":ts, :ts)"
            ),
            {
                "id": file_id,
                "name": name,
                "mime": file.content_type or _mime(name),
                "size": len(data),
                "md5": md5,
                "path": str(target),
                "created_by": created_by,
                "ts": now(),
            },
        )
    return ok(
        {
            "id": file_id,
            "name": name,
            "size": len(data),
            "type": file.content_type or _mime(name),
            "md5": md5,
            "status": 1,
        }
    )


class InitInput(BaseModel):
    name: str
    size: int
    md5: str = ""
    mime_type: str = ""
    provider: str = "local"


class ChunkCompleteInput(BaseModel):
    id: str
    parts: list[dict] = []


@router.post("/file/upload/init")
def init_chunked(payload: InitInput, request: Request):
    if payload.size <= 0:
        raise validation("文件大小不合法")
    if payload.size > 2048 * 1024 * 1024:
        raise validation("文件超过 2GB 上限")
    name = os.path.basename(payload.name)
    with named_lock(f"upload:init:{payload.md5}:{payload.size}") as connection:
        if payload.md5:
            existing = connection.execute(
                text(
                    "SELECT id FROM files WHERE md5=:md5 AND size=:size AND status=1 LIMIT 1"
                ),
                {"md5": payload.md5, "size": payload.size},
            ).scalar()
            if existing:
                return ok({"id": existing, "exist": True})
        upload_id = str(uuid.uuid4())
        timestamp = now()
        connection.execute(
            text(
                "INSERT INTO file_uploads(id, name, mime_type, expected_size, md5, provider, status, "
                "created_by, created_at, updated_at) VALUES(:id, :name, :mime, :size, :md5, 'local', 0, "
                ":created_by, :ts, :ts)"
            ),
            {
                "id": upload_id,
                "name": name,
                "mime": payload.mime_type or _mime(name),
                "size": payload.size,
                "md5": payload.md5,
                "created_by": actor_id(request),
                "ts": timestamp,
            },
        )
    return ok({"id": upload_id, "exist": False})


@router.post("/file/upload/chunk")
def upload_chunk(request: Request, id: str = Form(...), part_number: int = Form(...), chunk: UploadFile = File(...)):
    if part_number <= 0:
        raise validation("分片序号不合法")
    data = chunk.file.read()
    if not data:
        raise validation("分片内容为空")
    if len(data) > MAX_CHUNK_MB * 1024 * 1024:
        raise validation(f"分片超过 {MAX_CHUNK_MB}MB 上限")
    with get_engine().begin() as connection:
        record = connection.execute(
            text("SELECT created_by, status FROM file_uploads WHERE id=:id"), {"id": id}
        ).first()
        if record is None or record[1] != 0:
            raise not_found("上传会话不存在")
        if record[0] != actor_id(request):
            raise forbidden()
        part_dir = _staging_dir() / id
        part_dir.mkdir(parents=True, exist_ok=True)
        part_path = part_dir / str(part_number)
        part_path.write_bytes(data)
        etag = hashlib.md5(data).hexdigest()
        connection.execute(
            text("DELETE FROM file_upload_parts WHERE upload_id=:id AND part_number=:part"),
            {"id": id, "part": part_number},
        )
        connection.execute(
            text(
                "INSERT INTO file_upload_parts(upload_id, part_number, size, etag, storage_path, "
                "created_at) VALUES(:id, :part, :size, :etag, :path, :ts)"
            ),
            {
                "id": id,
                "part": part_number,
                "size": len(data),
                "etag": etag,
                "path": str(part_path),
                "ts": now(),
            },
        )
        connection.execute(
            text("UPDATE file_uploads SET updated_at=:ts WHERE id=:id"),
            {"ts": now(), "id": id},
        )
    return ok({"part_number": part_number, "etag": etag})


@router.post("/file/upload/complete")
def complete_chunked(payload: ChunkCompleteInput, request: Request):
    with named_lock(f"upload:complete:{payload.id}") as connection:
        record = connection.execute(
            text(
                "SELECT name, mime_type, expected_size, md5, created_by, status FROM file_uploads "
                "WHERE id=:id"
            ),
            {"id": payload.id},
        ).mappings().first()
        if record is None or record["status"] != 0:
            raise not_found("上传会话不存在")
        if record["created_by"] != actor_id(request):
            raise forbidden()
        parts = connection.execute(
            text(
                "SELECT part_number, etag, storage_path, size FROM file_upload_parts "
                "WHERE upload_id=:id ORDER BY part_number"
            ),
            {"id": payload.id},
        ).mappings().all()
        if not parts:
            raise validation("没有已上传的分片")
        for index, part in enumerate(parts, start=1):
            if part["part_number"] != index:
                raise conflict("分片序号不连续")
        total_size = sum(part["size"] for part in parts)
        if total_size != record["expected_size"]:
            raise conflict("文件大小与预期不一致")
        file_id = str(uuid.uuid4())
        target = _storage_dir() / file_id
        md5 = hashlib.md5()
        with target.open("wb") as output:
            for part in parts:
                data = Path(part["storage_path"]).read_bytes()
                md5.update(data)
                output.write(data)
        if record["md5"] and md5.hexdigest() != record["md5"]:
            target.unlink(missing_ok=True)
            raise conflict("文件 MD5 校验失败")
        connection.execute(
            text(
                "INSERT INTO files(id, name, mime_type, size, md5, status, storage_path, created_by, "
                "created_at, updated_at) VALUES(:id, :name, :mime, :size, :md5, 1, :path, :created_by, "
                ":ts, :ts)"
            ),
            {
                "id": file_id,
                "name": record["name"],
                "mime": record["mime_type"],
                "size": total_size,
                "md5": md5.hexdigest(),
                "path": str(target),
                "created_by": record["created_by"],
                "ts": now(),
            },
        )
        connection.execute(
            text("UPDATE file_uploads SET status=1, updated_at=:ts WHERE id=:id"),
            {"ts": now(), "id": payload.id},
        )
    return ok(
        {
            "id": file_id,
            "name": record["name"],
            "size": total_size,
            "type": record["mime_type"],
            "md5": md5.hexdigest(),
            "status": 1,
        }
    )


def _content_disposition(name: str, fallback: str) -> str:
    """构造可安全编码的 Content-Disposition。

    HTTP 头必须以 latin-1 编码；若文件名含中文等非 ASCII 字符，直接写入会抛
    UnicodeEncodeError 导致 500。这里按 RFC 5987 提供 filename* 与 ASCII 回退名。
    """
    ascii_map = name.encode("ascii", "ignore").decode("ascii").strip() or fallback
    encoded = quote(name or fallback)
    return f"inline; filename=\"{ascii_map}\"; filename*=UTF-8''{encoded}"


def _serve(file_id: str, expect_prefix: str | None, request: Request, require_auth: bool) -> Response:
    with get_engine().connect() as connection:
        row = connection.execute(
            text(
                "SELECT id, name, mime_type, size, storage_path, status FROM files WHERE id=:id"
            ),
            {"id": file_id},
        ).mappings().first()
        connection.commit()
    if row is None or row["status"] != 1:
        raise not_found("文件不存在")
    if expect_prefix and not (row["mime_type"] or "").startswith(expect_prefix):
        raise not_found("文件类型不匹配")
    if require_auth:
        actor_id(request)
    path = Path(row["storage_path"])
    if not path.exists():
        raise not_found("文件已丢失")
    headers = {
        "Accept-Ranges": "bytes",
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": _content_disposition(row["name"], file_id),
    }
    range_header = request.headers.get("range")
    if range_header and range_header.startswith("bytes="):
        spec = range_header[len("bytes="):]
        start_str, _, end_str = spec.partition("-")
        try:
            start = int(start_str) if start_str else 0
            end = int(end_str) if end_str else row["size"] - 1
        except ValueError:
            start, end = 0, row["size"] - 1
        start = max(0, start)
        end = min(end, row["size"] - 1)
        if start > end:
            start, end = 0, row["size"] - 1
        length = end - start + 1
        with path.open("rb") as handle:
            handle.seek(start)
            data = handle.read(length)
        headers["Content-Range"] = f"bytes {start}-{end}/{row['size']}"
        return Response(
            content=data,
            status_code=206,
            media_type=row["mime_type"],
            headers=headers,
        )
    return FileResponse(path, media_type=row["mime_type"], headers=headers)


@router.get("/image/{file_id}")
def image(file_id: str, request: Request):
    return _serve(file_id, "image/", request, False)


@router.get("/video/{file_id}")
def video(file_id: str, request: Request):
    return _serve(file_id, "video/", request, True)


@router.get("/file/{file_id}")
def download(file_id: str, request: Request):
    return _serve(file_id, None, request, True)

