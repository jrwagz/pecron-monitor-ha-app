#!/usr/bin/env bash
# Smoke test a built app image against a throwaway Mosquitto broker.
# Needs only Docker. Usage: tests/smoke/run.sh <image>
#
# Files go into the containers with "docker cp", so no bind mounts are needed.
# Every wait is bounded and a watchdog ends the script before 3 minutes.
set -euo pipefail

image=${1:?usage: tests/smoke/run.sh <image>}
mosquitto=eclipse-mosquitto:2.0.22
run_seconds=60

id=pecron-smoke-$$
broker=$id-broker
app=$id-app
invalid=$id-invalid

mqtt_user=smoke
mqtt_password=dummy-mqtt-password
account_password=dummy-account-password
setup_password=dummy-setup-password
keys=(AABBCC000001 AABBCC000002)
auth_keys=(ZHVtbXktYXV0aC1rZXktMQ== ZHVtbXktYXV0aC1rZXktMg==)

tmp=
watchdog=

cleanup() {
  status=$?
  trap - EXIT INT TERM
  [[ -z "$watchdog" ]] || kill "$watchdog" 2>/dev/null || true
  if [[ $status -ne 0 ]]; then
    for container in "$invalid" "$app" "$broker"; do
      echo "--- logs: $container ---"
      docker logs --tail 200 "$container" 2>&1 || true
    done
    echo "SMOKE TEST FAILED" >&2
  fi
  docker rm -f -v "$invalid" "$app" "$broker" >/dev/null 2>&1 || true
  docker network rm "$id" >/dev/null 2>&1 || true
  [[ -z "$tmp" ]] || rm -rf "$tmp"
  exit "$status"
}
trap cleanup EXIT
trap 'echo "FAIL: interrupted or timed out" >&2; exit 1' INT TERM

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

pass() {
  echo "ok: $*"
}

# wait_for <seconds> <command...>: retry once a second until the command succeeds.
wait_for() {
  local deadline=$((SECONDS + $1))
  shift
  until "$@"; do
    [[ $SECONDS -lt $deadline ]] || return 1
    sleep 1
  done
}

state() {
  docker inspect --format "{{.State.$2}}" "$1"
}

stopped() {
  [[ $(state "$1" Running) == false ]]
}

# Not "docker logs | grep -q": under pipefail an early grep exit fails the pipe.
logged() {
  local logs
  logs=$(docker logs "$1" 2>&1)
  grep -qF -- "$2" <<<"$logs"
}

retained() {
  docker exec "$broker" mosquitto_sub -u "$mqtt_user" -P "$mqtt_password" \
    --retained-only -C 1 -W 5 -t "$1"
}

availability_is() {
  [[ $(retained pecron/bridge/availability) == "$1" ]]
}

# create_app <name> <options.json>
create_app() {
  mkdir -p "$tmp/$1/data" "$tmp/$1/config"
  cp "$2" "$tmp/$1/data/options.json"
  cp "$tmp/pecron-setup.yaml" "$tmp/$1/config/"
  # No --init: s6-overlay must be PID 1, as under the Supervisor.
  docker create --name "$1" --network "$id" "$image" >/dev/null
  docker cp "$tmp/$1/data" "$1:/"
  docker cp "$tmp/$1/config" "$1:/"
}

docker image inspect "$image" >/dev/null 2>&1 || fail "image not found locally: $image"
docker image inspect "$mosquitto" >/dev/null 2>&1 || docker pull --quiet "$mosquitto"

# Output is discarded so the sleep never holds a CI step's pipes open.
(sleep 170 && kill -TERM $$) >/dev/null 2>&1 &
watchdog=$!
disown "$watchdog"

tmp=$(mktemp -d)

cat >"$tmp/options.json" <<JSON
{
  "connection_mode": "Local only",
  "account": {"email": "smoke@example.com", "password": "$account_password", "region": "na"},
  "devices": [
    {"model": "F3000LFP", "product_key": "pkF3000", "device_key": "${keys[0]}",
     "lan_ip": "192.0.2.10", "auth_key": "${auth_keys[0]}"},
    {"model": "F1000LFP", "product_key": "pkF1000", "device_key": "${keys[1]}",
     "lan_ip": "192.0.2.11", "auth_key": "${auth_keys[1]}"}
  ],
  "polling": {"poll_interval": 70},
  "mqtt": {"host": "broker", "port": 1883, "username": "$mqtt_user", "password": "$mqtt_password"},
  "energy": {"energy_sensors": false},
  "restore_outputs_after_shutdown": {"enabled": false},
  "log_level": "debug"
}
JSON

{
  echo "password: $setup_password"
  echo "devices:"
  for key in "${keys[@]}"; do
    cat <<YAML
  - device_key: "$key"
    tsl_cache:
      ac_switch_hm: {access: RW, desc: Ac output, id: 40, type: BOOL}
      dc_switch_hm: {access: RW, desc: Dc output, id: 38, type: BOOL}
      battery_percentage: {access: R, desc: Battery charge, id: 1, type: INT}
YAML
  done
} >"$tmp/pecron-setup.yaml"

docker network create --internal "$id" >/dev/null

# The broker writes its own config so that no host file permissions matter.
# shellcheck disable=SC2016  # $1 and $2 expand inside the container
docker run -d --name "$broker" --network "$id" --network-alias broker "$mosquitto" sh -c '
  printf "listener 1883\nallow_anonymous false\npassword_file /tmp/passwords\n" >/tmp/smoke.conf
  mosquitto_passwd -b -c /tmp/passwords "$1" "$2"
  chown mosquitto:mosquitto /tmp/passwords
  exec mosquitto -c /tmp/smoke.conf
' sh "$mqtt_user" "$mqtt_password" >/dev/null
wait_for 15 logged "$broker" " running" || fail "the broker did not start"

# An invalid configuration stops the container with a non-zero exit code.
echo '{"connection_mode": "Local only", "devices": []}' >"$tmp/invalid.json"
create_app "$invalid" "$tmp/invalid.json"
docker start "$invalid" >/dev/null
wait_for 30 stopped "$invalid" || fail "invalid options: the container kept running"
code=$(state "$invalid" ExitCode)
[[ $code -ne 0 ]] || fail "invalid options: the container exited 0"
logged "$invalid" "The configuration is invalid" || fail "invalid options: no configuration error logged"
pass "invalid options make the container exit $code"

create_app "$app" "$tmp/options.json"
docker start "$app" >/dev/null
started=$SECONDS

wait_for 45 logged "$app" "Ready: entities are under" || fail "no ready line in the app logs"
pass "ready line logged"

for key in "${keys[@]}"; do
  retained "homeassistant/+/pecron_$key/+/config" >/dev/null ||
    fail "no retained discovery message for $key"
  pass "retained discovery messages for $key"
done
wait_for 10 availability_is online || fail "bridge availability is not online"
pass "bridge availability is online"

while [[ $((SECONDS - started)) -lt $run_seconds ]]; do
  sleep 1
done
[[ $(state "$app" Running) == true ]] || fail "the container stopped within $run_seconds s"
! logged "$app" "Retry 1 in " || fail "pecron-monitor exited and was restarted"
pass "still running after $run_seconds s without restarting pecron-monitor"

stop_started=$SECONDS
docker stop -t 30 "$app" >/dev/null
stop_took=$((SECONDS - stop_started))
code=$(state "$app" ExitCode)
[[ $code -eq 0 ]] || fail "docker stop: exit code $code"
# Whole seconds: a difference below 10 means the stop took under 10 s.
[[ $stop_took -lt 10 ]] || fail "docker stop took $stop_took s"
pass "docker stop took ${stop_took} s, exit code 0"
wait_for 10 availability_is offline || fail "bridge availability is not offline after stop"
pass "bridge availability is offline"

for secret in "$mqtt_password" "$account_password" "$setup_password" "${auth_keys[@]}"; do
  for container in "$app" "$invalid"; do
    ! logged "$container" "$secret" || fail "a dummy secret appears in the logs of $container"
  done
done
pass "no dummy password or auth key in the app logs"

echo "SMOKE TEST PASSED"
