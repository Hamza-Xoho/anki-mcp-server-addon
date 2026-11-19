# Experimental collection binding and media readback

This branch is an experiment, not an installed add-on upgrade or release. The
original patch is c4cad4a6d41063f14611566b92ce5f6349141f97 on upstream 278f5e9
(source version 0.41.2). Source version alone cannot identify this branch.

`collection_identity` is discovered through the normal essential-tools package;
it takes no arguments and is annotated read-only/non-destructive. Profile, path
and creation time remain corroborating signals, never numerical uniqueness proof.
Missing/invalid values are null, `identity_complete` is false, the missing keys
are listed, and `identity_sha256` is null. A genuine profile named `unknown` is
valid. A complete fingerprint retains its original serialization/hash semantics.

`collection_session` is runtime freshness, initialized by profile-open hooks and
invalidated by profile-close/app-close hooks or replacement Collection objects.
It is null if the lifecycle was not observed, attributes are incomplete or the
collection cannot be weakly referenced. It changes when the same profile/collection
is closed and reopened. It does not persist across process restarts. It does not
detect an in-place restore with neither a lifecycle event nor object replacement.
It never authorizes a mutation by itself.

A coordinator must explicitly bind the intended profile/path, validate complete
identity plus a live session, bind reviewed note/card ownership and exact state,
and check those preconditions at write dispatch. Separate read-then-write calls
still have a race; these tools do not implement atomic conditional mutation.
A future narrow conditional-operation contract is needed before claiming that
profile switches between preflight and dispatch are prevented. Missing signals,
changed sessions, changed/foreign targets and inconclusive reads must fail closed.
A copied nonce is not a substitute for these checks. Equal numeric note/card IDs
are valid; ownership is verified from typed relationships.

`read_media_file(filename)` returns exact base64 data, size and SHA-256. It accepts
one unchanged sanitized media filename, applies the existing media MIME/containment
validators and rejects symlinks, nonregular files and content over 8 MiB. Successful
responses are never truncated. It does not fetch URLs or arbitrary host paths.
The client must verify returned bytes/digest and account for Anki's actual stored
filename. File-name listing alone remains insufficient evidence.

## Reproduction and scope

Build vendor dependencies with Python 3.13, as package.sh requires:

```sh
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python pip -r requirements-dev.txt
PYTHON=.venv/bin/python bash package.sh
.venv/bin/python -m pytest tests/unit -q
```

On Linux Python 3.13.18: unchanged upstream 278f5e9 passes 825 tests; original
c4cad4a passes 839; this implementation passes 867, no failures/skips. Missing
attribute regressions failed 14 assertions before the fix; freshness tests failed
5 cases before the module existed; media tests failed 9 cases before the tool
existed. A validator argument type error caused two intermediate failures and was
corrected; all final cases pass. pytest-asyncio emits the existing unset-loop-scope
deprecation warning. Environments and raw results stay ignored in .artifacts/.

The standalone container procedure is in tests/isolated/README.md. Packaged
imports and synthetic memory-stream MCP operations pass on Linux aqt/anki 26.9.2,
including byte readback and unsuspend, using both textual and numeric add-on
package directory names. This does not validate Mac installation, GUI queue
routing, HTTP authentication, real profiles, ColdRecall templates, production
coordinator/UI/onboarding, lost receipts or atomic dispatch preconditions.
