"""
The credential itself never reaches the log backend.

Manifest section 9 draws the line: `is_secret = true` redacts the Alloy
API and component exports, but a configuration-load error may quote a
fragment of the value Alloy read, and that is Alloy's behaviour rather
than the contract's choice. Documenting a limit is only half the work --
the half that still holds needs proving, and it holds where it matters
most: the password itself.

The reference collects the stdout/stderr of every container including
Alloy's own (dogfooding), so if a credential ever surfaced in a
diagnostic it would travel straight into Loki.
"""

from tests.e2e.conftest import LOGS_BUDGET, Stack, wait_until

#: Env keys of the per-run generated credentials. Randomised by
#: tools.stack_secrets, so a match cannot be a coincidence of wording.
_CREDENTIAL_KEYS = (
    "RU_3OPS_DISCOVERY_E2E_PG_PASSWORD",
    "RU_3OPS_DISCOVERY_E2E_MARIADB_PASSWORD",
    "RU_3OPS_DISCOVERY_E2E_REDIS_PASSWORD",
    "RU_3OPS_DISCOVERY_E2E_MONGO_PASSWORD",
)


def test_no_generated_credential_reaches_loki(stack: Stack) -> None:
    passwords = {
        key: stack.env[key] for key in _CREDENTIAL_KEYS if stack.env.get(key)
    }
    assert passwords, "no generated credentials in the stack environment"

    # Wait for the collector's own stream first: asserting absence over an
    # empty result set proves nothing, so the delivery path has to be
    # demonstrably live before the search means anything.
    selector = f'{{compose_project="{stack.project}", container=~".*alloy.*"}}'
    entries = wait_until(
        lambda: stack.loki_entries(selector),
        LOGS_BUDGET,
        "alloy's own logs never arrived in Loki",
    )

    leaked = {
        key: line
        for key, secret in passwords.items()
        for _ts, line in entries
        if secret in line
    }
    assert not leaked, f"a generated credential reached Loki: {sorted(leaked)}"
