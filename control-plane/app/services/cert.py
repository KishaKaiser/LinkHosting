"""Certificate generation service using OpenSSL (self-signed or CA-signed)."""
import logging
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from app.config import settings

log = logging.getLogger(__name__)

CA_KEY_PATH = Path("/data/certs/ca/ca.key")
CA_CERT_PATH = Path("/data/certs/ca/ca.crt")
CERT_VALIDITY_DAYS = 825  # ~2 years (max for modern browsers)


def _ensure_ca() -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    """Load or create the internal CA key/cert."""
    CA_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)

    if CA_KEY_PATH.exists() and CA_CERT_PATH.exists():
        with open(CA_KEY_PATH, "rb") as f:
            ca_key = serialization.load_pem_private_key(f.read(), password=None)
        with open(CA_CERT_PATH, "rb") as f:
            ca_cert = x509.load_pem_x509_certificate(f.read())
        return ca_key, ca_cert  # type: ignore[return-value]

    log.info("Generating new internal CA key and certificate")
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "LinkHosting Internal CA"),
            x509.NameAttribute(NameOID.COMMON_NAME, "LinkHosting Root CA"),
        ]
    )
    now = datetime.now(tz=timezone.utc)
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=True,
                crl_sign=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )

    with open(CA_KEY_PATH, "wb") as f:
        f.write(
            ca_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            )
        )
    with open(CA_CERT_PATH, "wb") as f:
        f.write(ca_cert.public_bytes(serialization.Encoding.PEM))

    log.info("Internal CA created at %s", CA_CERT_PATH)
    return ca_key, ca_cert


def issue_cert(domain: str, cert_dir: Path) -> tuple[Path, Path, datetime]:
    """
    Issue a TLS cert for *domain* signed by the internal CA.
    Returns (cert_path, key_path, valid_until).
    """
    if settings.dev_mode:
        log.info("[DEV] Would issue cert for %s", domain)
        cert_path = cert_dir / "cert.pem"
        key_path = cert_dir / "key.pem"
        cert_dir.mkdir(parents=True, exist_ok=True)
        # Write dummy PEM placeholders for dev
        if not cert_path.exists():
            cert_path.write_text("# dev cert placeholder\n")
        if not key_path.exists():
            key_path.write_text("# dev key placeholder\n")
        valid_until = datetime.now(tz=timezone.utc) + timedelta(days=CERT_VALIDITY_DAYS)
        return cert_path, key_path, valid_until

    cert_dir.mkdir(parents=True, exist_ok=True)
    cert_path = cert_dir / "cert.pem"
    key_path = cert_dir / "key.pem"

    ca_key, ca_cert = _ensure_ca()

    # Generate site key
    site_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    now = datetime.now(tz=timezone.utc)
    valid_until = now + timedelta(days=CERT_VALIDITY_DAYS)

    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, domain),
        ]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(site_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(valid_until)
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(domain)]),
            critical=False,
        )
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None), critical=True
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    with open(key_path, "wb") as f:
        f.write(
            site_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            )
        )
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
        f.write(ca_cert.public_bytes(serialization.Encoding.PEM))  # chain

    log.info("Issued cert for %s (valid until %s)", domain, valid_until.date())
    return cert_path, key_path, valid_until


def get_ca_cert_pem() -> str:
    """Return CA cert PEM for distribution to clients."""
    if settings.dev_mode:
        return "# dev CA cert placeholder\n"
    _, ca_cert = _ensure_ca()
    return ca_cert.public_bytes(serialization.Encoding.PEM).decode()
