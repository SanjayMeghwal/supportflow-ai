"""SupportFlow AI — Deterministic Demo Seed & Reset Script.

Purpose:
    Seeds a reproducible, realistic dataset showcasing:
      - 3 Demo Roles: Customer (Alice Johnson), Agent, Admin
      - 4 Realistic Tickets covering different categories, priorities, and statuses
      - 5 Knowledge Base Documents ingested into pgvector with real embeddings
      - 3 E-Commerce Orders with payments for bounded tool calling & IDOR demonstrations
      - 1 Pending Human-In-The-Loop Review for agent triage

Usage:
    python scripts/demo_seed.py           # Seed demo data (idempotent)
    python scripts/demo_seed.py --reset   # Clean demo data and re-seed fresh

Security Notice:
    THESE ACCOUNTS AND CREDENTIALS ARE FOR LOCAL DEMONSTRATION ONLY.
    NEVER RUN THIS SCRIPT IN A PRODUCTION ENVIRONMENT WITH LIVE USER DATA.
"""

import argparse
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.app.core.config import settings
from backend.app.core.security import hash_password
from backend.app.models.ai import (
    AIRun,
    AIRunStatus,
    AIToolInvocation,
    HumanReview,
    ReviewStatus,
)
from backend.app.models.knowledge import DocumentChunk, KnowledgeDocument, SourceType
from backend.app.models.order import (
    Order,
    OrderStatus,
    Payment,
    PaymentMethod,
    PaymentStatus,
)
from backend.app.models.ticket import (
    SenderType,
    Ticket,
    TicketCategory,
    TicketMessage,
    TicketPriority,
    TicketStatus,
)
from backend.app.models.user import Customer, CustomerTier, User, UserRole
from backend.app.services.knowledge import KnowledgeService

# Default demo credentials (configurable via environment variables)
DEMO_CUSTOMER_EMAIL = os.getenv("DEMO_CUSTOMER_EMAIL", "demo.customer@example.com")
DEMO_CUSTOMER_PASSWORD = os.getenv("DEMO_CUSTOMER_PASSWORD", "DemoCustomer123!")

DEMO_AGENT_EMAIL = os.getenv("DEMO_AGENT_EMAIL", "demo.agent@example.com")
DEMO_AGENT_PASSWORD = os.getenv("DEMO_AGENT_PASSWORD", "DemoAgent123!")

DEMO_ADMIN_EMAIL = os.getenv("DEMO_ADMIN_EMAIL", "demo.admin@example.com")
DEMO_ADMIN_PASSWORD = os.getenv("DEMO_ADMIN_PASSWORD", "DemoAdmin123!")

# Knowledge Document Contents
KNOWLEDGE_DOCS = [
    {
        "title": "Password Reset Policy",
        "filename": "password_reset_policy.md",
        "source_type": SourceType.MARKDOWN,
        "content": """# Password Reset Policy and Troubleshooting

## Self-Service Password Reset
Customers can initiate a password reset by navigating to the login page and clicking "Forgot Password". A secure, one-time verification link will be sent to the registered email address.

- **Link Expiration:** The reset link expires exactly 15 minutes after issuance.
- **Single-Use Invariant:** Each link can be used only once. Subsequent attempts require generating a new link.
- **Spam and Filtering:** If the reset email does not arrive within 3 minutes, customers should inspect their spam or promotions folders, or verify they are querying the exact registered email.

## Account Lockout Mechanism
For security, an account is automatically locked after 5 consecutive failed login attempts within a 30-minute window. When locked:
1. Automated password resets via email are suspended for 60 minutes.
2. A support agent can manually verify customer identity and dispatch an emergency unlock link.
3. Passwords must be at least 8 characters long and contain at least one uppercase letter, one number, and one special character.
""",
    },
    {
        "title": "Refund Policy",
        "filename": "refund_policy.md",
        "source_type": SourceType.MARKDOWN,
        "content": """# Refund and Return Policy

## 30-Day Money-Back Guarantee
Customers may request a full refund on eligible physical products within 30 calendar days of delivery. To qualify:
- Items must be returned in their original packaging with all included accessories.
- A valid order number (e.g., ORD-2024-XXXX) must accompany the return request.
- Clearance or personalized items marked "Final Sale" are non-refundable.

## Processing Timelines
Once returned merchandise arrives at our fulfillment center:
1. **Inspection:** Quality inspection takes 1 to 2 business days.
2. **Refund Authorization:** Once approved, the refund is initiated to the original payment method (Credit Card, Debit Card, or UPI).
3. **Banking Posting:** Credit card refunds take 5 to 7 business days to appear on customer bank statements, depending on the issuing institution.
4. **UPI Refunds:** UPI transactions typically reflect within 24 to 48 hours.

## Escalation for Delayed Refunds
If a refund was initiated but has not appeared on the customer account after 10 business days, support agents must verify the gateway transaction reference and escalate the ticket to the Finance Operations desk.
""",
    },
    {
        "title": "Shipping Policy",
        "filename": "shipping_policy.md",
        "source_type": SourceType.MARKDOWN,
        "content": """# Shipping & Delivery Guidelines

## Standard Shipping
- **Transit Time:** Standard domestic shipping takes 3 to 5 business days from the dispatch date.
- **Dispatch Cutoff:** Orders placed before 2:00 PM EST on business days are dispatched on the same day. Orders placed after 2:00 PM EST or on weekends are dispatched the next business day.
- **Carrier Partners:** Standard shipments are handled by FedEx Ground and UPS Standard.
- **Shipping Rates:** Free standard shipping is provided on all orders totaling $50.00 or higher. For orders under $50.00, a flat fee of $4.99 applies.

## Expedited and Express Shipping
- **Express Shipping:** 1 to 2 business days delivery for a flat rate of $14.99.
- **Next-Day Air:** Guaranteed delivery by 12:00 PM the following business day for $24.99.

## International Shipping
International shipping is available to select countries and takes 7 to 14 business days. Custom duties and import tariffs are calculated at checkout.
""",
    },
    {
        "title": "Account Security Policy",
        "filename": "account_security_policy.md",
        "source_type": SourceType.MARKDOWN,
        "content": """# Customer Account Security & Credential Protection

## Multi-Factor Authentication (MFA)
SupportFlow AI strongly encourages all customers and support personnel to enable Multi-Factor Authentication via TOTP authenticator apps (Google Authenticator, Authy, or 1Password).

## Session Management
- Authentication tokens (JWT) have an active lifespan of 60 minutes.
- Refresh tokens expire after 7 days of inactivity.
- Logging in from a new IP address or country automatically triggers a security verification notice via email.

## Credential Leakage & Breach Protocol
If an account is flagged for credential stuffing or exposed credentials in public databases:
- The session is immediately revoked across all devices.
- The account is placed in `RESTRICTED` status until the customer contacts verified support and completes identity verification.
""",
    },
    {
        "title": "Escalation Policy",
        "filename": "escalation_policy.md",
        "source_type": SourceType.MARKDOWN,
        "content": """# Support Operations Escalation Policy

## Deterministic Human Review Triggers
SupportFlow AI automatically transfers inquiries to human agents under any of the following conditions:
1. **Low Retrieval Confidence:** If the hybrid RAG retrieval confidence score falls below 0.70.
2. **Missing Knowledge Base Context:** If no relevant documents match the customer's query.
3. **High-Risk Business Actions:** Any request to initiate refunds exceeding $500.00, cancel already-shipped orders, or modify account ownership.
4. **Sentiment / Legal Keywords:** Explicit customer mentions of legal action, regulatory complaints, attorneys, chargebacks, or supervisor demands.
5. **Tool Failures or IDOR Denials:** Any attempted access to unowned customer records or unexpected API tool failure.

## Review Queue SLAs
- **Urgent Priority:** Human review within 15 minutes.
- **High Priority:** Human review within 1 hour.
- **Medium Priority:** Human review within 4 hours.
""",
    },
]


async def seed_demo_database(reset: bool = False, use_test_db: bool = False) -> None:
    """Execute the demo seeding workflow."""
    db_url = settings.async_test_database_url if use_test_db else settings.DATABASE_URL
    print(f"\n[SupportFlow AI] Connecting to: {db_url}")

    engine = create_async_engine(db_url, echo=False)
    session_maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with session_maker() as session:
        if reset:
            print("[SupportFlow AI] --reset flag supplied. Purging existing demo records...")
            # Clean up existing demo users and cascade relations
            demo_emails = [
                DEMO_CUSTOMER_EMAIL,
                DEMO_AGENT_EMAIL,
                DEMO_ADMIN_EMAIL,
                "rahul.sharma@example.com",
                "emily.carter@example.com",
            ]
            user_res = await session.execute(select(User).where(User.email.in_(demo_emails)))
            existing_users = user_res.scalars().all()
            for u in existing_users:
                await session.delete(u)

            # Clean up knowledge documents
            for doc_spec in KNOWLEDGE_DOCS:
                k_res = await session.execute(
                    select(KnowledgeDocument).where(KnowledgeDocument.title == doc_spec["title"])
                )
                for kd in k_res.scalars().all():
                    await session.delete(kd)

            await session.commit()
            print("[SupportFlow AI] Purge completed successfully.")

        # -------------------------------------------------------------------
        # 1. Seed Users & Customer Profiles
        # -------------------------------------------------------------------
        print("\n[1/5] Seeding Demo Users & Profiles...")

        # A. Customer: Alice Johnson
        res = await session.execute(select(User).where(User.email == DEMO_CUSTOMER_EMAIL))
        alice_user = res.scalar_one_or_none()
        if not alice_user:
            alice_user = User(
                email=DEMO_CUSTOMER_EMAIL,
                hashed_password=hash_password(DEMO_CUSTOMER_PASSWORD),
                role=UserRole.CUSTOMER,
                is_active=True,
            )
            session.add(alice_user)
            await session.flush()

            alice_customer = Customer(
                user_id=alice_user.id,
                full_name="Alice Johnson",
                phone_number="+1-555-0101",
                tier=CustomerTier.PREMIUM,
            )
            session.add(alice_customer)
            await session.flush()
            print(f"  + Created Customer: {DEMO_CUSTOMER_EMAIL} (Alice Johnson, Tier: PREMIUM)")
        else:
            cust_res = await session.execute(select(Customer).where(Customer.user_id == alice_user.id))
            alice_customer = cust_res.scalar_one_or_none()
            print(f"  = Exists: {DEMO_CUSTOMER_EMAIL}")

        # B. Agent: Demo Agent
        res = await session.execute(select(User).where(User.email == DEMO_AGENT_EMAIL))
        agent_user = res.scalar_one_or_none()
        if not agent_user:
            agent_user = User(
                email=DEMO_AGENT_EMAIL,
                hashed_password=hash_password(DEMO_AGENT_PASSWORD),
                role=UserRole.SUPPORT_AGENT,
                is_active=True,
            )
            session.add(agent_user)
            await session.flush()
            print(f"  + Created Agent:    {DEMO_AGENT_EMAIL} (Support Agent)")
        else:
            print(f"  = Exists: {DEMO_AGENT_EMAIL}")

        # C. Admin: Demo Admin
        res = await session.execute(select(User).where(User.email == DEMO_ADMIN_EMAIL))
        admin_user = res.scalar_one_or_none()
        if not admin_user:
            admin_user = User(
                email=DEMO_ADMIN_EMAIL,
                hashed_password=hash_password(DEMO_ADMIN_PASSWORD),
                role=UserRole.ADMIN,
                is_active=True,
            )
            session.add(admin_user)
            await session.flush()
            print(f"  + Created Admin:    {DEMO_ADMIN_EMAIL} (System Admin)")
        else:
            print(f"  = Exists: {DEMO_ADMIN_EMAIL}")

        # D. Secondary Customer: Rahul Sharma (for IDOR demonstration)
        res = await session.execute(select(User).where(User.email == "rahul.sharma@example.com"))
        rahul_user = res.scalar_one_or_none()
        if not rahul_user:
            rahul_user = User(
                email="rahul.sharma@example.com",
                hashed_password=hash_password("RahulSharma123!"),
                role=UserRole.CUSTOMER,
                is_active=True,
            )
            session.add(rahul_user)
            await session.flush()

            rahul_customer = Customer(
                user_id=rahul_user.id,
                full_name="Rahul Sharma",
                phone_number="+1-555-0202",
                tier=CustomerTier.STANDARD,
            )
            session.add(rahul_customer)
            await session.flush()
            print("  + Created Customer: rahul.sharma@example.com (Rahul Sharma, Tier: STANDARD)")
        else:
            cust_res = await session.execute(select(Customer).where(Customer.user_id == rahul_user.id))
            rahul_customer = cust_res.scalar_one_or_none()

        await session.commit()

        # -------------------------------------------------------------------
        # 2. Seed Orders & Payments (for Bounded AI Tools)
        # -------------------------------------------------------------------
        print("\n[2/5] Seeding E-Commerce Orders & Payments for Bounded Tools...")

        # Alice's Order 1 (ORD-2024-1001) - SHIPPED
        ord1_res = await session.execute(select(Order).where(Order.order_number == "ORD-2024-1001"))
        order1 = ord1_res.scalar_one_or_none()
        if not order1:
            order1 = Order(
                order_number="ORD-2024-1001",
                customer_id=alice_customer.id,
                total_amount=Decimal("149.99"),
                currency="USD",
                order_status=OrderStatus.SHIPPED,
                items_json=[
                    {"item": "Wireless Noise-Canceling Headphones", "qty": 1, "price": 149.99}
                ],
            )
            session.add(order1)
            await session.flush()

            pay1 = Payment(
                order_id=order1.id,
                transaction_reference="TXN-2024-98765",
                amount=Decimal("149.99"),
                payment_method=PaymentMethod.CREDIT_CARD,
                payment_status=PaymentStatus.SUCCESS,
            )
            session.add(pay1)
            print("  + Created Order: ORD-2024-1001 (Customer: Alice Johnson, Status: SHIPPED)")
        else:
            print("  = Exists: ORD-2024-1001")

        # Alice's Order 2 (ORD-2024-1002) - PROCESSING
        ord2_res = await session.execute(select(Order).where(Order.order_number == "ORD-2024-1002"))
        order2 = ord2_res.scalar_one_or_none()
        if not order2:
            order2 = Order(
                order_number="ORD-2024-1002",
                customer_id=alice_customer.id,
                total_amount=Decimal("45.00"),
                currency="USD",
                order_status=OrderStatus.PROCESSING,
                items_json=[{"item": "USB-C Fast Charging Hub", "qty": 1, "price": 45.00}],
            )
            session.add(order2)
            await session.flush()

            pay2 = Payment(
                order_id=order2.id,
                transaction_reference="TXN-2024-98766",
                amount=Decimal("45.00"),
                payment_method=PaymentMethod.UPI,
                payment_status=PaymentStatus.SUCCESS,
            )
            session.add(pay2)
            print("  + Created Order: ORD-2024-1002 (Customer: Alice Johnson, Status: PROCESSING)")
        else:
            print("  = Exists: ORD-2024-1002")

        # Rahul's Order (ORD-2024-2002) - DELIVERED (belongs to Rahul, NOT Alice -> tests IDOR!)
        ord3_res = await session.execute(select(Order).where(Order.order_number == "ORD-2024-2002"))
        order3 = ord3_res.scalar_one_or_none()
        if not order3:
            order3 = Order(
                order_number="ORD-2024-2002",
                customer_id=rahul_customer.id,
                total_amount=Decimal("89.50"),
                currency="USD",
                order_status=OrderStatus.DELIVERED,
                items_json=[{"item": "Mechanical Gaming Keyboard", "qty": 1, "price": 89.50}],
            )
            session.add(order3)
            await session.flush()

            pay3 = Payment(
                order_id=order3.id,
                transaction_reference="TXN-2024-55443",
                amount=Decimal("89.50"),
                payment_method=PaymentMethod.DEBIT_CARD,
                payment_status=PaymentStatus.SUCCESS,
            )
            session.add(pay3)
            print("  + Created Order: ORD-2024-2002 (Customer: Rahul Sharma, for IDOR checks)")
        else:
            print("  = Exists: ORD-2024-2002")

        await session.commit()

        # -------------------------------------------------------------------
        # 3. Seed Knowledge Documents & pgvector Embeddings
        # -------------------------------------------------------------------
        print("\n[3/5] Ingesting Knowledge Base Documents with Dense Vector Embeddings...")
        ks = KnowledgeService()

        for doc_item in KNOWLEDGE_DOCS:
            existing_doc = await session.execute(
                select(KnowledgeDocument).where(KnowledgeDocument.title == doc_item["title"])
            )
            if existing_doc.scalar_one_or_none() is None:
                doc = await ks.ingest_document(
                    db=session,
                    title=doc_item["title"],
                    content_bytes=doc_item["content"].encode("utf-8"),
                    filename=doc_item["filename"],
                    source_type=doc_item["source_type"],
                )
                chunk_count = await session.execute(
                    select(DocumentChunk).where(DocumentChunk.document_id == doc.id)
                )
                chunks = chunk_count.scalars().all()
                print(f"  + Ingested '{doc.title}' ({len(chunks)} chunks vectorized with pgvector)")
            else:
                print(f"  = Exists: '{doc_item['title']}'")

        # -------------------------------------------------------------------
        # 4. Seed Support Tickets & Lifecycle Messages
        # -------------------------------------------------------------------
        print("\n[4/5] Seeding Support Tickets...")

        # Ticket 1: Password reset issue (OPEN)
        t1_res = await session.execute(
            select(Ticket).where(Ticket.title == "Unable to reset my password")
        )
        t1 = t1_res.scalar_one_or_none()
        if not t1:
            t1 = Ticket(
                ticket_number="TKT-DEMO-001",
                customer_id=alice_customer.id,
                title="Unable to reset my password",
                description="I clicked 'Forgot Password' multiple times today but haven't received the reset link in my inbox or spam folder.",
                category=TicketCategory.TECHNICAL,
                priority=TicketPriority.HIGH,
                status=TicketStatus.OPEN,
            )
            session.add(t1)
            await session.flush()

            m1 = TicketMessage(
                ticket_id=t1.id,
                sender_id=alice_user.id,
                sender_type=SenderType.CUSTOMER,
                content="I clicked 'Forgot Password' multiple times today but haven't received the reset link in my inbox or spam folder.",
                is_internal_note=False,
            )
            session.add(m1)
            print("  + Ticket 1: #TKT-DEMO-001 'Unable to reset my password' (OPEN)")
        else:
            print("  = Exists: Ticket 1 (#TKT-DEMO-001)")

        # Ticket 2: Refund has not appeared (PENDING_AGENT_REVIEW) - Escalated!
        t2_res = await session.execute(
            select(Ticket).where(Ticket.title == "Refund has not appeared on my account")
        )
        t2 = t2_res.scalar_one_or_none()
        if not t2:
            t2 = Ticket(
                ticket_number="TKT-DEMO-002",
                customer_id=alice_customer.id,
                title="Refund has not appeared on my account",
                description="I returned the defective headset two weeks ago under order ORD-2024-1001, but the refund hasn't shown up on my bank statement. Can someone check?",
                category=TicketCategory.BILLING,
                priority=TicketPriority.HIGH,
                status=TicketStatus.PENDING_AGENT_REVIEW,
            )
            session.add(t2)
            await session.flush()

            m2 = TicketMessage(
                ticket_id=t2.id,
                sender_id=alice_user.id,
                sender_type=SenderType.CUSTOMER,
                content="I returned the defective headset two weeks ago under order ORD-2024-1001, but the refund hasn't shown up on my bank statement. Can someone check?",
                is_internal_note=False,
            )
            session.add(m2)

            # Create AI Run record
            ai_run = AIRun(
                ticket_id=t2.id,
                model_name="llama-3.3-70b-versatile",
                intent_detected="REFUND_INQUIRY",
                confidence_score=Decimal("0.680"),
                execution_status=AIRunStatus.ESCALATED_LOW_CONFIDENCE,
                prompt_tokens=420,
                completion_tokens=85,
                latency_ms=890,
                response_text="I verified that your order ORD-2024-1001 was delivered and returned. However, because the refund confirmation exceeds 10 business days, I am routing this inquiry to our human billing operations team for manual verification.",
            )
            session.add(ai_run)
            await session.flush()

            # Create Human Review record in the agent queue
            review = HumanReview(
                ticket_id=t2.id,
                ai_run_id=ai_run.id,
                status=ReviewStatus.PENDING,
                escalation_reason="Billing refund dispute exceeded 10-day banking window; low confidence (0.68 < 0.70 threshold)",
                original_ai_draft="I verified that your order ORD-2024-1001 was delivered and returned. However, because the refund confirmation exceeds 10 business days, I am routing this inquiry to our human billing operations team for manual verification.",
            )
            session.add(review)
            print("  + Ticket 2: #TKT-DEMO-002 'Refund has not appeared on my account' (PENDING_AGENT_REVIEW)")
        else:
            print("  = Exists: Ticket 2 (#TKT-DEMO-002)")

        # Ticket 3: Shipping inquiry (RESOLVED)
        t3_res = await session.execute(
            select(Ticket).where(Ticket.title == "How long does standard shipping take?")
        )
        t3 = t3_res.scalar_one_or_none()
        if not t3:
            t3 = Ticket(
                ticket_number="TKT-DEMO-003",
                customer_id=alice_customer.id,
                title="How long does standard shipping take?",
                description="Hi, I placed an order with standard shipping. How many days should I expect before delivery?",
                category=TicketCategory.ORDER_STATUS,
                priority=TicketPriority.MEDIUM,
                status=TicketStatus.RESOLVED,
                resolution_summary="Provided standard delivery timeframe (3–5 business days) per company shipping policy.",
                closed_at=datetime.now(timezone.utc),
            )
            session.add(t3)
            await session.flush()

            m3_1 = TicketMessage(
                ticket_id=t3.id,
                sender_id=alice_user.id,
                sender_type=SenderType.CUSTOMER,
                content="Hi, I placed an order with standard shipping. How many days should I expect before delivery?",
                is_internal_note=False,
            )
            m3_2 = TicketMessage(
                ticket_id=t3.id,
                sender_id=None,
                sender_type=SenderType.AI_SYSTEM,
                content="Standard domestic shipping takes 3 to 5 business days from the dispatch date. Orders placed before 2:00 PM EST ship the same business day, and orders over $50 include free standard shipping.",
                is_internal_note=False,
            )
            m3_3 = TicketMessage(
                ticket_id=t3.id,
                sender_id=alice_user.id,
                sender_type=SenderType.CUSTOMER,
                content="Thank you, that answers my question perfectly!",
                is_internal_note=False,
            )
            session.add_all([m3_1, m3_2, m3_3])
            print("  + Ticket 3: #TKT-DEMO-003 'How long does standard shipping take?' (RESOLVED)")
        else:
            print("  = Exists: Ticket 3 (#TKT-DEMO-003)")

        # Ticket 4: Account locked (IN_PROGRESS)
        t4_res = await session.execute(
            select(Ticket).where(Ticket.title == "Account locked after multiple login attempts")
        )
        t4 = t4_res.scalar_one_or_none()
        if not t4:
            t4 = Ticket(
                ticket_number="TKT-DEMO-004",
                customer_id=alice_customer.id,
                assigned_agent_id=agent_user.id,
                title="Account locked after multiple login attempts",
                description="My account says locked out after typing my password wrong. Need urgent access to download my invoice.",
                category=TicketCategory.TECHNICAL,
                priority=TicketPriority.URGENT,
                status=TicketStatus.IN_PROGRESS,
            )
            session.add(t4)
            await session.flush()

            m4_1 = TicketMessage(
                ticket_id=t4.id,
                sender_id=alice_user.id,
                sender_type=SenderType.CUSTOMER,
                content="My account says locked out after typing my password wrong. Need urgent access to download my invoice.",
                is_internal_note=False,
            )
            m4_2 = TicketMessage(
                ticket_id=t4.id,
                sender_id=agent_user.id,
                sender_type=SenderType.AGENT,
                content="Hello Alice, I have verified your profile and unlocked your account. You will receive an email confirmation shortly.",
                is_internal_note=False,
            )
            m4_note = TicketMessage(
                ticket_id=t4.id,
                sender_id=agent_user.id,
                sender_type=SenderType.AGENT,
                content="Verified caller phone number matching record ending in 0101 before releasing account lock.",
                is_internal_note=True,
            )
            session.add_all([m4_1, m4_2, m4_note])
            print("  + Ticket 4: #TKT-DEMO-004 'Account locked after multiple login attempts' (IN_PROGRESS)")
        else:
            print("  = Exists: Ticket 4 (#TKT-DEMO-004)")

        await session.commit()

        # -------------------------------------------------------------------
        # 5. Summary & Verification
        # -------------------------------------------------------------------
        print("\n" + "=" * 65)
        print(" SupportFlow AI — Demo Environment Successfully Initialized")
        print("=" * 65)
        print("\nDEMO ACCOUNTS (FOR LOCAL DEMONSTRATION ONLY):")
        print("  Role      Email                       Password")
        print("  --------  --------------------------  ----------------")
        print(f"  CUSTOMER  {DEMO_CUSTOMER_EMAIL:<26}  {DEMO_CUSTOMER_PASSWORD}")
        print(f"  AGENT     {DEMO_AGENT_EMAIL:<26}  {DEMO_AGENT_PASSWORD}")
        print(f"  ADMIN     {DEMO_ADMIN_EMAIL:<26}  {DEMO_ADMIN_PASSWORD}")
        print("\nDEMO DATA OVERVIEW:")
        print("  - Customers: Alice Johnson (Premium), Rahul Sharma (Standard)")
        print("  - Tickets:   4 realistic tickets across all statuses (OPEN, PENDING_AGENT_REVIEW, RESOLVED, IN_PROGRESS)")
        print("  - Orders:    ORD-2024-1001 (Shipped), ORD-2024-1002 (Processing), ORD-2024-2002 (Rahul's order)")
        print("  - Reviews:   1 Pending Human Review ready in Agent Review Queue")
        print("  - Documents: 5 Ingested Policies with pgvector vector embeddings")
        print("=" * 65 + "\n")

    await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description="SupportFlow AI Demo Data Seed Script")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Purge existing demo data before re-seeding",
    )
    parser.add_argument(
        "--test-db",
        action="store_true",
        help="Seed into the test database (supportflow_test_db)",
    )
    args = parser.parse_args()

    asyncio.run(seed_demo_database(reset=args.reset, use_test_db=args.test_db))


if __name__ == "__main__":
    main()
