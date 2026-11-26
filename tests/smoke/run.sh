#!/usr/bin/env bash
# Smoke test a built app image against a throwaway Mosquitto broker.
# Needs only Docker. Usage: [SMOKE_APPARMOR=<profile>] tests/smoke/run.sh <image>
#
# The first app run uses manual broker settings, the second the Supervisor MQTT
# service from a stub "supervisor" container. With SMOKE_APPARMOR the app
# containers run under that loaded AppArmor profile.
#
# Files go into the containers with "docker cp", so no bind mounts are needed.
# Every wait is bounded and a watchdog ends the script before 4 minutes.
set -euo pipefail

image=${1:?usage: tests/smoke/run.sh <image>}
mosquitto=eclipse-mosquitto:2.0.22
run_seconds=60

id=pecron-smoke-$$
broker=$id-broker
app=$id-app
invalid=$id-invalid
supervisor=$id-supervisor
service_app=$id-service-app

mqtt_user=smoke
mqtt_password=dummy-mqtt-password
account_password=dummy-account-password
setup_password=dummy-setup-password
supervisor_token=dummy-supervisor-token
keys=(AABBCC000001 AABBCC000002)
auth_keys=(ZHVtbXktYXV0aC1rZXktMQ== ZHVtbXktYXV0aC1rZXktMg==)
containers=("$service_app" "$supervisor" "$invalid" "$app" "$broker")
security=()
[[ -z "${SMOKE_APPARMOR:-}" ]] || security=(--security-opt "apparmor=$SMOKE_APPARMOR")

tmp=
watchdog=

cleanup() {
  status=$?
  trap - EXIT INT TERM
  [[ -z "$watchdog" ]] || kill "$watchdog" 2>/dev/null || true
  if [[ $status -ne 0 ]]; then
    for container in "${containers[@]}"; do
      echo "--- logs: $container ---"
      docker logs --tail 200 "$container" 2>&1 || true
    done
    echo "SMOKE TEST FAILED" >&2
  fi
  docker rm -f -v "${containers[@]}" >/dev/null 2>&1 || true
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

# create_app <name> <options.json> [docker create options...]
create_app() {
  mkdir -p "$tmp/$1/data" "$tmp/$1/config"
  cp "$2" "$tmp/$1/data/options.json"
  cp "$tmp/pecron-setup.yaml" "$tmp/$1/config/"
  # No --init: s6-overlay must be PID 1, as under the Supervisor.
  docker create --name "$1" --network "$id" ${security[@]+"${security[@]}"} "${@:3}" "$image" >/dev/null
  docker cp "$tmp/$1/data" "$1:/"
  docker cp "$tmp/$1/config" "$1:/"
}

# The live label of PID 1. "docker inspect" only repeats the requested option,
# also on a host without AppArmor.
check_confined() {
  [[ -n "${SMOKE_APPARMOR:-}" ]] || return 0
  local label
  label=$(docker exec "$1" cat /proc/1/attr/current) || fail "$1: cannot read the AppArmor label"
  [[ $label == "$SMOKE_APPARMOR (enforce)" ]] || fail "$1: AppArmor label is '$label'"
  pass "$1 runs under AppArmor profile $label"
}

# write_options <file> <mqtt JSON object>
write_options() {
  cat >"$1" <<JSON
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
  "mqtt": $2,
  "energy": {"energy_sensors": false},
  "restore_outputs_after_shutdown": {"enabled": false},
  "log_level": "debug"
}
JSON
}

docker image inspect "$image" >/dev/null 2>&1 || fail "image not found locally: $image"
docker image inspect "$mosquitto" >/dev/null 2>&1 || docker pull --quiet "$mosquitto"

# Output is discarded so the sleep never holds a CI step's pipes open.
(sleep 230 && kill -TERM $$) >/dev/null 2>&1 &
watchdog=$!
disown "$watchdog"

tmp=$(mktemp -d)

write_options "$tmp/options.json" \
  "{\"host\": \"broker\", \"port\": 1883, \"username\": \"$mqtt_user\", \"password\": \"$mqtt_password\"}"
# The Supervisor default: no manual broker settings.
write_options "$tmp/service-options.json" "{}"

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
check_confined "$app"

for key in "${keys[@]}"; do
  retained "homeassistant/+/pecron_$key/+/config" >/dev/null ||
    fail "no retained discovery message for $key"
  pass "retained discovery messages for $key"
done
wait_for 10 availability_is online || fail "bridge availability is not online"
pass "bridge availability is online"

# A switch command reaches the library. There is no device on this network and
# no cloud in Local only, so nothing is sent.
ac_command=pecron/${keys[0]}/ac/set
retained "homeassistant/switch/pecron_${keys[0]}/ac/config" | grep -qF "\"$ac_command\"" ||
  fail "the AC switch discovery message does not name $ac_command"
docker exec "$broker" mosquitto_pub -u "$mqtt_user" -P "$mqtt_password" -q 1 \
  -t "$ac_command" -m ON
wait_for 30 logged "$app" "Cannot send control ac_switch_hm" ||
  fail "the command on $ac_command did not reach the library"
pass "a command on $ac_command reaches the library"

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

# The Supervisor MQTT service answers only with the right bearer token.
# shellcheck disable=SC2016  # the Python source is literal
docker run -d --name "$supervisor" --network "$id" --network-alias supervisor \
  --entrypoint python3 "$image" -c '
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
token, user, password = sys.argv[1:]
class Service(BaseHTTPRequestHandler):
    def do_GET(self):
        ok = (self.path == "/services/mqtt"
              and self.headers.get("Authorization") == "Bearer " + token)
        data = {"host": "broker", "port": 1883, "ssl": False,
                "username": user, "password": password}
        body = json.dumps({"result": "ok", "data": data} if ok else {}).encode()
        self.send_response(200 if ok else 401)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)
HTTPServer(("", 80), Service).serve_forever()
' "$supervisor_token" "$mqtt_user" "$mqtt_password" >/dev/null

create_app "$service_app" "$tmp/service-options.json" -e "SUPERVISOR_TOKEN=$supervisor_token"
docker start "$service_app" >/dev/null
wait_for 45 logged "$service_app" "Ready: entities are under" ||
  fail "Supervisor MQTT service: no ready line in the app logs"
logged "$service_app" "MQTT broker: Home Assistant MQTT service, broker:1883" ||
  fail "Supervisor MQTT service: the broker settings were not taken from the service"
wait_for 10 availability_is online || fail "Supervisor MQTT service: availability is not online"
pass "the Supervisor MQTT service supplies the broker"
check_confined "$service_app"
docker stop -t 30 "$service_app" >/dev/null
code=$(state "$service_app" ExitCode)
[[ $code -eq 0 ]] || fail "Supervisor MQTT service: docker stop: exit code $code"

for secret in "$mqtt_password" "$account_password" "$setup_password" "$supervisor_token" \
  "${auth_keys[@]}"; do
  for container in "$app" "$invalid" "$service_app"; do
    ! logged "$container" "$secret" || fail "a dummy secret appears in the logs of $container"
  done
done
pass "no dummy password, token or auth key in the app logs"

echo "SMOKE TEST PASSED"
