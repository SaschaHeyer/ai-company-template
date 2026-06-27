# loop_state.md — current state & backlog

> The agent reads the tail of this file each loop and appends to it. The loop counter and the chosen
> BRAND NAME live here. Keep entries short: what you did + what's next.

## Brand
- **Name:** _not chosen yet_
- **Domain:** _not registered yet_

## Loop 0 — fresh start
- New autonomous CEO on the Gemini managed-agent runtime. Harness: `agent/` (definition), `runner/`
  (trigger), `deploy/` (Cloud Run + Scheduler), `workspace/` (this git memory). Auth is proxy-only (Step 0).
- **Next loop:** read `human-tasks.md` + `BUSINESS.md`. If the business is undefined, you're in IDEATION:
  run the `competitor-analysis` skill on the niche first (mandatory), then propose the business + its
  competitor map and wait. If defined + approved, start at the top of the backlog (name the company).

## Backlog (highest-EV first)
- [ ] Ideation: run `competitor-analysis` on the niche, then propose the business (`BUSINESS.md`) + competitor map and get operator approval.
- [ ] Name the company, register a domain, set up the Resend sending domain + a basic landing page.
- [ ] Build the product MVP; wire signup → Stripe → Firestore CRM.
- [ ] Operator comms: send the first digest; start handling inbound email.
- [ ] Compounding assets: a "how it works" page + one SEO/AEO page for the niche.

<!-- append new loop entries below this line -->
