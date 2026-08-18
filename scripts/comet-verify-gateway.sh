#!/usr/bin/env bash
set -euo pipefail
python3 -m json.tool schemas/capability.schema.json >/tmp/capability.schema.check.json
python3 -m json.tool schemas/execution-result.schema.json >/tmp/execution-result.schema.check.json
cd services/gateway
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
export GRADLE_USER_HOME=/tmp/gradle-home
/tmp/gradle-8.8/bin/gradle --no-daemon test
