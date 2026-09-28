from agent_control_plane.executor_os_isolation import ServiceIsolationEvidence

def test_current_disposable_lab_is_contained_but_not_minimal_token():
 e=ServiceIsolationEvidence(True,True,True,False,True,True,False)
 assert e.containment_controls_established
 assert not e.minimal_token_verified
 assert not e.minimal_token_currently_enforced
 assert not e.complete_os_isolation_verified

def test_required_privileges_alone_do_not_prove_live_token():
 e=ServiceIsolationEvidence(True,True,True,True,True,True,False)
 assert not e.minimal_token_verified

def test_reversible_trial_can_verify_policy_without_enforcing_it():
 e=ServiceIsolationEvidence(True,True,True,True,True,True,True,True,False)
 assert e.minimal_token_verified
 assert not e.minimal_token_currently_enforced
 assert not e.complete_os_isolation_verified

def test_enforcement_requires_verified_trial_and_active_policy():
 e=ServiceIsolationEvidence(True,True,True,True,True,True,True,True,True)
 assert e.minimal_token_verified
 assert e.minimal_token_currently_enforced
 assert not e.complete_os_isolation_verified
