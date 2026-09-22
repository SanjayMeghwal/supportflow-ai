# ADR-003: UUIDv4 Primary Keys Across Domain Entities

## Status
Accepted

## Context
Standard relational designs often default to auto-incrementing integer IDs (`1, 2, 3...`).
In support platforms and multi-tenant architectures, sequential integers introduce severe security risks (enumeration attacks, guessing ticket IDs, leaking total business inquiry volume) and make distributed data migration or horizontal scaling difficult.

## Decision
All domain entities implement **UUIDv4 (`UUID(as_uuid=True)`) primary keys** via a shared `UUIDPrimaryKeyMixin`. Human-readable identifiers (such as `ticket_number` `TICK-2026-0001` or `order_number` `ORD-99214`) are stored as separate unique, indexed string columns.

## Consequences & Trade-offs
### Positive
- **Security by Infeasibility:** Prevents ID enumeration attacks across external endpoints.
- **Client/Agent Correlation:** UUIDs can be generated on the client or within background worker queues prior to persistence without colliding.
- **Clear Separation:** Decouples internal database object identification from public customer reference numbers.

### Negative / Mitigations
- **Index Footprint:** 16-byte UUIDs consume more index space than 4-byte or 8-byte integers.
- *Mitigation:* Modern hardware easily manages this overhead for the volume of support tickets, and PostgreSQL's native `uuid` type is heavily optimized.
