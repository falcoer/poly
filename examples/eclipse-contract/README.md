# External configuration/hydration contract fixture

This independent plugin imports only `poly.driver` and `poly.model`. It contributes
an `add eclipse-configuration` facade, a versioned configuration schema, a blueprint
for initial values, and an ordinary `hydrate` driver. It is loaded only by tests;
it is not a bundled or installed production Eclipse integration.

The facade creates a normal pathless configuration node through the constructor.
Hydration waits for `WORKSPACE_COHERENT`, consumes the consolidated inventory, and
materializes `.poly/projections/<node>/request.xml`. Identical regeneration is a
no-op; differing existing output is refused. This request is a fixture artifact,
not an Eclipse workspace or a successful Eclipse import.

```shell
uv run pytest tests/test_blueprint_contract.py tests/test_hydration_configuration.py --no-cov
```

The tests also hydrate a missing locked Git checkout, discover its Maven modules,
retain manual natures and compare the outputs produced under two different roots.
The fixture uses Driver API and Extension API 2.0. See the
[configuration hydration contract](../../docs/architecture/configuration-hydration.md).
