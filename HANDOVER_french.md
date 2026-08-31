# UC17 — EfficientIP DDI Enrichment — Paquet de transfert (déploiement air-gapped)

Généré le 2026-08-31 10:18 UTC à partir de `efficientip_ddi_enrich` (environnement source : `soar8`).

Ce paquet est autonome — tout ce qu'il faut pour déployer ce cas d'usage manuellement
dans un environnement sans accès réseau vers ce dépôt ni vers `soar8`.

*(Version anglaise : `HANDOVER.md` dans ce même dossier.)*

## Contenu

| Chemin | Contenu |
|--------|---------|
| `connectors/` | Paquet(s) applicatif(s) connecteur : efficientip_ddi.tgz, efficientip_ddi_classic-v1.0.2.tgz |
| `connectors/source/` | Même(s) connecteur(s), extrait(s) — pour lecture, pas pour import |
| `playbooks/*.tgz` (PB) | efficientip_ddi_enrich, efficientip_ddi_action_test, efficientip_ddi_classic_action_test |
| `playbooks/source/` | Mêmes CF/playbooks, extraits — pour lecture, pas pour import |
| `assets/*.json` | Modèles de configuration d'assets (identifiants masqués — voir ci-dessous) |
| `docs/` | Document de plan d'implémentation, pour le contexte de conception complet |

## [!] Mise à niveau d'une installation existante — à lire en premier

Ne concerne que le cas où cette application est déjà installée sur la cible
depuis un paquet précédent. Sur une cible vierge, passez à l'ordre
d'installation.

- **Si vous avez déjà un actif (asset) pour cette application issu d'un paquet antérieur (v1.0.3 ou plus ancien), vous devez ressaisir `client_cert` et `client_ca` après l'installation.** Ces deux champs sont passés d'un type secret à un champ texte simple en v1.0.4, car un certificat et une chaîne d'autorité de certification ne sont pas des secrets — seule la clé privée en est un. SOAR ne convertit pas ce qui était déjà enregistré : l'ancienne valeur chiffrée reste en place puis est utilisée comme si elle était le texte du certificat. L'application s'installe correctement et l'actif semble toujours rempli, mais toutes les actions échouent. L'erreur mentionne TLS ou l'authentification, ce qui est trompeur — vos identifiants ne sont pas en cause. Ouvrez l'actif, recollez le certificat et la chaîne d'autorité, enregistrez, puis lancez Test Connectivity. `client_key` n'est pas concerné.

## Ordre d'installation

1. **Installer l'application/les applications connecteur** — Apps > Install App, charger
   chaque fichier de `connectors/`.
   (`connectors/source/` est le même code extrait pour lecture — ne pas importer depuis ce
   dossier, l'interface a besoin du `.tgz`.)
2. **Configurer les assets à partir des modèles dans `assets/`** — Apps > Configure New Asset
   pour chacun. Les champs listés dans le `redacted_fields` d'un modèle sont des espaces
   réservés (`<<SET ME...>>`) — **vous devez les renseigner vous-même** ; ils n'ont jamais
   été exportés avec des valeurs utilisables. Deux raisons distinctes apparaissent dans
   cette liste, et chaque espace réservé précise laquelle s'applique :

   - **Secrets** (mots de passe, clés d'API, certificats/clés) — à reprendre depuis votre
     propre coffre-fort (vault)/CMDB. SOAR chiffre les champs de type `password` au repos,
     le processus d'export ne peut donc pas les relire sous une forme utilisable, même en
     principe.
   - **Identités et adresses** (noms d'utilisateur, client/app id, URL des points de
     terminaison) — non secrètes, mais elles appartenaient à l'environnement source et
     n'ont aucun sens ici. Saisissez les valeurs attendues par *votre* système cible.
     **Une identité doit correspondre au justificatif saisi à côté d'elle** — un vrai mot
     de passe associé à un nom d'utilisateur résiduel de l'environnement source ne
     s'authentifie auprès de rien et renvoie une erreur HTTP 401.
3. **Importer les playbooks** depuis `playbooks/*.tgz`, via Apps/Playbooks > Import dans
   l'interface SOAR cible. (`playbooks/source/` est le même code extrait pour lecture —
   ne pas importer depuis ce dossier, l'interface a besoin du `.tgz`.)
4. **Rien à activer.** Tous les playbooks de ce paquet sont des playbooks d'entrée
   (`data`) — il n'y a aucun déclencheur d'automatisation à activer ni d'utilisateur
   **Run As** à définir. Vous les lancez à la main depuis un container : ouvrez le
   container, puis Playbooks > Run Playbook et choisissez celui voulu. Voir le document
   de plan d'implémentation dans `docs/`.

## Vérification

Une fois tout importé, ouvrez (ou créez) un container portant l'artifact que ce cas
d'usage lit, puis lancez le playbook à la main dessus : Playbooks > Run Playbook. Voir le
document de plan d'implémentation dans `docs/` pour les champs d'artifact attendus par
chaque playbook,
et vérifiez que l'exécution se termine et que ses résultats d'action / artifacts ajoutés
sont corrects dans le container. Consultez `playbook.log`/`actiond.log` sur l'hôte SOAR
cible si une exécution échoue ou si une action renvoie une erreur.

## Ce qui n'a volontairement PAS été exporté

- Les valeurs réelles des identifiants pour tout champ de configuration de type `password`
  (voir l'étape 2 ci-dessus).
- Tout ce qui n'est pas explicitement listé dans Contenu ci-dessus.
