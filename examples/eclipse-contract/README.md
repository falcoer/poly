# Eclipse contribution contract fixture

This independent Python plugin imports only the public `poly.driver` SDK and
canonical `poly.model` types. It exposes one configure facade, one declarative
blueprint, and one process-action planning driver. It is not a production Eclipse
integration: it creates only a minimal `.project`, once, and refuses overwrite.

The core-owned integration test loads `eclipse_contract:plugin` through
`load_plugin_entrypoint`, registers it, resolves the facade and blueprint, freezes
the proposal, executes it, and parses the generated XML. Run from a Poly checkout:

```bash
uv run pytest tests/test_blueprint_contract.py --no-cov
```

```powershell
uv run pytest tests/test_blueprint_contract.py --no-cov
```

The fixture module is placed on the test import path; it is not installed as a
production plugin. No configure CLI command is introduced. See the
[contract](../../docs/architecture/contribution-contracts.md) for implemented and
reserved boundaries. The complete fixture test also runs in the existing
Windows/Linux workspace CI matrix.
