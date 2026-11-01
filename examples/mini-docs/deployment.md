# Deployment

## Health checks
The private service exposes /health for its process health check.
Health checks never return document snippets or credentials.

## Bundle updates
New bundles are published in separate version directories.
A smoke query must pass before switching the active bundle pointer.

## Recovery
If a new bundle fails its smoke query, keep the previous bundle active.
An operator can roll back by selecting the previous version.
