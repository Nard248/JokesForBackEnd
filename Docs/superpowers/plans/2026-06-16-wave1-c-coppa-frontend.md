# Wave 1C — Registration Age-Gate UI (frontend)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]` checkboxes. Wave 1 (launch-gating compliance); decisions CD1-CD6 locked in 2026-06-16-wave1-decisions-and-user-action-items.md.

---
## Work-stream C: Age-gate (DOB) UI at registration

**Goal:** Add a neutral date-of-birth input to the registration flow, send date_of_birth ("YYYY-MM-DD") in the register request, and handle the backend under-13 rejection (HTTP 400 with body {"date_of_birth":["You must be at least 13 years old to use Jokes For."]}) by surfacing the message inline on the DOB field and NOT proceeding. A 13+ DOB continues unchanged through the existing gated email-verification flow. Full TDD with vitest.

**Architecture:** The frontend register call already posts to /auth/registration/ via authApi.register (src/lib/api.ts:80-81) and returns the union AuthResponse | EmailVerificationPending. The RegisterPage is a 2-step form: Step 1 collects the functional fields (firstName, handle, email, password) and gates client-side validation before advancing to Step 2; Step 2 is mostly cosmetic and its "Create account & start setup" button invokes handleFinish, which is the ONLY place registerMutation.mutate runs. Therefore the register request — and thus the backend's under-13 enforcement — fires on the Step-2 finish, even though the DOB INPUT will live in Step 1 alongside the other identity fields (it is a registration-identity field, not a personalization field).

Two distinct concerns must be handled:
1) Client-side presence/format: DOB is required to advance past Step 1 (added to validateStep1). This catches an empty/garbage DOB before any network call. We do NOT do client-side age math for the block — per LOCKED CD2 and the cross-agent contract, the backend is the single source of truth for the under-13 rejection (anti-bypass; keeps the 13-year boundary logic in one place). We collect a real date (a native <input type="date">), never a yes/no "are you 18" checkbox.
2) Server-side under-13 block: handleFinish's onError already inspects axiosError.response.data. Today it maps non_field_errors/email/password1/password2/detail into a single top-level `error` banner and calls setStep(1) to send the user back. We extend RegistrationApiError with date_of_birth?: string[] and, when present, surface that exact message. Because the user is sent back to Step 1 (where the DOB field lives) on any register error, the message can be shown inline beneath the DOB field. We add a dedicated dobError state so the DOB rejection renders next to the field (the contract is a FIELD error) rather than only in the generic top banner; the generic banner remains the fallback for the other error shapes. On under-13 we must NOT navigate — the existing onError path already does not navigate (it only navigates on the 502 branch), so correctness here is: ensure the date_of_birth branch returns after setting the field error + setStep(1) and never falls through to navigation.

Type/contract plumbing: add date_of_birth: string to RegisterCredentials (src/lib/api.ts) so authApi.register carries it; RegisterPage holds a `dob` state string (the native date input already yields "YYYY-MM-DD") and passes date_of_birth: dob into registerMutation.mutate alongside email/password1/password2. The inline RegistrationApiError interface in RegisterPage.tsx gains date_of_birth?: string[].

FlowInput (the styled input atom in RegisterPage.tsx) currently accepts only value/onChange/placeholder/type/autoComplete/autoFocus. A date input benefits from a `max` (today, to discourage future dates) and an `id`/`name` for label association and test targeting. Extend FlowInput minimally to forward `max`, `id`, and `name`; keep all existing call sites working (new props optional). Wire the DOB FormField label to the input via htmlFor/id so the test can query getByLabelText.

Testing follows the established pattern from src/pages/RegisterPage.verify.test.tsx and VerifyEmailPage.test.tsx: mock @/features/auth (useRegister, useUpdateUser) with vi.mock spreading the real module, render RegisterPage inside MemoryRouter + Routes (with a stub /verify-email route), drive the form with userEvent, and assert mutate payloads + navigation. For the under-13 case the mocked useRegister.mutate invokes opts.onError with the 400 body; for the 13+ case it invokes opts.onSuccess with a gated EmailVerificationPending payload and we assert the date_of_birth value was in the mutate vars and that navigation to verify-page occurred.

**Tech Stack:** React 18 + Vite + TypeScript; react-router (MemoryRouter in tests); @tanstack/react-query; vitest + @testing-library/react + @testing-library/user-event + jest-dom. Test command: npm run test (vitest run). No new dependencies.

**Files:**

| Action | Path | Responsibility |
|---|---|---|
| edit | `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/lib/api.ts` | Add date_of_birth: string to the RegisterCredentials interface (lines 17-21) so authApi.register (lines 80-81) carries the new field to /auth/registration/ per the cross-agent contract. |
| edit | `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/pages/RegisterPage.tsx` | Add a neutral date-of-birth input to Step 1; add `dob` and `dobError` state; require DOB in validateStep1; include date_of_birth: dob in registerMutation.mutate; extend the inline RegistrationApiError interface with date_of_birth?: string[]; in handleFinish onError surface data.date_of_birth[0] inline under the DOB field (and ensure NO navigation on that branch); extend FlowInput to forward max/id/name; associate the DOB label with the input via htmlFor/id. |
| create | `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/pages/RegisterPage.agegate.test.tsx` | New vitest suite: (a) DOB field is present and required (cannot advance past Step 1 without it); (b) an under-13 DOB surfaces the exact block message and does NOT navigate; (c) a 13+ DOB includes date_of_birth in the mutate payload and proceeds to /verify-email. Mocks @/features/auth (useRegister/useUpdateUser), mirrors RegisterPage.verify.test.tsx setup. |

### Task 1: Task 1 — Plumb date_of_birth into the register contract (type + request)

**Files:** `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/lib/api.ts`, `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/pages/RegisterPage.tsx`

- [ ] **Step 1 (note): Confirm the contract field name and shape from the prompt: register accepts date_of_birth as ISO 'YYYY-MM-DD'; under-13 -> 400 {"date_of_birth":["You must be at least 13 years old to use Jokes For."]}. A native <input type="date"> .value is already 'YYYY-MM-DD', so no formatting is needed.**

- [ ] **Step 2 (impl): In src/lib/api.ts, add date_of_birth to RegisterCredentials.**

```
export interface RegisterCredentials {
  email: string
  password1: string
  password2: string
  date_of_birth: string // ISO 'YYYY-MM-DD' — backend enforces the under-13 block
}
```

- [ ] **Step 3 (impl): In src/pages/RegisterPage.tsx, extend the inline RegistrationApiError interface (lines 25-31) with the new field-error key.**

```
interface RegistrationApiError {
  non_field_errors?: string[]
  email?: string[]
  password1?: string[]
  password2?: string[]
  date_of_birth?: string[]
  detail?: string
}
```

- [ ] **Step 4 (impl): Add DOB state near the other Step 1 fields (after `const [password, setPassword] = useState('')`).**

```
const [dob, setDob] = useState('')
const [dobError, setDobError] = useState<string | null>(null)
```

- [ ] **Step 5 (run): Type-check compiles (no behavior yet): npx tsc --noEmit (or rely on the next test run). Expect no type errors from the new optional/required fields at existing call sites EXCEPT the registerMutation.mutate call, which will now be missing date_of_birth — that is fixed in Task 2.**

  - Expected: tsc reports only the expected missing-property error at the mutate call site in handleFinish (resolved in Task 2).

### Task 2: Task 2 — RED: write the age-gate vitest suite

**Files:** `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/pages/RegisterPage.agegate.test.tsx`

- [ ] **Step 1 (note): Model the suite on src/pages/RegisterPage.verify.test.tsx: mock @/features/auth spreading the real module, override useRegister/useUpdateUser; render RegisterPage in MemoryRouter+Routes with a stub /verify-email route; drive Step 1 then Step 2. The DOB input lives in Step 1, so fill it before clicking Continue. Target the DOB input via getByLabelText (label associated by htmlFor/id added in Task 3).**

- [ ] **Step 2 (test): Create the test file with three tests: field-required, under-13-blocked, 13+-proceeds.**

```
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { vi } from 'vitest'

const mockRegister = vi.fn()
vi.mock('@/features/auth', async (orig) => ({
  ...(await orig<typeof import('@/features/auth')>()),
  useRegister: () => ({ mutate: mockRegister, isPending: false }),
  useUpdateUser: () => ({ mutate: vi.fn(), isPending: false }),
}))

import { RegisterPage } from './RegisterPage'

function setup() {
  const qc = new QueryClient()
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/register']}>
        <Routes>
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/verify-email" element={<div>verify-page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const BLOCK_MSG = 'You must be at least 13 years old to use Jokes For.'

async function fillStep1(user: ReturnType<typeof userEvent.setup>, dobValue?: string) {
  await user.type(screen.getByPlaceholderText('Alex'), 'Test')
  await user.type(screen.getByPlaceholderText('you@studio.com'), 'a@b.com')
  await user.type(screen.getByPlaceholderText('At least 8 characters'), 'password123')
  if (dobValue !== undefined) {
    const dobInput = screen.getByLabelText(/date of birth/i)
    await user.clear(dobInput)
    await user.type(dobInput, dobValue)
  }
}

function clickContinue(user: ReturnType<typeof userEvent.setup>) {
  const submitBtn = screen
    .getAllByRole('button', { name: /continue/i })
    .find((b) => (b as HTMLButtonElement).type === 'submit')
  return user.click(submitBtn!)
}

test('DOB field is present and required to advance past step 1', async () => {
  const user = userEvent.setup()
  setup()
  expect(screen.getByLabelText(/date of birth/i)).toBeInTheDocument()
  // Fill everything EXCEPT dob, then try to continue — should stay on step 1.
  await fillStep1(user) // no dob
  await clickContinue(user)
  // Still on step 1: the "Create account" button (step 2) is absent.
  expect(screen.queryByRole('button', { name: /create account/i })).not.toBeInTheDocument()
})

test('an under-13 DOB surfaces the block message and does not navigate', async () => {
  const user = userEvent.setup()
  mockRegister.mockImplementation((_vars: unknown, opts: { onError: (e: unknown) => void }) =>
    opts.onError({ response: { status: 400, data: { date_of_birth: [BLOCK_MSG] } } }),
  )
  setup()
  await fillStep1(user, '2020-01-01') // clearly under 13
  await clickContinue(user)
  await user.click(screen.getByRole('button', { name: /create account/i }))
  expect(await screen.findByText(BLOCK_MSG)).toBeInTheDocument()
  expect(screen.queryByText('verify-page')).not.toBeInTheDocument()
})

test('a 13+ DOB includes date_of_birth and proceeds to verify-email', async () => {
  const user = userEvent.setup()
  mockRegister.mockImplementation((vars: { date_of_birth?: string }, opts: { onSuccess: (d: unknown) => void }) => {
    expect(vars.date_of_birth).toBe('2000-01-01')
    opts.onSuccess({ detail: 'Verification code sent to your email.', email: 'a@b.com' })
  })
  setup()
  await fillStep1(user, '2000-01-01')
  await clickContinue(user)
  await user.click(screen.getByRole('button', { name: /create account/i }))
  await waitFor(() => expect(screen.getByText('verify-page')).toBeInTheDocument())
  expect(mockRegister).toHaveBeenCalledWith(
    expect.objectContaining({ date_of_birth: '2000-01-01' }),
    expect.any(Object),
  )
})
```

- [ ] **Step 3 (run): Run only this suite: npm run test -- src/pages/RegisterPage.agegate.test.tsx**

  - Expected: RED — all three fail: getByLabelText(/date of birth/i) finds nothing (field not added yet), and the mutate payload lacks date_of_birth. This confirms the tests exercise the not-yet-built behavior.

### Task 3: Task 3 — GREEN: implement the DOB field, validation, request payload, and inline error

**Files:** `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/pages/RegisterPage.tsx`

- [ ] **Step 1 (impl): Extend FlowInput to forward max/id/name (keep existing props/behavior). Update FlowInputProps and the component.**

```
interface FlowInputProps {
  value: string
  onChange: (v: string) => void
  placeholder?: string
  type?: string
  autoComplete?: string
  autoFocus?: boolean
  max?: string
  id?: string
  name?: string
}

function FlowInput({ value, onChange, placeholder, type = 'text', autoComplete, autoFocus, max, id, name }: FlowInputProps) {
  return (
    <input
      id={id}
      name={name}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      type={type}
      max={max}
      autoComplete={autoComplete}
      autoFocus={autoFocus}
      className="flow-input"
    />
  )
}
```

- [ ] **Step 2 (impl): Make the DOB FormField label associate to the input. Add an optional htmlFor to FormField so getByLabelText works.**

```
function FormField({ label, htmlFor, children }: { label: string; htmlFor?: string; children: React.ReactNode }) {
  return (
    <div>
      <label htmlFor={htmlFor} style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 13, color: '#1A1A1A', display: 'block', marginBottom: 8 }}>
        {label}
      </label>
      {children}
    </div>
  )
}
```

- [ ] **Step 3 (impl): Render the DOB field inside the Step-1 <form>, after the Email FormField and before Password (a neutral identity field). Use a real date input capped at today; render the inline dobError beneath it. Compute today's ISO date for max.**

```
// near top of RegisterPage(), before return or inline:
const todayIso = new Date().toISOString().slice(0, 10)

// JSX inserted after the Email FormField:
<FormField label="Date of birth" htmlFor="dob">
  <FlowInput id="dob" name="date_of_birth" value={dob} onChange={(v) => { setDob(v); if (dobError) setDobError(null) }} type="date" max={todayIso} autoComplete="bday" />
  {dobError && (
    <p role="alert" style={{ fontSize: 12, color: '#A02B16', marginTop: 6 }}>{dobError}</p>
  )}
</FormField>
```

- [ ] **Step 4 (impl): Require DOB in validateStep1 (presence only — NO client-side age math; the backend owns the 13-year boundary).**

```
const validateStep1 = (): string | null => {
  if (!firstName.trim()) return 'First name is required'
  if (!email.trim()) return 'Email is required'
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return 'Please enter a valid email address'
  if (password.length < 8) return 'Password must be at least 8 characters'
  if (!dob) return 'Date of birth is required'
  return null
}
```

- [ ] **Step 5 (impl): Include date_of_birth in the register payload in handleFinish.**

```
registerMutation.mutate(
  { email, password1: password, password2: password, date_of_birth: dob },
  { /* existing onSuccess / onError */ },
)
```

- [ ] **Step 6 (impl): In handleFinish onError, surface the date_of_birth field error inline (set dobError) and ensure NO navigation. Add the branch BEFORE the generic banner mapping; keep setStep(1) so the user lands back on Step 1 where the DOB field + inline error are visible.**

```
onError: (err) => {
  const axiosError = err as AxiosError<RegistrationApiError>
  const data = axiosError.response?.data
  if (axiosError.response?.status === 502) {
    navigate(`/verify-email?email=${encodeURIComponent(email)}&sendFailed=1`, { replace: true })
    return
  }
  if (data?.date_of_birth) {
    setDobError(data.date_of_birth[0])
    setStep(1)
    return // do NOT navigate; the under-13 block stops here
  }
  if (data?.non_field_errors) setError(data.non_field_errors[0])
  else if (data?.email) setError(`Email: ${data.email[0]}`)
  else if (data?.password1) setError(`Password: ${data.password1[0]}`)
  else if (data?.password2) setError(`Password: ${data.password2[0]}`)
  else if (data?.detail) setError(data.detail)
  else setError('Unable to create account. Please try again.')
  setStep(1)
},
```

- [ ] **Step 7 (impl): Clear any stale dobError when a fresh finish attempt starts. At the top of handleFinish, alongside setError(null), add setDobError(null).**

- [ ] **Step 8 (run): Re-run the suite: npm run test -- src/pages/RegisterPage.agegate.test.tsx**

  - Expected: GREEN — all three pass: field present+required, under-13 shows the exact block message without navigating, 13+ sends date_of_birth and proceeds to verify-page.

### Task 4: Task 4 — Regression + full check

**Files:** `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/pages/RegisterPage.verify.test.tsx`, `/Users/narekmeloyan/WebstormProjects/jokes-for-frontend/src/lib/api.ts`

- [ ] **Step 1 (note): RegisterPage.verify.test.tsx drives Step 1 -> Step 2 WITHOUT filling DOB. After Task 3, DOB is required in validateStep1, so clickContinue will no longer advance and those two existing tests will regress (they will never reach the Create-account button).**

- [ ] **Step 2 (impl): Update src/pages/RegisterPage.verify.test.tsx to fill the DOB field in Step 1 before clicking Continue (add a getByLabelText(/date of birth/i) type of a valid 13+ date in both tests, mirroring the agegate suite's fillStep1).**

```
// in each of the two tests, after typing password and before finding the submit button:
const dobInput = screen.getByLabelText(/date of birth/i)
await user.type(dobInput, '2000-01-01')
```

- [ ] **Step 3 (run): Run the whole frontend test suite: npm run test**

  - Expected: All suites pass (vitest run, 0 failing), including api.verify, parseAuthError, VerifyEmailPage, RegisterPage.verify, and the new RegisterPage.agegate.

- [ ] **Step 4 (run): Type-check the project: npx tsc --noEmit**

  - Expected: No type errors. RegisterCredentials now requires date_of_birth and the only producer (handleFinish) supplies it; mock-api / mock-data do not construct RegisterCredentials so they are unaffected (verify via grep that no other file builds a RegisterCredentials object).

- [ ] **Step 5 (note): Optional sanity grep before committing: grep -rn 'RegisterCredentials' src to confirm authApi.register is the sole consumer and no other call site needs updating for the new required field.**

- [ ] **Step 6 (commit): Commit with a plain message (NO Co-Authored-By / generated-with footer, per project convention).**

```
git add src/lib/api.ts src/pages/RegisterPage.tsx src/pages/RegisterPage.agegate.test.tsx src/pages/RegisterPage.verify.test.tsx
git commit -m "feat(register): collect date of birth and surface backend under-13 block"
```

**Decisions in this plan:**

- *Where should the DOB input live — Step 1 (functional) or Step 2 (cosmetic)?* → Step 1. DOB is a registration-identity field that gates account creation, not personalization. Putting it in Step 1 lets validateStep1 require it before advancing, and — critically — the backend under-13 error sends the user back to Step 1 (existing setStep(1) behavior), so the inline field error renders right next to the input. Placing it in Step 2 would orphan the error from the field after the setStep(1) bounce.
- *Should the under-13 block be enforced client-side (compute age from DOB) or rely on the backend 400?* → Rely on the backend 400, as the cross-agent contract and LOCKED CD2 dictate. Client-side we only require DOB presence in Step 1. Doing age math on the client would duplicate the 13-year boundary, drift from the backend, and be trivially bypassable; the backend is the single source of truth. (A native <input type="date"> with max=today is the only client-side guard, and only to discourage future dates.)
- *Inline field error vs the existing top-level error banner for the under-13 message?* → Inline, via a dedicated dobError state rendered beneath the DOB field. The contract delivers a FIELD error keyed date_of_birth, so the message belongs on the field for clarity and a11y (role=alert). Keep the existing top banner as the fallback for non_field_errors/email/password/detail. This matches the prompt's 'show the field error message inline'.
- *How to render the date entry — native input or custom?* → Native <input type="date">, surfaced through the existing FlowInput atom (extended to forward max/id/name). It yields 'YYYY-MM-DD' directly (no formatting glue), is keyboard/locale-accessible for free, satisfies 'a real date entry — not a yes/no checkbox', and keeps the styling consistent via the existing .flow-input class. autoComplete='bday' is a small UX win.
- *Do existing RegisterPage tests need changing?* → Yes — RegisterPage.verify.test.tsx drives Step 1 without a DOB; once DOB is required in validateStep1 those tests stop advancing to Step 2. Update both to fill a valid 13+ DOB in Step 1. This is a necessary regression fix, included as Task 4, not scope creep.

**Risks:**

- validateStep1 becoming DOB-required breaks the two existing RegisterPage.verify.test.tsx tests (they advance to Step 2 without a DOB). Task 4 fixes them by filling a valid date; do not skip it or the suite goes red.
- Making date_of_birth a REQUIRED field on RegisterCredentials is a TS breaking change for any other producer of that type. Grep confirmed authApi.register is the sole consumer and no mock builds a RegisterCredentials object, but re-run the grep before committing in case other branches added one.
- userEvent typing into a native <input type="date"> can be finicky across environments/locales; jsdom accepts setting the value as 'YYYY-MM-DD'. If user.type proves flaky, fall back to fireEvent.change(dobInput, { target: { value: '2000-01-01' } }) — value semantics are identical and the assertions still hold.
- getByLabelText requires the label's htmlFor to match the input id; if the FormField/label association is omitted the field test fails to find the input. Task 3 explicitly wires htmlFor="dob" to id="dob".
- The under-13 message must match the backend byte-for-byte ('You must be at least 13 years old to use Jokes For.'). We render data.date_of_birth[0] verbatim (no hardcoded copy in the component), so it always mirrors the server; tests assert the contract string as a constant.
- The DOB field appears on /register only; the existing 'By signing up you agree to Terms/Privacy' copy and consent banner (CD4/CD5) are separate work-streams — do not bundle them here (YAGNI scope).
