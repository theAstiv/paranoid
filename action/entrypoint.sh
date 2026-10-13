#!/bin/bash
set -e

# GitHub Actions passes inputs as INPUT_<NAME> env vars,
# with hyphens converted to underscores and names uppercased.
DESCRIPTION_FILE="${INPUT_DESCRIPTION_FILE}"
PROVIDER="${INPUT_PROVIDER:-anthropic}"
MODEL="${INPUT_MODEL:-}"
FRAMEWORK="${INPUT_FRAMEWORK:-STRIDE}"
ITERATIONS="${INPUT_ITERATIONS:-3}"
SARIF_OUTPUT="${INPUT_SARIF_OUTPUT:-paranoid-results.sarif}"
STRICT="${INPUT_STRICT:-false}"
FAIL_ON_FINDINGS="${INPUT_FAIL_ON_FINDINGS:-false}"
MANIFEST="${INPUT_MANIFEST:-}"
LOCKFILE="${INPUT_LOCKFILE:-}"
DEPS_SOURCE="${INPUT_DEPS_SOURCE:-npm}"
SCORING_METHOD="${INPUT_SCORING_METHOD:-dread}"
FAST_MODEL="${INPUT_FAST_MODEL:-}"

# Resolve relative paths against the workspace root.
# Docker container actions mount the checked-out repository at $GITHUB_WORKSPACE.
if [[ "${DESCRIPTION_FILE}" != /* ]]; then
  DESCRIPTION_FILE="${GITHUB_WORKSPACE}/${DESCRIPTION_FILE}"
fi
if [[ "${SARIF_OUTPUT}" != /* ]]; then
  SARIF_OUTPUT="${GITHUB_WORKSPACE}/${SARIF_OUTPUT}"
fi
if [ -n "${MANIFEST}" ] && [[ "${MANIFEST}" != /* ]]; then
  MANIFEST="${GITHUB_WORKSPACE}/${MANIFEST}"
fi
if [ -n "${LOCKFILE}" ] && [[ "${LOCKFILE}" != /* ]]; then
  LOCKFILE="${GITHUB_WORKSPACE}/${LOCKFILE}"
fi

# Validate: description file must exist
if [ -z "${INPUT_DESCRIPTION_FILE}" ]; then
  echo "::error::Input 'description-file' is required."
  exit 1
fi
if [ ! -f "${DESCRIPTION_FILE}" ]; then
  echo "::error::Description file not found: ${DESCRIPTION_FILE}"
  exit 1
fi

# Validate: dependency inputs
if [ -n "${LOCKFILE}" ] && [ -z "${MANIFEST}" ]; then
  echo "::error::Input 'lockfile' requires 'manifest'."
  exit 1
fi
for f in "${MANIFEST}" "${LOCKFILE}"; do
  if [ -n "${f}" ] && [ ! -f "${f}" ]; then
    echo "::error::Dependency file not found: ${f}"
    exit 1
  fi
done

# Validate: API key required for cloud providers; Ollama runs locally without one,
# and Bedrock uses the AWS credential chain (env vars set by an earlier step)
case "${PROVIDER}" in
  anthropic|openai)
    if [ -z "${INPUT_API_KEY}" ]; then
      echo "::error::Input 'api-key' is required for provider '${PROVIDER}'."
      exit 1
    fi
    ;;
esac

# Wire the API key to the correct provider env var
case "${PROVIDER}" in
  anthropic) export ANTHROPIC_API_KEY="${INPUT_API_KEY}" ;;
  openai)    export OPENAI_API_KEY="${INPUT_API_KEY}" ;;
esac
if [ -n "${INPUT_AWS_REGION:-}" ]; then
  export AWS_REGION="${INPUT_AWS_REGION}"
fi

# Use a temp DB — no persistence needed for a single action run
export DB_PATH="/tmp/paranoid-action.db"

# Build the paranoid run argument list
ARGS=(
  "${DESCRIPTION_FILE}"
  --format sarif
  --output "${SARIF_OUTPUT}"
  --provider "${PROVIDER}"
  --framework "${FRAMEWORK}"
  --iterations "${ITERATIONS}"
  --scoring-method "${SCORING_METHOD}"
  --quiet
)

# --strict causes paranoid to exit 2 on error-severity description gaps.
# set -e will propagate this exit code and abort the workflow step before
# the fail-on-findings block below — that is the intended behaviour.
[ "${STRICT}" = "true" ] && ARGS+=(--strict)
[ -n "${MODEL}" ]        && ARGS+=(--model "${MODEL}")
if [ -n "${MANIFEST}" ]; then
  ARGS+=(--manifest "${MANIFEST}" --deps-source "${DEPS_SOURCE}")
  [ -n "${LOCKFILE}" ] && ARGS+=(--lockfile "${LOCKFILE}")
fi
# "none" disables routing (every step on the main model): the CLI's `--fast-model=` form.
if [ "${FAST_MODEL}" = "none" ]; then
  ARGS+=(--fast-model=)
elif [ -n "${FAST_MODEL}" ]; then
  ARGS+=(--fast-model "${FAST_MODEL}")
fi

echo "::group::Paranoid threat modeling"
paranoid run "${ARGS[@]}"
echo "::endgroup::"

# Expose the SARIF file path as an action output
echo "sarif-file=${SARIF_OUTPUT}" >> "${GITHUB_OUTPUT}"

# Count threats in the SARIF output and always surface the number in the job log.
# SARIF_OUTPUT is passed via env to avoid shell-injection from user-controlled paths.
FINDING_COUNT=0
if [ -f "${SARIF_OUTPUT}" ]; then
  FINDING_COUNT=$(SARIF="${SARIF_OUTPUT}" python3 -c '
import json, os
with open(os.environ["SARIF"]) as f:
    sarif = json.load(f)
print(sum(len(run.get("results", [])) for run in sarif.get("runs", [])))
')
fi
echo "::notice::Paranoid identified ${FINDING_COUNT} threat(s). See ${SARIF_OUTPUT} for details."

# Optionally fail the step when threats are found
if [ "${FAIL_ON_FINDINGS}" = "true" ] && [ "${FINDING_COUNT}" -gt 0 ]; then
  echo "::error::Failing workflow — ${FINDING_COUNT} threat(s) found. Upload the SARIF file to GitHub Security for details."
  exit 1
fi
