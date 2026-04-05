# Trusting the LinkHosting Internal CA

When you issue TLS certificates via LinkHosting, they are signed by an **internal Certificate Authority (CA)**. Browsers and OS tools will show a security warning until the CA certificate is trusted on each client machine.

## Download the CA Certificate

```bash
curl http://<host-ip>:8000/ca.crt -o linkhosting-ca.crt
```

Or via script:
```bash
LINKHOSTING_API=http://192.168.1.100:8000 \
  curl http://192.168.1.100:8000/ca.crt -o linkhosting-ca.crt
```

---

## Install the CA Certificate

### Ubuntu / Debian Linux

```bash
sudo cp linkhosting-ca.crt /usr/local/share/ca-certificates/linkhosting-ca.crt
sudo update-ca-certificates
# Verify
openssl verify -CAfile /etc/ssl/certs/ca-certificates.crt linkhosting-ca.crt
```

### macOS

```bash
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain \
  linkhosting-ca.crt
```

Or via GUI: Open Keychain Access → drag `linkhosting-ca.crt` into "System" → set "Always Trust".

### Windows

```powershell
# Run as Administrator
certutil -addstore "Root" linkhosting-ca.crt
```

Or via GUI: Double-click `linkhosting-ca.crt` → "Install Certificate" → "Local Machine" → "Trusted Root Certification Authorities".

### Firefox (all platforms)

Firefox uses its own trust store and does not read the OS store by default:

1. Open `about:preferences#privacy`
2. Scroll to **Certificates** → click **View Certificates**
3. Select **Authorities** tab → click **Import**
4. Select `linkhosting-ca.crt`
5. Check "Trust this CA to identify websites"

---

## Verify

After trusting the CA, visit `https://mysite.local` in a browser. You should see a valid padlock with no warnings.

```bash
# CLI verification
curl --cacert linkhosting-ca.crt https://mysite.local
```

---

## Revoking / Rotating the CA

There is no CRL (Certificate Revocation List) implemented in this release.

If the CA key is compromised:
1. Delete `/data/certs/ca/ca.key` and `/data/certs/ca/ca.crt` on the host
2. Restart the control-plane — it will generate a new CA automatically
3. Re-issue all site certificates: `./scripts/create-cert.sh <sitename>`
4. Distribute the new CA cert to all clients and remove the old one
5. Remove the old CA from all client trust stores using the platform-specific reverse of the instructions above
