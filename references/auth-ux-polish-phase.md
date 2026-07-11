# Auth UX polish phase reference

Use this reference when a SuperGoal phase is about auth UI polish, error-state clarity, activation/link prompts, or dark-theme-safe auth surfaces.

## Scope expansion rule

Mandatory commands may name only the obvious pages (`login/page.tsx`, `login-form.tsx`, `reset-password/page.tsx`), but UX polish often spans adjacent auth surfaces. Inspect and, when relevant, include:

- login page and login form
- reset password page and form
- email-start fallback redirects and query params
- activation / promo-code cards
- Telegram link card and Telegram login widget
- payment claim / link handoff prompts if they surface auth state

Do not stop at the mandatory lint trio if the visible auth journey continues through adjacent components.

## User-safe error copy

Never pass arbitrary query-param error text directly into visible UI. For login/reset flows:

1. Keep an allowlist of server-generated safe messages, or map status/error codes to copy.
2. Collapse unknown query text to a generic safe message.
3. Render errors as accessible status surfaces, not hardcoded red text.

Good shape:

```tsx
<div role="alert" className="... bg-[var(--el-color-bg-surface-emphasis)] text-[var(--el-color-text-primary)]">
  <span className="font-semibold">Не получилось: </span>
  <span>{safeError}</span>
</div>
```

For success states use `role="status"` with the same tokenized surface pattern.

## CTA and recovery matrix

Every auth state needs one primary action and one recovery/back path:

- email entry: primary continue, back to home/previous public surface
- password choice: primary password, recovery email, change email
- password sign-in: primary sign in, forgot password, change email
- register/check-email/reset-sent: primary send/resend, back/change email
- reset-password: primary save password, return to login while preserving `next`
- Telegram link prompt: primary widget/bot/link continue, retry/change email
- promo activation: primary activate/open access, payment/back path where applicable

For reset-password recovery links, preserve `next` and set `email_flow=recovery` when returning to login for recovery mode.

## Theme and heading guardrails

- Prefer `var(--el-*)` colors/surfaces for changed auth UI.
- Search touched auth files for `text-red-500`, `text-emerald-600`, `bg-white/`, `bg-green-50`, and visible `Human20` product copy. Replace with tokenized surfaces and `Человек 2.0` unless the literal bot/account name is intended.
- Provider brand buttons may keep provider colors if contrast is explicit and documented.
- Check heading structure: no duplicated shell title plus page `<h1>`. Standalone Card `h2` is fine when there is no shell title/hero duplicate.

## Verification pattern

Run at least:

```bash
npm run test -- <login/reset/auth component tests>
npm run lint -- src/app/login/page.tsx src/components/auth/login-form.tsx src/app/reset-password/page.tsx
npm run lint -- <extra touched auth files/tests>
npx tsc --noEmit --pretty false  # if baseline red, grep for touched file errors
```

Also run the platform-native cleanliness check over the complete working-tree
delta. `repo-state.sh added-lines <baseline>` is only an optional Unix helper;
bind the observation through Python evidence authority.

## RPD focus prompts

For `RPD_PHASE_REVIEW` with UX focus, explicitly test:

- Can a user recover if the email link/session is stale?
- Can arbitrary server/query text leak internals into visible UI?
- Do dark-theme status surfaces remain legible?
- Did adjacent activation/Telegram/payment auth prompts drift from the polished state?
