# Render Static Site implementation plan

**Goal:** Show the BIM Insight UI immediately from Render's static CDN while the existing free Python API wakes up.

**Architecture:** A new free Static Site builds the existing React application with `VITE_API_BASE_URL` pointing to `https://bim-insight-demon.onrender.com`. The API retains its existing URL, database, account permissions and single-service UI fallback. `BIM_FRONTEND_ORIGIN` allows exactly the static site's HTTPS origin alongside the API's original origin. Initial remote health checks retry transient startup/network failures for up to two minutes and can be cancelled.

**Isolation:** Root workspace has unrelated, uncommitted class/practice work. Implement against deployed commit `62293ac` in `.local/render-static-split`, commit only this task, and fast-forward the remote `deploy/render-demo` branch. Preserve the original working tree and do not publish unrelated work.

## Tasks

- [x] Add failing API tests for the second exact HTTPS origin, original URL compatibility, preflight, invalid origins and retained account/project authorization.
- [x] Add a focused connection self-check for transient failures, HTML waking pages, permanent errors, cancellation and bounded retry.
- [x] Extend web configuration and CORS without wildcard origins or relaxed authentication.
- [x] Read the public API URL from the frontend build environment and add cancellable startup retries and clear waiting copy.
- [x] Add a static-only Blueprint and exact manual deployment/Git instructions; retain the existing backend service and secrets.
- [x] Run focused backend/connection tests, default and static frontend builds, stream parsers, and desktop/mobile browser checks with a delayed cross-origin API.
- [ ] Review, commit and push the task to `deploy/render-demo`; create/configure the free Static Site if Render authorization becomes active. Otherwise record the exact pending dashboard step and connection blocker.

## Constraints

No paid resources, secret exports, bulk staging, database changes, or unrelated feature publication. Static hosting improves UI availability; API cold starts and ephemeral files still exist. Keep backend health-check Host permissions tied to the API domain, independently from browser CORS origins.

## Verification

- Clean deployed baseline: 13 web tests and frontend build passed in the isolated worktree.
- Watched six new backend cases and the startup-connection self-check fail before implementation, then pass.
- Focused web/account/API regression: 47 passed, 1 optional integration test skipped.
- `npm run test:processor-connection` and both existing stream parser checks passed.
- Default same-origin build and separately configured API build passed. Static Blueprint parsed and checked for a static-only service, existing public API URL and no credentials/paid plan.
- Browser plugin not available; Playwright used two actual localhost HTTPS origins. Confirmed branded waiting UI while API returned two startup failures, automatic transition, login, project creation, cross-origin XHR PDF upload and report download, 1440px desktop/375px mobile, no horizontal overflow, logout, no uncaught JavaScript errors. Temporary fixtures/screenshots are outside tracked source in `.local/render-static-qa/`.
- Fresh-context review found no important concrete issues.
- No live Static Site claim until Render authorization is active and the actual frontend origin is configured on the backend.
