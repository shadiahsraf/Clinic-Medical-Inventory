"""Seed comprehensive, realistic demo data for manual testing of the Clinic Inventory application.

Populates:
- Users & Roles (admin/admin123, keeper/keeper123, issuer/issuer123, dr_sara/doctor123)
- Suppliers (Ahram, Nile, Shifa, Delta)
- Departments (Emergency, Surgery, Dental, Internal, Pediatrics, Nursing, Lab)
- Categories & Units
- Medical items with barcodes, min stocks, and categories
- Confirmed incoming purchases & batches (FIFO)
- Donations (in-kind and cash)
- Draft incoming purchase order (for manual confirmation testing)
- Confirmed issue documents to departments
- Supplier payments (partial, full, unpaid)
- Returns (reusable returned to batch, damaged)
- Damaged stock records
- Stocktaking sessions (one completed, one open draft for manual testing)
- Automatic alerts (low stock & out of stock)
- Clinic settings
"""

import sys
import os
import shutil
from datetime import date, datetime, timedelta

# Ensure correct stdout encoding on Windows
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from clinic_inventory import db, bootstrap
from clinic_inventory.models import (
    User, Role, Item, Category, Unit, Supplier, Department,
    IncomingDoc, IssueDoc, IssueLine, Batch, Setting, StockMovement
)
from clinic_inventory.money import to_e4
from clinic_inventory.services import (
    auth, catalog, inventory as inv, settings as settings_svc, alerts
)
from sqlalchemy import select


def seed_database(db_path: str | None = None):
    target_path = db_path or db.default_db_path()
    print(f"[*] Target database: {target_path}")

    # Step 1: Backup current database if it exists
    if os.path.exists(target_path) and os.path.getsize(target_path) > 0:
        bak_file = f"{target_path}.demo_seed_{datetime.now():%Y%m%d_%H%M%S}.bak"
        shutil.copyfile(target_path, bak_file)
        print(f"[OK] Created safety backup before seeding: {bak_file}")

    # Step 2: Initialize database schema & default roles
    engine = bootstrap.init_database(target_path)

    today = date.today()

    # Step 3: Seed / verify users
    print("[*] Seeding users...")
    with db.session_scope() as s:
        auth.seed_roles(s)

        # Check existing users
        existing_users = {u.username: u for u in s.scalars(select(User)).all()}
        any_admin = next((u for u in existing_users.values() if u.has("users.manage")), None)

        # 1. Admin
        if "admin" not in existing_users:
            admin_user = auth.create_user(s, any_admin, "admin", "د. أيمن عدلي (المدير العام)", "admin123", "مدير النظام")
        else:
            admin_user = existing_users["admin"]
            auth.change_password(s, admin_user, admin_user.id, "admin123")

        # Also reset ayman@clinic.com if present
        if "ayman@clinic.com" in existing_users:
            ayman_user = existing_users["ayman@clinic.com"]
            auth.change_password(s, admin_user, ayman_user.id, "admin123")

        # 2. Storekeeper (أمين المخزن)
        if "keeper" not in existing_users:
            keeper_user = auth.create_user(s, admin_user, "keeper", "أحمد محمود (أمين المخزن)", "keeper123", "أمين المخزن")
        else:
            keeper_user = existing_users["keeper"]
            auth.change_password(s, admin_user, keeper_user.id, "keeper123")

        # 3. Issuer (مسؤول الصرف)
        if "issuer" not in existing_users:
            issuer_user = auth.create_user(s, admin_user, "issuer", "مروة إبراهيم (مسؤول الصرف)", "issuer123", "مسؤول الصرف")
        else:
            issuer_user = existing_users["issuer"]
            auth.change_password(s, admin_user, issuer_user.id, "issuer123")

        # 4. Doctor / Viewer
        if "dr_sara" not in existing_users:
            dr_user = auth.create_user(s, admin_user, "dr_sara", "د. سارة حسن (رئيس قسم)", "doctor123", "مسؤول الصرف")
        else:
            dr_user = existing_users["dr_sara"]

    print("[OK] Users configured (passwords: admin123, keeper123, issuer123, doctor123)")

    # Fetch users in active session for subsequent transactions
    with db.session_scope() as s:
        admin = s.scalar(select(User).where(User.username == "admin"))
        keeper = s.scalar(select(User).where(User.username == "keeper"))
        issuer = s.scalar(select(User).where(User.username == "issuer"))

        # Step 4: Seed Suppliers
        print("[*] Seeding suppliers...")
        suppliers_data = [
            {
                "name": "شركة الأهرام للمستلزمات الطبية",
                "phone": "01012345678",
                "address": "15 شارع القصر العيني - القاهرة",
                "contact_person": "م. سامح رءوف",
                "notes": "توريد شاش وخيوط ومشارط ومستهلكات جراحية معتمدة"
            },
            {
                "name": "شركة النيل للأدوية والمستهلكات",
                "phone": "01223456789",
                "address": "المنطقة الصناعية - العبور",
                "contact_person": "د. هاني فوزي",
                "notes": "مورد رئيسي للمحاليل والمطهرات الطبية والكحول"
            },
            {
                "name": "مؤسسة الشفاء للتجهيزات الطبية",
                "phone": "01134567890",
                "address": "40 شارع مصطفى النحاس - مدينة نصر",
                "contact_person": "أ. خالد سعيد",
                "notes": "سرنجات وكانيولات ومستهلكات الحقن والوريد"
            },
            {
                "name": "شركة دلتا ميديكال تكنولوجي",
                "phone": "01545678901",
                "address": "طنطا - شارع الجيش",
                "contact_person": "أ. وائل مراد",
                "notes": "مستلزمات طب الأسنان ومكافحة العدوى والوقاية"
            }
        ]
        sup_map = {}
        for sup_info in suppliers_data:
            existing_sup = s.scalar(select(Supplier).where(Supplier.name == sup_info["name"]))
            if not existing_sup:
                sup_obj = catalog.create_supplier(s, admin, **sup_info)
            else:
                sup_obj = existing_sup
            sup_map[sup_info["name"]] = sup_obj.id

        # Step 5: Seed Departments
        print("[*] Seeding departments...")
        depts_data = [
            {
                "name": "قسم الطوارئ والاستقبال",
                "dept_type": "طوارئ",
                "location": "الطابق الأرضي",
                "doctor": "د. حازم إمام",
                "contact": "100",
                "notes": "يعمل على مدار 24 ساعة للحالات الحرجة"
            },
            {
                "name": "عيادة الجراحة والعمليات الصغرى",
                "dept_type": "عيادة تخصصية",
                "location": "الطابق الأول - جناح العمليات",
                "doctor": "د. كريم عبد الله",
                "contact": "102",
                "notes": "عمليات جراحية صغرى وغيار جراحي"
            },
            {
                "name": "عيادة الأسنان",
                "dept_type": "عيادة تخصصية",
                "location": "الطابق الأول - غرفة 12",
                "doctor": "د. طارق عبد الرحمن",
                "contact": "101",
                "notes": "علاج وجراحة الفم والأسنان"
            },
            {
                "name": "عيادة الباطنة والقلب",
                "dept_type": "عيادة باطنية",
                "location": "الطابق الثاني - غرفة 21",
                "doctor": "د. سمير شريف",
                "contact": "103",
                "notes": "كشف باطنة ورسم قلب"
            },
            {
                "name": "عيادة الأطفال وحديثي الولادة",
                "dept_type": "عيادة أطفال",
                "location": "الطابق الثاني - غرفة 24",
                "doctor": "د. منى زكي",
                "contact": "104",
                "notes": "رعاية وتطعيمات ومتابعة نمو"
            },
            {
                "name": "قسم التمريض والعناية",
                "dept_type": "رعاية وتمريض",
                "location": "محطة التمريض المركزية",
                "doctor": "مس نادية فهمي",
                "contact": "105",
                "notes": "إعطاء الأدوية والمحاليل والمتابعة"
            },
            {
                "name": "المعمل والتحاليل الطبية",
                "dept_type": "مختبر",
                "location": "الطابق الأرضي - معمل 1",
                "doctor": "د. إيمان خليل",
                "contact": "106",
                "notes": "سحب عينات وفحوصات مخبرية"
            }
        ]
        dept_map = {}
        for dept_info in depts_data:
            existing_dept = s.scalar(select(Department).where(Department.name == dept_info["name"]))
            if not existing_dept:
                dept_obj = catalog.create_department(s, admin, **dept_info)
            else:
                dept_obj = existing_dept
            dept_map[dept_info["name"]] = dept_obj.id

        # Step 6: Seed Categories and Units & Items
        print("[*] Seeding items and categories...")
        # Check if existing items exist
        existing_items = {it.name: it for it in s.scalars(select(Item)).all()}

        items_definitions = [
            {
                "name": "قطن طبي هيدروفيلي 500 جم",
                "unit": "علبة",
                "category": "مستهلكات عامة",
                "min_stock": 15,
                "barcode": "6221100000018",
                "desc": "قطن طبي ناصع البياض عالي الامتصاص"
            },
            {
                "name": "شاش طبي معقم 10×10 سم",
                "unit": "باكت",
                "category": "مستلزمات جراحية",
                "min_stock": 25,
                "barcode": "6221100000025",
                "desc": "باكت 5 قطع معقم للاستخدام الجراحي"
            },
            {
                "name": "كحول طبي إيثيلي 70% 1 لتر",
                "unit": "زجاجة",
                "category": "محاليل ومطهرات",
                "min_stock": 20,
                "barcode": "6221100000032",
                "desc": "كحول نقي لتعقيم وتطهير الأيدي والأسطح"
            },
            {
                "name": "سرنجات بلاستيكية 3 سم معقمة",
                "unit": "علبة",
                "category": "مستلزمات الحقن والوريد",
                "min_stock": 10,
                "barcode": "6221100000049",
                "desc": "علبة 100 سرنجة مع سن رفيع 23G"
            },
            {
                "name": "سرنجات بلاستيكية 5 سم معقمة",
                "unit": "علبة",
                "category": "مستلزمات الحقن والوريد",
                "min_stock": 10,
                "barcode": "6221100000056",
                "desc": "علبة 100 سرنجة للاستخدام العضلي والوريدي"
            },
            {
                "name": "قفازات لاتكس فحص طبي مقاس L",
                "unit": "علبة",
                "category": "وقاية ومكافحة عدوى",
                "min_stock": 15,
                "barcode": "6221100000063",
                "desc": "علبة 100 قفاز بودرة خفيفة"
            },
            {
                "name": "قفازات لاتكس فحص طبي مقاس M",
                "unit": "علبة",
                "category": "وقاية ومكافحة عدوى",
                "min_stock": 15,
                "barcode": "6221100000070",
                "desc": "علبة 100 قفاز مقاس متوسط"
            },
            {
                "name": "كانيولا وريدية مقاس 20G وردي",
                "unit": "علبة",
                "category": "مستلزمات الحقن والوريد",
                "min_stock": 8,
                "barcode": "6221100000087",
                "desc": "علبة 50 كانيولا بمحبس حقن"
            },
            {
                "name": "كانيولا وريدية مقاس 22G أزرق",
                "unit": "علبة",
                "category": "مستلزمات الحقن والوريد",
                "min_stock": 8,
                "barcode": "6221100000094",
                "desc": "علبة 50 كانيولا للأوردة الدقيقة"
            },
            {
                "name": "خيوط جراحية حرير 3/0 مع إبرة",
                "unit": "علبة",
                "category": "مستلزمات جراحية",
                "min_stock": 5,
                "barcode": "6221100000100",
                "desc": "علبة 36 خيط جراحي غير ممتص"
            },
            {
                "name": "بلاستر طبي لاصق 5 سم",
                "unit": "بكرة",
                "category": "مستهلكات عامة",
                "min_stock": 30,
                "barcode": "6221100000117",
                "desc": "بكرة شريط لاصق طبي أكسيد زنك"
            },
            {
                "name": "محلول ملح 0.9% 500 مل",
                "unit": "عبوة",
                "category": "محاليل ومطهرات",
                "min_stock": 50,
                "barcode": "6221100000124",
                "desc": "عبوة محلول كلوريد صوديوم وريدي"
            },
            {
                "name": "محلول رينجر لاكتات 500 مل",
                "unit": "عبوة",
                "category": "محاليل ومطهرات",
                "min_stock": 30,
                "barcode": "6221100000131",
                "desc": "عبوة محلول إلكتروليتات وريدي"
            },
            {
                "name": "كمامات طبية 3 طبقات ذات دعامة",
                "unit": "علبة",
                "category": "وقاية ومكافحة عدوى",
                "min_stock": 20,
                "barcode": "6221100000148",
                "desc": "علبة 50 كمامة استك ناعم"
            },
            {
                "name": "خافض لسان خشبي معقم",
                "unit": "علبة",
                "category": "مستهلكات عامة",
                "min_stock": 12,
                "barcode": "6221100000155",
                "desc": "علبة 100 خافض لسان تغليف فردي"
            },
            {
                "name": "مشرط جراحي معقم مقاس 15",
                "unit": "علبة",
                "category": "مستلزمات جراحية",
                "min_stock": 6,
                "barcode": "6221100000162",
                "desc": "علبة 10 سلاح مشرط كربون ستيل"
            },
            {
                "name": "مطهر بيتادين 10% 1 لتر",
                "unit": "زجاجة",
                "category": "محاليل ومطهرات",
                "min_stock": 10,
                "barcode": "6221100000179",
                "desc": "محلول بوفيدون أيودين مطهر موضعي"
            },
            {
                "name": "مريلة فحص بلاستيكية استخدام مرة واحدة",
                "unit": "باكت",
                "category": "وقاية ومكافحة عدوى",
                "min_stock": 10,
                "barcode": "6221100000186",
                "desc": "باكت 100 مريلة واقية للممارسين"
            }
        ]

        item_map = {}
        # If item "قطن" already exists from initial setup, update it cleanly
        if "قطن" in existing_items:
            cotton_item = existing_items["قطن"]
            cotton_item.name = "قطن طبي هيدروفيلي 500 جم"
            cotton_item.min_stock = 15
            cotton_item.barcode = "6221100000018"
            item_map["قطن طبي هيدروفيلي 500 جم"] = cotton_item.id

        for it_def in items_definitions:
            if it_def["name"] in item_map:
                continue
            matching = s.scalar(select(Item).where(Item.name == it_def["name"]))
            if not matching:
                new_it = catalog.create_item(
                    s, admin,
                    name=it_def["name"],
                    unit_name=it_def["unit"],
                    category_name=it_def["category"],
                    min_stock=it_def["min_stock"],
                    barcode=it_def["barcode"],
                    description=it_def["desc"]
                )
                item_map[it_def["name"]] = new_it.id
            else:
                item_map[it_def["name"]] = matching.id

    # Step 7: Incoming documents (Purchases and Donations)
    print("[*] Recording incoming purchases and donations...")
    with db.session_scope() as s:
        keeper = s.scalar(select(User).where(User.username == "keeper"))
        admin = s.scalar(select(User).where(User.username == "admin"))

        # 1. Purchase invoice from Ahram
        p1 = inv.create_incoming(
            s, keeper,
            source_type="purchase",
            doc_date=today - timedelta(days=25),
            supplier_id=sup_map["شركة الأهرام للمستلزمات الطبية"],
            reference="INV-AHR-101",
            notes="توريد مستلزمات جراحية وشاش وقطن",
            lines=[
                {"item_id": item_map["قطن طبي هيدروفيلي 500 جم"], "quantity": 100, "unit_cost": to_e4("28.00"), "expiry_date": today + timedelta(days=700)},
                {"item_id": item_map["شاش طبي معقم 10×10 سم"], "quantity": 120, "unit_cost": to_e4("12.50"), "expiry_date": today + timedelta(days=600)},
                {"item_id": item_map["خيوط جراحية حرير 3/0 مع إبرة"], "quantity": 25, "unit_cost": to_e4("140.00"), "expiry_date": today + timedelta(days=500)},
                {"item_id": item_map["مشرط جراحي معقم مقاس 15"], "quantity": 30, "unit_cost": to_e4("45.00"), "expiry_date": today + timedelta(days=800)}
            ]
        )
        inv.confirm_incoming(s, keeper, p1.id)
        p1_id = p1.id

        # 2. Purchase invoice from Nile
        p2 = inv.create_incoming(
            s, keeper,
            source_type="purchase",
            doc_date=today - timedelta(days=18),
            supplier_id=sup_map["شركة النيل للأدوية والمستهلكات"],
            reference="INV-NIL-204",
            notes="توريد محاليل وريدية ومطهرات وكحول طبي",
            lines=[
                {"item_id": item_map["كحول طبي إيثيلي 70% 1 لتر"], "quantity": 90, "unit_cost": to_e4("35.00"), "expiry_date": today + timedelta(days=550)},
                {"item_id": item_map["محلول ملح 0.9% 500 مل"], "quantity": 250, "unit_cost": to_e4("15.00"), "expiry_date": today + timedelta(days=400)},
                {"item_id": item_map["محلول رينجر لاكتات 500 مل"], "quantity": 150, "unit_cost": to_e4("18.00"), "expiry_date": today + timedelta(days=400)},
                {"item_id": item_map["مطهر بيتادين 10% 1 لتر"], "quantity": 45, "unit_cost": to_e4("65.00"), "expiry_date": today + timedelta(days=350)}
            ]
        )
        inv.confirm_incoming(s, keeper, p2.id)
        p2_id = p2.id

        # 3. Purchase invoice from Shifa
        p3 = inv.create_incoming(
            s, keeper,
            source_type="purchase",
            doc_date=today - timedelta(days=12),
            supplier_id=sup_map["مؤسسة الشفاء للتجهيزات الطبية"],
            reference="INV-SHF-889",
            notes="توريد سرنجات وكانيولات وقفازات فحص",
            lines=[
                {"item_id": item_map["سرنجات بلاستيكية 3 سم معقمة"], "quantity": 60, "unit_cost": to_e4("85.00"), "expiry_date": today + timedelta(days=700)},
                {"item_id": item_map["سرنجات بلاستيكية 5 سم معقمة"], "quantity": 60, "unit_cost": to_e4("95.00"), "expiry_date": today + timedelta(days=700)},
                {"item_id": item_map["كانيولا وريدية مقاس 20G وردي"], "quantity": 50, "unit_cost": to_e4("160.00"), "expiry_date": today + timedelta(days=600)},
                {"item_id": item_map["كانيولا وريدية مقاس 22G أزرق"], "quantity": 10, "unit_cost": to_e4("160.00"), "expiry_date": today + timedelta(days=600)},
                {"item_id": item_map["قفازات لاتكس فحص طبي مقاس L"], "quantity": 70, "unit_cost": to_e4("110.00"), "expiry_date": today + timedelta(days=650)},
                {"item_id": item_map["قفازات لاتكس فحص طبي مقاس M"], "quantity": 70, "unit_cost": to_e4("110.00"), "expiry_date": today + timedelta(days=650)}
            ]
        )
        inv.confirm_incoming(s, keeper, p3.id)
        p3_id = p3.id

        # 4. In-kind donation
        don1 = inv.create_incoming(
            s, keeper,
            source_type="donation",
            doc_date=today - timedelta(days=10),
            donor_name="جمعية أصدقاء المرضى الخيرية",
            reference="DON-2026-05",
            notes="تبرع عيني بكمامات وخوافض لسان لدعم العيادات",
            lines=[
                {"item_id": item_map["كمامات طبية 3 طبقات ذات دعامة"], "quantity": 100, "unit_cost": to_e4("25.00"), "expiry_date": today + timedelta(days=500)},
                {"item_id": item_map["خافض لسان خشبي معقم"], "quantity": 60, "unit_cost": to_e4("30.00"), "expiry_date": today + timedelta(days=500)}
            ]
        )
        inv.confirm_incoming(s, keeper, don1.id)

        # 5. Cash donation
        inv.record_cash_donation(
            s, admin,
            amount=to_e4(15000),
            move_date=today - timedelta(days=9),
            donor_name="فاعل خير - كفالة مستلزمات طبية",
            notes="تبرع نقدي بخزينة المركز لدعم مستلزمات الطوارئ"
        )

        # 6. Draft purchase invoice (left unconfirmed so user can test confirming it!)
        draft_p = inv.create_incoming(
            s, keeper,
            source_type="purchase",
            doc_date=today,
            supplier_id=sup_map["شركة دلتا ميديكال تكنولوجي"],
            reference="DRAFT-ORD-01",
            notes="أمر توريد تجريبي بانتظار استلام الشحنة وتأكيد الوارد",
            lines=[
                {"item_id": item_map["بلاستر طبي لاصق 5 سم"], "quantity": 50, "unit_cost": to_e4("14.00"), "expiry_date": today + timedelta(days=700)},
                {"item_id": item_map["مريلة فحص بلاستيكية استخدام مرة واحدة"], "quantity": 30, "unit_cost": to_e4("40.00"), "expiry_date": today + timedelta(days=600)}
            ]
        )
        print(f"[OK] Incoming documents created (Draft document: {draft_p.number})")

    # Step 8: Supplier Payments
    print("[*] Recording supplier payments...")
    with db.session_scope() as s:
        keeper = s.scalar(select(User).where(User.username == "keeper"))
        # Partial payment on Ahram invoice (4,000 EGP)
        inv.record_payment(
            s, keeper,
            doc_id=p1_id,
            amount=to_e4(4000),
            pay_date=today - timedelta(days=15),
            method="شيك بنكي",
            notes="دفعة أولى بشيك رقم 40591 بنك مصر"
        )

        # Full payment on Nile invoice
        doc_nile = s.get(IncomingDoc, p2_id)
        tot_nile = inv.outstanding(s, doc_nile)
        inv.record_payment(
            s, keeper,
            doc_id=p2_id,
            amount=tot_nile,
            pay_date=today - timedelta(days=10),
            method="تحويل بنكي",
            notes="سداد كامل الفاتورة بحوالة بنكية رقم TRF-902"
        )
        # Note: Shifa invoice (p3_id) is left UNPAID so the user can test paying it!

    # Step 9: Confirmed issues to departments
    print("[*] Recording issues to departments...")
    issue1_id = None
    issue1_line_syringe = None
    issue1_line_gauze = None
    with db.session_scope() as s:
        issuer = s.scalar(select(User).where(User.username == "issuer"))

        # Issue 1: Emergency Department
        iss1 = inv.create_issue(
            s, issuer,
            department_id=dept_map["قسم الطوارئ والاستقبال"],
            recipient="د. حازم إمام",
            notes="صرفية دورية لقسم الطوارئ والاستقبال للأسبوع الأول",
            lines=[
                {"item_id": item_map["كانيولا وريدية مقاس 20G وردي"], "quantity": 8},
                {"item_id": item_map["سرنجات بلاستيكية 3 سم معقمة"], "quantity": 15},
                {"item_id": item_map["سرنجات بلاستيكية 5 سم معقمة"], "quantity": 12},
                {"item_id": item_map["محلول ملح 0.9% 500 مل"], "quantity": 40},
                {"item_id": item_map["شاش طبي معقم 10×10 سم"], "quantity": 20},
                {"item_id": item_map["كحول طبي إيثيلي 70% 1 لتر"], "quantity": 10},
                {"item_id": item_map["قفازات لاتكس فحص طبي مقاس M"], "quantity": 15}
            ]
        )
        issue1_id = iss1.id
        for l in iss1.lines:
            if l.item_id == item_map["سرنجات بلاستيكية 3 سم معقمة"]:
                issue1_line_syringe = l.id
            elif l.item_id == item_map["شاش طبي معقم 10×10 سم"]:
                issue1_line_gauze = l.id

        # Issue 2: Surgery Clinic
        inv.create_issue(
            s, issuer,
            department_id=dept_map["عيادة الجراحة والعمليات الصغرى"],
            recipient="د. كريم عبد الله",
            notes="مستلزمات الغيار الجراحي والعمليات الصغرى",
            lines=[
                {"item_id": item_map["خيوط جراحية حرير 3/0 مع إبرة"], "quantity": 6},
                {"item_id": item_map["مشرط جراحي معقم مقاس 15"], "quantity": 8},
                {"item_id": item_map["شاش طبي معقم 10×10 سم"], "quantity": 25},
                {"item_id": item_map["مطهر بيتادين 10% 1 لتر"], "quantity": 10},
                {"item_id": item_map["قفازات لاتكس فحص طبي مقاس L"], "quantity": 15}
            ]
        )

        # Issue 3: Dental Clinic
        inv.create_issue(
            s, issuer,
            department_id=dept_map["عيادة الأسنان"],
            recipient="د. طارق عبد الرحمن",
            notes="مستهلكات عيادة الأسنان الأسبوعية",
            lines=[
                {"item_id": item_map["قفازات لاتكس فحص طبي مقاس M"], "quantity": 12},
                {"item_id": item_map["كحول طبي إيثيلي 70% 1 لتر"], "quantity": 6},
                {"item_id": item_map["شاش طبي معقم 10×10 سم"], "quantity": 10},
                {"item_id": item_map["قطن طبي هيدروفيلي 500 جم"], "quantity": 15}
            ]
        )

        # Issue 4: Internal Medicine Clinic
        # Dispense cannula 22G to bring its balance down to 4 (min_stock is 8) -> triggers LOW stock alert!
        inv.create_issue(
            s, issuer,
            department_id=dept_map["عيادة الباطنة والقلب"],
            recipient="د. سمير شريف",
            notes="مستهلكات عيادة الباطنة وكانيولات",
            lines=[
                {"item_id": item_map["سرنجات بلاستيكية 3 سم معقمة"], "quantity": 8},
                {"item_id": item_map["قفازات لاتكس فحص طبي مقاس M"], "quantity": 8},
                {"item_id": item_map["كحول طبي إيثيلي 70% 1 لتر"], "quantity": 4},
                {"item_id": item_map["كانيولا وريدية مقاس 22G أزرق"], "quantity": 6}
            ]
        )

    # Step 10: Returns & Damaged stock
    print("[*] Recording returns and damage...")
    with db.session_scope() as s:
        issuer = s.scalar(select(User).where(User.username == "issuer"))
        keeper = s.scalar(select(User).where(User.username == "keeper"))

        if issue1_line_syringe:
            # Return reusable syringes back to original batch
            ret1 = inv.record_return(
                s, issuer,
                issue_line_id=issue1_line_syringe,
                quantity=2,
                condition="reusable",
                reason="زيادة عن حاجة القسم بعد انتهاء النوبتجية",
                return_date=today - timedelta(days=2)
            )
            inv.approve_return(s, keeper, ret1.id, approve=True)

        if issue1_line_gauze:
            # Return damaged gauze (unusable)
            ret2 = inv.record_return(
                s, issuer,
                issue_line_id=issue1_line_gauze,
                quantity=1,
                condition="damaged",
                reason="تلف الغلاف المعقم أثناء التداول بالقسم",
                return_date=today - timedelta(days=1)
            )
            inv.approve_return(s, keeper, ret2.id, approve=True)

        # Record damaged alcohol bottle in warehouse
        alcohol_batch = s.scalar(select(Batch).where(
            Batch.item_id == item_map["كحول طبي إيثيلي 70% 1 لتر"],
            Batch.remaining_qty > 2
        ))
        if alcohol_batch:
            inv.record_damage(
                s, keeper,
                batch_id=alcohol_batch.id,
                quantity=2,
                reason_type="damaged",
                reason="كسر زجاجتين أثناء النقل الداخلي على الرف",
                event_date=today - timedelta(days=3)
            )

    # Step 11: Stocktaking sessions
    print("[*] Creating stocktaking sessions...")
    with db.session_scope() as s:
        keeper = s.scalar(select(User).where(User.username == "keeper"))
        admin = s.scalar(select(User).where(User.username == "admin"))

        # 1. Closed and approved stocktake for surgical items
        surg_items = [
            item_map["خيوط جراحية حرير 3/0 مع إبرة"],
            item_map["مشرط جراحي معقم مقاس 15"]
        ]
        st1 = inv.start_stocktake(s, keeper, item_ids=surg_items, notes="جرد دوري شهري لقسم المستلزمات الجراحية")
        for line in st1.lines:
            inv.record_count(s, keeper, st1.id, line.item_id, line.book_qty, "مطابق تمامًا للرصيد الفعلي")
        inv.submit_stocktake(s, keeper, st1.id)
        inv.approve_stocktake(s, admin, st1.id)

        # 2. Open active stocktake session for all items (for the user to test!)
        st_open = inv.start_stocktake(s, keeper, notes="جلسة جرد عام للمستودع الرئيسي - جاهزة للإدخال والتسوية")
        print(f"[OK] Created open stocktake session for manual testing: {st_open.number}")

    # Step 12: Configure Settings & Scan alerts
    print("[*] Updating clinic settings and evaluating alerts...")
    with db.session_scope() as s:
        admin = s.scalar(select(User).where(User.username == "admin"))
        settings_svc.save_settings(s, admin, {
            "clinic_name": "مجمع الشفاء الطبي التخصصي",
            "currency": "ج.م",
            "expiry_alert_days": 90,
            "enable_desktop_notifications": True,
            "date_format": "YYYY-MM-DD",
            "auto_backup_enabled": True
        })
        # Evaluate all alerts
        alerts.scan_all(s)
        pending_alerts = alerts.pending_desktop_notifications(s)
        print(f"[OK] Evaluated alerts: {len(pending_alerts)} active alerts triggered.")

    print("\n=======================================================")
    print("   [SUCCESS] DEMO DATA SEEDED SUCCESSFULLY!")
    print("=======================================================")
    print("بيانات الدخول التجريبية الجاهزة للاختبار:")
    print("-------------------------------------------------------")
    print("1. مدير النظام (صلاحيات كاملة):")
    print("   - اسم المستخدم : admin")
    print("   - كلمة المرور  : admin123")
    print("   (أو الحساب السابق: ayman@clinic.com بكلمة مرور: admin123)")
    print()
    print("2. أمين المخزن (إدارة الأصناف، الوارد، السداد، الجرد، الهالك):")
    print("   - اسم المستخدم : keeper")
    print("   - كلمة المرور  : keeper123")
    print()
    print("3. مسؤول الصرف (صرف المستلزمات للأقسام، المرتجعات):")
    print("   - اسم المستخدم : issuer")
    print("   - كلمة المرور  : issuer123")
    print()
    print("4. طبيب / رئيس قسم:")
    print("   - اسم المستخدم : dr_sara")
    print("   - كلمة المرور  : doctor123")
    print("-------------------------------------------------------")
    print("ما تم تجهيزه لتجربته بيدك:")
    print("• شاشة الوارد: يوجد مستند شراء مسودة جاهز للمراجعة والتأكيد.")
    print("• شاشة المدفوعات: فاتورة مؤسسة الشفاء غير مسددة جاهزة للتجربة.")
    print("• شاشة الصرف: جميع الأقسام معرفة والأرصدة جاهزة للصرف.")
    print("• شاشة الجرد: جلسة جرد مفتوحة جاهزة لتسجيل الكميات واعتمادها.")
    print("• شاشة التنبيهات: تنبيهات نشطة لانخفاض ونفاد المخزون.")
    print("• شاشة التقارير وحركة المخزون: ممتلئة بالحركات المالية والمخزنية.")
    print("=======================================================\n")


if __name__ == "__main__":
    db_arg = sys.argv[1] if len(sys.argv) > 1 else None
    seed_database(db_arg)
