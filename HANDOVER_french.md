# UC17 — EfficientIP DDI Enrichment — Paquet de transfert (déploiement air-gapped)

Généré le 2026-10-02 15:11 UTC à partir de `efficientip_ddi_enrich` (environnement source : `soar8`).

Ce paquet est autonome — tout ce qu'il faut pour déployer ce cas d'usage manuellement
dans un environnement sans accès réseau vers ce dépôt ni vers `soar8`.

*(Version anglaise : `HANDOVER.md` dans ce même dossier.)*

## Contenu

| Chemin | Contenu |
|--------|---------|
| `connectors/` | Paquet(s) applicatif(s) connecteur : efficientip_ddi-v1.0.16.tgz |
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

- **La mise en page de la note de `efficientip_ddi_enrich` a changé (2026-10-02).** Le tableau a maintenant les colonnes IP, Hostname, Aliases, Subnet, Parent subnet, Lookup ; Space, MAC, Class et Description sont passés dans la section **Per-IP detail**, désormais un bloc par enregistrement avec un champ par ligne (voir Vérification). Seule la note change : le connecteur reste en v1.0.16 (rien à installer) et les sorties sont les mêmes. Ré-importez `efficientip_ddi_enrich` pour qu'il remplace la version précédente, puis pointez de nouveau son bloc action sur votre asset et enregistrez.

- **Le connecteur v1.0.16 et `efficientip_ddi_enrich` ont changé (2026-10-01, plus tard).** La v1.0.16 ne change que les sorties déclarées par `get ip address` : elle liste désormais `parent_subnet_name`, `site_class_name` et `ip_alias` (champs que votre SOLIDserver renvoie) et ne liste plus `multistatus` (qu'il ne renvoie pas). Installez-la par-dessus l'application existante, en mise à jour sur place (votre asset et ses identifiants restent). `efficientip_ddi_enrich` accepte maintenant une ou plusieurs adresses dans `ip` et écrit une note avec un tableau (voir Vérification) ; ré-importez-le pour qu'il remplace la version précédente. **Ses sorties ont changé.** `status` vaut maintenant `success` (toutes les adresses trouvées), `partial` (certaines trouvées), `not_found`, `failed` (au moins une recherche a échoué) ou `error` : `partial` revient, avec ce nouveau sens. Toutes les autres sorties (`hostname`, `subnet`, `space`, ...) sont maintenant des listes avec une entrée par ligne du tableau, et il y a de nouvelles sorties `lookup`, `aliases`, `parent_subnet` et `space_class`. Un de vos playbooks qui lit ces sorties doit être modifié.

- **Le connecteur v1.0.15 et les deux playbooks ont changé (2026-10-01).** La v1.0.15 est le même connecteur, simplifié : les diagnostics ajoutés pendant la recherche du HTTP 401 sont retirés, le champ d'asset `user_agent` aussi (une valeur déjà saisie est ignorée), et `debug_logging` ajoute désormais une ligne par appel (URL, statut, `X-Backside-Transport`, `APIm-Debug-Trans-Id`, début de la réponse). Il inclut la correction v1.0.12 du HTTP 401 permanent sur Test Connectivity (publiée le 2026-09-30) : les identifiants SOLIDserver partent en `X-IPM-Username` / `X-IPM-Password` (c'était `X-DDI-*`, qui faisait échouer chaque appel avec « The specified document is not valid JSON data »), et `get ip address` filtre sur `hostaddr` (il utilisait `host_addr`, qui n'existe pas sur l'appliance). **Vérifiez le `base_url` de l'asset : il doit inclure le préfixe de chemin de l'APIM placé avant `/rest`** (par exemple `https://apim.example/prefix/segment`) ; le connecteur y ajoute `/rest/<service>`. Installez le connecteur par-dessus l'application existante, en mise à jour sur place (votre asset et ses identifiants restent), puis ré-importez `efficientip_ddi_enrich` et `efficientip_ddi_action_test` pour qu'ils remplacent les versions précédentes. La sortie `status` d'`efficientip_ddi_enrich` valait `partial` aussi bien pour « absente de l'IPAM » que pour « recherche en échec » ; elle vaut maintenant `not_found` ou `failed`. Un de vos playbooks qui testait `partial` doit être modifié. `efficientip_ddi_action_test` prend maintenant les entrées facultatives `ip`/`subnet_name` (voir Vérification). Les deux playbooks sont conçus pour résister à un enregistrement : re-pointer leurs blocs d'action vers le nom de votre asset est sans risque.

- **Ce paquet retire deux actions du connecteur : `get ip pool` et `list aliases`** (connecteur v1.0.11). Le connecteur n'appelle plus que deux services SOLIDserver : `ip_address_list` (`get ip address`) et `ip_block_subnet_list` (`list subnets`, `test connectivity`). Après la mise à jour, tout playbook qui appelle encore une action retirée échoue à cette étape. Cela inclut les playbooks `efficientip_ddi_enrich` et `efficientip_ddi_action_test` de tout paquet précédent : réimportez les deux depuis ce paquet pour qu'ils remplacent les versions précédentes. Si vous avez construit vos propres playbooks sur `get ip pool` ou `list aliases`, retravaillez-les avant la mise à jour. Votre actif (asset) et ses identifiants ne sont pas concernés. Le nouveau `efficientip_ddi_enrich` corrige aussi sa note de synthèse : avec les paquets du 2026-08-31 au 2026-09-09, le nom d'hôte, le sous-réseau, l'espace, l'adresse MAC et la classe revenaient vides. Ils sont désormais renseignés.

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

   **Les playbooks sont livrés pointant vers les noms d'assets ci-dessous.** Créez vos
   assets avec ces noms, ou gardez vos propres noms et redirigez les blocs d'action de
   chaque playbook vers vos assets dans le VPE, puis enregistrez : chaque playbook de ce
   paquet est conçu pour résister à un enregistrement. (Un enregistrement rend un playbook
   lancé à la main disponible sur tous les libellés de conteneur ; le réimporter rétablit
   le libellé.)

   | Nom de l'asset | Application | Utilisé par | Modèle |
   |---|---|---|---|
   | `efficientip_ddi mock` | EfficientIP DDI | `efficientip_ddi_action_test`, `efficientip_ddi_enrich` | `assets/efficientip_ddi_mock.json` |

3. **Importer les playbooks** depuis `playbooks/*.tgz`, via *Import Playbook* sur la page
   Playbooks de l'interface SOAR cible. (`playbooks/source/` est le même code extrait pour lecture —
   ne pas importer depuis ce dossier, l'interface a besoin du `.tgz`.)
4. **Rien à activer.** Tous les playbooks de ce paquet sont des playbooks d'entrée
   (`data`) — il n'y a aucun déclencheur d'automatisation à activer ni d'utilisateur
   **Run As** à définir. Vous les lancez à la main depuis un container : ouvrez le
   container, puis Playbooks > Run Playbook et choisissez celui voulu. Voir le document
   de plan d'implémentation dans `docs/`.

## Vérification

1. **Lancez d'abord `efficientip_ddi_action_test`, avec des valeurs de votre IPAM.** Ouvrez n'importe quel container, puis Playbooks > Run Playbook et choisissez-le. Il demande deux entrées facultatives : `ip`, une adresse qui existe dans votre IPAM, et `subnet_name`, le NOM d'un de vos sous-réseaux (un libellé, pas un CIDR). Laissées vides, elles prennent les valeurs du mock du labo (`10.20.30.40`, `CORP_LAN-USERS`), absentes de votre IPAM : ces deux tests sont alors FAIL avec « not found ». Il écrit deux notes, une par action du connecteur (`get ip address`, `list subnets`), chacune PASS ou FAIL avec le message de l'action. Attendez deux PASS. Il ne lance pas `test connectivity` : utilisez pour cela le bouton Test Connectivity de l'asset. Un « not found » prouve quand même que l'appel a atteint SOLIDserver et est revenu. Un message HTTP 401, TLS ou BAD REQUEST, non.

2. **Lancez ensuite `efficientip_ddi_enrich` de la même façon.** Il ne lit aucun artifact. Run Playbook demande sa seule entrée, `ip` : une ou plusieurs adresses, séparées par des virgules, des espaces ou des retours à la ligne (50 au plus). Il écrit une note `EfficientIP DDI Enrichment` : une ligne de synthèse, un tableau avec une ligne par enregistrement IPAM (IP, Hostname, Aliases, Subnet, Parent subnet, Lookup), puis une section **Per-IP detail** : un bloc par enregistrement, l'IP puis une ligne pour chacun de ces champs : espace, classe de l'espace, MAC, classe, description, IP en hexadécimal et paramètres de classe (`-` si vide) ; le bloc d'une recherche en échec donne son message. La colonne Lookup vaut `found`, `not found`, `failed`, `invalid address` ou `skipped`. Une adresse présente dans plusieurs espaces a une ligne par espace (5 au plus). Sa sortie `status` dit ce qui s'est passé : `success` (toutes les adresses trouvées), `partial` (certaines trouvées), `not_found` (aucune trouvée ; les recherches ont fonctionné), `failed` (au moins une recherche a elle-même échoué : lisez sa ligne de détail), `error` (aucune adresse valide). Une exécution où une recherche a échoué ou n'a rien trouvé peut apparaître en échec dans la liste des exécutions ; c'est la note qu'il faut lire. À essayer en une seule exécution : une adresse de votre IPAM, une adresse inutilisée et une faute de frappe, par exemple `<votre IP>, <IP inutilisée>, 10.0.0.999` (attendu : `found`, `not found`, `invalid address`, status `partial`) et, si votre site en a, une adresse IPv6 présente dans votre IPAM. On ne sait pas encore si ce service SOLIDserver renvoie les enregistrements IPv6 : indiquez ce que vous obtenez.

3. **Un HTTP 401 indique désormais de quel type il s'agit.** Le message cite l'en-tête `X-Backside-Transport` de la passerelle. `OK OK` : SOLIDserver lui-même a refusé les identifiants, vérifiez `ddi_username`/`ddi_password` (pas de nouvel essai). `FAIL FAIL` : l'APIM n'a pas pu joindre son backend ; ce n'est pas un problème d'identifiants, transmettez l'`APIm-Debug-Trans-Id` du message à l'administrateur de l'APIM. Pas d'en-tête : vérifiez `client_id`/`client_secret` et le certificat client. Notez lequel des trois vous voyez.

Si une exécution échoue d'une façon que les notes n'expliquent pas, consultez `playbook.log`/`actiond.log` sur l'hôte SOAR cible. Pour plus de détail sur un appel en échec, cochez `debug_logging` sur l'asset : chaque résultat d'action affiche alors une ligne par appel (URL, statut, en-têtes de la passerelle, début de la réponse).

## Diagnostics

`diagnostics/` contient des scripts à exécuter **sur la cible**, car les
questions auxquelles ils répondent portent sur votre environnement et ne
peuvent pas être tranchées depuis celui qui a produit ce paquet.

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
