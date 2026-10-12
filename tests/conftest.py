import pytest
from datetime import date
from clinic_inventory import bootstrap, db
from clinic_inventory.services import auth, catalog
from clinic_inventory.permissions import ROLE_ADMIN, ROLE_KEEPER, ROLE_ISSUER


@pytest.fixture
def env(tmp_path):
    path = str(tmp_path / "t.db")
    bootstrap.init_database(path)
    with db.session_scope() as s:
        admin = auth.create_user(s, None, "admin", "المدير", "secret1", ROLE_ADMIN)
        keeper = auth.create_user(s, admin, "keeper", "أمين المخزن", "secret1", ROLE_KEEPER)
        issuer = auth.create_user(s, admin, "issuer", "مسؤول الصرف", "secret1", ROLE_ISSUER)
        item = catalog.create_item(s, admin, "شاش طبي", "علبة", "مستلزمات", min_stock=20)
        dept = catalog.create_department(s, admin, "عيادة الباطنة")
        sup = catalog.create_supplier(s, admin, "مورد الشفاء")
        ids = dict(admin=admin.id, keeper=keeper.id, issuer=issuer.id, item=item.id, dept=dept.id, sup=sup.id)
    class E: pass
    e = E(); e.path = path; e.ids = ids
    return e


def user(uid):
    from clinic_inventory.models import User
    with db.session_scope() as s:
        u = s.get(User, uid); s.expunge(u); return u
