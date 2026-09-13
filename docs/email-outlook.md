# Outlook / Office 365 email accounts

Pantheon signs in to Outlook and Microsoft 365 mailboxes with Microsoft OAuth.
There is no password to type, and there is no password that would work: Microsoft
has disabled basic authentication for IMAP and SMTP in every Exchange Online
tenant, so a mailbox password returns errors such as

- `IMAP: AUTHENTICATE failed`
- `SMTP: 535 5.7.139 Authentication unsuccessful, basic authentication is disabled`

The **Sign in with Microsoft** button on the email account form is the way in.
It appears once an operator has registered an app, which is a one-time job for
the whole install.

## One-time setup, by an operator

1. Register an application in Microsoft Entra ID —
   <https://learn.microsoft.com/entra/identity-platform/quickstart-register-app>.
2. Add a **Web** redirect URI. The exact string to paste is printed on the email
   account form under the Connect button; it looks like
   `https://your-pantheon-host/api/email/oauth/microsoft/callback`. It has to
   match character for character or Microsoft answers `redirect_uri_mismatch`.
   Behind a reverse proxy, set **Public App URL** in Settings so the value shown
   is the one the outside world uses.
3. Under **API permissions**, add these *delegated* Microsoft Graph / Office 365
   Exchange Online permissions and grant consent:
   - `https://outlook.office.com/IMAP.AccessAsUser.All`
   - `https://outlook.office.com/SMTP.Send`
   - `offline_access` (without it Microsoft returns no refresh token and the
     mailbox stops working roughly an hour after it is linked)
4. Create a client secret.
5. Put both values in `.env` and restart:

   ```
   MICROSOFT_OAUTH_CLIENT_ID=...
   MICROSOFT_OAUTH_CLIENT_SECRET=...
   ```

   A single-tenant registration can also set `MICROSOFT_OAUTH_TENANT` to the
   tenant id or domain. The default is `common`, which accepts both work or
   school accounts and personal Microsoft accounts.

## Then, per mailbox

Choose the **Outlook / Office 365** preset, press **Sign in with Microsoft**, and
approve. The callback fills in the host, port, security mode, username and
from-address from the account you signed in to — nothing else needs typing.

## Server settings, for reference

| | Host | Port | Security |
|---|---|---|---|
| IMAP | `outlook.office365.com` | 993 | TLS |
| SMTP (Microsoft 365) | `smtp.office365.com` | 587 | STARTTLS |
| SMTP (personal Outlook.com) | `smtp-mail.outlook.com` | 587 | STARTTLS |

Both SMTP hosts are accepted; the preset fills in the first. POP and IMAP access
must be enabled on a personal Outlook.com account before it will connect.

## If it does not work

- **`redirect_uri_mismatch`** — the URI registered in Entra is not byte-identical
  to the one the form prints. The form also says where that value came from
  (`request`, `app_public_url`, an environment variable), which is usually the
  thing that is wrong.
- **The button is greyed out** — the client id or the client secret is missing
  from this deployment's `.env`. The button reports that before it is pressed
  rather than after you have already granted access.
- **The mailbox works for an hour and then stops** — `offline_access` was not
  granted, so no refresh token was issued.
