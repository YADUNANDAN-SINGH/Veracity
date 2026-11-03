# PayPal sandbox setup

Protected Send only talks to the PayPal **sandbox** (`api-m.sandbox.paypal.com`): test accounts, test money, nothing real. This takes about 15 minutes. Steps 4 and 5 are optional.

| Step | You get | Goes in |
| --- | --- | --- |
| [1. Sandbox app](#1-create-a-sandbox-app) | Client ID and secret | `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET` |
| [2. Test buyer](#2-make-a-sandbox-test-buyer) | A sandbox personal login for the PayPal pop-up | `VERA_SANDBOX_BUYER_EMAIL`, `VERA_SANDBOX_BUYER_PASSWORD` (hosted build only) |
| [3. Run it](#3-run-it-locally) | A held, then voided, $2,400 payment | — |
| [4. Webhooks](#4-webhooks-optional) | PayPal's own events in the audit trail | `PAYPAL_WEBHOOK_ID` |
| [5. Payouts](#5-payouts-optional) | Released money forwarded to the recipient | `PAYPAL_PAYOUTS=1` |
| [6. Deploy](#6-deploy-the-judge-build-on-render) | The hosted judge build | Render |

## 1. Create a sandbox app

1. Log in to the [PayPal Developer Dashboard](https://developer.paypal.com/dashboard/) with any PayPal account, and switch the toggle to **Sandbox**.
2. Open **Apps & Credentials** and create an app: name it `Veracity`, type **Merchant**, and choose the default sandbox business account. That business account receives the money when a payment is released.
3. Copy the app's **Client ID** and **Secret** into `veracity-backend/.env` (start from `.env.example`):

   ```bash
   PAYPAL_CLIENT_ID=...
   PAYPAL_CLIENT_SECRET=...
   ```

The client ID is public: the PayPal button needs it in the browser. The secret stays on the server; the dashboard never sees it.

## 2. Make a sandbox test buyer

The payer approves a Protected Send in PayPal's own pop-up, logged in as a sandbox **personal** account.

1. Go to **Testing Tools → Sandbox Accounts**. PayPal made a default personal account when you first logged in; to make your own, select **Create account**, choose **Personal** and a country.
2. In the account's **Settings** menu choose **View/Edit account**, then **Change password** under *Login Info*, and set one you'll remember (8 to 20 characters). PayPal won't show it again.
3. For the hosted judge build, set `VERA_SANDBOX_BUYER_EMAIL` and `VERA_SANDBOX_BUYER_PASSWORD` to this account, so the setup screen tells judges how to log in to the pop-up. They're sandbox credentials with fake money; never put a real PayPal login there.

## 3. Run it locally

```bash
cd veracity-backend
cp .env.example .env            # then fill in step 1, and set VERA_REGION=US
source venv/bin/activate
VERA_FAKE=1 uvicorn main:app --reload --port 8000 --env-file .env
```

In a second terminal, `cd veracity-frontend/veracity && npm run dev`, and open <http://localhost:5173>.

1. Step 1 shows **PayPal sandbox: ready**.
2. Step 2 offers the sample calls; pick **"Grandma, it's me": a grandparent scam**.
3. Step 3 replays the call. When the caller asks for $2,400, the Protected Send panel is already filled in: select the PayPal button and log in as the test buyer from step 2.
4. PayPal authorizes the payment and the gate **holds** it, quoting the caller's own words. While the call is still going on, only **Cancel payment** is offered: the caller may be listening.
5. Select **End call & build report**, then **Jake didn't ask: cancel** on the held payment. Veracity voids the authorization at PayPal; the *PayPal activity* list shows each call PayPal answered, with its status and `debug_id`.

The order and authorization ids on the held screen are PayPal's own, so you can look them up in the sandbox business account at [sandbox.paypal.com](https://www.sandbox.paypal.com).

To try the other outcomes: the **concert money** sample call is low risk, so its $40 is released when the call ends. On the grandparent call, **Jake confirmed: release** starts a 15-minute cooling-off first (`VERA_COOL_OFF_MIN`).

## 4. Webhooks (optional)

Without webhooks, every status comes from PayPal's answers to Veracity's own API calls, which is enough for the demo. With them, PayPal also reports changes made outside Veracity (an authorization voided in PayPal, say), and each event shows up in the audit trail.

1. Webhooks need a public HTTPS address: your Render URL (step 6), or a tunnel to your laptop such as `cloudflared tunnel --url http://localhost:8000` or `ngrok http 8000`.
2. On **Apps & Credentials**, open the app, and under **Sandbox Webhooks** add a webhook:
   - URL: `https://<your-host>/api/paypal/webhook`
   - Events: `CHECKOUT.ORDER.APPROVED`, `PAYMENT.AUTHORIZATION.CREATED`, `PAYMENT.AUTHORIZATION.VOIDED`, `PAYMENT.CAPTURE.COMPLETED`, `PAYMENT.CAPTURE.DENIED`, `PAYMENT.CAPTURE.DECLINED`, and with Payouts `PAYMENT.PAYOUTSBATCH.SUCCESS`, `PAYMENT.PAYOUTSBATCH.DENIED`, `PAYMENT.PAYOUTS-ITEM.SUCCEEDED`, `PAYMENT.PAYOUTS-ITEM.FAILED`
3. Copy the **Webhook ID** into `PAYPAL_WEBHOOK_ID` and restart the backend.

Every delivery is checked with PayPal's `POST /v1/notifications/verify-webhook-signature` before it changes anything, and each event id is applied only once, because PayPal retries deliveries. Events from PayPal's **Webhooks simulator** can't be verified that way ([PayPal says so](https://developer.paypal.com/api/rest/webhooks/simulator/)), so Veracity answers them with `400`. Test with a real sandbox payment instead.

## 5. Payouts (optional)

With `PAYPAL_PAYOUTS=1`, a released payment is also forwarded from the sandbox business account to the recipient's PayPal email with the Payouts API, and its status becomes *Paid out*.

1. Set `PAYPAL_PAYOUTS=1` and restart. Protected Send now asks for the recipient's PayPal email.
2. Use the email of a second sandbox personal account (step 2) as the recipient.
3. The captured money lands in the sandbox business account, which pays for the payout. If PayPal refuses the payout as not permitted, check that Payouts is turned on in the app's features on **Apps & Credentials**.

If a payout fails, the money stays captured in the business account and the trail says so ("Payout failed: the money is captured but not forwarded").

## 6. Deploy the judge build on Render

1. Push the repo to GitHub.
2. In the [Render dashboard](https://dashboard.render.com/), choose **New → Blueprint** and pick the repo. Render reads [`render.yaml`](../render.yaml): one Docker web service, with `/api/health` as its health check.
3. Render asks for the values marked `sync: false`, so they never live in the repo: `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_WEBHOOK_ID` (leave it empty for now), `VERA_SANDBOX_BUYER_EMAIL` and `VERA_SANDBOX_BUYER_PASSWORD`.
4. Once it's live, add the webhook (step 4) with the Render URL, put its id in `PAYPAL_WEBHOOK_ID`, and redeploy.
5. Open the URL: the header says **Hosted demo** with a **JUDGE MODE** pill, and Step 1 lists what's real in this build.

Two things about Render's free plan ([Render's docs](https://render.com/docs/free)): it spins a service down after 15 minutes without traffic, and the next visitor waits about a minute; and its disk is wiped on every spin-down, restart or redeploy, so payments and reports start fresh. While judging is on, switch the service to a paid instance so no judge lands on a cold start.

## What runs where

| | Where it runs | What PayPal sees |
| --- | --- | --- |
| The call's audio, transcript and voice scores | Your laptop (or, in the judge build, nowhere: the call is replayed) | Nothing |
| Creating, authorizing, capturing and voiding the payment | The backend, with the secret | The amount, the currency, a description with the recipient's name, and the payment's and call's ids |
| Approving the payment | PayPal's pop-up, through the JavaScript SDK v6 | The payer's login, as with any PayPal checkout |
