# Vivid Inference Sidecar

FastAPI sidecar for Vivid V1 local generation, queue, model, and project APIs.

## Run
`npm run dev:sidecar`

## API Surface
- `/models/*`
- `/jobs/*`
- `/projects/*`
- `/health`
- `/events` websocket

## Notes
- Database bootstrap, queue persistence, recovery, and websocket event streaming are implemented.
- Simulation mode is used when no compatible active model is available.
