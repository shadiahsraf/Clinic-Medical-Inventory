"""Consistent SQLite backups (sqlite3 online backup API) and safe restore."""
import os, shutil, sqlite3
from datetime import datetime
from ..errors import AppError
from ..models import BackupMeta
from .common import require, audit


def _verify(path: str) -> bool:
    try:
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        ok = c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        c.execute("SELECT count(*) FROM items"); c.close()
        return ok
    except sqlite3.Error:
        return False


def create_backup(s, actor, db_path: str, dest_dir: str, kind: str = "manual") -> str:
    require(actor, "backup.manage")
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, f"clinic-backup-{datetime.now():%Y%m%d-%H%M%S}-{kind}.db")
    src = sqlite3.connect(db_path); dst = sqlite3.connect(dest)
    try:
        src.backup(dst)          # consistent snapshot even while the app is running
    finally:
        dst.close(); src.close()
    ok = _verify(dest)
    s.add(BackupMeta(path=dest, kind=kind, status="ok" if ok else "failed",
                     size_bytes=os.path.getsize(dest), created_by=actor.id))
    audit(s, actor, "backup", "backup", dest, new={"ok": ok})
    if not ok:
        raise AppError("فشل التحقق من سلامة النسخة الاحتياطية.")
    return dest


def restore_backup(actor, backup_path: str, db_path: str, safety_dir: str, engine_dispose):
    """Caller must have closed all sessions. A safety copy of the CURRENT database
    is always taken first; restore happens via temp-file + atomic replace."""
    if not actor.has("backup.manage"):
        raise AppError("ليست لديك صلاحية استعادة النسخ الاحتياطية.")
    if not _verify(backup_path):
        raise AppError("ملف النسخة الاحتياطية غير صالح أو تالف؛ لن يتم تغيير البيانات الحالية.")
    os.makedirs(safety_dir, exist_ok=True)
    safety = os.path.join(safety_dir, f"before-restore-{datetime.now():%Y%m%d-%H%M%S}.db")
    src = sqlite3.connect(db_path); dst = sqlite3.connect(safety)
    src.backup(dst); dst.close(); src.close()
    engine_dispose()
    tmp = db_path + ".restoring"
    shutil.copyfile(backup_path, tmp)
    for ext in ("-wal", "-shm"):
        if os.path.exists(db_path + ext):
            os.remove(db_path + ext)
    os.replace(tmp, db_path)
    return safety


def verify_backup(backup_path: str) -> bool:
    return _verify(backup_path)


def list_backups(s):
    from ..models import User
    from sqlalchemy import select
    records = list(s.scalars(select(BackupMeta).order_by(BackupMeta.id.desc())))
    result = []
    for r in records:
        u = s.get(User, r.created_by) if r.created_by else None
        result.append({
            "id": r.id,
            "created_at": r.created_at,
            "path": r.path,
            "kind": r.kind,
            "status": r.status,
            "size_bytes": r.size_bytes or 0,
            "creator_name": u.display_name if u else "تلقائي"
        })
    return result

