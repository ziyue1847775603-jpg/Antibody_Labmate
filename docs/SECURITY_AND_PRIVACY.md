# Security and privacy boundaries

- Replay accepts only the exact `demo_001` normalized CDR and antigen bytes.
- PDB input is bounded by file size, atom count, and chain count; NUL bytes, invalid coordinates, empty selected chains, unsafe artifact paths, and fixture hash mismatches fail closed.
- `project.yaml` antigen paths must be relative and remain below the project directory.
- ZIP entries are constructed only from paths below the run directory and are checked for absolute paths and `..` components.
- HTML uses Jinja2 autoescape and embeds no online CDN.
- The report uses relative artifact paths and excludes environment variables, tokens, API keys, external URLs carrying data, and local absolute paths.
- Phase 1 has no network client, subprocess runner, remote endpoint, authentication token, or persistent user database.

The parser is intentionally limited and is not a hardened general-purpose PDB sanitation service. Do not expose this P0 app as an unauthenticated public upload service.

