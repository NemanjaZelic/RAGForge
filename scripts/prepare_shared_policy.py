"""Convert operator-supplied public RSA JWKS to a validated offline shared policy.

This maintenance command never fetches issuer keys, creates tokens or deploys.
"""

import argparse
import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from jwt.algorithms import RSAAlgorithm

from ragforge.shared.policy import JWTVerifier, Principal, SharedPolicy, VerificationKey


def prepare(jwks_file, output, *, issuer, resource, collection, subjects, document_ids=None):
    if jwks_file.stat().st_size > 1024**2:
        raise ValueError("JWKS exceeds 1 MiB")
    jwks = json.loads(jwks_file.read_text(encoding="utf-8"))
    records = jwks["keys"]
    if not isinstance(records, list) or not 1 <= len(records) <= 10:
        raise ValueError("expected 1..10 public signing keys")
    keys = []
    for record in records:
        if (
            record.get("kty") != "RSA"
            or record.get("use", "sig") != "sig"
            or record.get("alg", "RS256") != "RS256"
            or any(field in record for field in ("d", "p", "q", "dp", "dq", "qi", "oth"))
            or record.get("key_ops", ["verify"]) != ["verify"]
        ):
            raise ValueError("JWKS must contain only public RSA signing keys for RS256")
        key = RSAAlgorithm.from_jwk(json.dumps(record))
        public = key.public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode("ascii")
        keys.append(VerificationKey(key_id=record["kid"], public_key_pem=public))
    value = {
        "issuer_url": issuer,
        "resource_url": resource,
        "verification_keys": [key.model_dump() for key in keys],
        "principals": [
            Principal(
                subject=subject, collection_id=collection, document_ids=document_ids or None
            ).model_dump()
            for subject in subjects
        ],
    }
    policy = SharedPolicy.model_validate_json(json.dumps(value))
    JWTVerifier(policy)  # Reject weak/malformed keys before writing anything.
    payload = (policy.model_dump_json(indent=2) + "\n").encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(payload)
    return {
        "output": str(output),
        "keys": len(keys),
        "principals": len(subjects),
        "tokens_created": False,
        "network_used": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jwks-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--issuer", required=True)
    parser.add_argument("--resource", required=True)
    parser.add_argument("--collection", required=True)
    parser.add_argument("--subject", action="append", required=True)
    parser.add_argument("--document-id", action="append")
    args = parser.parse_args()
    print(
        json.dumps(
            prepare(
                args.jwks_file,
                args.output,
                issuer=args.issuer,
                resource=args.resource,
                collection=args.collection,
                subjects=args.subject,
                document_ids=args.document_id,
            )
        )
    )


if __name__ == "__main__":
    main()
