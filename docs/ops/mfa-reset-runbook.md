# MFA reset runbook (lost authenticator)

MFA (TOTP) is mandatory for admin-class users: Owner, and anyone who can manage users or roles (Q01-03). This runbook is for a user who can no longer produce a code.

## 1. First choice: a backup code

At enrolment (`/auth/mfa/confirm`) every user gets **10 one-time backup codes**, shown once on the enrolment screen.
- On the sign-in code screen, choose **Use a backup code** and type one. Case, spaces and the dash don't matter.
- Each code works once. Every use is audited as `auth.mfa` / `mfa_backup_code_used`, with the number of codes left.

If the user still has a code, stop here. Once they are signed in they should reset their MFA (step 2) to get a new authenticator and new codes; there is no in-app "regenerate" yet.

## 2. Break-glass: ops reset (no codes left)

Nobody in the org can reset a sole Owner from the app, so this runs on the server.

1. **Verify identity out of band.** Call the person on a number you already have on file, and record a ticket or call reference. The reset hands the account to whoever knows the password.
2. On the server, from `backend/`, with migration-level DB access:

   ```bash
   MIGRATION_DATABASE_URL=postgresql://fabric:...@localhost:5432/fabric_erp \
     uv run python -m scripts.reset_mfa \
       --email owner@example.com \
       --org "Rajesh Textiles" \
       --reason "lost phone; verified by call 2026-10-12, ticket #123"
   ```

   - `--org` must be the organization name exactly as typed at login.
   - Exit code `0` prints `MFA reset for … : enrolment cleared, N session(s) revoked …`.
   - Exit code `2` means the org or user was not found; nothing was changed.

3. What the reset did, in one transaction:
   - cleared `mfa_enabled`, the TOTP secret and the backup codes
   - bumped `permissions_version`, so every outstanding access token is rejected on its next request
   - revoked all of the user's refresh sessions
   - wrote the audit row `auth.mfa` / `mfa_reset` (`user_id` NULL = system), with your `--reason`
4. Tell the user to sign in. As an admin-class user they are taken straight to MFA setup. They scan the new key, confirm a code, and **save the 10 new backup codes**.

## 3. Afterwards

- Check the audit log for the `mfa_reset` row and file it with the ticket.
- If the request looked suspicious, rotate the user's password too (`/auth/forgot`).
