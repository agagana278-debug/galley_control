"""Production operations CLI for Galley Control (create-admin, seed-catalog)."""

from __future__ import annotations

import argparse
from sqlalchemy import select

from app.database import db_session, init_db
from app.models import Organisation, User
from app.seed_data import (
    ensure_roles_and_permissions,
    seed_catalog_base,
)
from app.services.auth_service import hash_password


def main() -> None:
    parser = argparse.ArgumentParser(description="Galley Control Operations CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    admin_cmd = sub.add_parser("create-admin", help="Create a Platform Admin account")
    admin_cmd.add_argument("--email", required=True)
    admin_cmd.add_argument("--username", required=True)
    admin_cmd.add_argument("--full-name", default="Platform Administrator")
    admin_cmd.add_argument("--password", required=True)

    cat_cmd = sub.add_parser("seed-catalog", help="Create/seed an active organisation catalog")
    cat_cmd.add_argument("--org-name", default="Main Campus Canteen Network")
    cat_cmd.add_argument("--org-slug", default="main-campus")
    cat_cmd.add_argument("--org-email", default="campus-ops@galley.edu")

    args = parser.parse_args()
    init_db()

    if args.command == "create-admin":
        with db_session() as db:
            role_map = ensure_roles_and_permissions(db)
            existing = db.execute(
                select(User).where(
                    (User.email == args.email.strip().lower())
                    | (User.username == args.username.strip().lower())
                )
            ).scalar_one_or_none()
            if existing:
                raise SystemExit(f"User already exists: {existing.email}")
            db.add(
                User(
                    organisation_id=None,
                    username=args.username.strip().lower(),
                    email=args.email.strip().lower(),
                    full_name=args.full_name.strip(),
                    password_hash=hash_password(args.password),
                    role="admin",
                    role_id=role_map.get("admin"),
                    outlet_id=None,
                    is_active=True,
                    manager_approval_status="APPROVED",
                )
            )
        print(f"Platform Admin created: {args.email.strip().lower()}")

    elif args.command == "seed-catalog":
        with db_session() as db:
            ensure_roles_and_permissions(db)
            org = db.execute(
                select(Organisation).where(Organisation.slug == args.org_slug.strip().lower())
            ).scalar_one_or_none()
            if not org:
                org = Organisation(
                    name=args.org_name.strip(),
                    slug=args.org_slug.strip().lower(),
                    campus_location="Campus",
                    contact_email=args.org_email.strip().lower(),
                    status="ACTIVE",
                )
                db.add(org)
                db.flush()
            org_id, outlet_ids = seed_catalog_base(db, organisation_id=org.id)
        print(f"Catalog ready for org_id={org_id} with outlets: {outlet_ids}")


if __name__ == "__main__":
    main()
