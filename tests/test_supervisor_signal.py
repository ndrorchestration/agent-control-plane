import signal

from agent_control_plane.supervisor_signal import SupervisorSignalLatch


def test_first_signal_is_latched_and_repeated_signal_is_idempotent():
    latch = SupervisorSignalLatch()
    latch._handler(signal.SIGTERM, None)
    assert latch.signal_name() == "SIGTERM"
    latch._handler(signal.SIGINT, None)
    assert latch.signal_name() == "SIGTERM"


def test_install_and_restore_are_idempotent():
    latch = SupervisorSignalLatch()
    previous_term = signal.getsignal(signal.SIGTERM)
    previous_int = signal.getsignal(signal.SIGINT)
    try:
        latch.install()
        latch.install()
        assert signal.getsignal(signal.SIGTERM) == latch._handler
        assert signal.getsignal(signal.SIGINT) == latch._handler
    finally:
        latch.restore()
        latch.restore()
    assert signal.getsignal(signal.SIGTERM) == previous_term
    assert signal.getsignal(signal.SIGINT) == previous_int
