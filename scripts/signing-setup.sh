#!/usr/bin/env bash
# One-time: create the persistent self-signed code-signing identity for release builds.
#
# Why: an ad-hoc signature's designated requirement is the build's cdhash, so every
# new build looks like a different app to macOS and Microphone / Screen Recording /
# Accessibility have to be granted again. Signing every release with the same
# certificate gives a stable requirement (identifier + certificate), so grants
# survive updates. It does not remove Gatekeeper's "can't verify" warning; that
# needs an Apple Developer ID (scripts/install.sh avoids the warning anyway).
#
# Creates a dedicated keychain in ~/.cora-signing (outside the repo; never commit
# it). The login keychain and system trust settings are not touched. Back up
# ~/.cora-signing: losing it means users re-grant permissions once more.
set -euo pipefail

NAME="${CORA_SIGN_NAME:-Cora AI Meeting Notes Signing}"
DIR="$HOME/.cora-signing"
KC="$DIR/cora-signing.keychain-db"
PASS_FILE="$DIR/keychain-password"

if [[ -f "$KC" ]]; then
  echo "Signing keychain already exists at $KC"
  security find-identity -p codesigning "$KC"
  exit 0
fi

umask 077
mkdir -p "$DIR"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

openssl rand -hex 32 > "$PASS_FILE"
P12_PASS="$(openssl rand -hex 16)"

cat > "$work/cert.cnf" <<EOF
[req]
distinguished_name = dn
prompt = no
x509_extensions = ext
[dn]
CN = $NAME
O = Sutra AI
[ext]
basicConstraints = critical,CA:false
keyUsage = critical,digitalSignature
extendedKeyUsage = critical,codeSigning
EOF

openssl req -x509 -newkey rsa:3072 -sha256 -days 3650 -nodes \
  -keyout "$work/key.pem" -out "$work/cert.pem" -config "$work/cert.cnf" 2>/dev/null
openssl pkcs12 -export -legacy -inkey "$work/key.pem" -in "$work/cert.pem" \
  -name "$NAME" -out "$work/id.p12" -passout "pass:$P12_PASS" 2>/dev/null \
  || openssl pkcs12 -export -inkey "$work/key.pem" -in "$work/cert.pem" \
       -name "$NAME" -out "$work/id.p12" -passout "pass:$P12_PASS"

security create-keychain -p "$(cat "$PASS_FILE")" "$KC"
security set-keychain-settings "$KC"   # no auto-lock timeout
security unlock-keychain -p "$(cat "$PASS_FILE")" "$KC"
security import "$work/id.p12" -k "$KC" -P "$P12_PASS" -T /usr/bin/codesign >/dev/null
security set-key-partition-list -S apple-tool:,apple: -s -k "$(cat "$PASS_FILE")" "$KC" >/dev/null

echo "Created signing identity \"$NAME\" in $KC"
security find-identity -p codesigning "$KC"
echo "Back up $DIR somewhere safe (password manager / encrypted disk)."
