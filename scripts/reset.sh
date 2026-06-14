#!/bin/bash
# reset.sh — tear down all Integrator-managed nodes and wipe both DBs.
#
# Removes: participant-* and coordinator-* containers, networks, working
# dirs, infra.yml entries, and central certs. Does NOT touch the static
# Brane nodes (alice, bob, worker1, etc.) or the central node.
#
# Usage: bash scripts/reset.sh [--yes]
#   --yes   skip confirmation prompt

set -euo pipefail

BRANE_NODES="${HOME}/brane/nodes"
INFRA_YML="${BRANE_NODES}/central/infra.yml"
INTEGRATOR_DB="$(dirname "$0")/../integrator.db"
MOCK_HUB_DB="$(dirname "$0")/../../mock-branehub/mock_branehub.db"

WSL_DOCKER="/mnt/wsl/docker-desktop/cli-tools/usr/bin"
export PATH="${WSL_DOCKER}:${PATH}"

# ── Confirmation ───────────────────────────────────────────────────────────────

if [[ "${1:-}" != "--yes" ]]; then
    echo "This will permanently delete:"
    echo "  • All participant-* and coordinator-* Docker containers and networks"
    echo "  • Their working directories in ${BRANE_NODES}/"
    echo "  • Their entries in central/infra.yml"
    echo "  • Their certs in central/certs/"
    echo "  • integrator.db"
    echo "  • mock_branehub.db"
    echo ""
    read -r -p "Type YES to continue: " confirm
    if [[ "$confirm" != "YES" ]]; then
        echo "Aborted."
        exit 0
    fi
fi

echo ""
echo "=== Step 1: Stop and remove provisioned containers ==="
for prefix in participant coordinator; do
    for svc in job reg chk prx; do
        for ctr in $(docker ps -a --format "{{.Names}}" | grep "^brane-${svc}-${prefix}-" || true); do
            echo "  Removing ${ctr}..."
            docker stop "$ctr" 2>/dev/null || true
            docker rm -f "$ctr" 2>/dev/null || true
        done
    done
done

echo ""
echo "=== Step 2: Remove provisioned Docker networks ==="
for prefix in participant coordinator; do
    for net in $(docker network ls --format "{{.Name}}" | grep "^brane-worker-${prefix}-" || true); do
        echo "  Removing network ${net}..."
        docker network rm "$net" 2>/dev/null || true
    done
done

echo ""
echo "=== Step 3: Delete working directories ==="
for prefix in participant coordinator; do
    for dir in "${BRANE_NODES}/${prefix}"-*/; do
        if [[ -d "$dir" ]]; then
            echo "  Deleting ${dir}..."
            sudo rm -rf "$dir"
        fi
    done
done

echo ""
echo "=== Step 4: Clean infra.yml ==="
if [[ -f "$INFRA_YML" ]]; then
    python3 - <<'PYEOF'
import yaml, re, sys, os

infra_path = os.path.expanduser("~/brane/nodes/central/infra.yml")
with open(infra_path) as f:
    infra = yaml.safe_load(f) or {}

locations = infra.get("locations", {})
removed = [k for k in list(locations.keys())
           if re.match(r"^(participant|coordinator)-", k)]
for k in removed:
    del locations[k]

with open(infra_path, "w") as f:
    yaml.dump(infra, f, default_flow_style=False, allow_unicode=True)

print(f"  Removed {len(removed)} entries from infra.yml: {removed}")
PYEOF
else
    echo "  infra.yml not found — skipping"
fi

echo ""
echo "=== Step 5: Remove central certs for provisioned nodes ==="
CERTS_DIR="${BRANE_NODES}/central/certs"
for prefix in participant coordinator; do
    for cert_dir in "${CERTS_DIR}/${prefix}"-*/; do
        if [[ -d "$cert_dir" ]]; then
            echo "  Deleting ${cert_dir}..."
            rm -rf "$cert_dir"
        fi
    done
done

echo ""
echo "=== Step 6: Delete databases ==="
for db in "$INTEGRATOR_DB" "$MOCK_HUB_DB"; do
    real_db="$(realpath "$db" 2>/dev/null || echo "$db")"
    if [[ -f "$real_db" ]]; then
        echo "  Deleting ${real_db}..."
        rm -f "$real_db"
    else
        echo "  ${real_db} not found — skipping"
    fi
done

echo ""
echo "=== Step 7: Remove all Brane packages from local registry ==="
for pkg in $(brane package list 2>/dev/null | awk 'NR>1 {print $1}' | sort -u || true); do
    echo "  Removing package ${pkg}..."
    echo "y" | brane package remove "$pkg" 2>/dev/null || true
done

echo ""
echo "=== Step 8: Remove all registered Brane datasets ==="
BRANE_DATA_REGISTRY="${HOME}/.local/share/brane/data"
if [[ -d "$BRANE_DATA_REGISTRY" ]]; then
    for ds_dir in "${BRANE_DATA_REGISTRY}"/*/; do
        if [[ -d "$ds_dir" ]]; then
            echo "  Removing dataset registry entry: ${ds_dir}..."
            rm -rf "$ds_dir"
        fi
    done
else
    echo "  No Brane data registry found — skipping"
fi

echo ""
echo "Done. Start the Integrator fresh:"
echo "  cd $(dirname "$0")/.."
echo "  uvicorn main:app --reload --port 8000"
