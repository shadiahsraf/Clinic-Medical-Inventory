"""Permission keys and default role definitions (Arabic labels)."""

PERMISSIONS = {
    "items.manage": "إدارة الأصناف",
    "partners.manage": "إدارة الموردين والعيادات",
    "incoming.create": "تسجيل الوارد",
    "incoming.cancel": "إلغاء الوارد المؤكد",
    "payments.manage": "تسجيل مدفوعات الموردين",
    "issue.create": "صرف المستلزمات",
    "returns.create": "تسجيل المرتجعات",
    "returns.approve": "اعتماد المرتجعات",
    "damage.create": "تسجيل الهالك والتالف",
    "stocktake.manage": "إجراء الجرد",
    "stocktake.approve": "اعتماد تسويات الجرد",
    "stock.view": "عرض المخزون",
    "reports.view": "عرض التقارير",
    "users.manage": "إدارة المستخدمين والصلاحيات",
    "backup.manage": "النسخ الاحتياطي والاستعادة",
    "settings.manage": "إدارة الإعدادات",
    "audit.view": "عرض سجل المراجعة",
    "alerts.manage": "إدارة التنبيهات",
}

ROLE_ADMIN = "مدير النظام"
ROLE_KEEPER = "أمين المخزن"
ROLE_ISSUER = "مسؤول الصرف"

DEFAULT_ROLES = {
    ROLE_ADMIN: list(PERMISSIONS),
    ROLE_KEEPER: ["items.manage", "partners.manage", "incoming.create", "payments.manage",
                  "stock.view", "reports.view", "stocktake.manage", "returns.approve",
                  "damage.create", "alerts.manage"],
    ROLE_ISSUER: ["stock.view", "issue.create", "returns.create", "alerts.manage"],
}
