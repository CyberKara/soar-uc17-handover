# UC17 — EfficientIP DDI Enrichment — Paquet de transfert (déploiement air-gapped)

Généré le 2026-08-26 08:47 UTC à partir de `efficientip_ddi_enrich` (environnement source : `soar8`).

Ce paquet est autonome — tout ce qu'il faut pour déployer ce cas d'usage manuellement
dans un environnement sans accès réseau vers ce dépôt ni vers `soar8`.

*(Version anglaise : `HANDOVER.md` dans ce même dossier.)*

## Contenu

| Chemin | Contenu |
|--------|---------|
| `connectors/` | Paquet(s) applicatif(s) connecteur : efficientip_ddi.tgz, efficientip_ddi_classic-v1.0.0.tgz |
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
4. **Activer les playbooks d'automatisation** et définir leur utilisateur **Run As** selon
   le guide d'installation du document de plan d'implémentation (voir `docs/`).

## Vérification

Une fois tout importé et les playbooks d'automatisation activés, déclenchez une exécution
manuelle (par ex. le poll manuel de l'asset Timer, ou selon la section de déclenchement du
document de plan d'implémentation)
et vérifiez : qu'un container est créé et que le(s) playbook(s) enfant(s) attendu(s)
s'exécute(nt) jusqu'au bout. Consultez `spawn.log`/`decided.log`/`actiond.log` sur l'hôte
SOAR cible si quelque chose ne se déclenche pas comme prévu.

## Ce qui n'a volontairement PAS été exporté

- Les valeurs réelles des identifiants pour tout champ de configuration de type `password`
  (voir l'étape 2 ci-dessus).
- Tout ce qui n'est pas explicitement listé dans Contenu ci-dessus.
