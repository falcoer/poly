# Maven reference driver

`poly.driver.maven` inspects the workspace directly and proposes finite Maven
reactor actions. It does not invoke Maven while inspecting or planning.

## Inspection

Every discovered `pom.xml` becomes a `maven/project` node. The driver records
GAV coordinates, packaging, the POM path, wrapper availability, and separate
relations for:

- local parent inheritance;
- membership declared by an aggregator's `<modules>` section;
- local project dependencies;
- locally built plugins and build extensions.

Inheritance alone never makes a project a member of its parent's reactor.
Invalid POMs, missing declared modules, unresolved local models, and ambiguous
coordinates are returned as inspection diagnostics without hiding valid nodes.

## Planning

For `build`, `test`, `package`, `verify`, or `install`, selected modules sharing
the same highest usable local aggregator become one action. Its command is
explicit, including the reactor root, project selectors, `-am`, lifecycle phase,
and run-local repository when required:

```text
mvn -f platform/pom.xml -pl com.example:service-a -am verify
```

Maven owns ordering inside that action. When a selected project depends on a
project in another local reactor, the default `workspace` policy proposes a
separate upstream action, changes its phase to `install`, and connects the two
actions with a temporary constraint. All affected Maven actions use:

```text
-Dmaven.repo.local=${POLY_RUN_DIRECTORY}/maven-repository
```

The alternative `repository` policy does not add local upstream actions. The
`exact` policy blocks the plan unless the corresponding repository-availability
constraints are supplied. `clean` never closes over local dependencies and
does not add `-am`.

Full Maven effective-model parity, profile activation, and artifact publication
remain outside this reference milestone.
