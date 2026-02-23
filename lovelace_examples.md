# Tisseo Lovelace Card Examples

Here are example Lovelace card configurations to display your Tisseo departure data.

---

## 🌟 NEW: Tisseo Departures Card (Custom Component)

A dedicated custom Lovelace card is now available at:
`/config/www/community/tisseo-departures-card/`

### Installation

1. **Add the resource** in Home Assistant:
   - Go to **Settings → Dashboards → Resources** (top-right menu)
   - Click **Add Resource**
   - URL: `/local/community/tisseo-departures-card/tisseo-departures-card.js`
   - Type: **JavaScript Module**

2. **Restart Home Assistant** or reload the browser

3. **Add the card** to your dashboard:
   ```yaml
   type: custom:tisseo-departures-card
   entity: sensor.tisseo_metro_a_mermoz_balma_gramont_departures
   ```

### Card Options

```yaml
type: custom:tisseo-departures-card
entity: sensor.tisseo_metro_a_mermoz_balma_gramont_departures
show_header: true
show_line_badge: true
show_destination: true
show_realtime_indicator: true
max_departures: 3
compact_mode: false
```

### Multi-Stop Card

Display multiple stops in a grid:

```yaml
type: custom:tisseo-departures-multi-card
title: My Commute
columns: 2
max_departures_per_stop: 2
entities:
  - sensor.tisseo_metro_a_mermoz_balma_gramont_departures
  - sensor.tisseo_metro_b_jean_jaures_ramonville_departures
```

---

## Alternative: Button Card Templates

If you prefer using Button Card, here are some templates:

## Recommended: Custom Departure Card

This card provides a clean, modern look similar to official transit apps:

```yaml
type: custom:button-card
entity: sensor.tisseo_metro_a_mermoz_balma_gramont_departures
show_name: false
show_icon: false
show_state: false
styles:
  card:
    - padding: 0
    - background: var(--card-background-color)
    - border-radius: 12px
    - overflow: hidden
custom_fields:
  content: |
    [[[
      const departures = entity.attributes.departures || [];
      const deviceName = "Metro A - Mermoz";
      const direction = "Balma-Gramont";

      // Line colors
      const lineColors = {
        'A': '#E3007A',
        'B': '#FFCD00',
        'T1': '#006DB8',
        'T2': '#FF6600',
        'L1': '#00A651',
      };

      const lineColor = lineColors['A'] || '#666';

      let html = `
        <div style="background: ${lineColor}; color: white; padding: 12px 16px; font-weight: 600;">
          <div style="display: flex; align-items: center; gap: 8px;">
            <ha-icon icon="mdi:subway-variant" style="--mdc-icon-size: 24px;"></ha-icon>
            <span style="font-size: 16px;">Metro A</span>
            <span style="margin-left: auto; font-size: 14px; opacity: 0.9;">→ ${direction}</span>
          </div>
        </div>
        <div style="padding: 8px 0;">
      `;

      if (departures.length === 0) {
        html += `<div style="padding: 16px; text-align: center; color: var(--secondary-text-color);">Aucun départ</div>`;
      } else {
        departures.slice(0, 5).forEach((dep, i) => {
          const mins = dep.minutes_until;
          const isImminent = mins <= 2;
          const bgColor = i % 2 === 0 ? 'transparent' : 'var(--secondary-background-color)';
          const textColor = isImminent ? '#E53935' : 'var(--primary-text-color)';
          const weight = isImminent ? '700' : '400';

          html += `
            <div style="display: flex; align-items: center; padding: 10px 16px; background: ${bgColor};">
              <div style="width: 40px; height: 24px; background: ${lineColor}; border-radius: 4px; display: flex; align-items: center; justify-content: center; color: white; font-weight: 600; font-size: 12px;">
                ${dep.line}
              </div>
              <div style="flex: 1; margin-left: 12px; font-size: 14px; color: var(--primary-text-color);">
                ${dep.destination}
              </div>
              <div style="font-size: 16px; font-weight: ${weight}; color: ${textColor}; min-width: 50px; text-align: right;">
                ${mins} min
              </div>
            </div>
          `;
        });
      }

      html += '</div>';
      return html;
    ]]]
card_mod:
  style: |
    ha-card {
      overflow: hidden;
    }
```

## Simple Multi-Stop Overview

A compact view showing multiple stops:

```yaml
type: vertical-stack
cards:
  - type: markdown
    content: "## 🚇 Prochains départs"
    card_mod:
      style: |
        ha-card { background: transparent; box-shadow: none; }

  - type: horizontal-stack
    cards:
      - type: custom:button-card
        entity: sensor.tisseo_metro_a_mermoz_balma_gramont_minutes_until_departure
        name: Metro A
        icon: mdi:subway-variant
        show_state: true
        state_display: "[[[ return entity.state + \"'\" ]]]"
        styles:
          card:
            - background: "linear-gradient(135deg, #E3007A 0%, #c4006a 100%)"
            - color: white
            - border-radius: 12px
          icon:
            - color: white
          name:
            - color: white
            - font-size: 12px
          state:
            - color: white
            - font-size: 24px
            - font-weight: bold

      - type: custom:button-card
        entity: sensor.tisseo_metro_b_mermoz_borderouge_minutes_until_departure
        name: Metro B
        icon: mdi:subway-variant
        show_state: true
        state_display: "[[[ return entity.state + \"'\" ]]]"
        styles:
          card:
            - background: "linear-gradient(135deg, #FFCD00 0%, #e6b800 100%)"
            - color: "#333"
            - border-radius: 12px
          icon:
            - color: "#333"
          name:
            - color: "#333"
            - font-size: 12px
          state:
            - color: "#333"
            - font-size: 24px
            - font-weight: bold
```

## Markdown Table Card

Simple table using built-in cards:

```yaml
type: markdown
title: Tisseo - Prochains départs
content: |
  {% set deps = state_attr('sensor.tisseo_metro_a_mermoz_balma_gramont_departures', 'departures') %}
  {% if deps %}
  | Ligne | Direction | Départ |
  |:-----:|-----------|-------:|
  {% for d in deps[:5] %}
  | **{{ d.line }}** | {{ d.destination }} | {{ d.minutes_until }} min |
  {% endfor %}
  {% else %}
  *Aucun départ disponible*
  {% endif %}
```

## Mushroom Chips (Compact Overview)

If you have Mushroom Cards installed:

```yaml
type: custom:mushroom-chips-card
chips:
  - type: template
    icon: mdi:subway-variant
    icon_color: pink
    content: "A: {{ states('sensor.tisseo_metro_a_mermoz_balma_gramont_minutes_until_departure') }}'"
    tap_action:
      action: more-info
    entity: sensor.tisseo_metro_a_mermoz_balma_gramont_departures

  - type: template
    icon: mdi:subway-variant
    icon_color: amber
    content: "B: {{ states('sensor.tisseo_metro_b_mermoz_borderouge_minutes_until_departure') }}'"
    tap_action:
      action: more-info
    entity: sensor.tisseo_metro_b_mermoz_borderouge_departures

  - type: template
    icon: mdi:tram
    icon_color: blue
    content: "T1: {{ states('sensor.tisseo_tram_t1_arenes_aeroport_minutes_until_departure') }}'"
    tap_action:
      action: more-info
    entity: sensor.tisseo_tram_t1_arenes_aeroport_departures
```

## Imminent Departure Alert

Show a notification when departure is imminent:

```yaml
type: conditional
conditions:
  - condition: state
    entity: binary_sensor.tisseo_metro_a_mermoz_balma_gramont_imminent
    state: "on"
card:
  type: custom:button-card
  entity: sensor.tisseo_metro_a_mermoz_balma_gramont_minutes_until_departure
  name: DÉPART IMMINENT
  icon: mdi:subway-variant
  show_state: true
  state_display: "[[[ return entity.state + ' min' ]]]"
  styles:
    card:
      - background: "linear-gradient(135deg, #E53935 0%, #C62828 100%)"
      - color: white
      - animation: pulse 1s infinite
    icon:
      - color: white
      - animation: shake 0.5s infinite
    name:
      - color: white
      - font-weight: bold
    state:
      - color: white
      - font-size: 32px
      - font-weight: bold
  card_mod:
    style: |
      @keyframes pulse {
        0%, 100% { transform: scale(1); }
        50% { transform: scale(1.02); }
      }
      @keyframes shake {
        0%, 100% { transform: translateX(0); }
        25% { transform: translateX(-2px); }
        75% { transform: translateX(2px); }
      }
```

## Official Tisseo Line Colors

Use these colors for accurate branding:

| Line | Color | Hex |
|------|-------|-----|
| Metro A | Pink | `#E3007A` |
| Metro B | Yellow | `#FFCD00` |
| Tram T1 | Blue | `#006DB8` |
| Tram T2 | Orange | `#FF6600` |
| Linéo L1 | Green | `#00A651` |
| Linéo L2 | Purple | `#91278F` |

## Notes

- Entity IDs follow the pattern: `sensor.tisseo_<transport>_<line>_<stop>_<direction>_<sensor_type>`
- Example: `sensor.tisseo_metro_a_mermoz_balma_gramont_departures`
- Custom cards (Button Card, Mushroom) are available via HACS
- Replace entity IDs with your actual entities (check Developer Tools → States)
