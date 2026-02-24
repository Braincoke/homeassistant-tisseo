# Intégration Tisseo pour Home Assistant

Intégration Home Assistant personnalisée pour [Tisseo](https://www.tisseo.fr/), le réseau de transport public de Toulouse. Surveillez les prochains départs en temps réel, les alertes de service et les informations de transport pour n'importe quel arrêt du réseau (Métro, Tram, Bus et Linéo).

README en anglais : [README_en.md](README_en.md)
<img width="1119" height="708" alt="image" src="https://github.com/user-attachments/assets/e5f62f18-7756-4865-9e11-52f182ace388" />

## Avertissement legal

- Ce projet est une integration communautaire **non officielle** pour Home Assistant.
- Je n'ai **aucune affiliation** avec Tisseo.
- Le nom "Tisseo" est utilise uniquement pour faciliter la decouverte du projet.
- Si Tisseo souhaite que ce nom ne soit plus utilise dans ce depot, vous pouvez me contacter a : `braincoke+contact@protonmail.com`.

## Licence des donnees

Les donnees de transport Tisseo/Toulouse Metropole reutilisees par cette integration sont soumises a la licence **ODbL 1.0**.

- Texte de la licence ODbL : https://opendatacommons.org/licenses/odbl/1-0/
- Conditions d'utilisation Toulouse Metropole : https://data.toulouse-metropole.fr/page/licence


## Fonctionnalités

- **Assistant de configuration guidé** - Sélectionnez mode de transport, ligne, direction et arrêt via un parcours étape par étape. Pas besoin de connaître les identifiants d'arrêt ni les paramètres API.
- **Référentiel basé GTFS** - Les modes, lignes, directions, arrêts et couleurs de ligne sont chargés depuis le flux GTFS hebdomadaire officiel quand il est disponible, ce qui réduit l'usage de l'API temps réel.
- **Trois stratégies de mise à jour** - Choisissez entre mises à jour régulières, stratégie intelligente basée sur les départs, ou fenêtres horaires.
- **Stratégie par fenêtres horaires (recommandée)** - Utilise la logique intelligente pendant les périodes où vous consultez réellement les départs (par exemple matin/soir) et ralentit ou coupe les appels hors fenêtre pour réduire l'usage API.
- **Départs en temps réel** - Affiche les prochains départs avec indicateur temps réel vs théorique.
- **Alertes de service** - Surveille les alertes actives Tisseo pour votre ligne, avec détection des nouvelles alertes pour les automatisations de notification.
- **Couleurs officielles des lignes** - Lit `bgXmlColor` et `fgXmlColor` depuis l'API Tisseo pour afficher chaque ligne avec ses couleurs officielles dans les cartes compagnon.
- **Bouton d'actualisation manuelle** - Chaque ligne inclut un bouton pour déclencher un rafraîchissement à la demande.
- **Action départs planifiés** - Appelez un service intégré pour récupérer les départs sur une fenêtre future (par exemple demain matin), avec stockage optionnel du résultat sur un capteur dédié par arrêt.
- **Mode debug** - Option pour journaliser tous les appels API et réponses (anonymisés) avec le préfixe `[TISSEO]`.
- **Traductions françaises et anglaises** - Traductions UI complètes dans les deux langues.

## Prérequis

Vous avez besoin d'une **clé API Tisseo Open Data**. Demande gratuite sur :
https://data.toulouse-metropole.fr/ (ou via le portail Tisseo Open Data).

## Installation

### Manuelle

1. Copiez le dossier `tisseo` dans votre répertoire Home Assistant `custom_components/`.
2. Redémarrez Home Assistant.
3. Allez dans **Paramètres > Appareils et services > Ajouter une intégration** et recherchez **Tisseo**.

### HACS (dépôt personnalisé)

1. Dans HACS, cliquez sur le menu 3 points > **Custom repositories**.
2. Ajoutez l'URL du dépôt avec la catégorie **Integration**.
3. Installez **Tisseo** puis redémarrez Home Assistant.

## Configuration

<img width="457" height="637" alt="image" src="https://github.com/user-attachments/assets/ecbeb576-73f1-498f-ad4c-db2026c657ca" />

L'intégration se configure entièrement via l'interface en deux phases :

1. Ajoutez **Tisseo** une première fois pour créer l'entrée globale **Tisseo API Usage** :
1. Entrez la clé API (ou mode mock), le mode debug, la stratégie de mise à jour et les intervalles.
1. Si la stratégie est fenêtres horaires, configurez les fenêtres.
1. Sauvegardez.
1. Utilisez **Add entry** pour ajouter des arrêts :
1. Sélectionnez mode de transport, ligne, direction et arrêt.
1. Configurez le seuil de départ imminent pour cet arrêt.

Chaque entrée d'arrêt représente **un arrêt** sur **une ligne** dans **une direction**. Ajoutez autant d'entrées que nécessaire.

## Entités

Chaque arrêt configuré crée un device avec les entités suivantes :

<img width="1067" height="822" alt="image" src="https://github.com/user-attachments/assets/ab8bc630-3b1c-4c7a-af6f-cd2d8a008d1e" />


### Capteurs

| Entité | État | Description |
|--------|------|-------------|
| **Departures** | Compteur (int) | Nombre de départs à venir. Les attributs contiennent le tableau complet des départs (line, line_color, line_text_color, destination, departure_time, minutes_until, waiting_time, is_realtime, transport_mode). Inclut aussi alerts, stop_name, stop_city, et timestamps. **C'est l'entité principale utilisée par les cartes Lovelace compagnon.** |
| **Next departure** | Horodatage | Date/heure absolue du prochain départ. HA l'affiche en temps relatif (« dans 4 minutes »). Utile pour les automatisations basées sur le temps. |
| **Minutes until departure** | Entier (min) | Minutes avant le prochain départ. Utile pour les seuils d'automatisation et les graphiques d'historique. |
| **Line** | Chaîne | Nom court de la prochaine ligne (ex. « A », « L6 »). Attributs : line_name, line_color, transport_mode. |
| **Destination** | Chaîne | Destination du prochain départ. |
| **Planned departures** | Compteur (int) | Nombre de départs dans la dernière fenêtre future demandée pour cet arrêt. Attributs : `window_start`, `window_end`, `summary`, et liste complète `departures` pour notifications/tableaux de bord. |
| **API calls total** | Compteur (int) | Compteur global des requêtes API temps réel (`api.tisseo.fr`) sur toutes les entrées Tisseo, regroupé sous l'appareil **Tisseo API Usage**. Attributs : last_call, last_success, daily_calls_30d, endpoint_calls_top, et compteurs GTFS. |
| **API calls successful** | Compteur (int) | Nombre d'appels API temps réel réussis. |
| **API calls failed** | Compteur (int) | Nombre d'appels API temps réel en échec (HTTP/auth/connexion/timeout). |
| **API calls today** | Compteur (int) | Nombre d'appels API temps réel effectués aujourd'hui (fuseau Toulouse). |
| **GTFS calls total** | Compteur (int) | Compteur des requêtes GTFS (métadonnées du dataset + téléchargement ZIP GTFS). Attributs : détail des endpoints GTFS et historique journalier GTFS. |
| **GTFS calls successful** | Compteur (int) | Nombre de requêtes GTFS réussies. |
| **GTFS calls failed** | Compteur (int) | Nombre de requêtes GTFS en échec. |
| **GTFS calls today** | Compteur (int) | Nombre de requêtes GTFS effectuées aujourd'hui (fuseau Toulouse). |

### Capteurs binaires

| Entité | État | Description |
|--------|------|-------------|
| **Imminent departure** | on/off | Passe à ON quand le prochain départ est dans le seuil configuré (par défaut : 2 minutes). Device class : `occupancy`. |
| **Service alerts** | on/off | Passe à ON quand il y a des alertes de service actives Tisseo pour la ligne. Attributs : alert_count, tableau alerts, new_alerts pour automatisations de notification. Device class : `problem`. |

### Boutons

| Entité | Description |
|--------|-------------|
| **Refresh departures** | Appuyez pour déclencher un rafraîchissement immédiat des départs uniquement (un seul appel API départs). Les alertes/messages conservent leur cadence de rafraîchissement habituelle. |

## Stratégies de mise à jour

### Fenêtres horaires (recommandée)

C'est le meilleur compromis pour la majorité des utilisateurs et la meilleure façon de limiter l'usage API.

Fonctionnement :
- Pendant les fenêtres actives configurées, l'intégration utilise la logique **smart**.
- Hors fenêtres, elle utilise l'**intervalle hors fenêtre** configuré.
- Mettez l'intervalle hors fenêtre à `0` pour désactiver toute mise à jour hors fenêtre.

Cas d'usage typique :
- Fenêtre trajet du matin (par exemple `06:30-09:00`)
- Fenêtre fin de journée/soir (par exemple `16:30-20:00`)
- Peu ou pas de polling en dehors de ces périodes

### Smart (par défaut si aucune fenêtre n'est configurée)

Planifie les appels API selon le *prochain départ* au lieu de poller en continu :
- Si aucun départ n'est connu, nouvel essai dans **60s**.
- Si le prochain départ est dans plus de **60s**, rafraîchit à **T-60s**.
- Si le prochain départ est déjà dans **60s**, rafraîchit à **T+20s**.
- Si le départ affiché est déjà passé, nouvel essai dans **20s**.
- Impose un délai minimum de **10s** entre deux rafraîchissements smart.
- Met à jour le compte à rebours affiché toutes les **30s** (sans appel API).

Cette logique minimise les appels API tout en gardant des données fraîches aux moments utiles.

Voir [SMART_DEPARTURES_STRATEGY.md](SMART_DEPARTURES_STRATEGY.md) pour le détail complet et le dépannage.

### Régulière (intervalle fixe)

Interroge l'API à intervalle fixe (60 secondes par défaut). Configurez l'intervalle dans le flux d'options.

Note : cette stratégie s'appelle `static` en interne (code/options), mais correspond à des mises à jour régulières.

## Format des Entity IDs

Tous les entity IDs suivent le même motif :

```text
sensor.tisseo_<transport>_<line>_<stop>_<direction>_<type>
```

Exemples :
- `sensor.tisseo_metro_a_mermoz_balma_gramont_departures`
- `sensor.tisseo_lineo_l6_castanet_tolosan_ramonville_minutes_until`
- `binary_sensor.tisseo_tram_t1_arenes_aeroconstellation_imminent`
- `button.tisseo_bus_14_rangueil_aeroport_refresh`

## Exemples d'automatisations

### Notification quand le bus arrive

```yaml
automation:
  - alias: "Bus arriving notification"
    trigger:
      - platform: state
        entity_id: binary_sensor.tisseo_lineo_l6_castanet_tolosan_ramonville_imminent
        to: "on"
    action:
      - service: notify.mobile_app
        data:
          title: "Bus L6 arriving!"
          message: "Your bus is arriving in {{ state_attr('sensor.tisseo_lineo_l6_castanet_tolosan_ramonville_minutes_until', 'state') }} minutes"
```

### Notification sur nouvelle alerte de service

```yaml
automation:
  - alias: "Tisseo service alert"
    trigger:
      - platform: state
        entity_id: binary_sensor.tisseo_metro_a_mermoz_balma_gramont_alerts
        to: "on"
    condition:
      - condition: template
        value_template: "{{ state_attr('binary_sensor.tisseo_metro_a_mermoz_balma_gramont_alerts', 'new_alerts') | length > 0 }}"
    action:
      - service: notify.mobile_app
        data:
          title: "Tisseo Alert"
          message: "{{ state_attr('binary_sensor.tisseo_metro_a_mermoz_balma_gramont_alerts', 'first_new_alert_title') }}"
```

## Flux d'options

Après installation, utilisez le bouton **Configure** de l'intégration :

- Sur l'entrée **Tisseo API Usage** : paramètres globaux (stratégie de mise à jour, intervalles, fenêtres horaires, debug) et rotation de clé API.
  Utilisez le menu d'options pour modifier les paramètres ou changer de stratégie de mise à jour.
- Sur chaque entrée d'arrêt : seuil de départ imminent spécifique à l'arrêt.

## Services

### `tisseo.get_planned_departures`

Récupère les départs pour une fenêtre future sur un arrêt déjà configuré.

Entrées :
- `stop_entity_id` : n'importe quel entity_id de capteur de l'arrêt ciblé.
- `start_datetime` : début de fenêtre (`YYYY-MM-DD HH:MM` ou datetime ISO).
- `end_datetime` : fin de fenêtre (`YYYY-MM-DD HH:MM` ou datetime ISO).
- `number` (optionnel) : nombre max de départs demandés avant filtrage fenêtre (par défaut : `40`).
- `display_realtime` (optionnel) : utiliser les valeurs temps réel (par défaut : `false`).
- `store_result` (optionnel) : écrire le résultat sur le capteur **Planned departures** de l'arrêt (par défaut : `true`).

Retour :
- `count` et `departures` pour la fenêtre demandée.

## Mode debug

Quand il est activé, l'intégration journalise les détails requête/réponse en niveau `DEBUG` avec le préfixe `[TISSEO]`. Les clés API sont masquées dans les URLs.

Pour voir ces logs dans Home Assistant, activez le debug logger pour l'intégration :

```yaml
logger:
  logs:
    custom_components.tisseo: debug
```

## Référence API Tisseo

Voir [TISSEO_API_REFERENCE.md](TISSEO_API_REFERENCE.md) pour la documentation API détaillée, les endpoints et les structures de réponse.
Voir [GTFS_USAGE.md](GTFS_USAGE.md) pour la couverture GTFS, les règles de fallback et ce qui utilise encore l'API temps réel.
Pour la planification sur fenêtre future (exemple : demain 07:40-08:15 récupéré à 20:00), voir [PLANNED_WINDOW_DEPARTURES.md](PLANNED_WINDOW_DEPARTURES.md).

## Cartes compagnon

Cette intégration est conçue pour fonctionner avec le frontend Lovelace **Tisseo Departures Cards** :

- `custom:tisseo-departures-card` - Affichage des départs pour un seul arrêt
- `custom:tisseo-departures-multi-card` - Plusieurs arrêts dans une liste compacte
- `custom:tisseo-nearby-stops-card` - Arrêts proches selon la localisation

Les cartes lisent automatiquement `line_color` et `line_text_color` depuis les attributs du capteur pour afficher chaque ligne avec son identité visuelle officielle Tisseo.

## Attribution des données

Données fournies par [Tisseo Open Data](https://data.toulouse-metropole.fr/).

## Licence

- Code source : [MIT](LICENSE)
- Donnees Open Data : [ODbL 1.0](LICENSE-ODbL-1.0.md)
