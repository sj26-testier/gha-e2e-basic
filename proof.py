"""Real CLI probe. Emit assertions only; never print captured token/error output."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request


def emit(data):
    print("ID_PROOF " + json.dumps(data, sort_keys=True), flush=True)


def main():
    manifest = json.loads(Path("candidate-source.json").read_text())
    for name, digest in manifest["files"].items():
        assert hashlib.sha256(Path("candidate", name).read_bytes()).hexdigest() == digest
    emit({"source_revision": manifest["revision"], "source_files_verified": True,
          "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
          "context_present": {key: bool(os.getenv(key)) for key in [
              "BUILDKITE", "BUILDKITE_JOB_ID", "BUILDKITE_AGENT_ACCESS_TOKEN",
              "BUILDKITE_AGENT_JOB_API_SOCKET", "GITHUB_ACTIONS",
              "ACTIONS_ID_TOKEN_REQUEST_URL", "ACTIONS_ID_TOKEN_REQUEST_TOKEN"]},
          "buildkite_agent_on_path": shutil.which("buildkite-agent") is not None})
    import id
    import jwt

    assert Path(id.__file__).read_bytes() == Path("candidate/id/__init__.py").read_bytes()
    env = os.environ.copy()
    if env.get("BUILDKITE") and env.get("BUILDKITE_JOB_ID"):
        provider = "buildkite"
        issuer = "https://agent.buildkite.com"
        # The importer may emulate GitHub. Isolate the real Buildkite provider;
        # never synthesize a Buildkite context or copy another process's secrets.
        env.pop("GITHUB_ACTIONS", None)
    elif env.get("ACTIONS_ID_TOKEN_REQUEST_URL") and env.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN"):
        provider = "github"
        issuer = "https://token.actions.githubusercontent.com"
    else:
        emit({"status": "blocked", "exit_status": 2,
              "reason": "No native Buildkite job context or shell OIDC endpoint"})
        return 2
    result = subprocess.run([sys.executable, "-m", "id", "pypi"], env=env,
                            capture_output=True, text=True, timeout=60)
    emit({"command": "python -m id pypi", "provider": provider,
          "cli_exit_status": result.returncode})
    assert result.returncode == 0
    token = result.stdout.strip()
    with urllib.request.urlopen(issuer + "/.well-known/openid-configuration", timeout=30) as response:
        discovery = json.load(response)
    assert discovery["issuer"] == issuer
    key = jwt.PyJWKClient(discovery["jwks_uri"]).get_signing_key_from_jwt(token)
    claims = jwt.decode(token, key.key, algorithms=["RS256"], audience="pypi", issuer=issuer,
                        options={"require": ["iss", "aud", "exp", "iat", "sub"]})
    assertions = {"signature_valid": True, "issuer_valid": True, "audience_pypi": True,
                  "time_valid": True, "required_pypi_claims_present": all(
                      claims.get(key) for key in ["jti", "organization_id", "pipeline_id"])}
    if provider == "buildkite":
        ref = ("refs/tags/" + env["BUILDKITE_TAG"] if env.get("BUILDKITE_TAG")
               else "refs/heads/" + env["BUILDKITE_BRANCH"])
        expected_sub = (f"organization:{env['BUILDKITE_ORGANIZATION_SLUG']}:"
                        f"pipeline:{env['BUILDKITE_PIPELINE_SLUG']}:"
                        f"ref:{ref}:commit:{env['BUILDKITE_COMMIT']}:"
                        f"step:{env.get('BUILDKITE_STEP_KEY', '')}")
        assertions["default_subject_preserved"] = claims["sub"] == expected_sub
    else:
        assertions["repository_bound"] = claims["repository"] == "sj26-testier/gha-e2e-basic"
    emit({"provider": provider, "claim_names": sorted(claims), "assertions": assertions})
    if provider == "buildkite":
        assert assertions["required_pypi_claims_present"]
        assert assertions["default_subject_preserved"]
    else:
        assert assertions["repository_bound"]
    emit({"status": "passed", "provider": provider, "exit_status": 0})
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        # Exception text can contain a credential, URL, or response body.
        emit({"status": "failed", "error_type": type(error).__name__, "exit_status": 1})
        sys.exit(1)
