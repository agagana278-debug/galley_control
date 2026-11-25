"""Multi-tenant role/permission bootstrap, dev-only sample seeding, and safe production startup."""

from __future__ import annotations

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session

from app.config import settings
from app.database import DEFAULT_MENU_MEDIA, db_session
from app.models import (
    AgentActivityLog,
    AiConversation,
    AiMessage,
    AiRecommendation,
    AuditLog,
    InventoryMovement,
    MenuItem,
    Order,
    OrderItem,
    Organisation,
    Outlet,
    OutletPerformanceSnapshot,
    Permission,
    QrToken,
    Review,
    Role,
    RolePermission,
    SecurityEvent,
    User,
)
from app.services.auth_service import hash_password

ROLE_DEFINITIONS: dict[str, tuple[str, list[str]]] = {
    "student": (
        "Campus student ordering within their registered organisation.",
        [
            "catalog:read",
            "orders:create",
            "orders:read_own",
            "orders:cancel_own",
            "reviews:write",
            "ai:chat",
        ],
    ),
    "outlet_manager": (
        "Organisation/outlet manager supervising outlets and counters within their organisation.",
        [
            "catalog:read",
            "orders:manage_outlet",
            "qr:verify",
            "inventory:read",
            "inventory:write",
            "reviews:resolve",
            "recommendations:decide",
            "outlets:manage_org",
            "analytics:read_org",
            "ai:chat",
        ],
    ),
    "admin": (
        "Platform administrator with controlled cross-organisation approval and governance access.",
        [
            "catalog:read",
            "orders:create",
            "orders:read_own",
            "orders:cancel_own",
            "orders:manage_outlet",
            "qr:verify",
            "inventory:read",
            "inventory:write",
            "reviews:write",
            "reviews:resolve",
            "recommendations:decide",
            "analytics:read",
            "security:resolve",
            "outlets:manage",
            "users:manage",
            "organisations:manage",
            "ai:chat",
        ],
    ),
}

PERMISSION_DESCRIPTIONS = {
    "catalog:read": "Read organisation outlets and menu catalog",
    "orders:create": "Place meal orders and issue single-use QR passes",
    "orders:read_own": "View personal and friend-group order status",
    "orders:cancel_own": "Cancel uncollected personal orders",
    "orders:manage_outlet": "View and prepare orders for permitted outlets",
    "qr:verify": "Scan and verify single-use pickup QR passes",
    "inventory:read": "Read stock quantities and shortage alerts",
    "inventory:write": "Adjust menu item inventory quantities",
    "reviews:write": "Submit customer ratings and written feedback",
    "reviews:resolve": "Resolve customer feedback issues",
    "recommendations:decide": "Approve or dismiss AI operational recommendations",
    "analytics:read": "Access platform-wide or scoped analytics",
    "analytics:read_org": "Access organisation-level analytics and summaries",
    "security:resolve": "Resolve flagged QR and transaction security incidents",
    "outlets:manage": "Configure outlets across platform",
    "outlets:manage_org": "Create and configure outlets within own organisation",
    "users:manage": "Approve/create outlet managers and manage user accounts",
    "organisations:manage": "Approve, suspend, or reject campus organisations",
    "ai:chat": "Converse with the Central Orchestrator AI assistant",
}

OUTLETS = [
    ("Main Atrium Galley", "Academic Block A", "OPEN", 7.5, 4),
    ("Tech Block Cafe", "CSE & Innovation Wing", "OPEN", 5.0, 3),
    ("Hostel Night Canteen", "Student Residence Quad", "OPEN", 9.0, 2),
]

MENU_ITEMS = [
    (0, "Masala Dosa", "South Indian", 55.0, 24, 6, True),
    (0, "Idli Vada Combo", "South Indian", 40.0, 30, 3, True),
    (0, "Paneer Roll", "Quick Bites", 75.0, 14, 7, True),
    (0, "Veg Fried Rice", "Meals", 85.0, 0, 9, True),
    (0, "Veg Hakka Noodles", "Meals", 80.0, 18, 8, True),
    (1, "Cold Coffee", "Beverages", 50.0, 28, 3, True),
    (1, "Grilled Cheese Sandwich", "Quick Bites", 65.0, 16, 5, True),
    (1, "Chicken Tikka Wrap", "Quick Bites", 110.0, 10, 8, False),
    (1, "Fresh Lime Soda", "Beverages", 30.0, 35, 2, True),
    (2, "Egg Fried Rice", "Meals", 95.0, 15, 9, False),
    (2, "Maggi Masala Bowl", "Quick Bites", 45.0, 25, 4, True),
    (2, "Ginger Chai", "Beverages", 20.0, 40, 2, True),
]

SAMPLE_REVIEWS = [
    (1, "Aarav (Sample)", 2, "Waited 22 minutes during the 11:00 AM break at Main Atrium.", "NEGATIVE", "Waiting Time", False),
    (1, "Meera (Sample)", 2, "Break ended before my dosa order was ready—queue was jammed.", "NEGATIVE", "Waiting Time", False),
    (2, "Rohan (Sample)", 5, "Cold Coffee and Sandwich came out super quick in 4 minutes.", "POSITIVE", "Service", True),
    (3, "Diya (Sample)", 4, "Good taste and hot Maggi, seating area could be cleaner.", "NEUTRAL", "Hygiene", False),
]

DEMO_USERS = [
    ("student", "student@galley.edu", "Ananya Sharma", "Student@123", "student", 0),
    ("manager", "manager@galley.edu", "Rohan Verma", "Manager@123", "outlet_manager", 0),
    ("manager2", "manager2@galley.edu", "Siddharth Rao", "Manager@123", "outlet_manager", 1),
    ("admin", "admin@galley.edu", "Dr. Kavita Nair", "Admin@123", "admin", None),
]


def ensure_roles_and_permissions(db: Session) -> dict[str, int]:
    """Idempotently populate RBAC roles and permissions (safe in all environments)."""
    perm_map: dict[str, int] = {}
    for code, desc in PERMISSION_DESCRIPTIONS.items():
        perm = db.execute(select(Permission).where(Permission.code == code)).scalar_one_or_none()
        if not perm:
            perm = Permission(code=code, description=desc)
            db.add(perm)
            db.flush()
        perm_map[code] = perm.id

    role_map: dict[str, int] = {}
    for role_name, (desc, perm_codes) in ROLE_DEFINITIONS.items():
        role = db.execute(select(Role).where(Role.name == role_name)).scalar_one_or_none()
        if not role:
            role = Role(name=role_name, description=desc)
            db.add(role)
            db.flush()
        role_map[role_name] = role.id

        existing_perm_ids = set(
            db.execute(
                select(RolePermission.permission_id).where(RolePermission.role_id == role.id)
            ).scalars().all()
        )
        for pcode in perm_codes:
            pid = perm_map[pcode]
            if pid not in existing_perm_ids:
                db.add(RolePermission(role_id=role.id, permission_id=pid))

    db.flush()
    for role_name, role_id in role_map.items():
        db.execute(
            update(User)
            .where(User.role == role_name, User.role_id.is_(None))
            .values(role_id=role_id)
        )
    db.flush()
    return role_map


def ensure_bootstrap_admin(db: Session, role_map: dict[str, int]) -> None:
    """Create initial platform admin only if zero admins exist and bootstrap env vars are provided."""
    if not settings.bootstrap_admin_email or not settings.bootstrap_admin_password:
        return
    admin_count = db.execute(
        select(func.count(User.id)).where(User.role == "admin")
    ).scalar_one()
    if admin_count > 0:
        return

    email = settings.bootstrap_admin_email.lower()
    username = email.split("@", 1)[0][:32]
    db.add(
        User(
            organisation_id=None,
            username=username,
            email=email,
            full_name=settings.bootstrap_admin_name or "Platform Administrator",
            password_hash=hash_password(settings.bootstrap_admin_password),
            role="admin",
            role_id=role_map.get("admin"),
            outlet_id=None,
            is_active=True,
            manager_approval_status="APPROVED",
        )
    )
    db.flush()


def ensure_default_organisation(db: Session) -> Organisation:
    """Return existing primary organisation or create the default university tenant."""
    org = db.execute(select(Organisation).order_by(Organisation.id)).scalars().first()
    if org:
        return org
    org = Organisation(
        name="Main Campus Canteen Network",
        slug="main-campus",
        campus_location="Central University Campus",
        contact_email="campus-ops@galley.edu",
        status="ACTIVE",
    )
    db.add(org)
    db.flush()
    return org


def seed_catalog_base(db: Session, organisation_id: int | None = None) -> tuple[int, list[int]]:
    """Ensure outlets and menu catalog exist for the target organisation when empty."""
    if organisation_id is None:
        org = ensure_default_organisation(db)
        organisation_id = org.id

    existing_outlets = db.execute(
        select(Outlet).where(Outlet.organisation_id == organisation_id).order_by(Outlet.id)
    ).scalars().all()
    if existing_outlets:
        return organisation_id, [o.id for o in existing_outlets]

    outlet_ids: list[int] = []
    for name, loc, status, avg_prep, staff in OUTLETS:
        o = Outlet(
            organisation_id=organisation_id,
            name=name,
            location=loc,
            status=status,
            avg_prep_minutes=avg_prep,
            active_staff=staff,
        )
        db.add(o)
        db.flush()
        outlet_ids.append(o.id)

    items_by_name: dict[str, MenuItem] = {}
    for outlet_idx, name, cat, price, stock, prep, veg in MENU_ITEMS:
        desc, img = DEFAULT_MENU_MEDIA.get(name, ("", None))
        mi = MenuItem(
            organisation_id=organisation_id,
            outlet_id=outlet_ids[outlet_idx],
            name=name,
            description=desc,
            image_url=img,
            category=cat,
            price=price,
            stock_qty=stock,
            prep_minutes=prep,
            is_veg=veg,
            is_available=True,
        )
        db.add(mi)
        db.flush()
        items_by_name[name] = mi

    fried_rice = items_by_name["Veg Fried Rice"]
    noodles = items_by_name["Veg Hakka Noodles"]
    fried_rice.substitute_item_id = noodles.id
    db.flush()
    return organisation_id, outlet_ids


def seed_users(
    db: Session,
    role_map: dict[str, int] | None = None,
    default_org_id: int | None = None,
) -> None:
    """Seed development demo accounts only when effective_demo_mode is True."""
    if not settings.effective_demo_mode:
        return
    if role_map is None:
        role_map = ensure_roles_and_permissions(db)
    if default_org_id is None:
        default_org_id = ensure_default_organisation(db).id

    outlet_ids = list(
        db.execute(
            select(Outlet.id)
            .where(Outlet.organisation_id == default_org_id)
            .order_by(Outlet.id)
        ).scalars().all()
    )

    for username, email, full_name, plain_pw, role, outlet_idx in DEMO_USERS:
        org_for_user = None if role == "admin" else default_org_id
        assigned_outlet = (
            outlet_ids[outlet_idx]
            if role == "outlet_manager" and outlet_idx is not None and outlet_idx < len(outlet_ids)
            else None
        )
        existing = db.execute(
            select(User).where((User.username == username) | (User.email == email))
        ).scalar_one_or_none()
        if existing:
            if existing.role_id is None:
                existing.role_id = role_map.get(role)
            if role != "admin" and existing.organisation_id is None:
                existing.organisation_id = org_for_user
            if role == "outlet_manager" and existing.outlet_id is None and assigned_outlet is not None:
                existing.outlet_id = assigned_outlet
            continue

        db.add(
            User(
                organisation_id=org_for_user,
                username=username,
                email=email,
                full_name=full_name,
                password_hash=hash_password(plain_pw),
                role=role,
                role_id=role_map.get(role),
                outlet_id=assigned_outlet,
                is_active=True,
                manager_approval_status="APPROVED",
            )
        )
    db.flush()


def seed_database(db: Session) -> None:
    """Run startup database bootstrapping cleanly separated by APP_ENV."""
    role_map = ensure_roles_and_permissions(db)
    ensure_bootstrap_admin(db, role_map)

    if not settings.effective_demo_mode:
        return

    existing_outlets = db.execute(select(func.count(Outlet.id))).scalar_one()
    if existing_outlets > 0:
        default_org = ensure_default_organisation(db)
        seed_users(db, role_map, default_org.id)
        return

    default_org_id, outlet_ids = seed_catalog_base(db)

    sample_orders = [
        ("SMP-1001", outlet_ids[0], "Sample Student 1", "09:00", 95.0, "PAID", "COLLECTED", 6),
        ("SMP-1002", outlet_ids[0], "Sample Student 2", "11:00", 130.0, "PAID", "COLLECTED", 14),
        ("SMP-1003", outlet_ids[0], "Sample Student 3", "11:00", 110.0, "PAID", "COLLECTED", 15),
        ("SMP-1004", outlet_ids[1], "Sample Student 4", "13:00", 115.0, "PAID", "COLLECTED", 5),
        ("SMP-1005", outlet_ids[1], "Sample Student 5", "13:00", 160.0, "PAID", "COLLECTED", 6),
        ("SMP-1006", outlet_ids[2], "Sample Student 6", "19:00", 115.0, "PAID", "COLLECTED", 8),
    ]
    for code, oid, sname, slot, amt, pay_st, ord_st, wait_m in sample_orders:
        db.add(
            Order(
                organisation_id=default_org_id,
                order_code=code,
                outlet_id=oid,
                student_name=sname,
                scheduled_slot=slot,
                total_amount=amt,
                payment_status=pay_st,
                order_status=ord_st,
                estimated_wait_minutes=wait_m,
                is_sample=True,
            )
        )

    for outlet_idx_1, sname, rating, comment, sent, cat, resolved in SAMPLE_REVIEWS:
        db.add(
            Review(
                organisation_id=default_org_id,
                outlet_id=outlet_ids[outlet_idx_1 - 1],
                student_name=sname,
                rating=rating,
                comment=comment,
                sentiment=sent,
                category=cat,
                is_resolved=resolved,
                is_sample=True,
            )
        )

    db.add(
        AiRecommendation(
            organisation_id=default_org_id,
            source_agent="Outlet Performance + Queue Agent",
            outlet_id=outlet_ids[0],
            title="Batch Masala Dosa orders during 11:00 AM break",
            rationale="Sample feedback shows recurring waiting-time complaints during 11:00 AM break at Main Atrium Galley.",
            status="PENDING_APPROVAL",
            is_sample=True,
        )
    )
    db.flush()
    seed_users(db, role_map, default_org_id)


def reset_database(db_path: str | None = None) -> None:
    """Development-only demo reset preserving registered users and active sessions."""
    if settings.is_production or not settings.effective_demo_mode:
        raise RuntimeError("Demo reset is permanently disabled in production mode.")

    with db_session(db_path) as db:
        db.execute(update(User).values(outlet_id=None, organisation_id=None))
        db.execute(update(Order).values(user_id=None))
        db.execute(update(MenuItem).values(substitute_item_id=None))
        for model in (
            AuditLog,
            AgentActivityLog,
            AiMessage,
            AiConversation,
            OutletPerformanceSnapshot,
            InventoryMovement,
            AiRecommendation,
            Review,
            SecurityEvent,
            QrToken,
            OrderItem,
            Order,
            MenuItem,
            Outlet,
            Organisation,
        ):
            db.execute(delete(model))

        dialect = db.bind.dialect.name if db.bind else ""
        if dialect == "sqlite":
            seq_exists = db.execute(
                text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'")
            ).first()
            if seq_exists:
                db.execute(
                    text(
                        "DELETE FROM sqlite_sequence WHERE name NOT IN ('users', 'user_sessions', 'roles', 'permissions', 'password_reset_tokens')"
                    )
                )
        elif dialect == "postgresql":
            for tbl in (
                "organisations",
                "outlets",
                "menu_items",
                "orders",
                "order_items",
                "qr_tokens",
                "reviews",
                "security_events",
                "ai_recommendations",
            ):
                db.execute(text(f"ALTER SEQUENCE {tbl}_id_seq RESTART WITH 1"))
        db.flush()
        seed_database(db)
