import uuid
from decimal import Decimal
import pytest
from backend.app.models import (
    Base,
    User,
    UserRole,
    Customer,
    CustomerTier,
    Ticket,
    TicketCategory,
    TicketPriority,
    TicketStatus,
    TicketMessage,
    SenderType,
    Order,
    OrderStatus,
    Payment,
    PaymentMethod,
    PaymentStatus,
    KnowledgeDocument,
    DocumentChunk,
    SourceType,
    AIRun,
    AIRunStatus,
    AIToolInvocation,
    HumanReview,
    ReviewAction,
    AuditLog,
)


def test_metadata_contains_all_twelve_tables():
    """Verify that all 12 core tables are registered in Base.metadata."""
    expected_tables = {
        "users",
        "customers",
        "tickets",
        "ticket_messages",
        "orders",
        "payments",
        "knowledge_documents",
        "document_chunks",
        "ai_runs",
        "ai_tool_invocations",
        "human_reviews",
        "audit_logs",
    }
    actual_tables = set(Base.metadata.tables.keys())
    assert expected_tables.issubset(actual_tables), (
        f"Missing tables: {expected_tables - actual_tables}"
    )


def test_user_and_customer_instantiation():
    """Verify User and Customer model attributes and defaults."""
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        email="support@example.com",
        hashed_password="fake_hashed_password",
        role=UserRole.SUPPORT_AGENT,
        is_active=True,
    )
    assert user.id == user_id
    assert user.email == "support@example.com"
    assert user.role == UserRole.SUPPORT_AGENT
    assert user.is_active is True

    customer = Customer(
        user_id=user_id,
        full_name="John Doe",
        phone_number="+919876543210",
        tier=CustomerTier.VIP,
    )
    assert customer.user_id == user_id
    assert customer.full_name == "John Doe"
    assert customer.tier == CustomerTier.VIP


def test_ticket_and_message_instantiation():
    """Verify Ticket and TicketMessage lifecycle states and enums."""
    cust_id = uuid.uuid4()
    ticket = Ticket(
        ticket_number="TICK-2026-0001",
        customer_id=cust_id,
        title="Charged twice for order",
        description="I was charged 2000 INR but order shows cancelled.",
        category=TicketCategory.BILLING,
        priority=TicketPriority.HIGH,
        status=TicketStatus.OPEN,
    )
    assert ticket.ticket_number == "TICK-2026-0001"
    assert ticket.category == TicketCategory.BILLING
    assert ticket.priority == TicketPriority.HIGH
    assert ticket.status == TicketStatus.OPEN

    message = TicketMessage(
        ticket_id=ticket.id,
        sender_type=SenderType.CUSTOMER,
        content="Please refund my money.",
        is_internal_note=False,
    )
    assert message.sender_type == SenderType.CUSTOMER
    assert message.is_internal_note is False


def test_order_and_payment_models():
    """Verify Order and Payment models with monetary decimals and items JSON."""
    cust_id = uuid.uuid4()
    order = Order(
        order_number="ORD-99214",
        customer_id=cust_id,
        total_amount=Decimal("2000.00"),
        currency="INR",
        order_status=OrderStatus.CANCELLED,
        items_json=[{"sku": "SKU-100", "name": "Wireless Headphones", "quantity": 1, "price": 2000.0}],
    )
    assert order.total_amount == Decimal("2000.00")
    assert order.order_status == OrderStatus.CANCELLED
    assert len(order.items_json) == 1

    payment = Payment(
        order_id=order.id,
        transaction_reference="TXN_UPI_987654321",
        amount=Decimal("2000.00"),
        payment_method=PaymentMethod.UPI,
        payment_status=PaymentStatus.SUCCESS,
    )
    assert payment.payment_method == PaymentMethod.UPI
    assert payment.payment_status == PaymentStatus.SUCCESS


def test_knowledge_base_pgvector_chunk_column():
    """Verify that document_chunks table defines the pgvector embedding column."""
    chunks_table = Base.metadata.tables["document_chunks"]
    assert "embedding" in chunks_table.c
    assert "chunk_text" in chunks_table.c
    assert "metadata_json" in chunks_table.c


def test_ai_run_and_human_review_models():
    """Verify AI observability and Human-In-The-Loop review data models."""
    ticket_id = uuid.uuid4()
    ai_runs_table = Base.metadata.tables["ai_runs"]
    assert "response_text" in ai_runs_table.c

    ai_run = AIRun(
        ticket_id=ticket_id,
        model_name="llama-3.3-70b-versatile",
        intent_detected="BILLING_REFUND",
        confidence_score=Decimal("0.520"),
        execution_status=AIRunStatus.ESCALATED_LOW_CONFIDENCE,
        prompt_tokens=450,
        completion_tokens=85,
        latency_ms=620,
        response_text="Draft: Refund of INR 2000 has been verified.",
    )
    assert ai_run.execution_status == AIRunStatus.ESCALATED_LOW_CONFIDENCE
    assert ai_run.confidence_score == Decimal("0.520")
    assert ai_run.response_text == "Draft: Refund of INR 2000 has been verified."

    review = HumanReview(
        ticket_id=ticket_id,
        ai_run_id=ai_run.id,
        reviewer_id=uuid.uuid4(),
        action_taken=ReviewAction.APPROVED,
        original_ai_draft="Your refund of INR 2000 is under processing.",
        final_submitted_text="Your refund of INR 2000 is under processing and will take 5-7 business days.",
        feedback_notes="Added explicit business day timeline per policy.",
    )
    assert review.action_taken == ReviewAction.APPROVED
    assert "5-7 business days" in review.final_submitted_text
