#!/bin/bash
# ===========================================================================
# LOAD  (runs on the Neo4j ENTERPRISE host, plain shell)
#
# Pulls the single .dump built on BlueBEAR and loads it into the running
# Enterprise DBMS as the combined database, then applies uniqueness constraints.
# Uses the host's native neo4j-admin + cypher-shell (this IS the DB server).
#
# DESTRUCTIVE: --overwrite-destination replaces the target database's store.
# Requires confirmation unless -y / --yes is given.
#
# Env (.env on the Enterprise host):
#   NEO4J_URI NEO4J_USER NEO4J_PASSWORD NEO4J_DATABASE   (server + target db)
#   HPC_SSH        user@bluebear-host      (ssh/scp source)
#   HPC_DUMP_DIR   remote /rds path holding <db>.dump + <db>.constraints.cypher
#   LOCAL_DUMP_DIR local dir to receive the .dump (neo4j-admin --from-path)
# ===========================================================================
set -euo pipefail

SCRIPT_DIR="$(dirname "$(realpath "${BASH_SOURCE[0]}")")"
source "${SCRIPT_DIR}/../../.env"

ASSUME_YES=0
case "${1:-}" in
    -y|--yes) ASSUME_YES=1 ;;
    "")       ;;
    *)        echo "usage: $(basename "$0") [-y|--yes]" >&2; exit 2 ;;
esac

DB="${NEO4J_DATABASE}"
DUMP="${LOCAL_DUMP_DIR}/${DB}.dump"
CONSTRAINTS="${LOCAL_DUMP_DIR}/${DB}.constraints.cypher"
mkdir -p "${LOCAL_DUMP_DIR}"

# --- 1) pull the artifact + constraints from BlueBEAR (single-file scp) ------
echo "=== FETCHING ${DB}.dump from ${HPC_SSH}:${HPC_DUMP_DIR} $(date -Is) ==="
scp "${HPC_SSH}:${HPC_DUMP_DIR}/${DB}.dump"                 "${DUMP}"
scp "${HPC_SSH}:${HPC_DUMP_DIR}/${DB}.constraints.cypher"   "${CONSTRAINTS}"

# --- confirm the destructive load -------------------------------------------
if [[ "${ASSUME_YES}" -ne 1 ]]; then
    read -r -p "Load '${DB}' from ${DUMP}, OVERWRITING any existing '${DB}' store? [y/N] " reply
    [[ "${reply}" =~ ^[Yy]$ ]] || { echo "aborted"; exit 1; }
fi

cyph() { cypher-shell -a "${NEO4J_URI}" -u "${NEO4J_USER}" -p "${NEO4J_PASSWORD}" -d system "$1"; }

# --- 2) load into the running DBMS: register, stop, load, start -------------
# Restoring a dump into a live Enterprise DBMS: the database must exist and be
# stopped so neo4j-admin can replace its store, then be started again.
echo "=== LOADING ${DB} $(date -Is) ==="
cyph "CREATE DATABASE \`${DB}\` IF NOT EXISTS;"
cyph "STOP DATABASE \`${DB}\`;"
neo4j-admin database load "${DB}" --from-path="${LOCAL_DUMP_DIR}" --overwrite-destination=true
cyph "START DATABASE \`${DB}\`;"

# --- 3) uniqueness constraints (idempotent: builder emits CREATE ... ) ------
# Applied against the loaded database, not system. IF NOT EXISTS-style stmts
# from the bulk builder make this safe to re-run.
echo "=== APPLYING CONSTRAINTS $(date -Is) ==="
cypher-shell -a "${NEO4J_URI}" -u "${NEO4J_USER}" -p "${NEO4J_PASSWORD}" -d "${DB}" \
    -f "${CONSTRAINTS}"

echo "=== DONE $(date -Is) — '${DB}' is online ==="
