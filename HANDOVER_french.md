# UC17 — EfficientIP DDI Enrichment — Paquet de transfert (déploiement air-gapped)

Généré le 2026-09-02 11:59 UTC à partir de `efficientip_ddi_enrich` (environnement source : `soar8`).

Ce paquet est autonome — tout ce qu'il faut pour déployer ce cas d'usage manuellement
dans un environnement sans accès réseau vers ce dépôt ni vers `soar8`.

*(Version anglaise : `HANDOVER.md` dans ce même dossier.)*

## Contenu

| Chemin | Contenu |
|--------|---------|
| `connectors/` | Paquet(s) applicatif(s) connecteur : efficientip_ddi-v1.0.8.tgz |
| `connectors/source/` | Même(s) connecteur(s), extrait(s) — pour lecture, pas pour import |
| `playbooks/*.tgz` (PB) | efficientip_ddi_enrich, efficientip_ddi_action_test |
| `playbooks/source/` | Mêmes CF/playbooks, extraits — pour lecture, pas pour import |
| `assets/*.json` | Modèles de configuration d'assets (identifiants masqués — voir ci-dessous) |
| `diagnostics/` | Scripts à exécuter sur la cible pour l'interroger — voir ci-dessous |
| `docs/` | Document de plan d'implémentation, pour le contexte de conception complet |

## [!] Mise à niveau d'une installation existante — à lire en premier

Ne concerne que le cas où cette application est déjà installée sur la cible
depuis un paquet précédent. Sur une cible vierge, passez à l'ordre
d'installation.

- **Ce qui s'applique dépend de ce qui est déjà installé — vérifiez d'abord la liste des applications.** Ouvrez Apps et recherchez `EfficientIP`. Si vous voyez **une seule** application (nommée `efficientip_ddi` / `EfficientIP DDI`), vous avez installé le paquet du 2026-08-31 ou un plus récent : celui-ci est une **mise à jour normale, sur place**. Installez-le par-dessus l'application existante — même identifiant interne — et votre actif (asset) existant continue de fonctionner avec tous ses identifiants. **Ne supprimez rien et ne ressaisissez aucun identifiant.** Si en revanche vous voyez **deux** applications (`efficientip_ddi` et `EfficientIP DDI (Classic)`), vous êtes encore sur un paquet antérieur au 2026-08-31, et c'est la note ci-dessous qui vous concerne.

- **Uniquement si la liste des applications en montrait DEUX.** Jusqu'au 2026-08-31, ce cas d'usage livrait deux applications : `efficientip_ddi` (basée sur le SDK) et `EfficientIP DDI (Classic)`. L'application SDK est retirée, car ses actions ne peuvent pas être exécutées depuis la page d'édition/consultation du connecteur dans l'interface web de SOAR — une limite de la plateforme, non de l'application. L'application classique est désormais la seule, et elle reprend le nom `efficientip_ddi` sous un nouvel identifiant interne : SOAR l'installe donc comme une application entièrement nouvelle, sans rien mettre à jour. Après l'installation : supprimez LES DEUX anciennes applications ainsi que leurs actifs (assets) via l'interface web (Apps > l'application > Delete), puis créez un nouvel actif pour la nouvelle application à partir du modèle fourni dans ce paquet. Ressaisissez tous les identifiants à la main ; les champs secrets ne sont pas transmis dans le modèle.

- **Deux nouveaux champs d'actif, tous deux facultatifs.** `retry_count` (défaut 3) et `retry_backoff` (défaut 2 secondes) contrôlent la répétition d'une requête ayant reçu un HTTP 401. Leurs valeurs par défaut sont fonctionnelles : une mise à jour sur place ne demande aucune action, laissez-les telles quelles sauf si vous souhaitez les ajuster. Mettez `retry_count` à 1 pour désactiver complètement la répétition.

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

## Diagnostics

`diagnostics/` contient des scripts à exécuter **sur la cible**, car les
questions auxquelles ils répondent portent sur votre environnement et ne
peuvent pas être tranchées depuis celui qui a produit ce paquet.

- **`uc17_client_bisect.py`** — Exécute curl et Python contre l'appliance l'un après l'autre, en ne changeant qu'un seul paramètre par ligne, afin de localiser une erreur HTTP 401 que seul l'un des deux clients rencontre.
- **`uc17_airgapped_probe.sh`** — Répond aux questions sur la forme de l'API que seule l'appliance réelle peut trancher : noms de champs réels, prise en compte d'un filtre, réponse renvoyée en cas d'absence de résultat.

Tous sont en lecture seule (chaque appel est un GET), lisent les identifiants
depuis des variables d'environnement et n'en affichent aucun. Définissez ces
variables une fois, les deux scripts les reprendront :

```bash
sudo su - phantom
export DDI_BASE=https://<votre hôte apim>
export DDI_CLIENT_ID=... DDI_CLIENT_SECRET=...
export DDI_USER=...      DDI_PASS=...
export DDI_CERT=/chemin/client.pem DDI_KEY=/chemin/client-key.pem
export DDI_CA=/chemin/ca.pem   # facultatif ; omettre pour ne pas vérifier TLS
```

Exécutez `uc17_client_bisect.py` avec le Python de SOAR, et non celui du système :
un autre Python embarque d'autres bibliothèques HTTP et TLS, si bien qu'un
résultat obtenu avec l'interpréteur système ne dit rien du comportement du
connecteur :

```bash
/opt/phantom/bin/phenv python3 diagnostics/uc17_client_bisect.py
```

Facultatif, pour ce script uniquement :

- `PROBE_PATH_OK` — un chemin de requête connu pour aboutir (défaut : une liste de sous-réseaux bornée)
- `PROBE_PATH_BAD` — le chemin qui renvoie 401, si vous en avez un — la même matrice lui est appliquée
- `PROBE_REPEATS` — tentatives par ligne (défaut 3) — augmentez-le si la panne est intermittente

Exécutez `uc17_airgapped_probe.sh` :

```bash
bash diagnostics/uc17_airgapped_probe.sh
```

Facultatif, pour ce script uniquement :

- `PROBE_SUBNET` — un nom de sous-réseau réel de votre IPAM — les sections qui en dépendent sont ignorées sans lui
- `PROBE_IP` — une adresse IPv4 réelle de votre IPAM
- `PROBE_IP_ID` — un ip_id réel de votre IPAM

Renvoyez la sortie à la personne qui maintient ce cas d'usage. Elle peut être
transmise telle quelle — aucun identifiant n'y figure.

## Ce qui n'a volontairement PAS été exporté

- Les valeurs réelles des identifiants pour tout champ de configuration de type `password`
  (voir l'étape 2 ci-dessus).
- Tout ce qui n'est pas explicitement listé dans Contenu ci-dessus.
