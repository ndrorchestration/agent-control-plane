from agent_control_plane.supervisor_recovery import (
    SupervisorRecoveryAdmissionPolicy,
    SupervisorRecoveryDecision,
)
from agent_control_plane.supervisor_runtime_checkpoint import (
    SupervisorPreviousRunDisposition,
    SupervisorRecoveryAssessment,
)


def assessment(disposition, stale_owner=False):
    return SupervisorRecoveryAssessment(
        disposition=disposition,
        previous=None,
        stale_owner=stale_owner,
    )


def test_default_policy_allows_only_fresh_and_clean_stop():
    policy = SupervisorRecoveryAdmissionPolicy()
    assert policy.decide(
        assessment(SupervisorPreviousRunDisposition.FRESH)
    ) is SupervisorRecoveryDecision.ALLOW
    assert policy.decide(
        assessment(SupervisorPreviousRunDisposition.CLEAN_STOP)
    ) is SupervisorRecoveryDecision.ALLOW

    for disposition in (
        SupervisorPreviousRunDisposition.UNCLEAN_EXIT,
        SupervisorPreviousRunDisposition.TERMINAL_GIVE_UP,
        SupervisorPreviousRunDisposition.PRIOR_FAILURE,
    ):
        assert policy.decide(
            assessment(disposition)
        ) is SupervisorRecoveryDecision.HOLD


def test_explicit_policy_can_allow_unclean_recovery():
    policy = SupervisorRecoveryAdmissionPolicy(
        allowed_dispositions=(
            SupervisorPreviousRunDisposition.FRESH,
            SupervisorPreviousRunDisposition.CLEAN_STOP,
            SupervisorPreviousRunDisposition.UNCLEAN_EXIT,
        )
    )
    assert policy.decide(
        assessment(
            SupervisorPreviousRunDisposition.UNCLEAN_EXIT,
            stale_owner=True,
        )
    ) is SupervisorRecoveryDecision.ALLOW
