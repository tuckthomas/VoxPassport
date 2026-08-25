# VoxPassport Configuration

The current checked-in operator configuration surface is intentionally small.

## Deployment configuration

`deployment.example.json` documents the optional JSON deployment boundary consumed by `runtime/config/deployment.py`.

To use a JSON file, copy it to the default path:

```text
configs/deployment.json
```

or point VoxPassport at another file:

```env
VOXPASSPORT_DEPLOYMENT_CONFIG=C:\path\to\deployment.json
```

Environment variables override matching JSON values.

| Environment variable | JSON field | Meaning |
| --- | --- | --- |
| `VOXPASSPORT_LOCAL_ONLY` | `local.only` | Single-user/local deployment; forces accounts and hosted abuse controls off |
| `VOXPASSPORT_AUTH_ENABLED` | `accounts.enabled` | Enables/disables the optional account surface when not local-only |
| `VOXPASSPORT_ACCOUNT_API_URL` | `accounts.api_url` | Account-service base URL |
| `VOXPASSPORT_ABUSE_CONTROLS_ENABLED` | `security.abuse_controls_enabled` | Enables hosted/multi-user abuse controls when not local-only |

For ordinary personal/local development, a root `.env` containing the following is normally sufficient:

```env
VOXPASSPORT_LOCAL_ONLY=true
```

See the repository-root `.env.example` for the current environment-variable surface.

## What is not configured here

VoxPassport no longer uses hand-maintained `app.example.yaml` or `models.example.yaml` files.

Application/session settings are owned by the integrated runtime and canonical Expo client. Model identity, installation state, active slots, installability, and lifecycle metadata are owned by the Model Registry/model-manager APIs and TTS manifests/backend-runtime catalogs where applicable.

Do not add a parallel YAML model catalog or old desktop/IPC configuration to `configs/`. If a new durable operator setting is needed, add it to the owning typed runtime configuration boundary and document its precedence here.
