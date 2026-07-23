#!/usr/bin/env bash
set -euo pipefail
cd services/gateway
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
export GRADLE_USER_HOME=/tmp/gradle-home
/tmp/gradle-8.8/bin/gradle --no-daemon test
