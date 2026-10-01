# MediaDrop — User Upload & Webhook Relay API

## Component overview

MediaDrop is a small backend service that lets authenticated partner
applications upload user-submitted images, have them resized into standard
thumbnail variants, and relay a notification to each partner's registered
webhook URL once processing completes. It's the kind of service a mid-size
SaaS product bolts on for "upload a profile photo" or "attach an image to a
support ticket" without building image infrastructure in-house.

**Technology stack:**
- Runtime: Node.js 20, Express 5 HTTP API
- Image processing: `sharp` (libvips bindings) for resize/crop/format conversion
- Outbound HTTP: `axios` for webhook delivery and partner API callbacks
- Auth: JWT bearer tokens (`jsonwebtoken`), validated against a partner API key
- Build: `esbuild` bundles the TypeScript source into a single deployable file
- Validation: `zod` schemas on every request body
- Identifiers: `uuid` for upload IDs and webhook delivery IDs
- Realtime: a `ws` WebSocket channel partners can subscribe to for live
  processing status, as an alternative to polling or webhooks
- Storage: uploads land in an S3-compatible object store; the bucket is
  private, served only via short-lived signed URLs
- Queue: a Redis-backed job queue holds pending resize jobs so the HTTP
  request returns immediately and processing happens asynchronously

## Architecture

1. A partner application calls `POST /uploads` with a JWT bearer token and a
   multipart image file. Express validates the token, the `zod` schema checks
   content-type/size, and the raw bytes are written to the object store under
   a UUID key.
2. A job is pushed to the Redis queue. A worker process (same codebase,
   separate entry point) pulls the job, uses `sharp` to generate three
   thumbnail variants (128px, 512px, 1024px), and writes each variant back to
   the object store.
3. On completion, the worker calls the partner's registered webhook URL via
   `axios`, POSTing a signed JSON payload with the resulting object keys. The
   same event is also pushed over any open `ws` connection for that partner.
4. Partners manage their webhook URL and rotate their API key through an
   admin UI that talks to the same Express API.
5. `esbuild` produces the production bundle for both the API process and the
   worker process from one TypeScript source tree, deployed as two containers
   behind a shared Redis and object store.

## Assumptions

**In scope:** the upload API, the resize worker, webhook delivery, the
WebSocket status channel, partner API key management.

**Out of scope:** the object store's own IAM configuration, the Redis
deployment's network isolation, the partner applications' own security.

**Security controls already in place:**
- All traffic is TLS-terminated at a load balancer in front of Express.
- JWTs are short-lived (15 minutes) and signed with a per-environment secret.
- Webhook payloads are HMAC-signed so partners can verify authenticity.
- Upload size is capped at 25 MB per request.

**Focus areas:** the dependency supply chain for the image-processing and
webhook-delivery path, since a compromised `sharp`, `axios`, or `esbuild`
release would run inside both the request path and the worker process with
access to the object store credentials and the partner webhook HMAC secret.
