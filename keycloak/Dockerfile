# Keycloak mit Realm "hka" und Login-Theme im Look des Portals.
# Das Design-Kit liegt als geprüfte Kopie in theme-kit/ (make keycloak-theme-update); kein eigener Build-Schritt.
# kit.css verweist relativ auf fonts/, deshalb liegen beide nebeneinander unter login/resources/.
FROM quay.io/keycloak/keycloak:26.4
COPY theme/hka /opt/keycloak/themes/hka
COPY theme-kit/kit.css /opt/keycloak/themes/hka/login/resources/kit.css
COPY theme-kit/fonts /opt/keycloak/themes/hka/login/resources/fonts
COPY hka-realm.json /opt/keycloak/data/import/hka-realm.json
CMD ["start-dev", "--import-realm"]
