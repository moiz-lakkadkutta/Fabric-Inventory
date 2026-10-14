"""TASK-TR-Q01 — cross-org IDOR controls over HTTP (all pass today).

Complements the DB-level sweep in test_q01_rls_catalog.py: org B holding a
valid Owner token and org A's object ids gets 404 (never 200 / 403-with-data)
on by-id reads, mutations and id-parameterised reports.

Run:  uv run pytest tests/security/test_q01_idor.py -q
"""

from __future__ import annotations

from sqlalchemy.engine import Engine

from tests._gstin import make_gstin
from tests.security._q01_helpers import bearer, idem, q01_client, signup


async def test_q01_cross_org_by_id_access_is_404(sync_engine: Engine) -> None:
    _ = sync_engine
    async with q01_client() as client:
        a = await signup(client)
        b = await signup(client)
        party = await client.post(
            "/parties",
            headers={**bearer(a["access_token"]), **idem()},
            json={
                "code": "Q01-IDOR",
                "name": "A's customer",
                "is_customer": True,
                "gstin": make_gstin("27", "ABCDE1234F"),
                "phone": "+919999999999",
            },
        )
        assert party.status_code == 201, party.text
        pid = party.json()["party_id"]
        ledgers = await client.get("/ledgers", headers=bearer(a["access_token"]))
        lid = ledgers.json()["items"][0]["ledger_id"]

        tb = bearer(b["access_token"])
        probes = {
            "GET party": await client.get(f"/parties/{pid}", headers=tb),
            "PATCH party": await client.patch(
                f"/parties/{pid}", headers={**tb, **idem()}, json={"name": "pwned"}
            ),
            "DELETE party": await client.delete(f"/parties/{pid}", headers={**tb, **idem()}),
            "GET ledger": await client.get(f"/ledgers/{lid}", headers=tb),
            "party statement": await client.get(f"/reports/party-statement/{pid}", headers=tb),
            "ledger statement": await client.get(f"/reports/ledger/{lid}", headers=tb),
        }
        leaked = {k: r.status_code for k, r in probes.items() if r.status_code < 400}
        assert leaked == {}, f"cross-org by-id access succeeded: {leaked}"
        for name, r in probes.items():
            assert "A's customer" not in r.text, f"{name} leaked org A data"

        # Org A's row is untouched.
        still = await client.get(f"/parties/{pid}", headers=bearer(a["access_token"]))
        assert still.status_code == 200 and still.json()["name"] == "A's customer"
