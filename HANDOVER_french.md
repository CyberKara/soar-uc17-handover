# UC17 — EfficientIP DDI Enrichment — Paquet de transfert (déploiement air-gapped)

Généré le 2026-08-28 16:01 UTC à partir de `efficientip_ddi_enrich` (environnement source : `soar8`).

Ce paquet est autonome — tout ce qu'il faut pour déployer ce cas d'usage manuellement
dans un environnement sans accès réseau vers ce dépôt ni vers `soar8`.

*(Version anglaise : `HANDOVER.md` dans ce même dossier.)*

## Contenu

| Chemin | Contenu |
|--------|---------|
| `connectors/` | Paquet(s) applicatif(s) connecteur : efficientip_ddi.tgz, efficientip_ddi_classic-v1.0.6.tgz |
| `connectors/source/` | Même(s) connecteur(s), extrait(s) — pour lecture, pas pour import |
| `playbooks/*.tgz` (PB) | efficientip_ddi_enrich, efficientip_ddi_action_test, efficientip_ddi_classic_action_test |
| `playbooks/source/` | Mêmes CF/playbooks, extraits — pour lecture, pas pour import |
| `assets/*.json` | Modèles de configuration d'assets (identifiants masqués — voir ci-dessous) |
| `docs/` | Document de plan d'implémentation, pour le contexte de conception complet |

## Ordre d'installation

1. **Installer l'application/les applications connecteur** — Apps > Install App, charger
   chaque fichier de `connectors/`.
   (`connectors/source/` est le même code extrait pour lecture — ne pas importer depuis ce
   dossier, l'interface a besoin du `.tgz`.)
2. **Configurer les assets à partir des modèles dans `assets/`** — Apps > Configure New Asset
   pour chacun. Les champs listés dans le `redacted_fields` d'un modèle sont des espaces
   réservés (`<<SET ME...>>`) — **vous devez les renseigner vous-même** depuis votre propre
   coffre-fort (vault)/CMDB ; ils n'ont jamais été exportés avec de vraies valeurs (SOAR
   chiffre les champs de type `password` au repos et le processus d'export ne peut pas les
   relire sous une forme utilisable, même en principe).
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
