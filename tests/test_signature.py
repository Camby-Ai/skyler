"""The signature is appended in code, once, to every staged email."""

import pytest

from skyler.gate import pre_send_check, with_signature
from skyler.models.campaign import Campaign, EmailStep
from skyler.models.conversation import Conversation

from tests.test_outbox_native import (  # reuse the native-path fixtures
    FakeProvider, make_handler, make_sender, seed_prospect, state,  # noqa: F401
)

SIG = "Jane Doe\n555.0100\n1 Main St, Somewhere, CA 90000\nReply STOP to opt out"


def test_with_signature_appends_once():
    out = with_signature("Hello there.\n\nQuick question?", SIG)
    assert out.endswith("\n\n" + SIG)
    assert out.count("Reply STOP to opt out") == 1


def test_with_signature_is_idempotent():
    once = with_signature("Body.", SIG)
    assert with_signature(once, SIG) == once


def test_with_signature_detects_model_written_signature_despite_whitespace():
    body = "Body.\n\nJane Doe  \n 555.0100\n1 Main St,  Somewhere, CA 90000\nReply STOP to opt out\n"
    assert with_signature(body, SIG).count("555.0100") == 1


def test_with_signature_noop_when_unset():
    assert with_signature("Body.", "") == "Body."
    assert with_signature("  Body. ", None) == "Body."


def test_signed_body_passes_gate():
    body = with_signature("Noticed the office has no online booking. Who handles after-hours calls?", SIG)
    assert pre_send_check("jane@acme.com", "after hours calls", body)


@pytest.mark.asyncio
async def test_sender_stages_with_signature(state):
    pid = await seed_prospect(state)
    camp = Campaign(
        id="", name="c", channel="email", status="draft", prospect_ids=[pid],
        sequence=[EmailStep(step=1, subject="hi {{first_name}}", body="Body for {{company}}.", delay_days=0)],
    )
    camp.id = await state.add_campaign(camp)
    sender = make_sender(state, FakeProvider())
    sender.config.persona.signature = SIG
    await sender._stage_campaign_native(camp)
    items = await state.get_outbox(status="pending_review")
    assert len(items) == 1
    assert items[0]["body"] == "Body for Acme." + "\n\n" + SIG


@pytest.mark.asyncio
async def test_sender_without_signature_unchanged(state):
    pid = await seed_prospect(state)
    camp = Campaign(id="", name="c", channel="email", status="draft", prospect_ids=[pid],
                    sequence=[EmailStep(step=1, subject="s", body="Plain body.", delay_days=0)])
    camp.id = await state.add_campaign(camp)
    sender = make_sender(state, FakeProvider())
    sender.config.persona.signature = ""  # Cfg.persona is a shared class; be explicit
    await sender._stage_campaign_native(camp)
    items = await state.get_outbox(status="pending_review")
    assert items[0]["body"] == "Plain body."


@pytest.mark.asyncio
async def test_handler_reply_gets_signature(state):
    pid = await seed_prospect(state)
    prospect = await state.get_prospect(pid)
    convo = Conversation(id="", prospect_id=pid)
    convo.id = await state.add_conversation(convo)
    handler = make_handler(state, FakeProvider())
    handler.config.persona.signature = SIG
    await handler._queue_native_reply(
        "Sure, happy to help.", prospect, convo,
        {"subject": "hello", "thread_ref": "t", "message_id": "<m@x>"}, "question",
    )
    items = await state.get_outbox(status="pending_review")
    assert len(items) == 1
    assert items[0]["kind"] == "reply"
    assert items[0]["body"] == "Sure, happy to help.\n\n" + SIG
