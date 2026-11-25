"""Comprehensive multi-tenant onboarding, governance, and strict tenant isolation tests."""

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.agents import orchestrator
from app.config import settings
from app.database import db_session, init_db
from app.main import app
from app.seed_data import reset_database
from app.services import llm_client


def _setup(tmp_path, monkeypatch):
    test_db = str(tmp_path / "multi_tenant_test.db")
    monkeypatch.setattr(settings, "database_path", test_db)
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "enable_demo_features", True)
    monkeypatch.setattr(settings, "llm_api_key", "")
    init_db(test_db)
    reset_database(test_db)
    return test_db, TestClient(app)


def _login(client: TestClient, identifier: str, password: str) -> str:
    res = client.post("/api/auth/login", json={"identifier": identifier, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_legacy_single_tenant_data_backfill_preserves_rows(tmp_path, monkeypatch):
    import sqlite3

    legacy_db = str(tmp_path / "pre_multitenant.db")
    monkeypatch.setattr(settings, "database_path", legacy_db)

    conn_raw = sqlite3.connect(legacy_db)
    conn_raw.executescript(
        """
        CREATE TABLE outlets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            location TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'OPEN',
            avg_prep_minutes REAL NOT NULL DEFAULT 8.0,
            active_staff INTEGER NOT NULL DEFAULT 3,
            created_at TEXT
        );
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            full_name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            role_id INTEGER,
            outlet_id INTEGER,
            is_active INTEGER NOT NULL DEFAULT 1,
            manager_approval_status TEXT NOT NULL DEFAULT 'APPROVED',
            created_at TEXT
        );
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_code TEXT NOT NULL UNIQUE,
            outlet_id INTEGER NOT NULL,
            user_id INTEGER,
            student_name TEXT NOT NULL,
            total_amount REAL NOT NULL,
            payment_status TEXT NOT NULL DEFAULT 'PAID',
            order_status TEXT NOT NULL DEFAULT 'PLACED',
            estimated_wait_minutes INTEGER NOT NULL DEFAULT 8,
            is_sample INTEGER NOT NULL DEFAULT 0,
            created_at TEXT
        );
        CREATE TABLE reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            outlet_id INTEGER NOT NULL,
            order_id INTEGER,
            user_id INTEGER,
            student_name TEXT NOT NULL,
            rating INTEGER NOT NULL,
            comment TEXT NOT NULL,
            sentiment TEXT NOT NULL,
            category TEXT NOT NULL,
            is_resolved INTEGER NOT NULL DEFAULT 0,
            is_sample INTEGER NOT NULL DEFAULT 0,
            created_at TEXT
        );
        INSERT INTO outlets (id, name, location) VALUES (1, 'Legacy Cafe', 'Old Quad');
        INSERT INTO users (id, username, email, full_name, password_hash, role) VALUES
            (1, 'admin', 'admin@legacy.edu', 'Legacy Admin', 'x', 'admin'),
            (2, 'stu1', 'stu1@legacy.edu', 'Legacy Student', 'x', 'student');
        INSERT INTO orders (id, order_code, outlet_id, user_id, student_name, total_amount)
            VALUES (1, 'GC-OLD-01', 1, 2, 'Legacy Student', 120.0);
        INSERT INTO reviews (id, outlet_id, order_id, user_id, student_name, rating, comment, sentiment, category)
            VALUES (1, 1, 1, 2, 'Legacy Student', 5, 'Great!', 'POSITIVE', 'Quality');
        """
    )
    conn_raw.commit()
    conn_raw.close()

    init_db(legacy_db)

    with db_session(legacy_db) as conn:
        orgs = conn.execute(text("SELECT id, slug, status FROM organisations")).fetchall()
        after_orders = conn.execute(text("SELECT COUNT(*), COUNT(organisation_id) FROM orders")).fetchone()
        after_outlets = conn.execute(text("SELECT COUNT(*), COUNT(organisation_id) FROM outlets")).fetchone()
        after_reviews = conn.execute(text("SELECT COUNT(*), COUNT(organisation_id) FROM reviews")).fetchone()
        admin_org = conn.execute(
            text("SELECT organisation_id FROM users WHERE role = 'admin' LIMIT 1")
        ).scalar_one()
        stu_org = conn.execute(
            text("SELECT organisation_id FROM users WHERE role = 'student' LIMIT 1")
        ).scalar_one()

    assert len(orgs) == 1
    assert orgs[0][1] == "main-campus"
    assert orgs[0][2] == "ACTIVE"
    assert after_orders == (1, 1)
    assert after_outlets == (1, 1)
    assert after_reviews == (1, 1)
    assert admin_org is None
    assert stu_org == orgs[0][0]


def test_org_onboarding_approval_suspension_and_strict_cross_tenant_isolation(tmp_path, monkeypatch):
    _test_db, client = _setup(tmp_path, monkeypatch)

    with client:
        # 1. Public directory initially shows only active Org 1
        pub1 = client.get("/api/organisations/public")
        assert pub1.status_code == 200
        assert [o["slug"] for o in pub1.json()["organisations"]] == ["main-campus"]
        org_a_id = pub1.json()["organisations"][0]["id"]

        # 2. Register Org B (Riverside Tech) + initial Org Manager -> PENDING_APPROVAL
        reg_org = client.post(
            "/api/organisations/register",
            json={
                "org_name": "Riverside Institute of Technology",
                "org_slug": "riverside-tech",
                "campus_location": "Riverside North Campus",
                "contact_email": "canteen@riverside.edu",
                "manager_full_name": "Rohan Kapoor",
                "manager_username": "rohan_riverside",
                "manager_email": "rohan@riverside.edu",
                "password": "Riverside@2026!",
                "confirm_password": "Riverside@2026!",
            },
        )
        assert reg_org.status_code == 201, reg_org.text
        org_b_id = reg_org.json()["organisation"]["id"]
        assert reg_org.json()["organisation"]["status"] == "PENDING_APPROVAL"
        assert org_b_id != org_a_id

        # Pending org must NOT appear in active public list or allow login or student signup
        pub_pending = client.get("/api/organisations/public")
        assert all(o["id"] != org_b_id for o in pub_pending.json()["organisations"])

        pending_login = client.post(
            "/api/auth/login",
            json={"identifier": "rohan@riverside.edu", "password": "Riverside@2026!"},
        )
        assert pending_login.status_code == 403

        pending_stu = client.post(
            "/api/auth/register",
            json={
                "full_name": "Meera Nair",
                "username": "meera_riverside",
                "email": "meera@riverside.edu",
                "password": "Meera@2026!",
                "confirm_password": "Meera@2026!",
                "organisation_id": org_b_id,
            },
        )
        assert pending_stu.status_code in (400, 403)

        # 3. Non-admin cannot access platform admin org controls
        stu_a_tok = _login(client, "student@galley.edu", "Student@123")
        mgr_a_tok = _login(client, "manager@galley.edu", "Manager@123")
        assert client.get("/api/admin/organisations", headers=_headers(stu_a_tok)).status_code == 403
        assert client.get("/api/admin/organisations", headers=_headers(mgr_a_tok)).status_code == 403
        assert (
            client.patch(
                f"/api/admin/organisations/{org_b_id}",
                headers=_headers(mgr_a_tok),
                json={"status": "ACTIVE"},
            ).status_code
            == 403
        )

        # 4. Platform Admin reviews and approves Org B
        admin_tok = _login(client, "admin@galley.edu", "Admin@123")
        adm_orgs = client.get("/api/admin/organisations", headers=_headers(admin_tok))
        assert adm_orgs.status_code == 200
        assert any(o["id"] == org_b_id and o["status"] == "PENDING_APPROVAL" for o in adm_orgs.json()["organisations"])

        approve_res = client.patch(
            f"/api/admin/organisations/{org_b_id}",
            headers=_headers(admin_tok),
            json={"status": "ACTIVE"},
        )
        assert approve_res.status_code == 200
        assert approve_res.json()["organisation"]["status"] == "ACTIVE"

        pub_active = client.get("/api/organisations/public")
        assert {o["slug"] for o in pub_active.json()["organisations"]} == {"main-campus", "riverside-tech"}

        # 5. Org B Manager logs in -> empty outlets initially, creates 2 outlets + unique menu items + outlet manager
        org_b_mgr_tok = _login(client, "rohan@riverside.edu", "Riverside@2026!")
        me_b = client.get("/api/auth/me", headers=_headers(org_b_mgr_tok)).json()["user"]
        assert me_b["organisation_id"] == org_b_id
        assert me_b["is_org_manager"] is True
        assert me_b["outlet_id"] is None

        empty_dash = client.get("/api/dashboard/outlet", headers=_headers(org_b_mgr_tok))
        assert empty_dash.status_code == 200
        assert empty_dash.json()["outlet"] is None
        assert empty_dash.json()["available_outlets"] == []

        out_b1_res = client.post(
            "/api/dashboard/outlets",
            headers=_headers(org_b_mgr_tok),
            json={"name": "Riverside North Cafe", "location": "Academic Block A", "avg_prep_minutes": 7.0, "active_staff": 4},
        )
        assert out_b1_res.status_code == 201
        out_b1_id = out_b1_res.json()["outlet"]["id"]

        out_b2_res = client.post(
            "/api/dashboard/outlets",
            headers=_headers(org_b_mgr_tok),
            json={"name": "Riverside Library Espresso", "location": "Central Library", "avg_prep_minutes": 4.0, "active_staff": 2},
        )
        assert out_b2_res.status_code == 201
        out_b2_id = out_b2_res.json()["outlet"]["id"]

        item_b1_res = client.post(
            "/api/dashboard/outlet/menu",
            headers=_headers(org_b_mgr_tok),
            json={
                "outlet_id": out_b1_id,
                "name": "Truffle Pasta",
                "category": "Gourmet Meals",
                "price": 180.0,
                "stock_qty": 15,
                "prep_minutes": 8,
                "is_veg": True,
            },
        )
        assert item_b1_res.status_code == 201
        item_b1_id = item_b1_res.json()["menu_item"]["id"]

        item_b2_res = client.post(
            "/api/dashboard/outlet/menu",
            headers=_headers(org_b_mgr_tok),
            json={
                "outlet_id": out_b2_id,
                "name": "Matcha Oat Latte",
                "category": "Beverages",
                "price": 110.0,
                "stock_qty": 20,
                "prep_minutes": 3,
                "is_veg": True,
            },
        )
        assert item_b2_res.status_code == 201

        # Org B Manager creates outlet-assigned manager for Riverside North Cafe ONLY
        sub_mgr_res = client.post(
            "/api/dashboard/org/managers",
            headers=_headers(org_b_mgr_tok),
            json={
                "full_name": "Kavita Rao",
                "username": "kavita_north",
                "email": "kavita@riverside.edu",
                "password": "Kavita@2026!",
                "outlet_id": out_b1_id,
            },
        )
        assert sub_mgr_res.status_code == 201
        sub_mgr_tok = _login(client, "kavita_north", "Kavita@2026!")

        # Outlet-assigned manager is restricted to out_b1_id within Org B
        assert client.get(f"/api/dashboard/outlet?outlet_id={out_b2_id}", headers=_headers(sub_mgr_tok)).status_code == 403
        assert client.get("/api/dashboard/org-summary", headers=_headers(sub_mgr_tok)).status_code == 403
        assert (
            client.post(
                "/api/dashboard/outlets",
                headers=_headers(sub_mgr_tok),
                json={"name": "Unauthorized Outlet", "location": "Block X"},
            ).status_code
            == 403
        )

        # Org B Manager can switch both Org B outlets and inspect org-summary
        org_b_summary = client.get("/api/dashboard/org-summary", headers=_headers(org_b_mgr_tok))
        assert org_b_summary.status_code == 200
        assert {
            o["outlet_id"] for o in org_b_summary.json()["outlet_performance"]["outlets"]
        } == {out_b1_id, out_b2_id}

        # 6. Register Student B in Org B via public registration
        reg_stu_b = client.post(
            "/api/auth/register",
            json={
                "full_name": "Meera Nair",
                "username": "meera_riverside",
                "email": "meera@riverside.edu",
                "password": "Meera@2026!",
                "confirm_password": "Meera@2026!",
                "organisation_id": org_b_id,
            },
        )
        assert reg_stu_b.status_code == 201, reg_stu_b.text
        stu_b_tok = _login(client, "meera@riverside.edu", "Meera@2026!")

        # 7. Checkout orders in both orgs with identical group_code 'GRP-SHARED'
        cat_a = client.get("/api/catalog/overview", headers=_headers(stu_a_tok)).json()
        assert cat_a["organisation_id"] == org_a_id
        assert all(o["organisation_id"] == org_a_id for o in cat_a["outlets"])
        assert all(i["name"] != "Truffle Pasta" for i in cat_a["menu_items"])
        item_a1 = next(i for i in cat_a["menu_items"] if i["outlet_id"] == 1 and i["stock_qty"] > 0)

        cat_b = client.get("/api/catalog/overview", headers=_headers(stu_b_tok)).json()
        assert cat_b["organisation_id"] == org_b_id
        assert {o["id"] for o in cat_b["outlets"]} == {out_b1_id, out_b2_id}
        assert all(i["name"] != item_a1["name"] for i in cat_b["menu_items"])

        order_a = client.post(
            "/api/orders/checkout",
            headers=_headers(stu_a_tok),
            json={
                "outlet_id": 1,
                "student_name": "Ananya Sharma",
                "group_code": "GRP-SHARED",
                "items": [{"menu_item_id": item_a1["id"], "quantity": 1}],
                "simulate_payment_success": True,
            },
        )
        assert order_a.status_code == 200, order_a.text
        ord_a_id = order_a.json()["order_id"]
        ord_a_qr = order_a.json()["qr_token"]

        order_b = client.post(
            "/api/orders/checkout",
            headers=_headers(stu_b_tok),
            json={
                "outlet_id": out_b1_id,
                "student_name": "Meera Nair",
                "group_code": "GRP-SHARED",
                "items": [{"menu_item_id": item_b1_id, "quantity": 1}],
                "simulate_payment_success": True,
            },
        )
        assert order_b.status_code == 200, order_b.text
        ord_b_id = order_b.json()["order_id"]
        ord_b_qr = order_b.json()["qr_token"]

        # Create complaint review in Org A & Org B (2 recurring in Org B triggers AI recommendation)
        rev_a = client.post(
            "/api/reviews",
            headers=_headers(stu_a_tok),
            json={
                "outlet_id": 1,
                "order_id": ord_a_id,
                "student_name": "Ananya Sharma",
                "rating": 2,
                "comment": "Main atrium queue took long today.",
            },
        ).json()
        client.post(
            "/api/reviews",
            headers=_headers(stu_b_tok),
            json={
                "outlet_id": out_b1_id,
                "order_id": ord_b_id,
                "student_name": "Meera Nair",
                "rating": 1,
                "comment": "Cold truffle pasta food quality delay at Riverside.",
            },
        )
        rev_b = client.post(
            "/api/reviews",
            headers=_headers(stu_b_tok),
            json={
                "outlet_id": out_b1_id,
                "order_id": ord_b_id,
                "student_name": "Meera Nair",
                "rating": 1,
                "comment": "Cold stale pasta taste quality problem again.",
            },
        ).json()

        dash_a_recs = client.get("/api/dashboard/outlet?outlet_id=1", headers=_headers(mgr_a_tok)).json()["recommendations"]
        dash_b_recs = client.get(f"/api/dashboard/outlet?outlet_id={out_b1_id}", headers=_headers(org_b_mgr_tok)).json()["recommendations"]
        rec_a_id = dash_a_recs[0]["id"]
        rec_b_id = dash_b_recs[0]["id"]

        # ==================== STRICT CROSS-TENANT ISOLATION PROOFS ====================
        # A. Direct client-supplied organisation_id probing rejected with 403
        assert client.get(f"/api/catalog/overview?organisation_id={org_b_id}", headers=_headers(stu_a_tok)).status_code == 403
        assert client.get(f"/api/orders?organisation_id={org_b_id}", headers=_headers(stu_a_tok)).status_code == 403
        assert client.get(f"/api/reviews?organisation_id={org_b_id}", headers=_headers(stu_a_tok)).status_code == 403
        assert client.get(f"/api/dashboard/org-summary?organisation_id={org_a_id}", headers=_headers(org_b_mgr_tok)).status_code == 403
        assert client.get(f"/api/qr/security-events?organisation_id={org_a_id}", headers=_headers(org_b_mgr_tok)).status_code == 403

        # B. Cross-tenant checkout, group order, cancellation, and reviews blocked
        assert (
            client.post(
                "/api/orders/checkout",
                headers=_headers(stu_a_tok),
                json={
                    "outlet_id": out_b1_id,
                    "student_name": "Ananya",
                    "items": [{"menu_item_id": item_b1_id, "quantity": 1}],
                },
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/orders/checkout",
                headers=_headers(stu_a_tok),
                json={
                    "outlet_id": 1,
                    "student_name": "Ananya",
                    "items": [{"menu_item_id": item_b1_id, "quantity": 1}],
                },
            ).status_code
            in (400, 403)
        )

        grp_a = client.get("/api/orders/group/GRP-SHARED", headers=_headers(stu_a_tok)).json()
        assert grp_a["member_count"] == 1
        assert grp_a["orders"][0]["id"] == ord_a_id
        assert grp_a["orders"][0]["organisation_id"] == org_a_id

        grp_b = client.get("/api/orders/group/GRP-SHARED", headers=_headers(stu_b_tok)).json()
        assert grp_b["member_count"] == 1
        assert grp_b["orders"][0]["id"] == ord_b_id
        assert grp_b["orders"][0]["organisation_id"] == org_b_id

        assert (
            client.post(
                f"/api/orders/{ord_b_id}/cancel",
                headers=_headers(stu_a_tok),
                json={"reason": "Cross-org probe"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"/api/orders/{ord_a_id}/cancel",
                headers=_headers(stu_b_tok),
                json={"reason": "Cross-org probe"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/reviews",
                headers=_headers(stu_a_tok),
                json={"outlet_id": out_b1_id, "student_name": "X", "rating": 5, "comment": "Cross org"},
            ).status_code
            == 403
        )

        # C. Cross-tenant Manager endpoints (dashboard, outlet config, menu, stock, prepare, QR, review, recs, org managers)
        assert client.get("/api/dashboard/outlet?outlet_id=1", headers=_headers(org_b_mgr_tok)).status_code == 403
        assert client.get(f"/api/dashboard/outlet?outlet_id={out_b1_id}", headers=_headers(mgr_a_tok)).status_code == 403
        assert client.patch(f"/api/dashboard/outlets/1", headers=_headers(org_b_mgr_tok), json={"status": "CLOSED"}).status_code == 403
        assert (
            client.post(
                "/api/dashboard/outlet/menu",
                headers=_headers(org_b_mgr_tok),
                json={"outlet_id": 1, "name": "Hack Item", "category": "Snacks", "price": 10.0},
            ).status_code
            == 403
        )
        assert (
            client.patch(
                f"/api/dashboard/outlet/menu/{item_a1['id']}/stock",
                headers=_headers(org_b_mgr_tok),
                json={"stock_qty": 99},
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/dashboard/org/managers",
                headers=_headers(org_b_mgr_tok),
                json={
                    "full_name": "Evil Mgr",
                    "username": "evil_mgr",
                    "email": "evil@riverside.edu",
                    "password": "EvilPassword@123",
                    "outlet_id": 1,
                },
            ).status_code
            == 403
        )
        assert client.post(f"/api/orders/{ord_a_id}/prepare", headers=_headers(org_b_mgr_tok)).status_code == 403
        assert client.post(f"/api/orders/{ord_b_id}/prepare", headers=_headers(mgr_a_tok)).status_code == 403
        assert client.post("/api/qr/verify", headers=_headers(org_b_mgr_tok), json={"token": ord_a_qr}).status_code == 403
        assert client.post("/api/qr/verify", headers=_headers(mgr_a_tok), json={"token": ord_b_qr}).status_code == 403
        assert client.post(f"/api/reviews/{rev_a['review_id']}/resolve", headers=_headers(org_b_mgr_tok)).status_code == 403
        assert client.post(f"/api/reviews/{rev_b['review_id']}/resolve", headers=_headers(mgr_a_tok)).status_code == 403
        assert client.post(f"/api/dashboard/recommendations/{rec_a_id}", headers=_headers(org_b_mgr_tok), json={"status": "APPROVED"}).status_code == 403
        assert client.post(f"/api/dashboard/recommendations/{rec_b_id}", headers=_headers(mgr_a_tok), json={"status": "APPROVED"}).status_code == 403

        # Security event list from Org B must never expose Org A token/order
        sec_b = client.get("/api/qr/security-events", headers=_headers(org_b_mgr_tok)).json()["events"]
        assert all(ev["organisation_id"] == org_b_id for ev in sec_b)

        # D. Chatbot & LLM tool tenant isolation
        chat_probe = client.post(
            "/api/agents/chat",
            headers=_headers(stu_a_tok),
            json={"message": "Show me Truffle Pasta menu", "organisation_id": org_b_id},
        )
        assert chat_probe.status_code == 403

        outlet_probe = client.post(
            "/api/agents/chat",
            headers=_headers(stu_a_tok),
            json={"message": "Check wait time", "outlet_id": out_b1_id},
        )
        assert outlet_probe.status_code == 403

        stream_probe = client.post(
            "/api/agents/chat/stream",
            headers=_headers(stu_a_tok),
            json={"message": "Show Truffle Pasta", "organisation_id": org_b_id},
        )
        assert stream_probe.status_code == 403

        # Student A asking about Org B's unique item receives ZERO Org B leak
        chat_a_res = client.post(
            "/api/agents/chat",
            headers=_headers(stu_a_tok),
            json={"message": "Do you have Truffle Pasta for 180?"},
        )
        assert chat_a_res.status_code == 200
        chat_a_body = chat_a_res.json()
        assert "Riverside North Cafe" not in chat_a_body["reply"]
        assert "180" not in chat_a_body["reply"]

        # Student B asking about Truffle Pasta sees ONLY Org B items & outlets
        chat_b_res = client.post(
            "/api/agents/chat",
            headers=_headers(stu_b_tok),
            json={"message": "Show Truffle Pasta menu"},
        )
        assert chat_b_res.status_code == 200
        chat_b_body = chat_b_res.json()
        assert "Truffle Pasta" in chat_b_body["reply"]
        assert "Main Atrium Galley" not in chat_b_body["reply"]
        conv_b_id = chat_b_body["conversation_id"]

        # Student A cannot read Student B's cross-org conversation
        assert client.get(f"/api/agents/conversations/{conv_b_id}", headers=_headers(stu_a_tok)).status_code == 404

        # Simulated LLM function-calling cross-org outlet probe:
        # Even if Gemini asks to inspect Org B's outlet_id inside Org A's chat session,
        # the backend tool executor MUST block and leak zero Org B rows.
        captured_tool_results = []

        def fake_chat_with_tools_and_history(
            *,
            system_prompt,
            history,
            user_message,
            tools,
            tool_executor,
            max_tokens=550,
        ):
            res_menu = tool_executor("search_menu_and_outlets", {"query": "Truffle Pasta"})
            res_cross_menu = tool_executor("search_menu_and_outlets", {"query": "", "outlet_id": out_b1_id})
            res_orders = tool_executor("lookup_outlet_orders", {"outlet_id": out_b1_id})
            captured_tool_results.append((res_menu, res_cross_menu, res_orders))
            return {
                "ok": True,
                "text": "Checked only Main Campus Canteen Network safely.",
                "tools_used": ["search_menu_and_outlets", "lookup_outlet_orders"],
                "provider": "gemini",
                "model": "gemini-2.5-flash",
            }

        monkeypatch.setattr(settings, "llm_api_key", "test-fake-key")
        monkeypatch.setattr(orchestrator, "chat_with_tools_and_history", fake_chat_with_tools_and_history)
        monkeypatch.setattr(llm_client, "chat_with_tools_and_history", fake_chat_with_tools_and_history)

        llm_probe = client.post(
            "/api/agents/chat",
            headers=_headers(mgr_a_tok),
            json={"message": "Show live orders for Riverside Cafe"},
        )
        assert llm_probe.status_code == 200
        assert len(captured_tool_results) == 1
        menu_tool_out, cross_menu_out, orders_tool_out = captured_tool_results[0]
        assert all("Truffle Pasta" != i["name"] for i in menu_tool_out["available_items"])
        assert all("Riverside" not in i["outlet_name"] for i in menu_tool_out["available_items"])
        assert "error" in cross_menu_out
        assert orders_tool_out["organisation_id"] == org_a_id
        assert orders_tool_out["outlet_id"] == 1
        assert all(
            o["outlet_name"] == "Main Atrium Galley" and "Riverside" not in o["outlet_name"]
            for o in orders_tool_out["orders"]
        )

        # Also prove an Org Manager (outlet_id=None) probing another org's outlet via LLM tool gets blocked cleanly
        org_b_captured = []

        def fake_org_b_chat(*, system_prompt, history, user_message, tools, tool_executor, max_tokens=550):
            res_cross = tool_executor("lookup_outlet_orders", {"outlet_id": 1})
            org_b_captured.append(res_cross)
            return {
                "ok": True,
                "text": "Checked only Riverside outlets.",
                "tools_used": ["lookup_outlet_orders"],
                "provider": "gemini",
                "model": "gemini-2.5-flash",
            }

        monkeypatch.setattr(orchestrator, "chat_with_tools_and_history", fake_org_b_chat)
        org_b_llm = client.post(
            "/api/agents/chat",
            headers=_headers(org_b_mgr_tok),
            json={"message": "Check Main Atrium orders"},
        )
        assert org_b_llm.status_code == 200
        assert "error" in org_b_captured[0]

        # E. Platform Admin controlled cross-org analytics
        sum_b = client.get(f"/api/dashboard/summary?organisation_id={org_b_id}", headers=_headers(admin_tok))
        assert sum_b.status_code == 200
        assert {
            o["outlet_id"] for o in sum_b.json()["outlet_performance"]["outlets"]
        } == {out_b1_id, out_b2_id}

        sum_a = client.get(f"/api/dashboard/summary?organisation_id={org_a_id}", headers=_headers(admin_tok))
        assert sum_a.status_code == 200
        org_a_eval_ids = {o["outlet_id"] for o in sum_a.json()["outlet_performance"]["outlets"]}
        assert out_b1_id not in org_a_eval_ids
        assert out_b2_id not in org_a_eval_ids

        # F. Suspending Org B immediately blocks both Org B Manager & Student B sessions
        suspend = client.patch(
            f"/api/admin/organisations/{org_b_id}",
            headers=_headers(admin_tok),
            json={"status": "SUSPENDED"},
        )
        assert suspend.status_code == 200
        assert client.get("/api/auth/me", headers=_headers(org_b_mgr_tok)).status_code == 403
        assert client.get("/api/catalog/overview", headers=_headers(stu_b_tok)).status_code == 403
