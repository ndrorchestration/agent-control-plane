from agent_control_plane.remote_mutation_transaction import (
    MUTATION_OPERATION_REGISTRY,
    MutationPlan,
    MutationTransactionError,
    MutationTransactionReceipt,
    MutationTransactionState,
    get_mutation_operation,
    prepare_mutation_transaction,
)

A = "a" * 64
B = "b" * 64
C = "c" * 64


def plan(**overrides):
    values = {
        "request_id": "req-1",
        "authority_id": "auth-1",
        "resource_id": "repo:acp",
        "resource_type": "git_repository",
        "operation_id": "repo.write_text_file",
        "parameters": {"path": "docs/example.md", "content_sha256": C},
        "precondition_sha256": A,
        "rollback_sha256": B,
    }
    values.update(overrides)
    return MutationPlan(**values)


def test_registry_is_small_and_immutable():
    assert set(MUTATION_OPERATION_REGISTRY) == {"repo.write_text_file", "repo.delete_file"}
    try:
        MUTATION_OPERATION_REGISTRY["x"] = get_mutation_operation("repo.write_text_file")
    except TypeError:
        pass
    else:
        raise AssertionError("registry must be immutable")


def test_plan_binds_operation_schema_and_hashes():
    p = plan()
    assert len(p.plan_sha256) == 64
    assert p.parameters["path"] == "docs/example.md"


def test_unknown_operation_fails_closed():
    try:
        plan(operation_id="repo.exec")
    except MutationTransactionError as exc:
        assert "unknown mutation operation" in str(exc)
    else:
        raise AssertionError("unknown operation should fail")


def test_parameter_schema_must_match_exactly():
    try:
        plan(parameters={"path": "docs/example.md", "content_sha256": C, "extra": "x"})
    except MutationTransactionError as exc:
        assert "exactly match" in str(exc)
    else:
        raise AssertionError("extra parameter should fail")


def test_resource_type_must_match_operation():
    try:
        plan(resource_type="filesystem")
    except MutationTransactionError as exc:
        assert "resource_type" in str(exc)
    else:
        raise AssertionError("resource mismatch should fail")


def test_matching_precondition_and_rollback_produce_nonexecuting_verified_receipt():
    p = plan()
    receipt = prepare_mutation_transaction(
        p,
        observed_precondition_sha256=A,
        observed_rollback_sha256=B,
    )
    assert receipt.state is MutationTransactionState.PRECONDITIONS_VERIFIED
    assert receipt.preconditions_verified is True
    assert receipt.rollback_available is True
    assert receipt.mutation_executed is False
    assert receipt.execution_enabled is False


def test_precondition_drift_blocks_transaction():
    receipt = prepare_mutation_transaction(
        plan(),
        observed_precondition_sha256=C,
        observed_rollback_sha256=B,
    )
    assert receipt.state is MutationTransactionState.BLOCKED
    assert receipt.preconditions_verified is False
    assert receipt.mutation_executed is False


def test_missing_expected_rollback_blocks_transaction():
    receipt = prepare_mutation_transaction(
        plan(),
        observed_precondition_sha256=A,
        observed_rollback_sha256=C,
    )
    assert receipt.state is MutationTransactionState.BLOCKED
    assert receipt.rollback_available is False


def test_receipt_cannot_claim_execution():
    p = plan()
    try:
        MutationTransactionReceipt(
            request_id=p.request_id,
            authority_id=p.authority_id,
            operation_id=p.operation_id,
            plan_sha256=p.plan_sha256,
            precondition_sha256=A,
            rollback_sha256=B,
            state=MutationTransactionState.PRECONDITIONS_VERIFIED,
            preconditions_verified=True,
            rollback_available=True,
            mutation_executed=True,
        )
    except MutationTransactionError as exc:
        assert "not implemented" in str(exc)
    else:
        raise AssertionError("execution claim should fail")
