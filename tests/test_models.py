"""Pruebas unitarias de las reglas de negocio."""
from __future__ import annotations

import pytest

from stocktrack.errors import Conflict, NotFound, ValidationError
from stocktrack.models import alerts, products, stock, users


def form(**kw):
    base = {"sku": "abc-1", "name": "Producto", "min_stock": "2", "cost": "10", "price": "20"}
    base.update(kw)
    return base


class TestProductValidation:
    def test_normalizes_sku_and_money(self):
        data = products.clean_form(form(cost="1,234.565", price="$99.9"))
        assert data["sku"] == "ABC-1" and data["cost_cents"] == 123457 and data["price_cents"] == 9990

    @pytest.mark.parametrize("field,value", [("sku", "a b"), ("sku", "-x"), ("sku", ""), ("name", " "),
                                             ("min_stock", "-1"), ("min_stock", "1.5"), ("cost", "-5"),
                                             ("price", "abc"), ("cost", "nan"), ("cost", "1e99")])
    def test_rejects_invalid(self, field, value):
        with pytest.raises(ValidationError) as err:
            products.clean_form(form(**{field: value}))
        assert err.value.errors

    def test_duplicate_sku_is_case_insensitive(self, make_product, conn, actor):
        make_product("DUP-1")
        with pytest.raises(Conflict):
            products.create(conn, products.clean_form(form(sku="dup-1")), actor, 100)

    def test_edit_keeps_stock_and_records_audit(self, make_product, conn, actor):
        pid = make_product("EDT-1", stock_qty=7)
        products.update(conn, pid, products.clean_form(form(sku="EDT-1", name="Nuevo nombre", min_stock="9")), actor)
        row = products.get(conn, pid)
        assert row["stock"] == 7 and row["name"] == "Nuevo nombre" and row["is_low"]
        assert conn.scalar("SELECT COUNT(*) FROM audit_log WHERE action = 'product.update' AND entity_id = ?", (pid,)) == 1


class TestMovements:
    def test_purchase_sale_return(self, make_product, move, conn):
        pid = make_product("MOV-1", stock_qty=10)
        assert move(pid, "compra", 5)["stock_after"] == 15
        assert move(pid, "venta", 6)["stock_after"] == 9
        assert move(pid, "devolucion", 2)["stock_after"] == 7          # Salida por Devolución resta (RF-21)
        rows = conn.all("SELECT kind, delta, stock_before, stock_after FROM stock_movements WHERE product_id = ? ORDER BY id", (pid,))
        assert [r["delta"] for r in rows] == [10, 5, -6, -2]

    @pytest.mark.parametrize("kind", ["venta", "devolucion", "reserva"])
    def test_cannot_exit_more_than_available(self, make_product, move, conn, kind):
        pid = make_product("NEG-1", stock_qty=3)
        with pytest.raises(ValidationError) as err:
            move(pid, kind, 4)
        assert "Solo hay 3" in err.value.errors["quantity"]                # RF-22: verifica stock suficiente
        assert products.get(conn, pid)["stock"] == 3
        assert conn.scalar("SELECT COUNT(*) FROM stock_movements WHERE product_id = ?", (pid,)) == 1

    @pytest.mark.parametrize("qty", ["0", "-2", "abc", "1.5", "", "1000001"])
    def test_rejects_bad_quantity(self, make_product, move, qty):
        pid = make_product("QTY-1", stock_qty=5)
        with pytest.raises(ValidationError):
            move(pid, "compra", qty)

    def test_unknown_kind_is_rejected(self, make_product, move):
        pid = make_product("KND-1", stock_qty=5)
        for kind in ("ajuste", "entrada", "salida", "x"):                  # tipos del modelo anterior ya no existen
            with pytest.raises(ValidationError):
                move(pid, kind, 1)

    def test_inactive_product_cannot_move(self, make_product, move, conn, actor):
        pid = make_product("ARC-1", stock_qty=5, min_stock=9)
        assert alerts.open_count(conn) == 1
        products.deactivate(conn, pid, actor)
        assert alerts.open_count(conn) == 0                      # desactivar cierra la alerta
        with pytest.raises(ValidationError):
            move(pid, "compra", 1)
        with pytest.raises(NotFound):
            move(9999, "compra", 1)

    def test_idempotency_key_prevents_duplicates(self, make_product, move, conn):
        pid = make_product("IDP-1", stock_qty=10)
        first = move(pid, "venta", 3, request_key="abc")
        again = move(pid, "venta", 3, request_key="abc")                    # RNF-15: reenvío del formulario
        assert again["duplicate"] and again["movement_id"] == first["movement_id"]
        assert products.get(conn, pid)["stock"] == 7


class TestReservations:
    def test_reserve_holds_units_until_validated(self, make_product, move, conn, actor):
        pid = make_product("RES-1", stock_qty=10, min_stock=3)
        res = move(pid, "reserva", 4)
        p = products.get(conn, pid)
        assert (p["stock"], p["reserved"], p["available"]) == (10, 4, 6) and res["status"] == "pendiente"
        with pytest.raises(ValidationError):
            move(pid, "venta", 7)                                            # solo 6 disponibles
        out = stock.validate_reservation(conn, res["movement_id"], True, actor)
        p = products.get(conn, pid)
        assert (p["stock"], p["reserved"], p["available"]) == (6, 0, 6) and out["child_id"]
        assert conn.scalar("SELECT status FROM stock_movements WHERE id = ?", (res["movement_id"],)) == "validado"
        assert conn.scalar("SELECT validated_by FROM stock_movements WHERE id = ?", (res["movement_id"],)) == actor["id"]
        assert conn.scalar("SELECT SUM(delta) FROM stock_movements WHERE product_id = ?", (pid,)) == 6

    def test_reject_releases_units_and_needs_reason(self, make_product, move, conn, actor):
        pid = make_product("RES-2", stock_qty=10)
        res = move(pid, "reserva", 4)
        with pytest.raises(ValidationError):
            stock.validate_reservation(conn, res["movement_id"], False, actor)
        stock.validate_reservation(conn, res["movement_id"], False, actor, "Cliente canceló")
        p = products.get(conn, pid)
        assert (p["stock"], p["reserved"]) == (10, 0)
        assert conn.scalar("SELECT status FROM stock_movements WHERE id = ?", (res["movement_id"],)) == "rechazado"

    def test_cannot_validate_twice(self, make_product, move, conn, actor):
        pid = make_product("RES-3", stock_qty=10)
        res = move(pid, "reserva", 2)
        stock.validate_reservation(conn, res["movement_id"], True, actor)
        with pytest.raises(Conflict):
            stock.validate_reservation(conn, res["movement_id"], True, actor)
        assert products.get(conn, pid)["stock"] == 8

    def test_reservation_triggers_shortage_alert_on_available_stock(self, make_product, move, conn):
        pid = make_product("RES-4", stock_qty=10, min_stock=5)
        assert alerts.open_count(conn) == 0
        assert move(pid, "reserva", 5)["new_alert_id"]                       # disponible 5 <= mínimo 5
        assert alerts.open_count(conn) == 1

    def test_cannot_deactivate_product_with_pending_reservation(self, make_product, move, conn, actor):
        pid = make_product("RES-5", stock_qty=10)
        move(pid, "reserva", 1)
        with pytest.raises(ValidationError):
            products.deactivate(conn, pid, actor)


class TestCategories:
    def test_crud_and_rules(self, conn, actor, make_product):
        from stocktrack.models import categories
        cid = categories.create(conn, "  Audio  ", actor)
        assert categories.get(conn, cid)["name"] == "Audio"
        with pytest.raises(Conflict):
            categories.create(conn, "audio", actor)                          # sin distinguir mayúsculas
        categories.rename(conn, cid, "Audio y video", actor)
        make_product("CAT-1", category="Audio y video")
        with pytest.raises(ValidationError):
            categories.set_active(conn, cid, False, actor)                   # tiene productos activos
        products.deactivate(conn, products.get_by_sku(conn, "CAT-1")["id"], actor)
        categories.set_active(conn, cid, False, actor)
        assert not categories.get(conn, cid)["is_active"]
        assert cid not in [c["id"] for c in categories.active_choices(conn)]


class TestUsers:
    def test_password_policy(self):
        for bad in ("short1", "alllettersonly", "123456789"):
            with pytest.raises(ValidationError):
                users.validate_password(bad)
        users.validate_password("Valida123")

    def test_cannot_remove_last_admin(self, conn):
        admin = users.get_by_email(conn, "admin@test.local")
        with pytest.raises(ValidationError):
            users.set_active(conn, admin["id"], False)
        with pytest.raises(ValidationError):
            users.update(conn, admin["id"], full_name="Admin", email="admin@test.local", role="consulta", receive_alerts=False)

    def test_inactive_user_cannot_authenticate(self, conn):
        user = users.get_by_email(conn, "encargado@test.local")
        users.set_active(conn, user["id"], False)
        assert users.authenticate(conn, "encargado@test.local", "Encargado12345") is None
        assert users.authenticate(conn, "ADMIN@test.local", "Admin12345")          # el correo no distingue mayúsculas
        assert users.authenticate(conn, "admin@test.local", "bad") is None

    def test_passwords_are_hashed(self, conn):
        row = users.get_by_email(conn, "admin@test.local")
        assert row["password_hash"].startswith("pbkdf2:sha256:") and "Admin12345" not in row["password_hash"]
