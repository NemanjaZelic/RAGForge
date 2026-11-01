# Transactions

## Rollback
A failed transaction rolls back all of its writes.
After rollback, the connection remains usable for a new transaction.

## Savepoints
A savepoint allows a partial rollback within an open transaction.
Releasing a savepoint does not commit the outer transaction.

## Retry
The caller may retry a transaction after a transient conflict.
Retries use exponential backoff and must not repeat external side effects.
