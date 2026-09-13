# Gmail and Google Workspace email accounts

Pantheon signs in to Gmail and Google Workspace mailboxes with Google OAuth.
An app password also still works, and is kept deliberately — for a personal
Gmail with 2FA it is the shorter road and nothing here takes it away.

**The setup steps are in the app.** Open the email account form, choose the
Gmail or Google Workspace preset, and if the Connect button is greyed out the
steps appear beside it with your deployment's own redirect URI, the exact scope
string, and the variable names — each with a copy button. This file is the same
thing in prose, for anyone who would rather read it first.

## One-time setup, by an operator

1. Create OAuth credentials at
   <https://console.cloud.google.com/apis/credentials> — **Create credentials →
   OAuth client ID → Web application**.
2. Enable the **Gmail API** for the project.
3. Add the redirect URI. The form prints the exact string; it looks like
   `https://your-pantheon-host/api/email/oauth/google/callback`. It has to match
   character for character or Google answers `redirect_uri_mismatch`. Behind a
   reverse proxy, set **Public App URL** in Settings so the value shown is the
   one the outside world uses.
4. On the consent screen, add the scopes:
   - `https://mail.google.com/`
   - `email`
5. Put the client id and secret in `.env` and restart:

   ```
   GOOGLE_OAUTH_CLIENT_ID=...apps.googleusercontent.com
   GOOGLE_OAUTH_CLIENT_SECRET=...
   ```

## Why the scope is the wide one

`https://mail.google.com/` is full mailbox access, and Google's own note says to
request it only when an app needs to permanently delete mail. Pantheon requests
it for a different reason: **it is the scope Google requires for IMAP and SMTP
over OAuth.** The narrower `gmail.readonly` and `gmail.send` scopes work with
the Gmail API, which is not the protocol this app speaks. There is no narrower
option that keeps IMAP working, and pretending otherwise would be worse than
saying so.

## What that means if you ever publish an app for other people

`https://mail.google.com/` is a **restricted** scope. For an app used only by
you and your own users on your own deployment, the normal consent screen is all
that is involved. If you were to distribute one registered application for other
people to use, Google requires verification **and an annual security assessment
by a Google-empanelled assessor**, and unverified apps are capped at a limited
number of accounts. That is why Pantheon ships **no** client id: every install
registers its own, which costs one setup and avoids all of it.

## Then, per mailbox

Choose the preset, press **Sign in with Google**, approve. The callback fills in
the host, port, security mode, username and from-address from the account you
signed in to — nothing else needs typing.

## Server settings, for reference

| | Host | Port | Security |
|---|---|---|---|
| IMAP | `imap.gmail.com` | 993 | TLS |
| SMTP | `smtp.gmail.com` | 587 | STARTTLS |

465 with TLS is also accepted for SMTP, and 143 with STARTTLS for IMAP.

## If it does not work

- **`redirect_uri_mismatch`** — the URI registered in Google Cloud Console is
  not byte-identical to the one the form prints. The form also says where that
  value came from (`request`, `app_public_url`, an environment variable), which
  is usually the thing that is wrong.
- **The button is greyed out** — the client id or the secret is missing from
  this deployment's `.env`, and the steps beside the button say which. It
  reports that *before* it is pressed rather than after you have already granted
  access to your mailbox.
- **"Google hasn't verified this app"** — expected for an app you registered
  yourself and have not submitted for verification. Add your own account as a
  test user on the consent screen.
- **The mailbox works and then stops** — the refresh token was not issued or was
  revoked. Press **Reconnect**.

## Using an app password instead

Still supported, and simpler for a single personal account: generate one at
<https://myaccount.google.com/apppasswords> (requires 2-Step Verification) and
paste it as the password. It is your **App Password**, not your account
password.
