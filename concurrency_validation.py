"""Strict validation of recorded residency evidence; no I/O."""


def validate_residency_record(record, digest, expected_present, num_ctx):
    """Validate the final successful observation, not an earlier snapshot."""
    if not isinstance(digest, str) or not digest.strip():
        raise ValueError("A non-empty expected digest is required.")
    if type(expected_present) is not bool:
        raise ValueError("Expected presence must be boolean.")
    if type(num_ctx) is not int or num_ctx < 1:
        raise ValueError("Expected context length must be a positive integer.")

    def require(condition, message):
        if not condition:
            raise RuntimeError(message)

    require(isinstance(record, dict), "Residency record must be an object.")
    require(record.get("status") == "success", "Residency verification failed.")
    require(record.get("model_digest") == digest, "Record digest mismatch.")
    require(
        record.get("expected_present") is expected_present,
        "Record expected-presence mismatch.",
    )

    observations = record.get("observations")
    require(
        isinstance(observations, list) and bool(observations),
        "Missing residency observations.",
    )
    final = observations[-1]
    require(isinstance(final, dict), "Final observation must be an object.")
    require(
        final.get("status") == "success",
        "Final observation was not successful.",
    )
    require(
        final.get("present") is expected_present,
        "Final observed presence mismatch.",
    )

    response = final.get("response")
    require(isinstance(response, dict), "Missing residency response object.")
    models = response.get("models")
    require(isinstance(models, list), "Missing residency models list.")

    for model in models:
        require(isinstance(model, dict), "Residency model must be an object.")
        model_digest = model.get("digest")
        require(
            isinstance(model_digest, str) and bool(model_digest.strip()),
            "Residency model lacks a valid digest.",
        )

    targets = [model for model in models if model["digest"] == digest]
    require(bool(targets) is expected_present, "Snapshot presence mismatch.")

    if expected_present:
        require(
            all(
                type(model.get("context_length")) is int
                and model["context_length"] == num_ctx
                for model in targets
            ),
            "Target context length mismatch.",
        )