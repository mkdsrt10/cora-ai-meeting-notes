# Beta receiver settings for a team build (sourced by scripts/build-app.sh and
# by tests/test_build_app_receiver.py). See docs/specs/beta-receiver-in-every-team-build.md.

# beta_receiver_load FILE: fill CORA_BETA_RECEIVER_URL / CORA_BETA_TOKEN, when
# not already set in the shell, from FILE (the release Mac's
# ~/.cora-signing/beta-receiver.env). KEY=value lines; tolerates an `export `
# prefix, spaces around `=`, quotes around the value, `#` comment lines, CRLF
# line ends and a missing final newline. A missing FILE is not an error here.
beta_receiver_load() {
  local file="$1" line key value
  [[ -f "$file" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    line="${line#"${line%%[![:space:]]*}"}"
    [[ -z "$line" || "$line" == \#* ]] && continue
    line="${line#export }"
    [[ "$line" == *=* ]] || continue
    key="${line%%=*}"
    key="${key//[[:space:]]/}"
    value="${line#*=}"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    if [[ ${#value} -ge 2 && ( "$value" == \"*\" || "$value" == \'*\' ) ]]; then
      value="${value:1:${#value}-2}"
    fi
    case "$key" in
      CORA_BETA_RECEIVER_URL) [[ -n "${CORA_BETA_RECEIVER_URL:-}" ]] || export CORA_BETA_RECEIVER_URL="$value" ;;
      CORA_BETA_TOKEN) [[ -n "${CORA_BETA_TOKEN:-}" ]] || export CORA_BETA_TOKEN="$value" ;;
    esac
  done < "$file"
}

# beta_receiver_problem: print why the receiver settings in this shell cannot
# work (missing, not an http(s) URL, spaces or quotes left in), or nothing.
# Never prints the token.
beta_receiver_problem() {
  local url="${CORA_BETA_RECEIVER_URL:-}" token="${CORA_BETA_TOKEN:-}"
  if [[ -z "$url" ]]; then echo "CORA_BETA_RECEIVER_URL is missing"
  elif [[ -z "$token" ]]; then echo "CORA_BETA_TOKEN is missing"
  elif ! [[ "$url" =~ ^https?://[^[:space:]\"\']+$ ]]; then echo "CORA_BETA_RECEIVER_URL is not an http(s) URL"
  elif ! [[ "$token" =~ ^[^[:space:]\"\']+$ ]]; then echo "CORA_BETA_TOKEN contains spaces or quotes"
  fi
}

# beta_receiver_check_stamped BUILD_INFO_JSON required|absent: fail (exit 1)
# unless the stamped build-info.json carries a usable receiver (a Team build)
# or none at all (public, or --team --no-telemetry).
beta_receiver_check_stamped() {
  node -e '
    const fs = require("fs");
    const i = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
    const required = process.argv[2] === "required";
    const usable = /^https?:\/\/[^\s"\x27]+$/.test(i.receiver_url || "") && /^[^\s"\x27]+$/.test(i.token || "");
    if (required && !usable) { console.error("error: build-info.json has no usable receiver; this Team build would never send"); process.exit(1); }
    if (!required && (i.receiver_url || i.token)) { console.error("error: build-info.json carries a receiver this build must not"); process.exit(1); }
  ' "$1" "$2"
}
