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
    def test_entry_exit_adjust(self, make_product, move, conn):
        pid = make_product("MOV-1", stock_qty=10)
        assert move(pid, "entrada", 5)["stock_after"] == 15
        assert move(pid, "salida", 6)["stock_after"] == 9
        assert move(pid, "ajuste", 20)["stock_after"] == 20
        rows = conn.all("SELECT kind, delta, stock_before, stock_after FROM stock_movements WHERE product_id = ? ORDER BY id", (pid,))
        assert [r["delta"] for r in rows] == [10, 5, -6, 11]

    def test_cannot_go_negative(self, make_product, move, conn):
        pid = make_product("NEG-1", stock_qty=3)
        with pytest.raises(ValidationError) as err:
            move(pid, "salida", 4)
        assert "Solo hay 3" in err.value.errors["quantity"]
        assert products.get(conn, pid)["stock"] == 3
        assert conn.scalar("SELECT COUNT(*) FROM stock_movements WHERE product_id = ?", (pid,)) == 1

    @pytest.mark.parametrize("qty", ["0", "-2", "abc", "1.5", "", "1000001"])
    def test_rejects_bad_quantity(self, make_product, move, qty):
        pid = make_product("QTY-1", stock_qty=5)
        with pytest.raises(ValidationError):
            move(pid, "entrada", qty)

    def test_adjust_to_same_value_is_rejected(self, make_product, move):
        pid = make_product("ADJ-1", stock_qty=5)
        with pytest.raises(ValidationError):
            move(pid, "ajuste", 5)

    def test_archived_product_cannot_move(self, make_product, move, conn, actor):
        pid = make_product("ARC-1", stock_qty=5, min_stock=9)
        assert alerts.open_count(conn) == 1
        products.archive(conn, pid, actor)
        assert alerts.open_count(conn) == 0                      # archivar cierra la alerta
        with pytest.raises(ValidationError):
            move(pid, "entrada", 1)
        with pytest.raises(NotFound):
            move(9999, "entrada", 1)


class TestUsers:
    def test_password_policy(self):
        for bad in ("short1", "alllettersonly", "123456789"):
            with pytest.raises(ValidationError):
                users.validate_password(bad)
        users.validate_password("Valida123")

    def test_cannot_remove_last_admin(self, conn):
        admin = users.get_by_username(conn, "admin")
        with pytest.raises(ValidationError):
            users.set_active(conn, admin["id"], False)
        with pytest.raises(ValidationError):
            users.update(conn, admin["id"], full_name="Admin", email=None, role="consulta", receive_alerts=False)

    def test_inactive_user_cannot_authenticate(self, conn):
        user = users.get_by_username(conn, "almacen")
        users.set_active(conn, user["id"], False)
        assert users.authenticate(conn, "almacen", "Almacen12345") is None
        assert users.authenticate(conn, "gerente", "bad") is None

    def test_passwords_are_hashed(self, conn):
        row = users.get_by_username(conn, "admin")
        assert row["password_hash"].startswith("pbkdf2:sha256:") and "Admin12345" not in row["password_hash"]
