# Planned Departures for a Future Time Window

Use this when you want a list of departures for a **future** window (example: tomorrow between `07:40` and `08:15`) and fetch it the day before (example: `20:00`).

## API Endpoint

Use `stops_schedules`:

```text
GET https://api.tisseo.fr/v2/stops_schedules.json?...&key=<API_KEY>
```

## Why This Endpoint Works

The official Tisseo API documentation for `stops_schedules` exposes:

- `datetime` (format `YYYY-MM-DD HH:MM`) to query from a specific date/time.
- `number` to get the next N departures.
- `lineId` or `stopsList` filters to scope to one line/direction.
- `displayRealTime` to request theoretical (`0`) or real-time (`1`) values.

Important limits:

- There is no explicit `end_datetime` filter; you request from a start time and then filter the returned rows client-side up to your end time.
- Data horizon is documented at 30 days (with recommendation to use 15 days for stability).

## Recommended Query Pattern

For a line + direction, use `stopsList`:

```text
stopsList=<STOP_OR_AREA>|<LINE_ID>|<DESTINATION_STOP_AREA>
```

Example:

```text
stop_area:SA_1033|line:6|stop_area:SA_206
```

Then query with tomorrow start time:

```text
https://api.tisseo.fr/v2/stops_schedules.json?stopsList=stop_area:SA_1033|line:6|stop_area:SA_206&datetime=2026-02-24%2007:40&number=40&displayRealTime=0&timetableByArea=0&key=<API_KEY>
```

For Monday **2026-02-23** at 20:00, that would request departures starting Tuesday **2026-02-24 07:40**.

## Response Shape (timetableByArea=0)

Relevant part:

```json
{
  "departures": {
    "departure": [
      {
        "dateTime": "2026-02-24 07:43:00",
        "realTime": "no",
        "line": { "id": "line:6", "shortName": "12" },
        "destination": [{ "id": "stop_area:SA_206", "name": "Basso Cambo" }]
      }
    ]
  }
}
```

Filter entries where:

```text
dateTime >= 2026-02-24 07:40:00
and
dateTime <= 2026-02-24 08:15:00
```

## Home Assistant Implementation (Mostly Built-in)

This approach uses only native HA building blocks:

1. `rest_command` to call Tisseo.
2. A trigger-based `template` sensor to run at 20:00, parse/filter departures, and persist result.
3. A notification automation to push the stored summary.
4. A dashboard card reading the same sensor.

## Integration-Native Approach (Recommended)

The custom component now exposes `tisseo.get_planned_departures`.
Use this action in automations/scripts instead of defining your own raw REST call.

Example automation (fetch at 20:00 and notify):

```yaml
automation:
  - alias: "Tisseo tomorrow morning departures (integration service)"
    triggers:
      - trigger: time
        at: "20:00:00"
    actions:
      - action: tisseo.get_planned_departures
        response_variable: planned
        data:
          stop_entity_id: sensor.tisseo_metro_b_jean_jaures_ramonville_departures
          start_datetime: "{{ (now() + timedelta(days=1)).strftime('%Y-%m-%d 07:40') }}"
          end_datetime: "{{ (now() + timedelta(days=1)).strftime('%Y-%m-%d 08:15') }}"
          number: 40
          display_realtime: false
          store_result: true
      - action: notify.mobile_app_your_phone
        data:
          title: "Tomorrow departures (07:40-08:15)"
          message: >-
            {% if planned.error is defined %}
              {{ planned.error }}
            {% elif planned.departures | count == 0 %}
              No departures in window
            {% else %}
              {{ planned.departures | map(attribute='departure_time') | map('regex_replace', '^.*T(\\d{2}:\\d{2}).*$', '\\1') | list | join(', ') }}
            {% endif %}
```

Stored result:
- If `store_result: true`, the stop sensor `sensor.<stop>_planned_departures` is updated.
- That sensor can be displayed in Lovelace and is historized by Recorder.

### 1) REST command

```yaml
rest_command:
  tisseo_window_departures:
    method: GET
    url: >-
      https://api.tisseo.fr/v2/stops_schedules.json?stopsList={{ stops_list }}&datetime={{ query_datetime }}&number={{ number }}&displayRealTime=0&timetableByArea=0&key={{ api_key }}
```

### 2) Trigger-based template sensor (fetch + store at 20:00)

```yaml
template:
  - triggers:
      - trigger: time
        at: "20:00:00"
    actions:
      - action: rest_command.tisseo_window_departures
        response_variable: tisseo_resp
        data:
          api_key: !secret tisseo_api_key
          stops_list: "stop_area:SA_1033|line:6|stop_area:SA_206"
          query_datetime: "{{ (now() + timedelta(days=1)).strftime('%Y-%m-%d') ~ '%2007:40' }}"
          number: 40
      - variables:
          window_start: "{{ (now() + timedelta(days=1)).strftime('%Y-%m-%d 07:40:00') }}"
          window_end: "{{ (now() + timedelta(days=1)).strftime('%Y-%m-%d 08:15:00') }}"
    sensor:
      - name: "Tisseo departures tomorrow morning"
        unique_id: tisseo_departures_tomorrow_morning
        icon: mdi:bus-clock
        state: >
          {% if tisseo_resp.status != 200 %}
            unavailable
          {% else %}
            {% set ns = namespace(count=0) %}
            {% for d in tisseo_resp.content.departures.departure | default([]) %}
              {% if window_start <= d.dateTime <= window_end %}
                {% set ns.count = ns.count + 1 %}
              {% endif %}
            {% endfor %}
            {{ ns.count }}
          {% endif %}
        attributes:
          requested_at: "{{ now().isoformat() }}"
          window_start: "{{ window_start }}"
          window_end: "{{ window_end }}"
          api_status: "{{ tisseo_resp.status }}"
          summary: >
            {% if tisseo_resp.status != 200 %}
              API error ({{ tisseo_resp.status }})
            {% else %}
              {% set ns = namespace(rows=[]) %}
              {% for d in tisseo_resp.content.departures.departure | default([]) %}
                {% if window_start <= d.dateTime <= window_end %}
                  {% set destination = d.destination[0].name if d.destination is sequence else d.destination.name %}
                  {% set ns.rows = ns.rows + [d.dateTime[11:16] ~ ' -> ' ~ destination] %}
                {% endif %}
              {% endfor %}
              {{ ns.rows | join(', ') if ns.rows else 'No departures in window' }}
            {% endif %}
```

### 3) Push notification

```yaml
automation:
  - alias: "Tisseo tomorrow morning departures"
    triggers:
      - trigger: time
        at: "20:01:00"
    actions:
      - action: notify.mobile_app_your_phone
        data:
          title: "Tomorrow departures (07:40-08:15)"
          message: "{{ state_attr('sensor.tisseo_departures_tomorrow_morning', 'summary') }}"
```

### 4) Dashboard display

Use a Markdown card:

```yaml
type: markdown
content: |
  **Tomorrow departures (07:40-08:15)**
  {{ state_attr('sensor.tisseo_departures_tomorrow_morning', 'summary') }}
```

## Notes

- For day-ahead planning, `displayRealTime=0` is usually more meaningful than real-time.
- If you need multiple windows/stops, duplicate the template sensor block (or parameterize with scripts/blueprints).
- Because this is a sensor, Recorder/history keeps snapshots over time for later audit.
