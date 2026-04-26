import pytest

from app.domain.status import TERMINAL, Status, can_transition, next_status


def test_terminal_set_contents():
    assert Status.PARSE_ERROR in TERMINAL
    assert Status.FILLED in TERMINAL
    assert Status.CANCELLED in TERMINAL
    assert Status.REJECTED in TERMINAL
    assert Status.SUBMIT_FAILED in TERMINAL
    assert Status.SKIPPED in TERMINAL
    assert Status.PENDING not in TERMINAL
    assert Status.PARTIAL not in TERMINAL


@pytest.mark.parametrize(
    "src,dst,ok",
    [
        (Status.RECEIVED, Status.PARSING, True),
        (Status.PARSING, Status.PARSE_ERROR, True),
        (Status.PARSING, Status.INSTRUCTION_READY, True),
        (Status.PARSING, Status.SKIPPED, True),
        (Status.INSTRUCTION_READY, Status.SUBMITTING, True),
        (Status.SUBMITTING, Status.PENDING, True),
        (Status.SUBMITTING, Status.SUBMIT_FAILED, True),
        (Status.SUBMITTING, Status.SKIPPED, True),
        (Status.PENDING, Status.PARTIAL, True),
        (Status.PENDING, Status.FILLED, True),
        (Status.PENDING, Status.CANCELLED, True),
        (Status.PENDING, Status.REJECTED, True),
        (Status.PARTIAL, Status.PARTIAL, True),
        (Status.PARTIAL, Status.FILLED, True),
        (Status.PARTIAL, Status.CANCELLED, True),
        # 非法转换
        (Status.FILLED, Status.PENDING, False),
        (Status.PARSE_ERROR, Status.PARSING, False),
        (Status.RECEIVED, Status.FILLED, False),
        (Status.CANCELLED, Status.FILLED, False),
        # Negative: SKIPPED is terminal, can't go back
        (Status.SKIPPED, Status.PARSING, False),
    ],
)
def test_transition_rules(src, dst, ok):
    assert can_transition(src, dst) is ok


def test_next_status_raises_on_invalid():
    with pytest.raises(ValueError, match="illegal transition"):
        next_status(Status.FILLED, Status.PENDING)


def test_next_status_returns_target_on_valid():
    assert next_status(Status.PENDING, Status.PARTIAL) == Status.PARTIAL
