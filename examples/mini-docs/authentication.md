# Authentication

## Access tokens
Clients send an access token in the Authorization header using the Bearer scheme.
An access token expires after 15 minutes. Tokens are never written to application logs.

## Refresh tokens
Refresh tokens are rotated after every successful refresh.
Reusing a rotated refresh token revokes its token family.

## Revocation
Administrators revoke a session by its session identifier.
Revocation takes effect before the next protected request is authorized.
