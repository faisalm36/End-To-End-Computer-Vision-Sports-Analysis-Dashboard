"""Self-signed TLS certificate for local HTTPS (127.0.0.1:8443). Dev only; browsers will warn once.

    cd backend && .venv/bin/python gen_cert.py            # -> certs/key.pem (0600) + certs/cert.pem, 825 days
    cd backend && .venv/bin/python gen_cert.py --force    # replace existing files

certs/ is gitignored. Uses the `cryptography` package (already a dependency); no openssl needed.
"""
import argparse
import datetime as dt
import ipaddress
import os
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

CERTS = Path(__file__).resolve().parent / "certs"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--days", type=int, default=825)
    args = ap.parse_args()
    key_path, cert_path = CERTS / "key.pem", CERTS / "cert.pem"
    if (key_path.exists() or cert_path.exists()) and not args.force:
        print(f"{cert_path} already exists (use --force to replace)")
        return 0
    CERTS.mkdir(mode=0o700, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Soccer Analytics Capstone (dev)")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(now + dt.timedelta(days=args.days))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"),
                                                        x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
            .sign(key, hashes.SHA256()))
    fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                   serialization.NoEncryption()))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    print(f"wrote {cert_path} (CN=localhost, SAN localhost/127.0.0.1, {args.days} days) and {key_path} (0600)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
