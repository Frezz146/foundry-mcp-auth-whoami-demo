#!/usr/bin/env bash
# Removes everything the Azure Container Apps test created. Safe to run twice.
#
#   deploy/teardown.sh            show the plan and ask before anything is deleted
#   deploy/teardown.sh --yes      do not ask
#   deploy/teardown.sh --wait     wait until the resource group is really gone
#   deploy/teardown.sh --purge    also empty the Entra recycle bin entry and purge the soft deleted Foundry
#                                 resource (implies --wait), so the names can be used again
#
# It deletes: the resource group (container app, environment, registry, log workspace),
# the Entra app registrations of the API and of the OAuth client (service principals, role assignments and
# consent grants go with them) and the local state files. The Foundry resource, its project, the connections and the test agent live
# in the resource group and go away with it.
set -uo pipefail
cd "$(dirname "$0")/.."
source deploy/vars.sh

YES=false
WAIT=false
PURGE=false
for arg in "$@"; do
  case "$arg" in
    --yes) YES=true ;;
    --wait) WAIT=true ;;
    --purge) PURGE=true ;;
    *) echo "Unknown option: $arg"; exit 2 ;;
  esac
done
[ "$PURGE" = "true" ] && WAIT=true

if ! az account show >/dev/null 2>&1; then
  echo "Not signed in. Run: az login"
  exit 1
fi

echo "Subscription: $(az account show --query name -o tsv)"
echo

# 1. What exists
RG_EXISTS=$(az group exists --name "$RG")
if [ "$RG_EXISTS" = "true" ]; then
  TAG=$(az group show --name "$RG" --query "tags.purpose" -o tsv 2>/dev/null)
  if [ "$TAG" != "$RG_TAG" ]; then
    echo "Refusing to continue: resource group $RG exists but has no tag purpose=$RG_TAG."
    echo "Check that it is the right group and tag it, or delete it by hand."
    exit 1
  fi
  echo "Resource group $RG will be deleted. It contains:"
  az resource list --resource-group "$RG" --query "[].{name:name, type:type}" -o table
else
  echo "Resource group $RG does not exist (nothing to delete there)."
fi
echo

APP_IDS=""
for NAME in "$API_APP_NAME" "${CLIENT_APP_NAME:-}"; do
  [ -z "$NAME" ] && continue
  FOUND=$(az ad app list --display-name "$NAME" --query "[].appId" -o tsv)
  if [ -n "$FOUND" ]; then
    echo "App registration(s) named $NAME will be deleted: $(echo "$FOUND" | wc -w | tr -d ' ') found."
    APP_IDS="$APP_IDS $FOUND"
  else
    echo "No app registration named $NAME (nothing to delete there)."
  fi
done
echo

# 2. Ask
if [ "$YES" != "true" ]; then
  read -r -p "Type the resource group name to confirm: " ANSWER
  if [ "$ANSWER" != "$RG" ]; then
    echo "Not confirmed. Nothing was deleted."
    exit 1
  fi
fi

# 3. Delete
if [ "$RG_EXISTS" = "true" ]; then
  az group delete --name "$RG" --yes --no-wait && echo "Deletion of $RG started."
fi

for ID in $APP_IDS; do
  OBJECT_ID=$(az ad app show --id "$ID" --query id -o tsv)
  if az ad app delete --id "$ID"; then
    echo "App registration deleted."
    if [ "$PURGE" = "true" ]; then
      az rest --method DELETE --uri "https://graph.microsoft.com/v1.0/directory/deletedItems/$OBJECT_ID" \
        && echo "App registration removed from the recycle bin."
    fi
  fi
done

if [ "$WAIT" = "true" ] && [ "$RG_EXISTS" = "true" ]; then
  echo "Waiting for the resource group to disappear ..."
  az group wait --name "$RG" --deleted
fi

# 4. Azure keeps a deleted Foundry resource for a while (soft delete). Purge it to free the name.
if [ "$PURGE" = "true" ] && [ "$RG_EXISTS" = "true" ]; then
  az cognitiveservices account purge --name "$FOUNDRY" --resource-group "$RG" --location "$FOUNDRY_LOCATION" \
    && echo "Foundry resource purged."
fi

# 5. Local files
rm -f deploy/.state.env deploy/.state.tmp deploy/.app-roles.json deploy/.scope.json

# 6. Check
echo
echo "Check:"
echo "  resource group exists: $(az group exists --name "$RG") (true can be fine for a few minutes without --wait)"
for NAME in "$API_APP_NAME" "${CLIENT_APP_NAME:-}"; do
  [ -z "$NAME" ] && continue
  echo "  app registrations left named $NAME: $(az ad app list --display-name "$NAME" --query 'length(@)' -o tsv)"
done
echo
echo "The Foundry resource, project, connections and test agent were part of the resource group."
echo "The role assignment of the Foundry identity and the consent grants went away together with the app registrations."
